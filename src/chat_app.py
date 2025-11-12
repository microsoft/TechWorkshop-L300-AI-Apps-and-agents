from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import os
from dotenv import load_dotenv
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.inference.models import SystemMessage, UserMessage
from app.agents.agent_processor import AgentProcessor
from azure.ai.inference import ChatCompletionsClient
from azure.core.credentials import AzureKeyCredential
from collections import deque
from typing import Deque, Tuple, Optional, Dict
import orjson  # Faster JSON library
from openai import AzureOpenAI
from app.tools.aiSearchTools import product_recommendations
from app.tools.understandImage import get_image_description
from app.tools.singleAgentExample import generate_response
from azure.core.credentials import AzureKeyCredential
import asyncio
import datetime
import time
from opentelemetry import trace
from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry.trace import SpanKind
from azure.ai.agents.telemetry import trace_function
from utils.history_utils import format_chat_history, redact_bad_prompts_in_history, clean_conversation_history
from utils.response_utils import extract_bot_reply, parse_agent_response, merge_cart_and_cora
from app.tools.imageCreationTool import create_image
import logging
import aiohttp
from concurrent.futures import ThreadPoolExecutor
from opentelemetry.instrumentation.openai_v2 import OpenAIInstrumentor

# Import modularized utilities and services
from utils.env_utils import load_env_vars, validate_env_vars
from utils.message_utils import (
    IMAGE_UPLOAD_MESSAGES, IMAGE_CREATE_MESSAGES, IMAGE_ANALYSIS_MESSAGES,
    VIDEO_UPLOAD_MESSAGES, VIDEO_ANALYSIS_MESSAGES,
    get_rotating_message
)
from services.agent_service import get_or_create_agent_processor
from services.handoff_service import call_handoff, select_agent
from services.fallback_service import call_fallback, cora_fallback

load_dotenv(override=True)

# Configure structured logging
logging.basicConfig(
    level=logging.INFO if os.getenv('DEBUG') else logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global thread pool executor for CPU-bound operations
thread_pool = ThreadPoolExecutor(max_workers=4)

application_insights_connection_string = os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"]
configure_azure_monitor(connection_string=application_insights_connection_string)
OpenAIInstrumentor().instrument()
os.environ["AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED"] = "true"


scenario = os.path.basename(__file__)
tracer = trace.get_tracer(__name__)

# Timing utility function with structured logging
def log_timing(operation_name: str, start_time: float, additional_info: str = ""):
    """Log timing information for operations using structured logging."""
    elapsed_time = time.time() - start_time
    timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    log_message = f"[TIMING] {timestamp} - {operation_name}: {elapsed_time:.3f}s"
    if additional_info:
        log_message += f" | {additional_info}"
    logger.info(log_message)
    return elapsed_time

async def get_cached_image_description(image_url: str, image_cache: dict) -> str:
    """Get image description with caching. If not in cache, fetch and store it."""
    if image_url in image_cache:
        logger.debug("Using cached image description", extra={"url": image_url[:50], "cache_size": len(image_cache)})
        return image_cache[image_url]
    
    logger.debug("Fetching new image description", extra={"url": image_url[:50]})
    try:
        # Use thread pool executor for CPU-bound operations
        loop = asyncio.get_event_loop()
        description = await loop.run_in_executor(thread_pool, get_image_description, image_url)
        image_cache[image_url] = description
        logger.debug("Cached image description", extra={"url": image_url[:50]})
        return description
    except Exception as e:
        logger.error("Failed to get image description", extra={"url": image_url[:50], "error": str(e)})
        return ""

async def pre_fetch_image_description(image_url: str, image_cache: dict):
    """Pre-fetch image description asynchronously without blocking."""
    if image_url and image_url not in image_cache:
        logger.debug("Pre-fetching image description", extra={"url": image_url[:50]})
        try:
            loop = asyncio.get_event_loop()
            description = await loop.run_in_executor(thread_pool, get_image_description, image_url)
            image_cache[image_url] = description
            logger.debug("Pre-fetched and cached image description", extra={"url": image_url[:50]})
        except Exception as e:
            logger.error("Failed to pre-fetch image description", extra={"url": image_url[:50], "error": str(e)})

def log_cache_status(image_cache: dict, current_url: str = ""):
    """Log the current status of the image cache using structured logging."""
    cache_size = len(image_cache)
    cache_keys = list(image_cache.keys())
    logger.debug("Image cache status", extra={
        "cache_size": cache_size,
        "cache_keys": [url[:30] + '...' for url in cache_keys],
        "current_url_in_cache": current_url in image_cache if current_url else None
    })

def extract_product_names_from_response(response_data) -> str:
    """Extract product names from response data and format them."""
    try:
        # Handle string response data
        if isinstance(response_data, str):
            try:
                response_data = orjson.loads(response_data)
            except (orjson.JSONDecodeError, TypeError):
                return ""
        
        # Handle dictionary response
        if isinstance(response_data, dict):
            products = response_data.get("products")
            if products:
                # Handle products as string (JSON)
                if isinstance(products, str):
                    try:
                        products_list = orjson.loads(products)
                    except (orjson.JSONDecodeError, TypeError):
                        return ""
                # Handle products as list
                elif isinstance(products, list):
                    products_list = products
                else:
                    return ""
                
                # Extract names from products
                if products_list and isinstance(products_list, list):
                    names = []
                    for product in products_list:
                        if isinstance(product, dict) and "name" in product:
                            names.append(product["name"])
                    if names:
                        return f" [Products Mentioned: {', '.join(names)}]"
        
        return ""
    except Exception:
        return ""

def format_chat_history(chat_history: Deque[Tuple[str, str]]) -> str:
    """Format chat history for the handoff prompt."""
    return "\n".join([
        f"user: {msg}" if role == "user" else f"bot: {msg}"
        for role, msg in chat_history
    ])

# Optimized JSON serialization function
def fast_json_dumps(obj, **kwargs):
    """Use orjson for faster JSON serialization."""
    return orjson.dumps(obj, **kwargs).decode('utf-8')

# Optimized string template for user message formatting
def format_user_message_with_products(image_url: str, image_data: str, video_summary: str, 
                                   formatted_history: str, products) -> str:
    """Optimized string formatting for user messages with products."""
    parts = [
        f'"image_url": "{image_url or ""}",',
        f'"image_description": "{image_data or ""}",',
        f'"video_description": "{video_summary or ""}",',
        f'"conversation_history": "{formatted_history}",',
        f'"products_available": {fast_json_dumps(products)}'
    ]
    return "{" + ", ".join(parts) + "}"

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

@tracer.start_as_current_span("assess_claims_with_context")
def select_agent(handoff_reply: str, env_vars: Dict[str, str]) -> Tuple[Optional[str], Optional[str]]:
    """Select agent and agent_name based on handoff reply."""
    start_time = time.time()
    reply = handoff_reply.lower()
    if "cora" in reply:
        result = env_vars.get('cora'), "cora"
    elif "interior_designer_create_image" in reply:
        result = env_vars.get('interior_designer'), "interior_designer_create_image"
    elif "interior_designer" in reply:
        result = env_vars.get('interior_designer'), "interior_designer"
    elif "inventory_agent" in reply:
        result = env_vars.get('inventory_agent'), "inventory_agent"
    elif "customer_loyalty" in reply:
        result = env_vars.get('customer_loyalty'), "customer_loyalty"
    else:
        result = None, None
    
    log_timing("Agent Selection", start_time, f"Selected: {result[1] if result[1] else 'None'}")
    return result

def call_handoff(handoff_client: ChatCompletionsClient, handoff_prompt: str, formatted_history: str, phi_4_deployment: str) -> str:
    """Call the handoff model and return its reply. Handles content filter errors."""
    start_time = time.time()
    with tracer.start_as_current_span("custom_function") as span:
        span.set_attribute("custom_attribute", "value")    
        try:
            handoff_response = handoff_client.complete(
                messages=[
                    SystemMessage(content=handoff_prompt),
                    UserMessage(content=formatted_history),
                ],
                max_tokens=2048,
                temperature=0.8,
                top_p=0.1,
                presence_penalty=0.0,
                frequency_penalty=0.0,
                model=phi_4_deployment
            )
            result = handoff_response.choices[0].message.content
            log_timing("Handoff Call", start_time, f"Model: {phi_4_deployment}")
            return result
        except Exception as e:
            # Check for content filter error
            err_str = str(e)
            if "content_filter" in err_str or "ResponsibleAIPolicyViolation" in err_str:
                # Return a special marker string so the caller can handle it 
                result = "__CONTENT_FILTER_ERROR__" + err_str
                log_timing("Handoff Call (Content Filter Error)", start_time, f"Error: {err_str[:50]}...")
                return result
            # Otherwise, re-raise
            log_timing("Handoff Call (Exception)", start_time, f"Exception: {str(e)[:50]}...")
            raise

def call_fallback(llm_client, fallback_prompt: str, gpt_deployment = "gpt-4.1"):
    """Call the fallback model and return its reply."""
    start_time = time.time()
    
    chat_prompt = [    
        {
            "role": "system",      
            "content": 
            [           
                {               
                    "type": "text",               
                    "text": fallback_prompt           
                }       
            ]   
        }]

    messages = chat_prompt
    completion = llm_client.chat.completions.create(
        model=gpt_deployment,
        messages=messages,
        temperature=0.7,
        stream=False)
    result = completion.choices[0].message.content
    log_timing("Fallback Call", start_time, f"Model: {gpt_deployment}")
    return result

def cora_fallback(llm_client, fallback_prompt: str, gpt_deployment = "Phi-4"):
    """Call the fallback model for cora and return its reply."""
    start_time = time.time()
    
    chat_prompt = [    
        {
            "role": "system",      
            "content": 
            [           
                {               
                    "type": "text",               
                    "text": fallback_prompt           
                }       
            ]   
        }]

    messages = chat_prompt
    completion = llm_client.chat.completions.create(
        model=gpt_deployment,
        messages=messages,
        temperature=0.7,
        top_p=0.95,
        frequency_penalty=0,
        presence_penalty=0,
        stop=None,
        stream=False)
    result = completion.choices[0].message.content
    log_timing("Cora Fallback Call", start_time, f"Model: {gpt_deployment}")
    return result

def cart_update(llm_client, cart_update_prompt: str):
    """Call the cart update model and return its reply."""
    start_time = time.time()
    
    chat_prompt = [    
        {
            "role": "system",      
            "content": 
            [           
                {               
                    "type": "text",               
                    "text": cart_update_prompt           
                }       
            ]   
        }]

    gpt_deployment = validated_env_vars['gpt_deployment']
    messages = chat_prompt
    completion = llm_client.chat.completions.create(
        model=gpt_deployment,
        messages=messages,
        temperature=0.7,
        top_p=0.95,
        frequency_penalty=0,
        presence_penalty=0,
        stop=None,
        stream=False)
    result = completion.choices[0].message.content
    log_timing("Cart Update Call", start_time, f"Model: {gpt_deployment}")
    return result

app = FastAPI()

load_dotenv()
env_vars = load_env_vars()
validated_env_vars = validate_env_vars(env_vars)

project_endpoint = os.environ.get("AZURE_AI_AGENT_ENDPOINT")
if not project_endpoint:
    raise ValueError("AZURE_AI_AGENT_ENDPOINT environment variable is required")
project_client = AIProjectClient(
    endpoint=project_endpoint,
    credential=DefaultAzureCredential(),
)

HANDOFF_PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'prompts', 'handoffPrompt.txt')
FALLBACK_PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'prompts', 'fallBackPrompt.txt')
CORA_FALLBACK_PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'prompts', 'CoraPrompt.txt')
CART_UPDATE_PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'prompts', 'addToCartPrompt.txt')

with open(HANDOFF_PROMPT_PATH, 'r') as file:
    HANDOFF_PROMPT = file.read()

with open(FALLBACK_PROMPT_PATH, 'r') as file:
    FALLBACK_PROMPT = file.read()

with open(CORA_FALLBACK_PROMPT_PATH, 'r') as file:
    CORA_FALLBACK_PROMPT = file.read()

with open(CART_UPDATE_PROMPT_PATH, 'r') as file:
    CART_UPDATE_PROMPT = file.read()

handoff_client = ChatCompletionsClient(
    endpoint=validated_env_vars['phi_4_endpoint'],
    credential=AzureKeyCredential(validated_env_vars['phi_4_api_key']),
    api_version=validated_env_vars['phi_4_api_version']
)

llm_client = AzureOpenAI(
    azure_endpoint=validated_env_vars['AZURE_OPENAI_ENDPOINT'],
    api_key=validated_env_vars['AZURE_OPENAI_KEY'],
    api_version=validated_env_vars['AZURE_OPENAI_API_VERSION'],
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
            "azure_openai_endpoint": bool(validated_env_vars.get('AZURE_OPENAI_ENDPOINT')),
            "azure_openai_key": bool(validated_env_vars.get('AZURE_OPENAI_KEY')),
            "azure_ai_agent_endpoint": bool(os.environ.get("AZURE_AI_AGENT_ENDPOINT"))
        }
    }

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    session_start_time = time.time()
    logger.info("WebSocket Session Started")
    
    await websocket.accept()
    thread = project_client.agents.threads.create()
    chat_history: Deque[Tuple[str, str]] = deque(maxlen=5)
    customer_loyalty_thread = project_client.agents.threads.create()
    
    # Flag to track if customer loyalty task has been executed
    customer_loyalty_executed = False
    
    # Session-level variable to track discount_percentage
    session_discount_percentage = ""
    # Store the full loyalty response for later
    session_loyalty_response = None
    
    # Flag to track if loyalty response has been sent to user
    loyalty_response_sent = False
    
    # Session-level variable to track persistent image URL
    persistent_image_url = ""

    # Session-level variable to track persistent cart state
    persistent_cart = []

    # Dictionary to cache image URLs and their descriptions
    image_cache = {}

    # Track bad prompts (those that triggered content filter)
    bad_prompts = set()

    # Use deque with maxlen for raw_io_history to prevent unbounded growth
    raw_io_history = deque(maxlen=100)

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
                thread_id=customer_loyalty_thread.id,
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

    # Run customer loyalty task only once when session starts
    customer_id = "CUST001"
    if not customer_loyalty_executed:
        asyncio.create_task(run_customer_loyalty_task(customer_id))
        customer_loyalty_executed = True

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
                has_video = parsed.get("has_video", False)
                video_url = parsed.get("video_url", "")
                cart = parsed.get("cart", [])
                
                # # Update persistent image URL if a new one is provided
                if image_url:
                    persistent_image_url = image_url
                    logger.debug("Persistent image URL updated", extra={"url": persistent_image_url})
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
                has_video = False
                video_url = None
                conversation_history = ""
            
            # Parse conversation history from string format
            history_start_time = time.time()
            try:
                if conversation_history:
                    # Clear existing chat history
                    chat_history.clear()
                    # Parse the string format: "user: message\nbot: message"
                    lines = conversation_history.strip().split('\n')
                    for i, line in enumerate(lines):
                        if line.startswith('user: '):
                            user_msg = line[6:]  # Remove "user: " prefix
                            chat_history.append(("user", user_msg))
                        elif line.startswith('bot: '):
                            bot_msg = line[5:]   # Remove "bot: " prefix
                            # Clean bot messages to remove large JSON data
                            try:
                                parsed_bot = orjson.loads(bot_msg)  # Use orjson
                                # Handle list format (new agent response format)
                                if isinstance(parsed_bot, list) and len(parsed_bot) > 0:
                                    first_item = parsed_bot[0]
                                    if isinstance(first_item, dict) and "answer" in first_item:
                                        bot_msg = first_item["answer"]
                                # Handle dict format (old format)
                                elif isinstance(parsed_bot, dict) and "answer" in parsed_bot:
                                    bot_msg = parsed_bot["answer"]
                            except (orjson.JSONDecodeError, TypeError):
                                pass
                            chat_history.append(("bot", bot_msg))
                    # Add the current user message to the history
                    chat_history.append(("user", user_message))
                else:
                    chat_history.append(("user", user_message))
                log_timing("History Parsing", history_start_time, f"History entries: {len(chat_history)}")
            except Exception as e:
                logger.error("Error parsing conversation history", exc_info=True)
                chat_history.append(("user", user_message))
            
            #await websocket.send_text(fast_json_dumps({"answer": "This application is not yet ready to serve results. Please check back later.", "agent": None, "cart": persistent_cart}))

            # Single-agent example
            # try:
            #     response = generate_response(user_message)
            #     await websocket.send_text(fast_json_dumps({"answer": response, "agent": "single", "cart": persistent_cart}))
            # except Exception as e:
            #     logger.error("Error during single-agent response generation", exc_info=True)
            #     await websocket.send_text(fast_json_dumps({"answer": "Error during single-agent response generation", "error": str(e), "cart": persistent_cart}))

            # Run handoff service
            try:
                handoff_start_time = time.time()
                formatted_history = format_chat_history(redact_bad_prompts_in_history(chat_history, bad_prompts))
                logger.debug("Handoff agent execution initiated - commencing agent selection protocol")
                with tracer.start_as_current_span("Handoff Agent Call"):
                    handoff_reply = call_handoff(
                        handoff_client,
                        HANDOFF_PROMPT,
                        formatted_history,
                        validated_env_vars['phi_4_deployment']
                    )
                logger.debug("Handoff agent response received - agent selection criteria processed")
                logger.debug(f"Handoff reply: {handoff_reply}")
                log_timing("Handoff Processing", handoff_start_time, f"Reply length: {len(handoff_reply)} chars")
                # Handle content filter error from handoff
                if isinstance(handoff_reply, str) and handoff_reply.startswith("__CONTENT_FILTER_ERROR__"):
                    error_message = handoff_reply.replace("__CONTENT_FILTER_ERROR__", "").strip()
                    # Add the last user message to bad_prompts
                    if chat_history and chat_history[-1][0] == "user":
                        bad_prompts.add(chat_history[-1][1])
                    await websocket.send_text(fast_json_dumps({
                        "answer": "Your message triggered a content filter and cannot be processed. Please modify your prompt and try again.",
                        "agent": None,
                        "error": error_message,
                        "cart": persistent_cart
                    }))
                    continue
            except Exception as e:
                logger.error("Error during handoff call", exc_info=True)
                await websocket.send_text(fast_json_dumps({"answer": "Error during handoff call", "error": str(e), "cart": persistent_cart}))
                continue
            
            # Check for 'cart' in the user query before agent selection
            try:
                if 'cart' in user_message.lower():
                    cart_start_time = time.time()
                    # Use the full raw_io_history as JSON - optimize with orjson
                    cart_prompt = CART_UPDATE_PROMPT + "\nRAW_IO_HISTORY:\n" + fast_json_dumps(list(raw_io_history), option=orjson.OPT_INDENT_2)
                    logger.debug("Cora agent cart update operation initiated - commencing cart state modification")
                    cora_prompt = CORA_FALLBACK_PROMPT + "\n" + formatted_history

                    async def run_cart_update():
                        loop = asyncio.get_event_loop()
                        result = await loop.run_in_executor(thread_pool, cart_update, llm_client, cart_prompt)
                        return result
                    async def run_cora_fallback():
                        loop = asyncio.get_event_loop()
                        result = await loop.run_in_executor(thread_pool, cora_fallback, llm_client, cora_prompt)
                        return result

                    try:
                        cart_reply_raw, cora_reply_raw = await asyncio.gather(run_cart_update(), run_cora_fallback())
                    except Exception as e:
                        logger.error("Error processing cart/cora", exc_info=True)
                        await websocket.send_text(fast_json_dumps({"answer": "Error processing cart/cora", "error": str(e), "cart": persistent_cart}))
                        continue

                    cart_json = parse_agent_response(cart_reply_raw)
                    cora_json = parse_agent_response(cora_reply_raw)

                    logger.debug(f"Cart reply: {cart_reply_raw}")
                    
                    logger.debug("Cart update operation completed - cart state successfully modified")
                    logger.debug("Cora agent thread execution terminated - response processing complete")

                    # Use new merge_cart_and_cora utility for robust merging
                    merged = merge_cart_and_cora(cart_reply_raw, cora_reply_raw)

                    logger.debug(f"Merged result: {merged}")
                    # Update persistent_cart with the latest cart state
                    if isinstance(merged.get("cart"), list):
                        persistent_cart = merged["cart"]
                    response_json = fast_json_dumps({**merged, "cart": persistent_cart})
                    raw_io_history.append({"output": response_json, "cart": persistent_cart})
                    
                    # Add the merged response to chat history with products if available
                    bot_answer = merged.get("answer", "")
                    product_names = extract_product_names_from_response(merged)
                    chat_history.append(("bot", bot_answer + product_names))
                    
                    await websocket.send_text(response_json)
                    log_timing("Cart/Cora Processing", cart_start_time, f"Cart items: {len(persistent_cart)}")
                    # After cart/cora response, send loyalty response if available (only once per session)
                    if session_loyalty_response and not loyalty_response_sent:
                        loyalty_response_with_cart = {**session_loyalty_response, "cart": persistent_cart}
                        await websocket.send_text(fast_json_dumps(loyalty_response_with_cart))
                        loyalty_response_sent = True
                    continue
            except Exception as e:
                logger.error("Error in cart/cora handling", exc_info=True)
                await websocket.send_text(fast_json_dumps({"answer": "Error in cart/cora handling", "error": str(e), "cart": persistent_cart}))
                continue

            # Fallback message if no agent is selected
            try:
                agent_selection_start_time = time.time()
                agent_selected, agent_name = select_agent(handoff_reply, validated_env_vars)
                if not agent_selected or not agent_name:
                    await websocket.send_text(fast_json_dumps({"answer": "Sorry, I could not determine the right agent.", "agent": None, "cart": persistent_cart}))
                    continue
                logger.debug(f"Agent selection protocol completed - {agent_name} agent designated for task execution")
                log_timing("Agent Selection", agent_selection_start_time, f"Selected: {agent_name}")
            except Exception as e:
                logger.error("Error during agent selection", exc_info=True)
                await websocket.send_text(fast_json_dumps({"answer": "Error during agent selection", "error": str(e), "cart": persistent_cart}))
                continue
            
            try:
                agent_execution_start_time = time.time()
                #check agent
                if agent_name == "interior_designer":
                    logger.debug("Interior Designer agent execution initiated - commencing design consultation protocol")
                    with tracer.start_as_current_span("Zava Interior Designer Agent Call"):
                        image_data = None
                        video_summary = None
                        products = None

                        if not image_url and not video_url:
                            product_start_time = time.time()
                            products = product_recommendations(user_message)
                            
                            log_timing("Product Recommendations", product_start_time, f"Products found: {len(products) if products else 0}")
                            logger.debug("Product recommendation engine execution completed - catalog query processed")

                            user_message = f"{user_message}\n\nProducts: {fast_json_dumps(products)}"
                            user_message = format_user_message_with_products(
                                image_url or "", image_data or "", video_summary or "", 
                                formatted_history, products
                            )

                            fallback_prompt = FALLBACK_PROMPT + f"\n\n {user_message}"
                            
                            fallback_start_time = time.time()
                            fallback_reply = call_fallback(
                                llm_client,
                                fallback_prompt,
                                validated_env_vars['gpt_deployment']
                            )
                            log_timing("Interior Designer Fallback", fallback_start_time, "No image/video")
                            
                            msg = fallback_reply
                            bot_reply = extract_bot_reply(msg)

                        else:
                            multimodal_data = ''
                            
                            if image_url:
                                image_start_time = time.time()
                                log_cache_status(image_cache, image_url)
                                image_data = await get_cached_image_description(image_url, image_cache)
                                log_timing("Image Analysis", image_start_time, f"URL: {image_url[:50]}...")
                                multimodal_data =  image_data
                                analysis_msg = get_rotating_message(IMAGE_ANALYSIS_MESSAGES)
                                await websocket.send_text(fast_json_dumps({"answer": analysis_msg, "agent": "interior_designer", "cart": persistent_cart}))
                                logger.debug("Image analysis pipeline completed - visual content processing terminated")
                                
                                product_start_time = time.time()
                                products = product_recommendations(user_message + multimodal_data + "paint accessories, paint sprayers, drop cloths, painters tape")
                                log_timing("Product Recommendations", product_start_time, f"Products found: {len(products) if products else 0}")
                                logger.debug("Product recommendation engine execution completed - catalog query processed")
                                user_message = f"{user_message}\n\nProducts: {fast_json_dumps(products)}"
                                user_message = format_user_message_with_products(
                                    image_url or "", image_data or "", video_summary or "", 
                                    formatted_history, products
                                )
                                fallback_prompt = FALLBACK_PROMPT + f"\n\n {user_message}"
                                
                                fallback_start_time = time.time()
                                fallback_reply = call_fallback(
                                    llm_client,
                                    fallback_prompt,
                                    validated_env_vars['gpt_deployment']
                                )
                                log_timing("Interior Designer Fallback", fallback_start_time, "With image")
                                msg = fallback_reply
                                bot_reply = extract_bot_reply(msg)
                            
                            
                            elif video_url:
                                video_start_time = time.time()
                                logger.debug("Video analysis initiated - commencing video content processing")
                                video_summary = get_video_summary(video_url)
                                thank_you_msg = get_rotating_message(VIDEO_UPLOAD_MESSAGES)
                                await websocket.send_text(fast_json_dumps({"answer": thank_you_msg, "agent": "interior_designer", "cart": persistent_cart}))
                                log_timing("Video Analysis", video_start_time, f"URL: {video_url[:50]}...")
                                multimodal_data = video_summary
                                analysis_msg = get_rotating_message(VIDEO_ANALYSIS_MESSAGES)
                                await websocket.send_text(fast_json_dumps({"answer": analysis_msg, "agent": "interior_designer", "cart": persistent_cart}))
                                logger.debug("Video analysis pipeline completed - temporal content processing terminated")
                                # await websocket.send_text(fast_json_dumps({"answer": multimodal_data, "agent": "interior_designer", "cart": persistent_cart}))
                                product_start_time = time.time()
                                products = product_recommendations(user_message + multimodal_data + "paint accessories, paint sprayers, drop cloths, painters tape")
                                log_timing("Product Recommendations", product_start_time, f"Products found: {len(products) if products else 0}")
                                logger.debug("Product recommendation engine execution completed - catalog query processed")
                                user_message = f"{user_message}\n\nProducts: {fast_json_dumps(products)}"
                                user_message = format_user_message_with_products(
                                    image_url or "", image_data or "", video_summary or "", 
                                    formatted_history, products
                                )
                                fallback_prompt = "Received video from user:" + FALLBACK_PROMPT + f"\n\n {user_message}"
                                
                                fallback_start_time = time.time()
                                fallback_reply = call_fallback(
                                    llm_client,
                                    fallback_prompt,
                                    validated_env_vars['gpt_deployment']
                                )
                                log_timing("Interior Designer Fallback", fallback_start_time, "With video")
                                msg = fallback_reply
                                bot_reply = extract_bot_reply(msg)
                
                elif agent_name == "interior_designer_create_image":
                    logger.debug("Interior Designer agent execution initiated - commencing design consultation protocol")
                    with tracer.start_as_current_span("Zava Interior Designer Agent Call"):
                        image_data = None
                        video_summary = None
                        products = None
                        thank_you_msg = get_rotating_message(IMAGE_CREATE_MESSAGES)
                        await websocket.send_text(fast_json_dumps({"answer": thank_you_msg, "agent": "interior_designer", "cart": persistent_cart}))
                        multimodal_data = ''
                        
                        image_start_time = time.time()
                        log_cache_status(image_cache, persistent_image_url)
                        image_data = await get_cached_image_description(persistent_image_url, image_cache)
                        log_timing("Image Analysis (Create)", image_start_time, f"URL: {persistent_image_url[:50]}...")
                        multimodal_data =  image_data
                        logger.debug("Image analysis pipeline completed - visual content processing terminated")
                        user_message = str(user_message) + str(multimodal_data)
                        
                        product_start_time = time.time()
                        products = product_recommendations(user_message + "paint accessories, sprayers, drop cloths, painters tape")
                        log_timing("Product Recommendations", product_start_time, f"Products found: {len(products) if products else 0}")
                        logger.debug("Product recommendation engine execution completed - catalog query processed")
                        INSTRUCTIONS = "ADDITIONAL INFO: Along with the created image, say that it will be good to have paint accessories, sprayers, drop cloths, painters tape"
                        user_message = f"{user_message + INSTRUCTIONS}\n\nProducts: {fast_json_dumps(products)}"
                        user_message = format_user_message_with_products(
                            persistent_image_url or "", image_data or "", video_summary or "", 
                            formatted_history, products
                        )
                        
                        image = create_image(text=user_message, image_url=persistent_image_url)

                        # Create the response in the specified format and send directly to frontend
                        response_data = {
                            "answer": "Here is the requested image",
                            "products": "",
                            "discount_percentage": session_discount_percentage or "",
                            "image_url": image,
                            "video_url": "",
                            "additional_data": "",
                            "cart": persistent_cart
                        }
                        
                        # Send the response directly to frontend
                        response_json = fast_json_dumps(response_data)
                        raw_io_history.append({"output": response_json, "cart": persistent_cart})
                        
                        # Add to chat history
                        bot_answer = response_data.get("answer", "")
                        product_names = extract_product_names_from_response(response_data)
                        chat_history.append(("bot", bot_answer + product_names))
                        
                        await websocket.send_text(response_json)
                        log_timing("Agent Execution", agent_execution_start_time, f"Agent: {agent_name}")
                        continue  # Skip the common response handling below
                
                elif agent_name == "cora":
                    logger.debug("Cora agent execution initiated - commencing conversational AI protocol")
                    with tracer.start_as_current_span("Agent Cora Call"):
                        prompt_for_cora = CORA_FALLBACK_PROMPT + formatted_history 
                        
                        cora_start_time = time.time()
                        cora_fallback_reply = cora_fallback(
                            llm_client,
                            prompt_for_cora,
                            validated_env_vars['phi_4_deployment']
                        )
                        log_timing("Cora Agent Call", cora_start_time, "Fallback model")
                        msg = cora_fallback_reply
                        bot_reply = extract_bot_reply(msg)
                    logger.debug("Cora agent execution terminated - conversational AI protocol completed")
                
                else:
                    logger.debug(f"{agent_name} agent execution initiated - commencing specialized task protocol")
                    with tracer.start_as_current_span("Customer Loyalty Agent Call - Additional"):
                        processor = get_or_create_agent_processor(
                            agent_id=agent_selected,
                            agent_type=agent_name,
                            thread_id=thread.id,
                            project_client=project_client
                        )
                    logger.debug(f"{agent_name} agent execution terminated - specialized task protocol completed")
                    bot_reply = ""
                    async for msg in processor.run_conversation_with_text_stream(input_message=user_message):
                        bot_reply = extract_bot_reply(msg)
                
                log_timing("Agent Execution", agent_execution_start_time, f"Agent: {agent_name}")
                
                # Parse the response first to get products
                parsed_response = parse_agent_response(bot_reply)
                parsed_response["agent"] = agent_name  # Override agent field
                
                # Add the bot reply to chat history with products if available
                bot_answer = parsed_response.get("answer", bot_reply or "")
                product_names = extract_product_names_from_response(parsed_response)
                chat_history.append(("bot", bot_answer + product_names))
                print(f"Chat history after bot reply: {chat_history}")
                
                # Clean the conversation history to remove large product data
                chat_history = clean_conversation_history(chat_history)
                print(f"Chat history after bot reply: {chat_history}")
                
                # Update session discount_percentage if a new one is received
                if parsed_response.get("discount_percentage"):
                    session_discount_percentage = parsed_response["discount_percentage"]
                
                # Include session discount_percentage in all responses if available
                if session_discount_percentage and not parsed_response.get("discount_percentage"):
                    parsed_response["discount_percentage"] = session_discount_percentage
                
                # When sending any other response, also append to raw_io_history
                response_json = fast_json_dumps({**parsed_response, "cart": persistent_cart})
                raw_io_history.append({"output": response_json, "cart": persistent_cart})
                await websocket.send_text(response_json)
            except Exception as e:
                logger.error("Error in agent execution", exc_info=True)
                try:
                    await websocket.send_text(fast_json_dumps({"answer": "Internal server error", "error": str(e), "cart": persistent_cart}))
                except Exception:
                    pass
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("WebSocket session error", exc_info=True)
        try:
            await websocket.send_text(fast_json_dumps({"answer": "Internal server error", "error": str(e), "cart": persistent_cart}))
        except Exception:
            pass
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