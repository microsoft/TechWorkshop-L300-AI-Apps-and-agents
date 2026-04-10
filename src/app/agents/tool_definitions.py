"""
FunctionTool definitions for Microsoft Foundry agents.

This module builds the list of FunctionTool objects that each agent type
needs. Rather than hardcoding JSON schemas, it discovers available tools
from the MCP server at startup and converts them into the FunctionTool
format that the Azure AI Agent Framework expects.

The mapping from MCP tool name to the local wrapper function name is
defined in TOOL_NAME_MAP. The per-agent tool assignments are in
AGENT_TOOL_ASSIGNMENTS.
"""

import asyncio
import logging
from typing import Any, Dict, List

from azure.ai.projects.models import FunctionTool

from app.servers.mcp_inventory_client import get_mcp_client

logger = logging.getLogger(__name__)

# Maps MCP server tool names to the local wrapper function names used by agents.
# The local names match the keys in mcp_tools.MCP_FUNCTIONS.
TOOL_NAME_MAP: Dict[str, str] = {
    "generate_product_image": "mcp_create_image",
    "get_product_recommendations": "mcp_product_recommendations",
    "get_customer_discount": "mcp_calculate_discount",
    "check_product_inventory": "mcp_inventory_check",
}

# Defines which local tool names each agent type can use.
AGENT_TOOL_ASSIGNMENTS: Dict[str, List[str]] = {
    "interior_designer": ["mcp_product_recommendations"],
    "customer_loyalty": ["mcp_calculate_discount"],
    "inventory_agent": ["mcp_inventory_check"],
    "cart_manager": [],
    "cora": ["mcp_product_recommendations"],
}

# Cache: MCP tool name -> FunctionTool (populated once from MCP discovery)
_discovered_tools: Dict[str, FunctionTool] = {}


async def _discover_tools() -> None:
    """Query the MCP server for available tools and build FunctionTool objects.

    This is called once on first use. The MCP server's tool schemas become
    the single source of truth for parameter definitions and descriptions.
    """
    if _discovered_tools:
        return

    mcp_client = await get_mcp_client()
    server_tools = await mcp_client.list_tools()

    for tool in server_tools:
        local_name = TOOL_NAME_MAP.get(tool.name)
        if not local_name:
            continue

        # The MCP inputSchema is already a valid JSON Schema object.
        # We need to ensure additionalProperties is False for strict mode.
        schema = dict(tool.inputSchema)

        # For mcp_inventory_check, the agent sends a list of product IDs,
        # but the MCP tool accepts a single product_id. Wrap it accordingly.
        if local_name == "mcp_inventory_check":
            schema = {
                "type": "object",
                "properties": {
                    "product_list": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of product IDs to check inventory for.",
                    }
                },
                "required": ["product_list"],
                "additionalProperties": False,
            }
        else:
            schema["additionalProperties"] = False

        _discovered_tools[local_name] = FunctionTool(
            name=local_name,
            parameters=schema,
            description=tool.description or "",
            strict=True,
        )

    logger.info(
        f"Discovered {len(_discovered_tools)} MCP tools: {list(_discovered_tools.keys())}"
    )


async def get_tools_for_agent(agent_type: str) -> List[FunctionTool]:
    """Return the list of FunctionTool objects an agent type needs.

    On first call, discovers tools from the MCP server. Subsequent calls
    use the cached definitions.
    """
    await _discover_tools()
    tool_names = AGENT_TOOL_ASSIGNMENTS.get(agent_type, [])
    return [_discovered_tools[name] for name in tool_names if name in _discovered_tools]


async def get_tools_for_agent_oneshot(agent_type: str) -> List[FunctionTool]:
    """Discover tools and close the MCP connection before returning.

    Use this in one-shot initializer scripts that call asyncio.run().
    Closing the MCP client before the event loop tears down prevents the
    RuntimeError from anyio's cancel scope cleanup.
    """
    tools = await get_tools_for_agent(agent_type)
    client = await get_mcp_client()
    await client.close()
    return tools
