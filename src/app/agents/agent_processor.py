import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from typing import List, Any, Dict
from azure.ai.projects.models import FunctionTool
from openai.types.responses.response_input_param import FunctionCallOutput, ResponseInputParam
import json

# Import MCP client for tool execution
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from app.servers.mcp_inventory_client import get_mcp_client

from opentelemetry import trace
from azure.monitor.opentelemetry import configure_azure_monitor
from azure.ai.agents.telemetry import trace_function
import asyncio
from concurrent.futures import ThreadPoolExecutor
import time
# from opentelemetry.instrumentation.openai_v2 import OpenAIInstrumentor

# # Enable Azure Monitor tracing
application_insights_connection_string = os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"]
# configure_azure_monitor(connection_string=application_insights_connection_string)
# OpenAIInstrumentor().instrument()

# scenario = os.path.basename(__file__)
# tracer = trace.get_tracer(__name__)

# Thread pool for running sync OpenAI calls from async context
_executor = ThreadPoolExecutor(max_workers=8)

# Cache for toolset configurations to avoid repeated initialization
_toolset_cache: Dict[str, List[FunctionTool]] = {}


# MCP-based tool wrapper functions (all async, using persistent connection)
async def mcp_create_image(prompt: str) -> str:
    """Generate an AI image based on a text description using DALL-E."""
    mcp_client = await get_mcp_client()
    return await mcp_client.call_tool("generate_product_image", {"prompt": prompt})

async def mcp_product_recommendations(question: str) -> str:
    """Search for product recommendations based on user query."""
    mcp_client = await get_mcp_client()
    return await mcp_client.call_tool("get_product_recommendations", {"question": question})

async def mcp_calculate_discount(customer_id: str) -> str:
    """Calculate the discount based on customer data."""
    mcp_client = await get_mcp_client()
    return await mcp_client.call_tool("get_customer_discount", {"customer_id": customer_id})

async def mcp_inventory_check(product_list: List[str]) -> list:
    """Check inventory for products using MCP client."""
    mcp_client = await get_mcp_client()
    results = []
    for product_id in product_list:
        try:
            inventory_data = await mcp_client.check_inventory(product_id)
            results.append(inventory_data)
        except Exception as e:
            print(f"Error checking inventory for {product_id}: {e}")
            results.append(None)
    return results


# Dispatch table mapping function names to async handlers
_MCP_FUNCTIONS = {
    "mcp_create_image": mcp_create_image,
    "mcp_product_recommendations": mcp_product_recommendations,
    "mcp_calculate_discount": mcp_calculate_discount,
    "mcp_inventory_check": mcp_inventory_check,
}


class AgentProcessor:
    def __init__(self, project_client, assistant_id, agent_type: str, thread_id=None):
        self.project_client = project_client
        self.agent_id = assistant_id
        self.agent_type = agent_type
        self.thread_id = thread_id

        # Use cached toolset or create new one
        self.toolset = self._get_or_create_toolset(agent_type)

    def _get_or_create_toolset(self, agent_type: str) -> List[FunctionTool]:
        """Get cached toolset or create new one to avoid repeated initialization."""
        if agent_type in _toolset_cache:
            return _toolset_cache[agent_type]

        functions = create_function_tool_for_agent(agent_type)
        _toolset_cache[agent_type] = functions
        return functions

    def run_conversation_with_text(self, input_message: str = ""):
        print("Running async!")
        start_time = time.time()
        openai_client = self.project_client.get_openai_client()
        thread_id = self.thread_id
        if thread_id:
            conversation = openai_client.conversations.retrieve(conversation_id=thread_id)
            openai_client.conversations.items.create(
                conversation_id=thread_id,
                items=[{"type": "message", "role": "user", "content": input_message}]
            )
        else:
            conversation = openai_client.conversations.create(
                items=[{"role": "user", "content": input_message}]
            )
            thread_id = conversation.id
            self.thread_id = thread_id
        print(f"[TIMELOG] Message creation took: {time.time() - start_time:.2f}s")
        messages = openai_client.responses.create(
            conversation=thread_id,
            extra_body={"agent": {"name": self.agent_id, "type": "agent_reference"}},
            input="",
            stream=True
        )
        for message in messages:
            yield message.response.output_text
        print(f"[TIMELOG] Total run_conversation_with_text time: {time.time() - start_time:.2f}s")

    async def _execute_function_calls(self, message) -> list:
        """Execute function calls from a message response, returning FunctionCallOutput items."""
        input_list: ResponseInputParam = []
        for item in message.output:
            if item.type != "function_call":
                continue

            handler = _MCP_FUNCTIONS.get(item.name)
            if handler:
                func_result = await handler(**json.loads(item.arguments))
            else:
                func_result = f"Unknown function: {item.name}"

            print(f"[DEBUG] Function {item.name} executed with result: {func_result}")
            input_list.append(FunctionCallOutput(
                type="function_call_output",
                call_id=item.call_id,
                output=json.dumps({"result": func_result})
            ))
        return input_list

    async def _run_conversation(self, input_message: str = ""):
        """Run a conversation turn, handling function calls asynchronously."""
        thread_id = self.thread_id
        start_time = time.time()
        print("Running conversation!")

        try:
            openai_client = self.project_client.get_openai_client()

            # Create message
            if thread_id:
                print(f"Using existing thread_id: {thread_id}")
                conversation = openai_client.conversations.retrieve(conversation_id=thread_id)
                openai_client.conversations.items.create(
                    conversation_id=thread_id,
                    items=[{"type": "message", "role": "user", "content": input_message}]
                )
            else:
                print("Creating new conversation thread")
                conversation = openai_client.conversations.create(
                    items=[{"role": "user", "content": input_message}]
                )
                print("Conversation created:", conversation)
                thread_id = conversation.id
                self.thread_id = thread_id
            print(f"[TIMELOG] Message creation took: {time.time() - start_time:.2f}s")

            # Get initial response (runs sync OpenAI call in thread pool)
            loop = asyncio.get_event_loop()
            message = await loop.run_in_executor(
                _executor,
                lambda: openai_client.responses.create(
                    conversation=thread_id,
                    extra_body={"agent": {"name": self.agent_id, "type": "agent_reference"}},
                    input="",
                    stream=False
                )
            )

            messages_start = time.time()
            print(f"[TIMELOG] Message retrieval took: {time.time() - messages_start:.2f}s")

            if len(message.output_text) == 0:
                print("[DEBUG] No output text found in message. Looking for function calls.")
                # Execute function calls asynchronously
                input_list = await self._execute_function_calls(message)

                # Re-run response creation to get final text output after function calls
                print("[DEBUG] Re-running response creation to get final text output after function calls.")
                message = await loop.run_in_executor(
                    _executor,
                    lambda: openai_client.responses.create(
                        input=input_list,
                        previous_response_id=message.id,
                        extra_body={"agent": {"name": self.agent_id, "type": "agent_reference"}},
                    )
                )

            # Extract text from response
            content = message.output_text
            if isinstance(content, list):
                text_blocks = []
                for block in content:
                    if isinstance(block, dict):
                        text_val = block.get('text', {}).get('value')
                        if text_val:
                            text_blocks.append(text_val)
                    elif hasattr(block, 'text'):
                        if hasattr(block.text, 'value'):
                            text_val = block.text.value
                            if text_val:
                                text_blocks.append(text_val)
                if text_blocks:
                    return ['\n'.join(text_blocks)]

            return [str(content)]

        except Exception as e:
            print(f"[ERROR] Conversation failed: {str(e)}")
            return [f"Error processing message: {str(e)}"]

    async def run_conversation_with_text_stream(self, input_message: str = ""):
        """Async conversation processing with MCP tool calls handled natively."""
        print(f"[DEBUG] Async conversation pipeline initiated", flush=True)
        try:
            messages = await self._run_conversation(input_message)
            for msg in messages:
                yield msg
        except Exception as e:
            print(f"[ERROR] Async conversation failed: {str(e)}")
            yield f"Error processing message: {str(e)}"

    @classmethod
    def clear_toolset_cache(cls):
        """Clear the toolset cache if needed."""
        global _toolset_cache
        _toolset_cache.clear()

    @classmethod
    def get_cache_stats(cls):
        """Get cache statistics for monitoring."""
        return {
            "toolset_cache_size": len(_toolset_cache),
            "cached_agent_types": list(_toolset_cache.keys())
        }

def create_function_tool_for_agent(agent_type: str) -> List[Any]:
    define_mcp_create_image =FunctionTool(
            name="mcp_create_image",
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Detailed description of the image to generate"
                    }
                },
                "required": ["prompt"],
                "additionalProperties": False
            },
            description="Generate an AI image based on a text description using the GPT image model of choice.",
            strict=True
        )
    define_mcp_product_recommendations = FunctionTool(
        name="mcp_product_recommendations",
        parameters={
            "type": "object",
            "properties": {
                    "question": {
                        "type": "string",
                        "description": "Natural language user query describing what products they're looking for"
                    }
                },
                "required": ["question"],
                "additionalProperties": False
            },
            description="Search for product recommendations based on user query.",
            strict=True
        )
    define_mcp_calculate_discount = FunctionTool(
        name="mcp_calculate_discount",
        parameters={
            "type": "object",
            "properties": {
                    "customer_id": {
                        "type": "string",
                        "description": "The ID of the customer."
                    }
                },
                "required": ["customer_id"],
                "additionalProperties": False
            },
            description="Calculate the discount based on customer data.",
            strict=True
        )
    define_mcp_inventory_check = FunctionTool(
        name="mcp_inventory_check",
        parameters={
            "type": "object",
            "properties": {
                    "product_list": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        },
                        "description": "List of product IDs to check inventory for."
                    }
                },
            "required": ["product_list"],
            "additionalProperties": False
        },
        description="Check inventory for a product using MCP client.",
        strict=True
        )

    functions = []

    if agent_type == "interior_designer":
        functions = [define_mcp_create_image, define_mcp_product_recommendations]
    elif agent_type == "customer_loyalty":
        functions = [define_mcp_calculate_discount]
    elif agent_type == "inventory_agent":
        functions = [define_mcp_inventory_check]
    elif agent_type == "cart_manager":
        functions = []
    elif agent_type == "cora":
        functions = [define_mcp_product_recommendations]
    return functions
