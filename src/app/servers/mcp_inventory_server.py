import json
import sys
from dotenv import load_dotenv
from pathlib import Path
from typing import Dict, Any
from mcp.server.fastmcp import FastMCP

env_path = Path(__file__).parent.parent.parent / '.env'
if env_path.exists():
    load_dotenv(dotenv_path=env_path, override=True)
else:
    # Try loading from current directory as fallback
    load_dotenv(override=True)

# Add src directory to Python path
src_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(src_path))
from app.tools import product_recommendations, inventory_check, calculate_discount, create_image


"""
MCP Server for Shopping Inventory and Customer Loyalty Tools

    cd to the `app/servers` directory and run:
        uv run server mcp_inventory_server stdio
    Test it in MCP inspector or via an MCP client: 
        mcp dev mcp_inventory_client.py
"""
# Create an MCP server
mcp = FastMCP("MCP Shop Inventory Server")


### MCP Tools ###
@mcp.tool()
def get_product_recommendations(question: str) -> str:
    """
    Search for product recommendations based on user query.
    
    Args:
        question: Natural language user query describing what products they're looking for
    
    Returns:
        Product details including ID, name, category, description, image URL, and price
    """
    results = product_recommendations(question)
    return json.dumps(results) if not isinstance(results, str) else results

@mcp.tool()
def check_product_inventory(product_id: str) -> str:
    """
    Check inventory availability for a specific product.
    
    Args:
        product_id: The unique product ID to check inventory for
    
    Returns:
        Inventory status and availability information
    """
    product_dict = {"id": product_id}
    result = inventory_check(product_dict)
    return json.dumps(result) if not isinstance(result, str) else result

@mcp.tool()
def get_customer_discount(customer_id: str) -> str:
    """
    Calculate available discounts for a customer based on their purchase history.
    
    Args:
        customer_id: The customer's unique identifier
    
    Returns:
        Discount information including percentage and final amount
    """
    result = calculate_discount(customer_id)
    return json.dumps(result) if not isinstance(result, str) else result

@mcp.tool()
def generate_product_image(prompt: str, size: str = "1024x1024") -> str:
    """
    Generate an AI image based on a text description using DALL-E.
    
    Args:
        prompt: Detailed description of the image to generate
        size: Image size (e.g., '1024x1024'), defaults to '1024x1024'
    
    Returns:
        URL or path to the generated image
    """
    result = create_image(prompt, size)
    return json.dumps(result) if not isinstance(result, str) else result


### MCP Prompts ###
# Get the prompts directory path
PROMPTS_DIR = Path(__file__).parent.parent.parent / 'prompts'

def read_prompt_file(filename: str) -> str:
    """Read a prompt file from the prompts directory."""
    file_path = PROMPTS_DIR / filename
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()

@mcp.prompt(title="AI Search Tool Prompt")
def aiSearchToolPrompt(srch_result: str, question: str) -> str:
    prompt_template = read_prompt_file('aiSearchToolPrompt.txt')
    return f"{prompt_template}\n\nsrch_explanation: {{srch_result}}\nquestion: {{question}}".format(srch_result=srch_result, question=question)


@mcp.prompt(title="Agent Prompt")
def agentPrompt(agent_name: str) -> str:
    """
    Returns the appropriate agent prompt based on the agent name.
    
    Args:
        agent_name: One of 'cora', 'customer_loyalty', 'discount_logic', 'interior_designer', or 'inventory'
    """
    prompt_files = {
        "cora": "ShopperAgentPrompt.txt",
        "customer_loyalty": "CustomerLoyaltyAgentPrompt.txt",
        "discount_logic": "DiscountLogicPrompt.txt",
        "interior_designer": "InteriorDesignAgentPrompt.txt",
        "inventory": "InventoryAgentPrompt.txt"
    }
    
    agent_name_lower = agent_name.lower()
    if agent_name_lower in prompt_files:
        return read_prompt_file(prompt_files[agent_name_lower])
    else:
        return f"Unknown agent name: {agent_name}. Valid options are: cora, customer_loyalty, discount_logic, interior_designer, inventory"

if __name__ == "__main__":
    mcp.run(transport="sse")
