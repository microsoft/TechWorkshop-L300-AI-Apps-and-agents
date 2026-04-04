"""
Multi-agent message handler with MCP tools and handoff service.

This handler implements the full multi-agent pipeline:
  1. Intent classification via the HandoffService to pick the right agent
  2. Context enrichment (images, product recommendations)
  3. Agent execution via AgentProcessor (which dispatches MCP tool calls)
  4. Response parsing, cart updates, and loyalty discount persistence

Enable this handler in chat_app.py by uncommenting the multi-agent block
in the WebSocket message loop.

The handler is broken into small functions so that each step of the pipeline
is independently testable and easy to follow.
"""

import asyncio
import logging
import time
from typing import Optional

import orjson

from services.agent_service import get_or_create_agent_processor
from utils.log_utils import log_timing, log_cache_status
from utils.response_utils import (
    extract_bot_reply, parse_agent_response, extract_product_names_from_response,
)
from utils.message_utils import (
    IMAGE_CREATE_MESSAGES, IMAGE_ANALYSIS_MESSAGES,
    get_rotating_message, fast_json_dumps,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Step 1: Intent classification
# ---------------------------------------------------------------------------

async def classify_intent(
    handoff_service,
    user_message: str,
    session_id: str,
    formatted_history: str,
    validated_env_vars: dict,
    websocket,
    persistent_cart: list,
):
    """Classify the user's intent and select the target agent.

    Returns:
        (agent_name, agent_selected) on success, or (None, None) if classification fails.
    """
    handoff_start = time.time()
    intent_result = handoff_service.classify_intent(
        user_message=user_message,
        session_id=session_id,
        chat_history=formatted_history,
    )

    agent_name = intent_result["agent_id"]
    agent_selected = validated_env_vars.get(agent_name)

    logger.info(
        f"Intent classification: domain={intent_result['domain']}, "
        f"confidence={intent_result['confidence']:.2f}, "
        f"reasoning={intent_result['reasoning']}"
    )
    log_timing("Handoff Processing", handoff_start,
               f"Selected: {agent_name} (confidence: {intent_result['confidence']:.2f})")

    if not agent_selected or not agent_name:
        await websocket.send_text(fast_json_dumps({
            "answer": "Sorry, I could not determine the right agent.",
            "agent": None,
            "cart": persistent_cart,
        }))
        return None, None

    return agent_name, agent_selected


# ---------------------------------------------------------------------------
# Step 2: Context enrichment (images + product search)
# ---------------------------------------------------------------------------

async def enrich_context(
    user_message: str,
    agent_name: str,
    image_url: Optional[str],
    image_cache: dict,
    get_cached_image_description,  # async callable
    websocket,
    persistent_cart: list,
) -> str:
    """Add image descriptions and product results to the user message.

    Returns the enriched message string.
    """
    enriched = user_message
    image_data = None
    products = None

    # Image analysis
    if image_url:
        image_data = await get_cached_image_description(image_url, image_cache)
        analysis_msg = get_rotating_message(IMAGE_ANALYSIS_MESSAGES)
        await websocket.send_text(fast_json_dumps({
            "answer": analysis_msg,
            "agent": agent_name,
            "cart": persistent_cart,
        }))

    # Product recommendations (for agents that browse products)
    if agent_name in ("interior_designer", "interior_designer_create_image", "cora"):
        from app.tools.aiSearchTools import product_recommendations
        search_query = user_message
        if image_data:
            search_query += f" {image_data} paint accessories, paint sprayers, drop cloths, painters tape"
        products = product_recommendations(search_query)

    # Build enriched message
    if image_data or products:
        parts = []
        if image_data:
            parts.append(f"Image description: {image_data}")
        if products:
            parts.append(f"Available products: {fast_json_dumps(products)}")
        enriched = f"{user_message}\n\n" + "\n".join(parts)

    return enriched


# ---------------------------------------------------------------------------
# Step 3: Agent execution
# ---------------------------------------------------------------------------

async def execute_agent(
    agent_name: str,
    agent_selected: str,
    agent_context: str,
    project_client,
    tracer,
):
    """Run the selected agent and return the raw bot reply text."""
    with tracer.start_as_current_span(f"{agent_name.title()} Agent Call"):
        processor = get_or_create_agent_processor(
            agent_id=agent_selected,
            agent_type=agent_name,
            thread_id=None,
            project_client=project_client,
        )
        bot_reply = ""
        async for msg in processor.run_conversation_with_text_stream(input_message=agent_context):
            bot_reply = extract_bot_reply(msg)
    return bot_reply


# ---------------------------------------------------------------------------
# Step 4: Image creation (special case — uses gpt-image-1 directly)
# ---------------------------------------------------------------------------

async def handle_image_creation(
    user_message: str,
    persistent_image_url: str,
    image_cache: dict,
    get_cached_image_description,
    session_discount_percentage: str,
    persistent_cart: list,
    websocket,
):
    """Handle the interior_designer_create_image special case.

    Returns a response dict ready to send over WebSocket.
    """
    from app.tools.imageCreationTool import create_image

    thank_you = get_rotating_message(IMAGE_CREATE_MESSAGES)
    await websocket.send_text(fast_json_dumps({
        "answer": thank_you,
        "agent": "interior_designer",
        "cart": persistent_cart,
    }))

    enriched = user_message
    if persistent_image_url:
        image_data = await get_cached_image_description(persistent_image_url, image_cache)
        enriched = f"{user_message} {image_data}"

    image = create_image(text=enriched, image_url=persistent_image_url)

    return {
        "answer": "Here is the requested image",
        "products": "",
        "discount_percentage": session_discount_percentage or "",
        "image_url": image,
        "additional_data": "",
        "cart": persistent_cart,
    }


# ---------------------------------------------------------------------------
# Step 5: Response processing and state updates
# ---------------------------------------------------------------------------

def process_response(
    bot_reply: str,
    agent_name: str,
    session_discount_percentage: str,
    persistent_cart: list,
):
    """Parse agent output, update discount and cart state.

    Returns (parsed_response, updated_discount, updated_cart).
    """
    parsed = parse_agent_response(bot_reply)
    parsed["agent"] = agent_name

    # Cart update
    if agent_name == "cart_manager" and isinstance(parsed.get("cart"), list):
        persistent_cart = parsed["cart"]

    # Discount persistence
    if parsed.get("discount_percentage"):
        session_discount_percentage = parsed["discount_percentage"]
    elif session_discount_percentage:
        parsed["discount_percentage"] = session_discount_percentage

    return parsed, session_discount_percentage, persistent_cart
