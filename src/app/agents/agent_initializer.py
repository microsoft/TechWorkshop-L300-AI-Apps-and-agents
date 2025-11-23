import os
from azure.ai.projects import AIProjectClient
from azure.ai.agents.models import ToolSet
from dotenv import load_dotenv

load_dotenv()

def initialize_agent(project_client : AIProjectClient, model : str, env_var_name : str, name : str, instructions : str, toolset : ToolSet):
    with project_client:
        agent = project_client.agents.create_agent(
            model=model,
            name=name,
            instructions=instructions,
            toolset=toolset
        )
        print(f"Created {name} agent, ID: {agent.id}")
