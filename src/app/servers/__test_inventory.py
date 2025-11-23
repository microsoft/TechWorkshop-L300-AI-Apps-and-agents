import asyncio
import nest_asyncio
from mcp import ClientSession
from mcp.client.sse import sse_client

nest_asyncio.apply()  # Needed to run interactive python

"""
Make sure:
1. The server is running before running this script.
2. The server is configured to use SSE transport.
3. The server is listening on port 8000.

To run the server:
uv run mcp_inventory_server.py
To test the client:
mcp dev mcp_inventory_client.py
"""


async def main():
    # Connect to the server using SSE
    async with sse_client("http://localhost:8000/sse") as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            # Initialize the connection
            await session.initialize()

            # List available tools
            #tools_result = await session.list_tools()

            # List available prompts
            prompts_result = await session.list_prompts()
            print("Available prompts:")
            for prompt in prompts_result.prompts:
                print(f"  - {prompt.name}: {prompt.description}")

            tools_result = await session.list_tools()
            print("Available tools:")
            for tool in tools_result.tools:
                print(f"  - {tool.name}: {tool.description}")
            # Call our calculator tool
            result = await session.call_tool("product_recommendations", arguments={"question": "Paint for a kitchen wall should be white?"})
            print(f"Product recommendations: {result.content[0].text}")


if __name__ == "__main__":
    asyncio.run(main())