import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.agents.models import FunctionTool, ToolSet
from typing import Callable, Set, Any
from tools.discountLogic import calculate_discount
# from tools.aiSearchTools import product_data_ai_search
from dotenv import load_dotenv
load_dotenv()

CL_PROMPT_TARGET = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'prompts', 'CustomerLoyaltyAgentPrompt.txt')
with open(CL_PROMPT_TARGET, 'r', encoding='utf-8') as file:
    CL_PROMPT = file.read()

project_endpoint= os.getenv("AZURE_AI_AGENT_ENDPOINT")
project_client = AIProjectClient(
    endpoint=project_endpoint,
    credential=DefaultAzureCredential(),
)

user_functions: Set[Callable[..., Any]] = {
    calculate_discount,
}

# Initialize agent toolset with user functions
functions = FunctionTool(user_functions)
toolset = ToolSet()
toolset.add(functions)
project_client.agents.enable_auto_function_calls(tools=functions)

with project_client:
    agent = project_client.agents.create_agent(
        model=os.getenv("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME"),  # Model deployment name
        name="Zava Customer Loyalty Agent",  # Name of the agent
        instructions=CL_PROMPT,  # Instructions for the agent
        toolset=toolset,
    )
    print(f"Created agent, ID: {agent.id}")
