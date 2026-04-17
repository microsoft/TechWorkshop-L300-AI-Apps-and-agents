import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from tool_definitions import get_tools_for_agent_oneshot
from agent_initializer import initialize_agent
import asyncio

load_dotenv()

IA_PROMPT_TARGET = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'prompts', 'InventoryAgentPrompt.txt')
with open(IA_PROMPT_TARGET, 'r', encoding='utf-8') as file:
    IA_PROMPT = file.read()

project_endpoint = os.environ["FOUNDRY_ENDPOINT"]

project_client = AIProjectClient(
    endpoint=project_endpoint,
    credential=DefaultAzureCredential(),
)

# Define the set of user-defined callable functions to use as tools (from MCP client)
functions = asyncio.run(get_tools_for_agent_oneshot("inventory_agent"))

initialize_agent(
    project_client=project_client,
    model=os.environ["gpt_deployment"],
    name="inventory-agent",
    description="Zava Inventory Agent",
    instructions=IA_PROMPT,
    tools=functions
)

