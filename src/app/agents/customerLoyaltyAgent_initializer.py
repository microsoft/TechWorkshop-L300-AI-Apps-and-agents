import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.agents.models import ToolSet
from dotenv import load_dotenv
from agent_processor import create_function_tool_for_agent
from agent_initializer import initialize_agent

load_dotenv()

CL_PROMPT_TARGET = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'prompts', 'CustomerLoyaltyAgentPrompt.txt')
with open(CL_PROMPT_TARGET, 'r', encoding='utf-8') as file:
    CL_PROMPT = file.read()

project_endpoint = os.environ["AZURE_AI_AGENT_ENDPOINT"]

project_client = AIProjectClient(
    endpoint=project_endpoint,
    credential=DefaultAzureCredential(),
)

# Define the set of user-defined callable functions to use as tools (from MCP client)
functions = create_function_tool_for_agent("customer_loyalty")
toolset = ToolSet()
toolset.add(functions)
project_client.agents.enable_auto_function_calls(tools=functions)

initialize_agent(
    project_client=project_client,
    model=os.environ["AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME"],
    env_var_name="customer_loyalty",
    name="Zava Customer Loyalty Agent",
    instructions=CL_PROMPT,
    toolset=toolset
)