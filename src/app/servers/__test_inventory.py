import asyncio
import sys
from pathlib import Path
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

"""
Test the MCP inventory server via stdio transport.

To run:
    python __test_inventory.py
"""

_SERVER_SCRIPT = str(Path(__file__).parent / "mcp_inventory_server.py")


async def main():
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[_SERVER_SCRIPT],
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # List available prompts
            prompts_result = await session.list_prompts()
            print("Available prompts:")
            for prompt in prompts_result.prompts:
                print(f"  - {prompt.name}: {prompt.description}")

            # List available tools
            tools_result = await session.list_tools()
            print("Available tools:")
            for tool in tools_result.tools:
                print(f"  - {tool.name}: {tool.description}")

            # Call a tool
            result = await session.call_tool(
                "get_product_recommendations",
                arguments={"question": "Should paint for a kitchen wall be white?"}
            )
            print(f"Product recommendations: {result.content[0].text}")


if __name__ == "__main__":
    asyncio.run(main())
