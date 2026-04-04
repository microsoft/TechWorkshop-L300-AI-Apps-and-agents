"""
Agent service: factory + cache for AgentProcessor instances.

Why a factory? Creating an AgentProcessor involves looking up the agent in
Microsoft Foundry and setting up conversation state. This module caches
processors by (agent_type, agent_id) so that repeated requests for the same
agent reuse the existing processor rather than reinitializing each time.

The thread_id is updated on each call because a new WebSocket session may
want to continue with the same agent but on a fresh conversation thread.

Usage in chat_app.py:
    processor = get_or_create_agent_processor(
        agent_id="cora",
        agent_type="cora",
        thread_id=None,
        project_client=project_client,
    )
    async for msg in processor.run_conversation_with_text_stream("Hello"):
        print(msg)
"""

from app.agents.agent_processor import AgentProcessor
from typing import Dict

# Cache: "agentType_agentId" -> AgentProcessor
_agent_processor_cache: Dict[str, AgentProcessor] = {}


def get_or_create_agent_processor(
    agent_id: str,
    agent_type: str,
    thread_id: str,
    project_client,
) -> AgentProcessor:
    """Return a cached AgentProcessor, or create and cache a new one.

    Args:
        agent_id: The agent name/ID as registered in Microsoft Foundry.
        agent_type: Logical type used for tool assignment (e.g. "cora", "inventory_agent").
        thread_id: Conversation thread to continue, or None for a new thread.
        project_client: An AIProjectClient connected to your Foundry project.

    Returns:
        An AgentProcessor ready to run conversations.
    """
    cache_key = f"{agent_type}_{agent_id}"

    if cache_key in _agent_processor_cache:
        processor = _agent_processor_cache[cache_key]
        processor.thread_id = thread_id
        return processor

    processor = AgentProcessor(
        project_client=project_client,
        assistant_id=agent_id,
        agent_type=agent_type,
        thread_id=thread_id,
    )
    _agent_processor_cache[cache_key] = processor
    return processor
