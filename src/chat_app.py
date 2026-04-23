# Core Libraries
import os
import asyncio
import datetime
import time
import uuid
from collections import deque
from typing import Deque, Tuple, Optional, Dict
from concurrent.futures import ThreadPoolExecutor
import orjson  # Faster JSON library
from dotenv import load_dotenv
from opentelemetry import trace
import logging
# from opentelemetry.instrumentation.openai_v2 import OpenAIInstrumentor

# Azure & OpenAI Imports
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from openai import AzureOpenAI
# from azure.monitor.opentelemetry import configure_azure_monitor
# from azure.ai.agents.telemetry import trace_function

# FastAPI Imports
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

# Custom Utilities
from utils.history_utils import (
    format_chat_history, redact_bad_prompts_in_history, clean_conversation_history,
    parse_conversation_history
)
from utils.response_utils import (
    extract_bot_reply, parse_agent_response, extract_product_names_from_response
)
from utils.log_utils import log_timing, log_cache_status
from utils.env_utils import load_env_vars, validate_env_vars
from utils.message_utils import (
    IMAGE_UPLOAD_MESSAGES, IMAGE_CREATE_MESSAGES, IMAGE_ANALYSIS_MESSAGES,
    get_rotating_message, fast_json_dumps
)

# Agent Imports
from app.tools.understandImage import get_image_description
from services.agent_service import get_or_create_agent_processor
# from handlers.single_agent_handler import handle_single_agent
from handlers.multi_agent_handler import (
    classify_intent, enrich_context, execute_agent,
    handle_image_creation, process_response,
)
from services.handoff_service import HandoffService


load_dotenv()
env_vars = load_env_vars()
validated_env_vars = validate_env_vars(env_vars)

# Configure structured logging
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global thread pool executor for CPU-bound operations
thread_pool = ThreadPoolExecutor(max_workers=4)

# application_insights_connection_string = os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"]
# configure_azure_monitor(connection_string=application_insights_connection_string)
# OpenAIInstrumentor().instrument()

scenario = os.path.basename(__file__)
tracer = trace.get_tracer(__name__)

async def get_cached_image_description(image_url: str, image_cache: dict) -> str:
    """Get image description with caching. If not in cache, fetch and store it."""
    if image_url in image_cache:
        logger.info("Using cached image description", extra={"url": image_url[:50], "cache_size": len(image_cache)})
        return image_cache[image_url]
    
    logger.info("Fetching new image description", extra={"url": image_url[:50]})
    try:
        # Use thread pool executor for CPU-bound operations
        loop = asyncio.get_event_loop()
        description = await loop.run_in_executor(thread_pool, get_image_description, image_url)
        image_cache[image_url] = description
        logger.info("Cached image description", extra={"url": image_url[:50]})
        return description
    except Exception as e:
        logger.error("Failed to get image description", extra={"url": image_url[:50], "error": str(e)})
        return ""

async def pre_fetch_image_description(image_url: str, image_cache: dict):
    """Pre-fetch image description asynchronously without blocking."""
    if image_url and image_url not in image_cache:
        logger.info("Pre-fetching image description", extra={"url": image_url[:50]})
        try:
            loop = asyncio.get_event_loop()
            description = await loop.run_in_executor(thread_pool, get_image_description, image_url)
            image_cache[image_url] = description
            logger.info("Pre-fetched and cached image description", extra={"url": image_url[:50]})
        except Exception as e:
            logger.error("Failed to pre-fetch image description", extra={"url": image_url[:50], "error": str(e)})

# Safe operation wrapper for better error handling
async def safe_operation(operation, fallback_value=None, operation_name="Unknown"):
    """Safely execute an operation with proper error handling."""
    try:
        return await operation()
    except (ValueError, TypeError) as e:
        logger.warning(f"{operation_name} failed: {e}")
        return fallback_value
    except Exception as e:
        logger.error(f"Unexpected error in {operation_name}: {e}", exc_info=True)
        return fallback_value

app = FastAPI()
#set up MCP inventory server as a mounted app
# inventory_mcp_app = inventory_mcp.sse_app()
# app.mount("/mcp-inventory/", inventory_mcp_app)
project_endpoint = os.environ.get("FOUNDRY_ENDPOINT")
if not project_endpoint:
    raise ValueError("FOUNDRY_ENDPOINT environment variable is required")
project_client = AIProjectClient(
    endpoint=project_endpoint,
    credential=DefaultAzureCredential(),
)

# LLM client for the handoff service.
# Retrieves an AzureOpenAI client from the project client.
# Handoff service determines which agent to route to based on intent classification.
# The default for this is Cora, the general shopping assistant.
llm_client = project_client.get_openai_client()

handoff_service = HandoffService(
    azure_openai_client=llm_client,
    deployment_name=validated_env_vars['gpt_deployment'],
    default_domain="cora",
    lazy_classification=True
)

@app.get("/")
async def get():
    chat_html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chat.html')
    with open(chat_html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/health")
async def health_check():
    """Health check endpoint for Azure Web App."""
    return {
        "status": "healthy",
        "timestamp": datetime.datetime.now().isoformat(),
        "environment_vars_configured": {
            "phi_4_endpoint": bool(validated_env_vars.get('phi_4_endpoint')),
            "foundry_endpoint": bool(validated_env_vars.get('FOUNDRY_ENDPOINT')),
            "gpt_endpoint": bool(os.environ.get("gpt_endpoint"))
        }
    }

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    session_start_time = time.time()
    session_id = str(uuid.uuid4())
    logger.info("WebSocket Session Started")
    
    await websocket.accept()

    chat_history: Deque[Tuple[str, str]] = deque(maxlen=5)

    # Session-level state variables
    customer_loyalty_executed = False               # Flag to track if customer loyalty task has been executed
    session_discount_percentage = ""                # Session-level variable to track discount_percentage
    session_loyalty_response = None                 # Store the full loyalty response for later
    loyalty_response_sent = False                   # Flag to track if loyalty response has been sent to user
    persistent_image_url = ""                       # Session-level variable to track persistent image URL
    persistent_cart = []                            # Session-level variable to track persistent cart state
    image_cache = {}                                # Dictionary to cache image URLs and their descriptions
    bad_prompts = set()                             # Set to track bad prompts for redaction
    raw_io_history = deque(maxlen=100)              # Use deque with maxlen for raw_io_history to prevent unbounded growth

    async def run_customer_loyalty_task(customer_id):
        start_time = time.time()
        with tracer.start_as_current_span("Run Customer Loyalty Thread"):
            nonlocal session_discount_percentage, session_loyalty_response
            message = f"Calculate discount for the customer with id {customer_id}"
            customer_loyalty_id = validated_env_vars.get('customer_loyalty')
            if not customer_loyalty_id:
                session_loyalty_response = {"answer": "Customer loyalty agent not configured.", "agent": "customer_loyalty"}
                log_timing("Customer Loyalty Task", start_time, "Agent not configured")
                return
                
            processor = get_or_create_agent_processor(
                agent_id=customer_loyalty_id,
                agent_type="customer_loyalty",
                thread_id=None,
                project_client=project_client
            )
            bot_reply = ""
            async for msg in processor.run_conversation_with_text_stream(input_message=message):
                bot_reply = extract_bot_reply(msg)
            parsed_response = parse_agent_response(bot_reply)
            parsed_response["agent"] = "customer_loyalty"  # Override agent field
            
            # Store the discount_percentage for the session
            if parsed_response.get("discount_percentage"):
                session_discount_percentage = parsed_response["discount_percentage"]
            session_loyalty_response = parsed_response  # Store the full response for later
            # Do NOT send the response here!
            log_timing("Customer Loyalty Task", start_time, f"Discount: {session_discount_percentage}")

    try:
        while True:
            message_start_time = time.time()
            try:
                data = await websocket.receive_text()
                parsed = orjson.loads(data)  # Use orjson for faster parsing
                user_message = parsed.get("message", "")
                has_image = parsed.get("has_image", False)
                image_url = parsed.get("image_url", "")
                conversation_history = parsed.get("conversation_history", "")
                cart = parsed.get("cart", [])
                
                # # Update persistent image URL if a new one is provided
                if image_url:
                    persistent_image_url = image_url
                    logger.info("Persistent image URL updated", extra={"url": persistent_image_url})
                    log_cache_status(image_cache, image_url)
                    # Pre-fetch the image description asynchronously
                    asyncio.create_task(pre_fetch_image_description(image_url, image_cache))
                
                # Append user message to raw_io_history
                raw_io_history.append({"input": user_message, "cart": persistent_cart})
                log_timing("Message Parsing", message_start_time, f"Message length: {len(user_message)} chars")
            except WebSocketDisconnect:
                logger.info("WebSocket connection terminated - client disconnected from endpoint")
                break
            except Exception as e:
                logger.error("Error parsing message", exc_info=True)
                user_message = data if 'data' in locals() else ''
                image_data = None
                has_image = False
                image_url = None
                conversation_history = ""
            
            chat_history = parse_conversation_history(conversation_history, chat_history, user_message)
            
            # await websocket.send_text(fast_json_dumps({"answer": "This application is not yet ready to serve results. Please check back later.", "agent": None, "cart": persistent_cart}))

            # =================================================================
            # EXERCISE 02: Single-agent example
            # Uncomment the import at the top of this file and the block below
            # to route all messages through a single Azure OpenAI agent.
            # =================================================================
            # await handle_single_agent(websocket, user_message, persistent_cart)

            # =================================================================
            # EXERCISE 02 (continued): Multi-agent example
            # Uncomment the imports at the top and the blocks below to enable
            # the full multi-agent pipeline with MCP tools and handoff service.
            # See handlers/multi_agent_handler.py for the implementation of
            # each step.
            # =================================================================

            # --- Step 1: Run customer loyalty in background (once per session) ---
            customer_id = "CUST001"
            if not customer_loyalty_executed:
                asyncio.create_task(run_customer_loyalty_task(customer_id))
                customer_loyalty_executed = True

            # --- Step 2: Classify intent and select agent ---
            try:
                formatted_history = format_chat_history(
                    redact_bad_prompts_in_history(chat_history, bad_prompts)
                )
                with tracer.start_as_current_span("Handoff Intent Classification"):
                    agent_name, agent_selected = await classify_intent(
                        handoff_service, user_message, session_id,
                        formatted_history, validated_env_vars,
                        websocket, persistent_cart,
                    )
                if not agent_name:
                    continue
            except Exception as e:
                logger.error("Error during handoff classification", exc_info=True)
                await websocket.send_text(fast_json_dumps({
                    "answer": "Error during handoff classification",
                    "error": str(e), "cart": persistent_cart,
                }))
                continue

            # --- Step 3: Enrich context and execute agent ---
            try:
                agent_execution_start_time = time.time()
            
                # Special case: image creation
                if agent_name == "interior_designer_create_image":
                    response_data = await handle_image_creation(
                        user_message, persistent_image_url, image_cache,
                        get_cached_image_description, session_discount_percentage,
                        persistent_cart, websocket,
                    )
                    await websocket.send_text(fast_json_dumps(response_data))
                    continue
            
                # Enrich message with image + product context
                enriched_message = await enrich_context(
                    user_message, agent_name, image_url, image_cache,
                    get_cached_image_description, websocket, persistent_cart,
                )
            
                # Prepare agent-specific context
                agent_context = enriched_message
                if agent_name == "cart_manager":
                    agent_context += f"\n\nRAW_IO_HISTORY:\n{fast_json_dumps(list(raw_io_history), option=orjson.OPT_INDENT_2)}"
                elif agent_name == "cora":
                    agent_context = f"{formatted_history}\n\nUser: {enriched_message}"
            
                # Execute agent
                bot_reply = await execute_agent(
                    agent_name, agent_selected, agent_context,
                    project_client, tracer,
                )
                log_timing("Agent Execution", agent_execution_start_time, f"Agent: {agent_name}")
            
                # --- Step 4: Process response and update session state ---
                parsed_response, session_discount_percentage, persistent_cart = process_response(
                    bot_reply, agent_name, session_discount_percentage, persistent_cart,
                )
            
                bot_answer = parsed_response.get("answer", bot_reply or "")
                product_names = extract_product_names_from_response(parsed_response)
                chat_history.append(("bot", bot_answer + product_names))
                chat_history = clean_conversation_history(chat_history)
            
                response_json = fast_json_dumps({**parsed_response, "cart": persistent_cart})
                raw_io_history.append({"output": response_json, "cart": persistent_cart})
                await websocket.send_text(response_json)
            
                # Send delayed loyalty response after first cart operation
                if agent_name == "cart_manager" and session_loyalty_response and not loyalty_response_sent:
                    await websocket.send_text(fast_json_dumps({**session_loyalty_response, "cart": persistent_cart}))
                    loyalty_response_sent = True
            
            except Exception as e:
                logger.error("Error in agent execution", exc_info=True)
                await websocket.send_text(fast_json_dumps({
                    "answer": "Internal server error",
                    "error": str(e), "cart": persistent_cart,
                }))
    
    # =============================================================================
    # SESSION-LEVEL ERROR HANDLING: Catch WebSocket disconnects and errors
    # =============================================================================
    # Handle normal disconnections (user closes tab) and unexpected session errors.
    # Log all errors for monitoring and debugging.
    # =============================================================================
    except WebSocketDisconnect:
        pass  # Normal disconnection, no action needed
    except Exception as e:
        logger.error("WebSocket session error", exc_info=True)
        try:
            await websocket.send_text(fast_json_dumps({
                "answer": "Internal server error",
                "error": str(e),
                "cart": persistent_cart
            }))
        except Exception:
            pass  # If sending error fails, give up gracefully
    
    # =============================================================================
    # SESSION CLEANUP: Log session duration and cleanup resources
    # =============================================================================
    # When the WebSocket connection closes (user disconnects, network error, etc.),
    # log the total session duration for monitoring and performance analysis.
    # =============================================================================
    finally:
        session_duration = time.time() - session_start_time
        logger.info(f"WebSocket Session Ended - Duration: {session_duration:.3f}s")

if __name__ == "__main__":
    import datetime
    import atexit
    
    # Register cleanup function
    def cleanup():
        """Cleanup function to close thread pool on shutdown."""
        logger.info("Shutting down thread pool executor")
        thread_pool.shutdown(wait=True)
    
    atexit.register(cleanup)
    
    now = datetime.datetime.now()
    # Format date as '19th June 4.51PM'
    day = now.day
    suffix = 'th' if 11 <= day <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
    formatted_date = now.strftime(f"%d{suffix} %B %I.%M%p")
    connection_message = f"Connection Established - Zava Chat App - {formatted_date}"
    with tracer.start_as_current_span(connection_message):
        import uvicorn
        port = int(os.environ.get("PORT", 8000))
        uvicorn.run("chat_app:app", host="0.0.0.0", port=port)