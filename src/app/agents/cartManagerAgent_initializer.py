import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from agent_processor import create_function_tool_for_agent
from agent_initializer import initialize_agent

load_dotenv()

CART_PROMPT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'prompts', 'CartManagerPrompt.txt')
with open(CART_PROMPT_PATH, 'r', encoding='utf-8') as file:
    CART_MANAGER_PROMPT = file.read()

project_endpoint = os.environ["FOUNDRY_ENDPOINT"]

project_client = AIProjectClient(
    endpoint=project_endpoint,
    credential=DefaultAzureCredential(),
)

# Create function tools for cart_manager agent
functions = create_function_tool_for_agent("cart_manager")

initialize_agent(
    project_client=project_client,
    model=os.environ["gpt_deployment"],
    name="cart-manager",
    description="Zava Cart Manager Agent",
    instructions=CART_MANAGER_PROMPT,
    tools=functions
)
