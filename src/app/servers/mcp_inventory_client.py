"""
Tools MCP Client - Connects to the mcp tools server via SSE
"""
import asyncio
import logging
from typing import Any, Dict, Optional, List
from mcp import ClientSession
from mcp.client.sse import sse_client
from contextlib import AsyncExitStack
import json


logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


class MCPShopperToolsClient:
    """Client for connecting to MCP tools server via SSE."""
    
    def __init__(self, server_url: Optional[str] = None):
        """
        Initialize the MCP tools client
        Args:
            server_url: URL of the MCP server.
        """
        self.server_url = server_url or "http://localhost:8000/sse"
        self.available_tools: List[Dict[str, Any]] = []



    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """
        Call a tool on the MCP server
        
        Args:
            tool_name: Name of the tool to call
            arguments: Dictionary of arguments to pass to the tool
            
        Returns:
            The result from the tool call
        """
        async with sse_client(self.server_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                logger.info(f"Calling tool '{tool_name}' with arguments: {arguments}")
                
                result_data = await session.call_tool(tool_name, arguments=arguments)
                logger.info(f"Tool '{tool_name}' returned: {result_data.content}")

                 # Extract the result from the response
                if result_data.content and len(result_data.content) > 0:
                    result = result_data.content[0].text
                else:
                    result = str(result_data)

                # Try to parse as JSON if it's a string
                if isinstance(result, str):
                    try:
                        return json.loads(result)
                    except (json.JSONDecodeError, ValueError):
                        return result
                
                return result
    
    async def list_tools(self):
        
        """
        List all available tools from the MCP server
        
        Returns:
            List of available tools
        """
        try:
            async with sse_client(self.server_url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    logger.info("Listing available tools...")
                    
                    tools_result = await session.list_tools()
                    logger.info(f"Found {len(tools_result.tools)} tools")
                    
                    return tools_result.tools
        except Exception as e:
            logger.error(f"Error listing tools: {e}")
            raise e
    
    async def get_mcp_tools_llm(self) -> List[Dict[str, Any]]:
        """Get available tools from the MCP server in OpenAI format.

        Returns:
            A list of tools in OpenAI format.
        """
        try:

            tools_result = await self.list_tools()
            return [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema,
                    },
                }
                for tool in tools_result
            ]
        except Exception as e:
            logger.error(f"Error getting MCP tools in LLM format: {e}")
        return []
    
    async def get_agent_prompt(self, agent_id: str) -> str:
        """Get the prompt template for a specific agent."""
        async with sse_client(self.server_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                logger.info(f"Fetching prompt for agent ID: {agent_id}")
                
                prompt_result = await session.get_prompt("agentPrompt", {"agent_name": agent_id})
                if prompt_result.messages:
                    # Typically prompts return text in the first message content
                    prompt_text = prompt_result.messages[0].content.text
                    
                    return prompt_text
                else:
                    logger.warning(f"Prompt '{agent_id}' returned no messages")
                    return ""
                
                return prompt_result.prompt_template
 
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
    
    async def cleanup(self):
        """Close the MCP session."""
        
        self._initialized = False
        print("[MCP] Disconnected from shopping tools server")


# Synchronous wrapper functions for easier use
def call_tool_sync(tool_name: str, arguments: Dict[str, Any]) -> Any:
    """Synchronous wrapper for calling a tool"""
    client = MCPShopperToolsClient()
    return asyncio.run(client.call_tool(tool_name, arguments))


def list_tools_sync():
    """Synchronous wrapper for listing tools"""
    client = MCPShopperToolsClient()
    return asyncio.run(client.list_tools())

# Example usage and testing
async def main():
    """Test the MCP Shopper Tools client"""
    client = MCPShopperToolsClient()
    
    print("=" * 60)
    print("Testing Tools MCP Client")
    print("=" * 60)
    
    try:
        # Test 1: List all tools
        print("\n1. Listing available tools:")
        tools = await client.list_tools()
        for tool in tools:
            print(f"   - {tool.name}: {tool.description}")
    

        # Test 3: Test get_product_recommendations tool
        result = await client.get_product_recommendations("Paint for a kitchen wall should be white?")
        print(f"   Product recommendations: {result}")
        
       
        
        print("\n" + "=" * 60)
        print("All tests completed successfully! ✓")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ ERROR during testing: {e}")
        import traceback
        traceback.print_exc()

# Singleton instance
_mcp_client: Optional[MCPShopperToolsClient] = None

async def get_mcp_client(server_url: str = "http://localhost:8000/see") -> MCPShopperToolsClient:
    """Get or create the singleton MCP client."""
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = MCPShopperToolsClient(server_url)
        _mcp_client.available_tools = await _mcp_client.list_tools()
    return _mcp_client

if __name__ == "__main__":
    asyncio.run(main())

