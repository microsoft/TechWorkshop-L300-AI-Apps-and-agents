import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from typing import List, Callable, Set, Any, Dict
from azure.ai.agents.models import (
    MessageImageUrlParam,
    MessageInputTextBlock,
    MessageInputImageUrlBlock,
    FunctionTool, ToolSet
)

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
_toolset_cache: Dict[str, ToolSet] = {}

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
def mcp_inventory_check(product_dict: dict) -> list:
    """
    Check inventory for products using MCP client.
    
    Args:
        product_dict (dict): Keys are product names, values are product IDs.
    
    Returns:
        list: Each element is the inventory info for the product ID if found, otherwise None.
    """
    async def _check_inventory():
        mcp_client = await get_mcp_client(_mcp_server_url)
        results = []
        for product_name, product_id in product_dict.items():
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
        
        self.project_client.agents.enable_auto_function_calls(tools = self.toolset)

    def _get_or_create_toolset(self, agent_type: str) -> ToolSet:
        """Get cached toolset or create new one to avoid repeated initialization."""
        if agent_type in _toolset_cache:
            return _toolset_cache[agent_type]
        
        functions = create_function_tool_for_agent(agent_type)

        toolset = ToolSet()
        toolset.add(functions)
        self.project_client.agents.enable_auto_function_calls(toolset)
        
        # Cache the toolset
        _toolset_cache[agent_type] = toolset
        return toolset

    def run_conversation_with_image(self, input_message: str = "", image_path: str = ""):
        start_time = time.time()
        span = trace.get_current_span()
        span.set_attribute("message_from_user", input_message)
        span.set_attribute("image_from_user", image_path)
        thread_id = self.thread_id
        url_param = MessageImageUrlParam(url=image_path, detail="high")
        content_blocks = [
            MessageInputTextBlock(text=input_message),
            MessageInputImageUrlBlock(image_url=url_param),
        ]
        message = self.project_client.agents.messages.create(
            thread_id=thread_id,
            role="user",
            content=content_blocks
        )
        print(f"[TIMELOG] Message creation took: {time.time() - start_time:.2f}s")
        run_start = time.time()
        run = self.project_client.agents.runs.create_and_process(thread_id=thread_id, agent_id=self.agent_id, tool_choice = "auto")
        print(f"[TIMELOG] Thread run took: {time.time() - run_start:.2f}s")
        messages = self.project_client.agents.messages.list(thread_id=thread_id)
        for message in messages:
            pass  # Only time logs are kept
        print(f"[TIMELOG] Total run_conversation_with_image time: {time.time() - start_time:.2f}s")

    
    def run_conversation_with_text(self, input_message: str = ""):
        start_time = time.time()
        thread_id = self.thread_id
        message = self.project_client.agents.messages.create(
            thread_id=thread_id,
            role="user",
            content=input_message,
        )
        print(f"[TIMELOG] Message creation took: {time.time() - start_time:.2f}s")
        run_start = time.time()
        run = self.project_client.agents.runs.create_and_process(thread_id=thread_id, agent_id=self.agent_id, tool_choice = "auto")
        print(f"[TIMELOG] Thread run took: {time.time() - run_start:.2f}s")
        messages = self.project_client.agents.messages.list(thread_id=thread_id)
        for message in messages:
            yield message.content
        print(f"[TIMELOG] Total run_conversation_with_text time: {time.time() - start_time:.2f}s")

    def _run_conversation_sync(self, input_message: str = ""):
        """Optimized synchronous conversation runner with better error handling."""
        thread_id = self.thread_id
        start_time = time.time()
        
        try:
            # Create message
            self.project_client.agents.messages.create(
                thread_id=thread_id,
                role="user",
                content=input_message,
            )
            print(f"[TIMELOG] Message creation took: {time.time() - start_time:.2f}s")
            
            # Run agent with timeout handling
            run_start = time.time()
            run = self.project_client.agents.runs.create_and_process(
                thread_id=thread_id, agent_id=self.agent_id, tool_choice="auto"
            )

            print(f"[TIMELOG] Thread run took: {time.time() - run_start:.2f}s")

            # Optimized message retrieval - only get the latest message instead of listing all
            messages_start = time.time()
            messages = list(self.project_client.agents.messages.list(thread_id=thread_id, limit=1))
            print(f"[TIMELOG] Message retrieval took: {time.time() - messages_start:.2f}s")
            
            # Find the latest assistant message (messages are most recent first)
            assistant_msg = next((m for m in messages if m.role == "assistant"), None)
            
            if assistant_msg:
                # Robustly extract all text values from all blocks
                content = assistant_msg.content
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
            else:
                return [""]
                
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


def create_function_tool_for_agent(agent_type: str) -> FunctionTool:
    
    default_functions: Set[Callable[..., Any]] = set()
    functions = FunctionTool(default_functions)

    if agent_type == "interior_designer":
        interior_functions: Set[Callable[..., Any]] = {mcp_create_image, mcp_product_recommendations}
        functions = FunctionTool(interior_functions)
    elif agent_type == "customer_loyalty":
        loyalty_functions: Set[Callable[..., Any]] = {mcp_calculate_discount}
        functions = FunctionTool(loyalty_functions)
    elif agent_type == "inventory_agent":
        inventory_functions: Set[Callable[..., Any]] = {mcp_inventory_check}
        functions = FunctionTool(inventory_functions)
    elif agent_type == "cart_manager":
        # Cart manager uses conversation context, minimal tools needed
        cart_functions: Set[Callable[..., Any]] = set()
        functions = FunctionTool(cart_functions)
    elif agent_type == "cora":
        # Cora is a general assistant with product recommendations
        cora_functions: Set[Callable[..., Any]] = {mcp_product_recommendations}
        functions = FunctionTool(cora_functions)
    return functions