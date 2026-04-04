import os
import sys
import requests
from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

# Cosmos DB configuration
COSMOS_ENDPOINT = os.environ.get("COSMOS_ENDPOINT")
DATABASE_NAME = os.environ.get("DATABASE_NAME")
CONTAINER_NAME = os.environ.get("CONTAINER_NAME")

# Embedding service configuration (used to encode the query)
EMBEDDING_ENDPOINT = os.environ.get("embedding_endpoint")
EMBEDDING_DEPLOYMENT = os.environ.get("embedding_deployment")
EMBEDDING_API_VERSION = os.environ.get("embedding_api_version")

credential = DefaultAzureCredential()

# Validate required Cosmos env vars
if not COSMOS_ENDPOINT:
    raise ValueError("COSMOS_ENDPOINT environment variable is not set")
if not DATABASE_NAME:
    raise ValueError("DATABASE_NAME environment variable is not set")
if not CONTAINER_NAME:
    raise ValueError("CONTAINER_NAME environment variable is not set")


def get_cosmos_client(endpoint: str | None):
    if not endpoint:
        raise ValueError("COSMOS_ENDPOINT must be provided in environment variables")

    client = CosmosClient(endpoint, credential=credential)
    _ = list(client.list_databases())
    return client


def get_request_embedding(text: str) -> list[float] | None:
    """Call embedding endpoint and return the embedding vector or None on failure."""
    if not EMBEDDING_ENDPOINT or not EMBEDDING_DEPLOYMENT or not EMBEDDING_API_VERSION:
        raise ValueError("Embedding endpoint configuration missing. Set EMBEDDING_ENDPOINT, EMBEDDING_DEPLOYMENT, EMBEDDING_API_VERSION")

    url = EMBEDDING_ENDPOINT.rstrip("/") + f"/openai/deployments/{EMBEDDING_DEPLOYMENT}/embeddings?api-version={EMBEDDING_API_VERSION}"
    token = credential.get_token("https://cognitiveservices.azure.com/.default")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token.token}",
    }
    payload = {"input": text}

    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    embedding = data.get("data", [{}])[0].get("embedding")
    return embedding


# Initialize Cosmos client and container
_cosmos_client = get_cosmos_client(COSMOS_ENDPOINT)
_database = _cosmos_client.get_database_client(DATABASE_NAME)
_container = _database.get_container_client(CONTAINER_NAME)


def product_recommendations(question: str, top_k: int = 8):
    """
    Input:
        question (str): Natural language user query
        top_k (int): number of nearest neighbors to return
    Output:
        list of product dicts with product information
    """

    # Generate embedding for the query
    query_vector = get_request_embedding(question)
    if query_vector is None:
        raise RuntimeError("Failed to generate query embedding")

    # Cosmos DB vector search SQL. Requires Cosmos account with vector search enabled
    query = (
        "SELECT c.id, c.ProductID, c.ProductName, c.ProductCategory, c.ProductDescription, "
        "c.ImageURL, c.ProductPunchLine, c.Price "
        "FROM c "
        "ORDER BY VECTORDISTANCE(c.request_vector, @vector) "
        "OFFSET 0 LIMIT @top"
    )

    parameters = [
        {"name": "@vector", "value": query_vector},
        {"name": "@top", "value": top_k},
    ]

    items = list(_container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True,
        max_item_count=top_k
    ))

    get = dict.get
    response = [
        {
            "id": get(item, "ProductID", None),
            "name": get(item, "ProductName", None),
            "type": get(item, "ProductCategory", None),
            "description": get(item, "ProductDescription", None),
            "imageURL": get(item, "ImageURL", None),
            "punchLine": get(item, "ProductPunchLine", None),
            "price": get(item, "Price", None)
        }
        for item in items
    ]

    return response
