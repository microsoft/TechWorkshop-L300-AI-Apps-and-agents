import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from agent_processor import create_function_tool_for_agent
from agent_initializer import initialize_agent

load_dotenv()

ID_PROMPT_TARGET = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'prompts', 'InteriorDesignAgentPrompt.txt')
with open(ID_PROMPT_TARGET, 'r', encoding='utf-8') as file:
    ID_PROMPT = file.read()

project_endpoint = os.environ["FOUNDRY_ENDPOINT"]

project_client = AIProjectClient(
    endpoint=project_endpoint,
    credential=DefaultAzureCredential(),
)

# Define the set of user-defined callable functions to use as tools (from MCP client)
functions = create_function_tool_for_agent("interior_designer")

initialize_agent(
    project_client=project_client,
    model=os.environ["gpt_deployment"],
    name="interior-designer",
    description="Zava Interior Design Agent",
    instructions=ID_PROMPT,
    tools=functions
)

