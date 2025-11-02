import logging
import pandas as pd
import os
from azure.cosmos import CosmosClient, PartitionKey
from azure.identity import DefaultAzureCredential
from azure.core.exceptions import AzureError
from dotenv import load_dotenv

load_dotenv()

# CONFIGURATIONS - Replace with your actual values
COSMOS_ENDPOINT = os.environ.get("COSMOS_ENDPOINT")
COSMOS_KEY = os.environ.get("COSMOS_KEY")
DATABASE_NAME = os.environ.get("DATABASE_NAME")
CONTAINER_NAME = os.environ.get("CONTAINER_NAME")
CSV_FILE = r"data/updated_product_catalog(in).csv"  #Placeholder here to avoid rerunning the code


# 1. Read data from CSV
df = pd.read_csv(CSV_FILE, encoding='cp1252') 

df['content_for_vector'] = (
    df['ProductName'].fillna('').astype(str) + ' | ' +
    df['ProductCategory'].fillna('').astype(str) + ' | ' +
    df['ProductDescription'].fillna('').astype(str)
)

# 2. Connect to Cosmos DB
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.WARNING)


def get_cosmos_client(endpoint: str | None, key: str | None = None):
    """Try to authenticate to Cosmos DB using DefaultAzureCredential first.

    If that fails, fall back to using the provided key.
    Returns a connected CosmosClient instance.
    """
    if not endpoint:
        raise ValueError("COSMOS_ENDPOINT must be provided in environment variables")

    # Try AAD first
    try:
        logger.info("Attempting to authenticate to Cosmos DB using DefaultAzureCredential (AAD)...")
        credential = DefaultAzureCredential()
        client = CosmosClient(endpoint, credential=credential)

        # perform a light operation to validate the credential (will raise if unauthorized)
        # Using read_account or listing databases is a small call; here we try to list databases.
        _ = list(client.list_databases())
        logger.info("Authenticated to Cosmos DB with DefaultAzureCredential.")
        return client
    except AzureError as ex:
        logger.warning("AAD authentication failed: %s", ex)

    # Fallback to key
    if key:
        try:
            logger.info("Falling back to endpoint + key authentication for Cosmos DB...")
            client = CosmosClient(endpoint, key)
            # validate key by a light operation
            _ = list(client.list_databases())
            logger.info("Authenticated to Cosmos DB with endpoint+key.")
            return client
        except Exception as ex:
            logger.error("Endpoint+key authentication failed: %s", ex)
            raise

    # If we reach here, both auth methods failed or no key provided
    raise RuntimeError("Failed to authenticate to Cosmos DB using DefaultAzureCredential and no valid COSMOS_KEY was provided")


# 2. Connect to Cosmos DB
client = get_cosmos_client(COSMOS_ENDPOINT, COSMOS_KEY)

if not DATABASE_NAME:
    raise ValueError("DATABASE_NAME must be provided in environment variables")

if not CONTAINER_NAME:
    raise ValueError("CONTAINER_NAME must be provided in environment variables")

database = client.create_database_if_not_exists(id=DATABASE_NAME)
container = database.create_container_if_not_exists(
    id=CONTAINER_NAME,
    partition_key=PartitionKey(path="/ProductID")
)

# 3. Upload items
for idx, row in df.iterrows():
    # Convert row to dict
    item = row.to_dict()
    item['id'] = str(item['ProductID'])
    item['ProductID'] = str(item['ProductID'])

    # Insert or update item
    container.upsert_item(body=item)
    print(f"Uploaded: ProductID {item['ProductID']}")

print("All data uploaded to Cosmos DB.")