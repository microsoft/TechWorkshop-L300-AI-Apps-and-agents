from collections import deque
from typing import Deque, Tuple
import json
import orjson
import time
import logging
from utils.log_utils import log_timing

logger = logging.getLogger(__name__)

def format_chat_history(chat_history: Deque[Tuple[str, str]]) -> str:
    """Format chat history for the handoff prompt."""
    return "\n".join([
        f"user: {msg}" if role == "user" else f"bot: {msg}"
        for role, msg in chat_history
    ])

def clean_conversation_history(history: Deque[Tuple[str, str]]) -> Deque[Tuple[str, str]]:
    """
    Clean conversation history by removing large product data and keeping only essential information.
    """
    cleaned_history = deque(maxlen=history.maxlen)
    for role, message in history:
        if role == "bot":
            try:
                parsed = json.loads(message)
                if isinstance(parsed, list) and len(parsed) > 0:
                    first_item = parsed[0]
                    if isinstance(first_item, dict) and "answer" in first_item:
                        cleaned_message = first_item["answer"]
                    else:
                        cleaned_message = message
                elif isinstance(parsed, dict) and "answer" in parsed:
                    cleaned_message = parsed["answer"]
                else:
                    cleaned_message = message
            except (json.JSONDecodeError, TypeError):
                cleaned_message = message
        else:
            cleaned_message = message
        cleaned_history.append((role, cleaned_message))
    return cleaned_history

def redact_bad_prompts_in_history(history, bad_prompts):
    # Returns a new deque with bad prompts replaced by <redacted>
    redacted = deque(maxlen=history.maxlen)
    for role, msg in history:
        if role == "user" and msg in bad_prompts:
            redacted.append((role, "<redacted>"))
        else:
            redacted.append((role, msg))
    return redacted

def parse_conversation_history(conversation_history: str, chat_history: Deque[Tuple[str, str]], user_message: str):
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
    return chat_history