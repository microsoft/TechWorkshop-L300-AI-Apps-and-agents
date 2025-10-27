from collections import deque
from typing import Deque, Tuple
import json

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