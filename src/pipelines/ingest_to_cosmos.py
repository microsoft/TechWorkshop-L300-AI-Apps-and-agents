import pandas as pd
import os
from azure.cosmos import CosmosClient, PartitionKey
from azure.identity import DefaultAzureCredential
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

credential = DefaultAzureCredential()
client = CosmosClient(COSMOS_ENDPOINT, credential=credential)
#client = CosmosClient(COSMOS_ENDPOINT, COSMOS_KEY)

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