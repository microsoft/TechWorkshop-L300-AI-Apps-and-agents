import os
from typing import Dict, Optional
from dotenv import load_dotenv
load_dotenv(override=True)

def load_env_vars() -> Dict[str, Optional[str]]:
    """Load environment variables and return as a dictionary."""
    return {
        'interior_designer': os.getenv("interior_designer"),
        'customer_loyalty': os.getenv("customer_loyalty"),
        'inventory_agent': os.getenv("inventory_agent"),
        'cora': os.getenv("cora"),
        'cart_manager': os.getenv("cart_manager"),
        'phi_4_endpoint': os.getenv("phi_4_endpoint"),
        'phi_4_deployment': os.getenv("phi_4_deployment"),
        'phi_4_api_version': os.getenv("phi_4_api_version"),
        'gpt_endpoint': os.getenv("gpt_endpoint"),
        'gpt_deployment': os.getenv("gpt_deployment"),
        'gpt_api_version': os.getenv("gpt_api_version"),
        'FOUNDRY_ENDPOINT': os.getenv("FOUNDRY_ENDPOINT"),
        'FOUNDRY_API_VERSION': os.getenv("FOUNDRY_API_VERSION"),
        'MCP_SERVER_URL': os.getenv("MCP_SERVER_URL"),
    }

def validate_env_vars(env_vars: Dict[str, Optional[str]]) -> Dict[str, str]:
    """Validate that required environment variables are set and return validated dict."""
    required_vars = [
        'phi_4_endpoint', 'phi_4_api_version', 'phi_4_deployment', 'MCP_SERVER_URL',
        'FOUNDRY_ENDPOINT', 'FOUNDRY_API_VERSION',
        'gpt_endpoint', 'gpt_deployment', 'gpt_api_version'
    ]
    missing_vars = [var for var in required_vars if not env_vars.get(var)]
    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
    validated_vars = {}
    for key, value in env_vars.items():
        if key in required_vars:
            validated_vars[key] = value  # type: ignore - we know it's not None after validation
        else:
            validated_vars[key] = value
    return validated_vars