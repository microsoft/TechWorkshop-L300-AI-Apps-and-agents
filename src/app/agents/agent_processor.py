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
from azure.ai.projects.models import (
    EvaluatorIds,
    AgentEvaluationRequest 
)
from tools.imageCreationTool import create_image
from tools.discountLogic import calculate_discount
from tools.inventoryCheck import inventory_check
from tools.aiSearchTools import product_recommendations

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
os.environ["AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED"] = "true"


# scenario = os.path.basename(__file__)
# tracer = trace.get_tracer(__name__)

# Increase thread pool size for better concurrency
_executor = ThreadPoolExecutor(max_workers=8)

# Cache for toolset configurations to avoid repeated initialization
_toolset_cache: Dict[str, ToolSet] = {}

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
        
        # Create new toolset based on agent type
        if agent_type == "interior_designer":
            interior_functions: Set[Callable[..., Any]] = {create_image, product_recommendations}
            functions = FunctionTool(interior_functions)
        elif agent_type == "customer_loyalty":
            loyalty_functions: Set[Callable[..., Any]] = {calculate_discount}
            functions = FunctionTool(loyalty_functions)
        elif agent_type == "inventory_agent":
            inventory_functions: Set[Callable[..., Any]] = {inventory_check}
            functions = FunctionTool(inventory_functions)
        else:
            default_functions: Set[Callable[..., Any]] = set()
            functions = FunctionTool(default_functions)
        
        # Adding attributes to the current span
        span = trace.get_current_span()
        span.set_attribute("selected_agent", agent_type)

        toolset = ToolSet()
        toolset.add(functions)
        self.project_client.agents.enable_auto_function_calls(toolset)
        
        # Cache the toolset
        _toolset_cache[agent_type] = toolset
        return toolset

    def get_toolset(self, agent_type: str):
        """Deprecated: Use _get_or_create_toolset instead."""
        return self._get_or_create_toolset(agent_type)

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

            # Agent processor code -- causes "too many requests" if enabled
            evaluators = {
                "Relevance": {"Id": EvaluatorIds.Relevance.value},
                "Fluency": {"Id": EvaluatorIds.Fluency.value},
                "Coherence": {"Id": EvaluatorIds.Coherence.value},
            }
            # self.project_client.evaluations.create_agent_evaluation(
            #     AgentEvaluationRequest(
            #         thread_id=thread_id,
            #         run_id=run.id,
            #         evaluators=evaluators,
            #         app_insights_connection_string=application_insights_connection_string,
            #     )
            # )
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
