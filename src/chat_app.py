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
from azure.monitor.opentelemetry import configure_azure_monitor
from azure.ai.agents.telemetry import trace_function

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
# from app.tools.singleAgentExample import generate_response
from app.tools.aiSearchTools import product_recommendations
from app.tools.imageCreationTool import create_image
from app.servers.mcp_inventory_server import mcp as inventory_mcp
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

application_insights_connection_string = os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"]
configure_azure_monitor(connection_string=application_insights_connection_string)
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
inventory_mcp_app = inventory_mcp.sse_app()
app.mount("/mcp-inventory/", inventory_mcp_app)
project_endpoint = os.environ.get("FOUNDRY_ENDPOINT")
if not project_endpoint:
    raise ValueError("FOUNDRY_ENDPOINT environment variable is required")
project_client = AIProjectClient(
    endpoint=project_endpoint,
    credential=DefaultAzureCredential(),
)

# # LLM client for the handoff service.
# # Retrieves an AzureOpenAI client from the project client.
# # Handoff service determines which agent to route to based on intent classification.
# # The default for this is Cora, the general shopping assistant.
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
            "phi_4_api_key": bool(validated_env_vars.get('phi_4_api_key')),
            "foundry_endpoint": bool(validated_env_vars.get('FOUNDRY_ENDPOINT')),
            "foundry_key": bool(validated_env_vars.get('FOUNDRY_KEY')),
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

            # # Single-agent example
            # try:
            #     response = generate_response(user_message)
            #     await websocket.send_text(fast_json_dumps({"answer": response, "agent": "single", "cart": persistent_cart}))
            # except Exception as e:
            #     logger.error("Error during single-agent response generation", exc_info=True)
            #     await websocket.send_text(fast_json_dumps({"answer": "Error during single-agent response generation", "error": str(e), "cart": persistent_cart}))

            # Multi-agent example with MCP inventory server and handoff service
            # Run customer loyalty task only once when session starts
            customer_id = "CUST001"
            if not customer_loyalty_executed:
                asyncio.create_task(run_customer_loyalty_task(customer_id))
                customer_loyalty_executed = True
            # Run handoff service
            try:
                print("Entering handoff service.")
                handoff_start_time = time.time()
                formatted_history = format_chat_history(redact_bad_prompts_in_history(chat_history, bad_prompts))
                logger.info("Handoff agent execution initiated - commencing agent selection protocol")
                with tracer.start_as_current_span("Handoff Intent Classification"):
                    # Intent classification using structured outputs for reliable routing
                    intent_result = handoff_service.classify_intent(
                        user_message=user_message,
                        session_id=session_id,
                        chat_history=formatted_history
                    )

                # Extract agent information from classification result
                agent_name = intent_result["agent_id"]  # e.g., "cora", "cart_manager"
                agent_selected = validated_env_vars.get(agent_name)  # Get agent ID from environment

                logger.info(f"Intent classification: domain={intent_result['domain']}, "
                           f"confidence={intent_result['confidence']:.2f}, "
                           f"reasoning={intent_result['reasoning']}")
                print(f"Intent classification: domain={intent_result['domain']}, "
                           f"confidence={intent_result['confidence']:.2f}, "
                           f"reasoning={intent_result['reasoning']}")
                log_timing("Handoff Processing", handoff_start_time, 
                          f"Selected: {agent_name} (confidence: {intent_result['confidence']:.2f})")
                
                # Check if agent selection failed
                if not agent_selected or not agent_name:
                    await websocket.send_text(fast_json_dumps({
                        "answer": "Sorry, I could not determine the right agent.",
                        "agent": None,
                        "cart": persistent_cart
                    }))
                    continue
            except Exception as e:
                logger.error("Error during handoff classification", exc_info=True)
                await websocket.send_text(fast_json_dumps({
                    "answer": "Error during handoff classification",
                    "error": str(e),
                    "cart": persistent_cart
                }))
                continue
            
            # =============================================================================
            # UNIFIED AGENT EXECUTION: Context Enrichment & Agent Processing
            # =============================================================================
            # All agents follow a consistent execution pattern:
            # 1. Context Enrichment: Add multimodal data (images, products)
            # 2. Agent-Specific Preparation: Format context based on agent needs
            # 3. Agent Execution: Use AgentProcessor for streaming responses
            # 4. Response Handling: Parse output, update state, send to user
            # =============================================================================
            try:
                agent_execution_start_time = time.time()
                logger.info(f"{agent_name} agent execution initiated")
                
                # Initialize context enrichment variables
                enriched_message = user_message  # Base message
                image_data = None                # Image description from vision analysis
                products = None                  # Product recommendations from AI Search
                
                # =============================================================================
                # MULTIMODAL CONTENT PROCESSING: Enrich context with visual data
                # =============================================================================
                # Process images to add visual understanding to the agent's context.
                # This enables contextually aware recommendations based on what the user shares.
                # =============================================================================
                
                # Process multimodal inputs if present
                if image_url:
                    # IMAGE ANALYSIS: Extract visual information from uploaded images
                    # Uses phi-4 vision model with caching to avoid re-analyzing same image
                    # Results are cached for the session and shared across agents
                    image_start_time = time.time()
                    log_cache_status(image_cache, image_url)
                    image_data = await get_cached_image_description(image_url, image_cache)
                    log_timing("Image Analysis", image_start_time, f"URL: {image_url[:50]}...")
                    
                    # Send analysis message to user (provides feedback during processing)
                    analysis_msg = get_rotating_message(IMAGE_ANALYSIS_MESSAGES)
                    await websocket.send_text(fast_json_dumps({
                        "answer": analysis_msg,
                        "agent": agent_name,
                        "cart": persistent_cart
                    }))
                    logger.info("Image analysis completed")
                
                # =============================================================================
                # PRODUCT RECOMMENDATIONS: Cosmos DB integration for contextual products
                # =============================================================================
                # For agents that make product recommendations, query Cosmos DB with enriched
                # context (user message + visual analysis). This provides the agent with
                # relevant product options to suggest based on user needs and visual context.
                # =============================================================================
                
                # Get product recommendations for relevant agents
                if agent_name in ["interior_designer", "interior_designer_create_image", "cora"]:
                    product_start_time = time.time()
                    # Build search query from all available context
                    search_query = user_message
                    if image_data:
                        # Add visual context to search (e.g., "blue living room" → search for blue paint)
                        search_query += f" {image_data} paint accessories, paint sprayers, drop cloths, painters tape"
                    
                    products = product_recommendations(search_query)
                    log_timing("Product Recommendations", product_start_time, f"Found: {len(products) if products else 0}")
                    logger.info("Product recommendations completed")
                
                # =============================================================================
                # CONTEXT ENRICHMENT: Build complete message with all available context
                # =============================================================================
                # Combine user message with multimodal analysis and product data to create
                # a comprehensive context for the agent. This enables more accurate and
                # contextually relevant responses.
                # =============================================================================
                
                # Build enriched message with all context
                if image_data or products:
                    context_parts = []
                    if image_data:
                        context_parts.append(f"Image description: {image_data}")
                    if products:
                        context_parts.append(f"Available products: {fast_json_dumps(products)}")
                    
                    # Prepend user message, append all enriched context
                    enriched_message = f"{user_message}\n\n" + "\n".join(context_parts)
                
                # =============================================================================
                # AGENT EXECUTION: Unified pattern for all agents (no if-else branching!)
                # =============================================================================
                # All agents now follow the same execution flow:
                # 1. Prepare agent-specific context (raw_io_history, conversation, enriched message)
                # 2. Get or create AgentProcessor for the selected agent
                # 3. Stream response chunks from the agent
                # 4. Parse structured response and update session state
                #
                # SPECIAL CASE: interior_designer_create_image uses gpt-image-1 instead of agent
                # =============================================================================
                
                # Execute agent based on type - unified agent processor pattern
                bot_reply = ""
                
                with tracer.start_as_current_span(f"{agent_name.title()} Agent Call"):
                    # =================================================================
                    # SPECIAL CASE: Image Creation (uses gpt-image-1, not agent processor)
                    # =================================================================
                    # This is the only case that doesn't use the unified agent pattern
                    # because it generates images via gpt-image-1 API rather than conversing
                    if agent_name == "interior_designer_create_image":
                        # Acknowledge image creation request
                        thank_you_msg = get_rotating_message(IMAGE_CREATE_MESSAGES)
                        await websocket.send_text(fast_json_dumps({
                            "answer": thank_you_msg,
                            "agent": "interior_designer",
                            "cart": persistent_cart
                        }))
                        
                        # Use persistent image URL for context (e.g., "make this room blue")
                        if persistent_image_url:
                            image_data = await get_cached_image_description(persistent_image_url, image_cache)
                            enriched_message = f"{user_message} {image_data}"
                        
                        # Create image using gpt-image-1
                        image = create_image(text=enriched_message, image_url=persistent_image_url)
                        
                        # Build response with generated image URL
                        response_data = {
                            "answer": "Here is the requested image",
                            "products": "",
                            "discount_percentage": session_discount_percentage or "",
                            "image_url": image,
                            "additional_data": "",
                            "cart": persistent_cart
                        }
                        
                        # Send response
                        response_json = fast_json_dumps(response_data)
                        raw_io_history.append({"output": response_json, "cart": persistent_cart})
                        
                        bot_answer = response_data.get("answer", "")
                        product_names = extract_product_names_from_response(response_data)
                        chat_history.append(("bot", bot_answer + product_names))
                        
                        await websocket.send_text(response_json)
                        log_timing("Agent Execution", agent_execution_start_time, f"Agent: {agent_name}")
                        continue  # Skip common response handling
                    
                    # =================================================================
                    # AGENT-SPECIFIC CONTEXT PREPARATION
                    # =================================================================
                    # Each agent type receives context tailored to its needs:
                    # - cart_manager: Full raw I/O history for tracking cart state changes
                    # - cora: Formatted conversation history for contextual responses
                    # - Others: Enriched message with multimodal + product data
                    # =================================================================
                    
                    # Prepare context based on agent type
                    agent_context = enriched_message  # Default: enriched message
                    
                    # Cart manager needs full raw_io_history for state management
                    if agent_name == "cart_manager":
                        # Provide complete interaction history so cart_manager can track
                        # all add/remove operations and maintain accurate cart state
                        agent_context = f"{enriched_message}\n\nRAW_IO_HISTORY:\n{fast_json_dumps(list(raw_io_history), option=orjson.OPT_INDENT_2)}"
                    
                    # Cora needs conversation history for contextual dialogue
                    elif agent_name == "cora":
                        # Provide formatted chat history so cora can reference previous
                        # conversation turns and maintain coherent multi-turn dialogue
                        agent_context = f"{formatted_history}\n\nUser: {enriched_message}"
                    
                    # =================================================================
                    # UNIFIED AGENT PROCESSOR EXECUTION (All agents use this pattern!)
                    # =================================================================
                    # Get or create an AgentProcessor instance for the selected agent.
                    # The processor manages the agent's execution lifecycle and streams
                    # responses back token-by-token for a better user experience.
                    #
                    # This replaces the old if-else branching with a single unified flow.
                    # =================================================================
                    
                    # All agents use unified agent processor pattern
                    processor = get_or_create_agent_processor(
                        agent_id=agent_selected,     # Agent ID from environment variables
                        agent_type=agent_name,       # Agent type (cora, cart_manager, etc.)
                        thread_id=None,              # Conversation thread for stateful agents
                        project_client=project_client  # Foundry client for agent execution
                    )
                    
                    # Stream response from agent (yields chunks as they're generated)
                    async for msg in processor.run_conversation_with_text_stream(input_message=agent_context):
                        bot_reply = extract_bot_reply(msg)  # Extract text from streaming message
                
                logger.info(f"{agent_name} agent execution completed")
                
                log_timing("Agent Execution", agent_execution_start_time, f"Agent: {agent_name}")
                
                # =============================================================================
                # RESPONSE PROCESSING: Parse structured output and update session state
                # =============================================================================
                # Agents return structured JSON responses with fields like answer, products,
                # discount_percentage, image_url, etc. We parse this, update session state,
                # and send formatted response to the user.
                # =============================================================================
                
                # Parse the response first to get structured fields (answer, products, etc.)
                parsed_response = parse_agent_response(bot_reply)
                parsed_response["agent"] = agent_name  # Override agent field to show which agent responded
                
                # =============================================================================
                # CART STATE UPDATE: Persist cart changes from cart_manager agent
                # =============================================================================
                # The cart_manager agent returns an updated cart array in its response.
                # We persist this to the session so all subsequent messages see the updated cart.
                # =============================================================================
                
                # Update persistent_cart if cart_manager returned a cart
                if agent_name == "cart_manager" and "cart" in parsed_response:
                    if isinstance(parsed_response.get("cart"), list):
                        persistent_cart = parsed_response["cart"]
                        logger.info(f"Cart updated by cart_manager: {len(persistent_cart)} items")
                
                # =============================================================================
                # CONVERSATION HISTORY UPDATE: Maintain chat context for multi-turn dialogue
                # =============================================================================
                # Add the bot's response to chat history so future messages have context.
                # Clean the history to remove large product data (keep only product names).
                # =============================================================================
                
                # Add the bot reply to chat history with products if available
                bot_answer = parsed_response.get("answer", bot_reply or "")
                product_names = extract_product_names_from_response(parsed_response)
                chat_history.append(("bot", bot_answer + product_names))
                print(f"Chat history after bot reply: {chat_history}")
                
                # Clean the conversation history to remove large product data (keep compact)
                chat_history = clean_conversation_history(chat_history)
                print(f"Chat history after bot reply: {chat_history}")
                
                # =============================================================================
                # DISCOUNT PERSISTENCE: Maintain customer loyalty tier across session
                # =============================================================================
                # Once the customer_loyalty agent calculates a discount, persist it across
                # all subsequent responses so the user sees consistent discount information.
                # =============================================================================
                
                # Update session discount_percentage if a new one is received
                if parsed_response.get("discount_percentage"):
                    session_discount_percentage = parsed_response["discount_percentage"]
                
                # Include session discount_percentage in all responses if available
                if session_discount_percentage and not parsed_response.get("discount_percentage"):
                    parsed_response["discount_percentage"] = session_discount_percentage
                
                # =============================================================================
                # RESPONSE TRANSMISSION: Send structured response to user
                # =============================================================================
                # Send the final response with all fields (answer, products, cart, discount, etc.)
                # Also append to raw_io_history for cart_manager's state tracking.
                # =============================================================================
                
                # When sending any other response, also append to raw_io_history
                response_json = fast_json_dumps({**parsed_response, "cart": persistent_cart})
                raw_io_history.append({"output": response_json, "cart": persistent_cart})
                await websocket.send_text(response_json)
                
                # =============================================================================
                # DELAYED LOYALTY RESPONSE: Send loyalty message after cart operations
                # =============================================================================
                # The customer_loyalty agent runs in background at session start.
                # Its response is delayed until after the first cart_manager operation,
                # ensuring users see their loyalty tier after interacting with the cart.
                # =============================================================================
                
                # After cart_manager response, send loyalty response if available (only once per session)
                if agent_name == "cart_manager" and session_loyalty_response and not loyalty_response_sent:
                    loyalty_response_with_cart = {**session_loyalty_response, "cart": persistent_cart}
                    await websocket.send_text(fast_json_dumps(loyalty_response_with_cart))
                    loyalty_response_sent = True
                    
            # =============================================================================
            # ERROR HANDLING: Failure during agent execution
            # =============================================================================
            # If agent execution fails, catch the exception, log it for debugging,
            # and send a user-friendly error message with the current cart state.
            # =============================================================================
            except Exception as e:
                logger.error("Error in agent execution", exc_info=True)
                try:
                    await websocket.send_text(fast_json_dumps({
                        "answer": "Internal server error",
                        "error": str(e),
                        "cart": persistent_cart
                    }))
                except Exception:
                    pass  # If even error sending fails, silently continue
    
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