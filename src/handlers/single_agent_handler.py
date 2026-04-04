"""
Single-agent message handler.

This handler routes every user message to a single Azure OpenAI agent
(via the singleAgentExample module). It demonstrates the simplest possible
agent integration: one agent, no routing, no tool calls.

Enable this handler in chat_app.py by uncommenting the single-agent block
in the WebSocket message loop.
"""

import logging
from utils.message_utils import fast_json_dumps

logger = logging.getLogger(__name__)


async def handle_single_agent(websocket, user_message: str, persistent_cart: list):
    """Send user_message to the single agent and relay the response.

    Args:
        websocket: The active WebSocket connection.
        user_message: The user's chat input.
        persistent_cart: Current cart state (passed through unchanged).
    """
    # Import here so the module can be loaded without the agent being configured.
    from app.tools.singleAgentExample import generate_response

    try:
        response = generate_response(user_message)
        await websocket.send_text(fast_json_dumps({
            "answer": response,
            "agent": "single",
            "cart": persistent_cart,
        }))
    except Exception as e:
        logger.error("Error during single-agent response generation", exc_info=True)
        await websocket.send_text(fast_json_dumps({
            "answer": "Error during single-agent response generation",
            "error": str(e),
            "cart": persistent_cart,
        }))
