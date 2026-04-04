"""
MCP Client - Connects to the MCP inventory server via stdio transport
with a persistent connection that is reused across tool calls.
"""
import asyncio
import logging
import sys
from typing import Any, Dict, List, Optional
from pathlib import Path
from contextlib import AsyncExitStack

from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters
import json

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# Path to the MCP server script
_SERVER_SCRIPT = str(Path(__file__).parent / "mcp_inventory_server.py")


class MCPShopperToolsClient:
    """Client for connecting to MCP tools server via stdio with a persistent connection."""

    def __init__(self):
        self._session: Optional[ClientSession] = None
        self._exit_stack: Optional[AsyncExitStack] = None
        self.available_tools: List[Dict[str, Any]] = []

    async def connect(self) -> None:
        """Establish a persistent stdio connection to the MCP server."""
        if self._session is not None:
            return  # Already connected

        self._exit_stack = AsyncExitStack()

        server_params = StdioServerParameters(
            command=sys.executable,
            args=[_SERVER_SCRIPT],
        )

        read, write = await self._exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await self._session.initialize()
        logger.info("MCP client connected via stdio")

    async def close(self) -> None:
        """Close the persistent connection."""
        if self._exit_stack is not None:
            await self._exit_stack.aclose()
            self._session = None
            self._exit_stack = None
            logger.info("MCP client disconnected")

    async def _ensure_connected(self) -> ClientSession:
        """Ensure the client is connected and return the session."""
        if self._session is None:
            await self.connect()
        return self._session

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any], timeout: float = 60.0) -> Any:
        """
        Call a tool on the MCP server using the persistent connection.

        Args:
            tool_name: Name of the tool to call
            arguments: Dictionary of arguments to pass to the tool
            timeout: Timeout in seconds for the tool call

        Returns:
            The result from the tool call
        """
        import time as _time
        session = await self._ensure_connected()
        logger.info(f"Calling tool '{tool_name}' with arguments: {arguments}")

        start = _time.perf_counter()
        result_data = await asyncio.wait_for(
            session.call_tool(tool_name, arguments=arguments),
            timeout=timeout,
        )
        elapsed = _time.perf_counter() - start
        logger.info(f"[MCP] {tool_name} completed in {elapsed:.3f}s")

        if result_data.content and len(result_data.content) > 0:
            result = result_data.content[0].text
        else:
            result = str(result_data)

        if isinstance(result, str):
            try:
                return json.loads(result)
            except (json.JSONDecodeError, ValueError):
                return result

        return result

    async def list_tools(self) -> list:
        """List all available tools from the MCP server."""
        session = await self._ensure_connected()
        tools_result = await session.list_tools()
        logger.info(f"Found {len(tools_result.tools)} tools")
        return tools_result.tools

    async def get_agent_prompt(self, agent_id: str) -> str:
        """Get the prompt template for a specific agent."""
        session = await self._ensure_connected()
        logger.info(f"Fetching prompt for agent ID: {agent_id}")

        prompt_result = await session.get_prompt("agentPrompt", {"agent_name": agent_id})
        if prompt_result.messages:
            return prompt_result.messages[0].content.text
        else:
            logger.warning(f"Prompt '{agent_id}' returned no messages")
            return ""

    async def get_product_recommendations(self, question: str) -> List[Dict[str, Any]]:
        """Get product recommendations based on query."""
        return await self.call_tool("get_product_recommendations", {"question": question})

    async def check_inventory(self, product_id: str) -> Dict[str, Any]:
        """Check inventory for a product."""
        return await self.call_tool("check_product_inventory", {"product_id": product_id})

    async def calculate_discount(self, customer_id: str) -> Dict[str, Any]:
        """Calculate discount for a customer based on their purchase history."""
        return await self.call_tool("get_customer_discount", {"customer_id": customer_id})

    async def create_image(self, prompt: str, size: str = "1024x1024") -> str:
        """Generate an image from a prompt."""
        return await self.call_tool("generate_product_image", {"prompt": prompt, "size": size})


# Singleton instance with persistent connection
_mcp_client: Optional[MCPShopperToolsClient] = None


async def get_mcp_client() -> MCPShopperToolsClient:
    """Get or create the singleton MCP client with a persistent connection."""
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = MCPShopperToolsClient()
        await _mcp_client.connect()
        _mcp_client.available_tools = await _mcp_client.list_tools()
    return _mcp_client


# Example usage and testing
async def main():
    """Test the MCP Shopper Tools client"""
    client = await get_mcp_client()

    print("=" * 60)
    print("Testing Tools MCP Client (stdio)")
    print("=" * 60)

    try:
        print("\n1. Listing available tools:")
        tools = await client.list_tools()
        for tool in tools:
            print(f"   - {tool.name}: {tool.description}")

        print("\n2. Testing get_product_recommendations:")
        result = await client.get_product_recommendations("Paint for a kitchen wall should be white?")
        print(f"   Product recommendations: {result}")

        print("\n" + "=" * 60)
        print("All tests completed successfully!")
        print("=" * 60)

    except Exception as e:
        print(f"\nERROR during testing: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
