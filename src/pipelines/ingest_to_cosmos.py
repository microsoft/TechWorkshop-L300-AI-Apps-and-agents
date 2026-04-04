import logging
import json
import os
from typing import Any
import requests

from azure.cosmos import CosmosClient, PartitionKey
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv


load_dotenv()

# CONFIGURATIONS - Replace with your actual values or set as env vars
COSMOS_ENDPOINT = os.environ.get("COSMOS_ENDPOINT")
DATABASE_NAME = os.environ.get("DATABASE_NAME")
CONTAINER_NAME = os.environ.get("CONTAINER_NAME")
JSON_FILE = os.environ.get("JSON_FILE", "data/product_catalog.json")
EMBEDDING_ENDPOINT = os.environ.get("embedding_endpoint")
EMBEDDING_DEPLOYMENT = os.environ.get("embedding_deployment")
EMBEDDING_API_VERSION = os.environ.get("embedding_api_version")

credential = DefaultAzureCredential()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.WARNING)


def get_cosmos_client(endpoint: str | None):
    if not endpoint:
        raise ValueError("COSMOS_ENDPOINT must be provided in environment variables")

    logger.info("Authenticating to Cosmos DB using DefaultAzureCredential (managed identity)...")
    client = CosmosClient(endpoint, credential=credential)
    _ = list(client.list_databases())
    logger.info("Authenticated to Cosmos DB with DefaultAzureCredential.")
    return client


def load_json_items(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data

    raise ValueError("Unsupported JSON structure in file")


def ensure_string_ids(item: dict[str, Any]) -> dict[str, Any]:
    # Ensure ProductID exists and both id and ProductID are strings
    if "ProductID" not in item:
        raise KeyError("Item missing 'ProductID' field")

    product_id = item["ProductID"]
    # Keep original value but convert to string for id and ProductID
    item["ProductID"] = str(product_id)
    item["id"] = str(product_id)

    return item


def get_request_embedding(text: str) -> list[float] | None:
    """Call embedding endpoint and return the embedding vector or None on failure."""
    if not EMBEDDING_ENDPOINT or not EMBEDDING_DEPLOYMENT or not EMBEDDING_API_VERSION:
        logger.error("Embedding env vars not fully set; failing embedding generation.")
        return None

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
    # Expecting Azure OpenAI style response: {"data":[{"embedding": [...]}, ...]}
    embedding = data.get("data", [{}])[0].get("embedding")
    return embedding


def main() -> None:
    client = get_cosmos_client(COSMOS_ENDPOINT)

    if not DATABASE_NAME:
        raise ValueError("DATABASE_NAME must be provided in environment variables")

    if not CONTAINER_NAME:
        raise ValueError("CONTAINER_NAME must be provided in environment variables")

    database = client.create_database_if_not_exists(id=DATABASE_NAME)
    container = database.create_container_if_not_exists(
        id=CONTAINER_NAME, partition_key=PartitionKey(path="/ProductID")
    )

    items = load_json_items(JSON_FILE)

    for raw in items:
        try:
            item = ensure_string_ids(dict(raw))

            # Build text to embed from ProductName, ProductCategory, ProductDescription
            name = str(item.get("ProductName", ""))
            category = str(item.get("ProductCategory", ""))
            desc = str(item.get("ProductDescription", ""))
            content_for_vector = " \n ".join([p for p in (name, category, desc) if p])

            try:
                embedding = get_request_embedding(content_for_vector)
                if embedding is not None:
                    item["request_vector"] = embedding
                else:
                    logger.warning("No embedding returned for ProductID %s", item.get("ProductID"))
            except Exception as e:
                logger.warning("Failed to generate embedding for ProductID %s: %s", item.get("ProductID"), e)

            container.upsert_item(body=item)
            print(f"Uploaded: ProductID {item['ProductID']}")
        except Exception as ex:
            logger.error("Failed to upload item: %s; error: %s", raw, ex)

    print("All data uploaded to Cosmos DB.")


if __name__ == "__main__":
    main()