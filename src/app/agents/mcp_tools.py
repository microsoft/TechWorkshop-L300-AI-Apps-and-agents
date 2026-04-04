"""
MCP tool wrappers for agent function calls.

Each function here is an async wrapper that calls the corresponding tool on the
MCP inventory server via the persistent stdio connection. These functions are
registered as agent tools in Microsoft Foundry so that agents can invoke them
during conversations.

The dispatch table at the bottom (_MCP_FUNCTIONS) maps tool names to handlers,
allowing the AgentProcessor to execute function calls without if/elif branching.
"""

import logging
import time
from typing import Any, Dict, List

from app.servers.mcp_inventory_client import get_mcp_client

logger = logging.getLogger(__name__)


class MCPToolError:
    """Structured error response returned when an MCP tool call fails."""

    def __init__(self, tool_name: str, message: str):
        self.tool_name = tool_name
        self.message = message

    def to_dict(self) -> Dict[str, str]:
        return {"error": self.message, "tool": self.tool_name}

    def __str__(self) -> str:
        return f"[MCP] {self.tool_name} failed: {self.message}"


async def _timed_call(tool_name: str, arguments: Dict[str, Any]) -> Any:
    """Call an MCP tool with structured logging and timing.

    Returns the tool result on success, or an MCPToolError dict on failure.
    """
    start = time.perf_counter()
    try:
        mcp_client = await get_mcp_client()
        result = await mcp_client.call_tool(tool_name, arguments)
        elapsed = time.perf_counter() - start
        logger.info(f"[MCP] {tool_name} completed in {elapsed:.3f}s")
        return result
    except Exception as e:
        elapsed = time.perf_counter() - start
        logger.error(f"[MCP] {tool_name} failed after {elapsed:.3f}s: {e}")
        return MCPToolError(tool_name, str(e)).to_dict()


async def mcp_create_image(prompt: str) -> Any:
    """Generate an AI image based on a text description using DALL-E."""
    return await _timed_call("generate_product_image", {"prompt": prompt})


async def mcp_product_recommendations(question: str) -> Any:
    """Search for product recommendations based on user query."""
    return await _timed_call("get_product_recommendations", {"question": question})


async def mcp_calculate_discount(customer_id: str) -> Any:
    """Calculate the discount based on customer data."""
    return await _timed_call("get_customer_discount", {"customer_id": customer_id})


async def mcp_inventory_check(product_list: List[str]) -> list:
    """Check inventory for a list of products using MCP client."""
    results = []
    for product_id in product_list:
        result = await _timed_call("check_product_inventory", {"product_id": product_id})
        results.append(result)
    return results


# Dispatch table: maps function names (as registered in Microsoft Foundry)
# to the async handler that executes them via MCP.
MCP_FUNCTIONS: Dict[str, Any] = {
    "mcp_create_image": mcp_create_image,
    "mcp_product_recommendations": mcp_product_recommendations,
    "mcp_calculate_discount": mcp_calculate_discount,
    "mcp_inventory_check": mcp_inventory_check,
}
