import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from typing import List, Callable, Set, Any, Dict
from azure.ai.projects.models import FunctionTool
from openai.types.responses.response_input_param import FunctionCallOutput, ResponseInputParam
import json

# Import MCP client for tool execution
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from app.servers.mcp_inventory_client import MCPShopperToolsClient

from opentelemetry import trace
from azure.monitor.opentelemetry import configure_azure_monitor
from azure.ai.agents.telemetry import trace_function
import asyncio
from concurrent.futures import ThreadPoolExecutor
import time
from opentelemetry.instrumentation.openai_v2 import OpenAIInstrumentor

# # Enable Azure Monitor tracing
application_insights_connection_string = os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"]
configure_azure_monitor(connection_string=application_insights_connection_string)
OpenAIInstrumentor().instrument()

# scenario = os.path.basename(__file__)
# tracer = trace.get_tracer(__name__)

# Increase thread pool size for better concurrency
_executor = ThreadPoolExecutor(max_workers=8)

# Cache for toolset configurations to avoid repeated initialization
_toolset_cache: Dict[str, List[FunctionTool]] = {}

from app.servers.mcp_inventory_client import get_mcp_client

_mcp_server_url = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp-inventory/sse")

# MCP-based tool wrapper functions
async def mcp_create_image(prompt: str) -> str:
    """
    Generate an AI image based on a text description using DALL-E.
    
    Args:
        prompt: Detailed description of the image to generate
        size: Image size (e.g., '1024x1024'), defaults to '1024x1024'
    
    Returns:
        URL or path to the generated image
    """
    
    mcp_client = await get_mcp_client(_mcp_server_url)
    """Wrapper for create_image using MCP client"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(
            mcp_client.call_tool("generate_product_image", {"prompt": prompt})
        )
        return result
    finally:
        loop.close()

def mcp_product_recommendations(question: str) -> str:
    """
    Search for product recommendations based on user query.
    
    Args:
        question: Natural language user query describing what products they're looking for
    
    Returns:
        Product details including ID, name, category, description, image URL, and price
    """
    async def _get_product_recommendations():
        mcp_client = await get_mcp_client(_mcp_server_url)
        results = await mcp_client.call_tool("get_product_recommendations", {"question": question})
        return results
    # Run async function in event loop
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(_get_product_recommendations())


def mcp_calculate_discount(customer_id: str) -> str:
    """
    Calculate the discount based on customer data.

    Args:
        CustomerID (str): The ID of the customer.
    
    Returns:
        float: The calculated discount amount and percentage.
    """
    async def _calculate():
        mcp_client = await get_mcp_client(_mcp_server_url)
        discount = await mcp_client.call_tool("get_customer_discount", {"customer_id": customer_id})
        return discount
    
    # Run async function in event loop
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(_calculate())

# Create wrapper function that uses MCP client
def mcp_inventory_check(product_list: List[str]) -> list:
    """
    Check inventory for products using MCP client.
    
    Args:
        product_list (List[str]): List of product IDs to check inventory for.
    
    Returns:
        list: Each element is the inventory info for the product ID if found, otherwise None.
    """
    async def _check_inventory():
        mcp_client = await get_mcp_client(_mcp_server_url)
        results = []
        for product_id in product_list:
            try:
                inventory_data = await mcp_client.check_inventory(product_id)
                results.append(inventory_data)
            except Exception as e:
                print(f"Error checking inventory for {product_id}: {e}")
                results.append(None)
        return results
    
    # Run async function in event loop
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(_check_inventory())

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
        
        # Cache the toolset
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

    def _run_conversation_sync(self, input_message: str = ""):
        """Optimized synchronous conversation runner with better error handling."""
        thread_id = self.thread_id
        start_time = time.time()
        print("Running sync!")
        
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

            # Message retrieval
            message = openai_client.responses.create(
                conversation=thread_id,
                extra_body={"agent": {"name": self.agent_id, "type": "agent_reference"}},
                input="",
                stream=False
            )

            messages_start = time.time()
            print(f"[TIMELOG] Message retrieval took: {time.time() - messages_start:.2f}s")

            if len(message.output_text) == 0:
                print("[DEBUG] No output text found in message. Looking for function calls.")
                # No output text, check for function calls
                input_list : ResponseInputParam = []
                for item in message.output:
                    if item.type == "function_call":
                        # Perform the function call first, then extract final text value below
                        if item.name == "mcp_create_image":
                            func_result = mcp_create_image(**json.loads(item.arguments))
                        elif item.name == "mcp_product_recommendations":
                            func_result = mcp_product_recommendations(**json.loads(item.arguments))
                        elif item.name == "mcp_calculate_discount":
                            func_result = mcp_calculate_discount(**json.loads(item.arguments))
                        elif item.name == "mcp_inventory_check":
                            func_result = mcp_inventory_check(**json.loads(item.arguments))
                        else:
                            func_result = f"Unknown function: {item.name}"
                        print(f"[DEBUG] Function {item.name} executed with result: {func_result}")

                        input_list.append(FunctionCallOutput(
                            type="function_call_output",
                            call_id=item.call_id,
                            output=json.dumps({"result": func_result})
                        ))

                # Re-run response creation to get final text output after function calls
                print("[DEBUG] Re-running response creation to get final text output after function calls.")
                message = openai_client.responses.create(
                    input=input_list,
                    previous_response_id=message.id,
                    extra_body={"agent": {"name": self.agent_id, "type": "agent_reference"}},
                )


            # Robustly extract all text values from all blocks
            content = message.output_text
            if isinstance(content, list):
                text_blocks = []
                for j, block in enumerate(content):
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
                    # Join all text blocks with newlines if multiple
                    result = ['\n'.join(text_blocks)]
                    return result
            
            # Fallback: return stringified content
            result = [str(content)]
            return result
                
        except Exception as e:
            print(f"[ERROR] Conversation failed: {str(e)}")
            return [f"Error processing message: {str(e)}"]

    async def run_conversation_with_text_stream(self, input_message: str = ""):
        """Async wrapper for conversation processing with better error handling."""
        print(f"[DEBUG] Async conversation pipeline initiated - commencing message processing protocol", flush=True)
        loop = asyncio.get_event_loop()
        try:
            messages = await loop.run_in_executor(
                _executor, self._run_conversation_sync, input_message
            )
            for i, msg in enumerate(messages):
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
        # Cart manager uses conversation context, minimal tools needed
        functions = []
    elif agent_type == "cora":
        # Cora is a general assistant with product recommendations
        functions = [define_mcp_product_recommendations]
    return functions