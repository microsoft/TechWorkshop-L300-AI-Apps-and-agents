import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential

from dotenv import load_dotenv
load_dotenv()

# Initialize Azure OpenAI and Azure Cognitive Search credentials
SEARCH_ENDPOINT = os.environ.get("SEARCH_ENDPOINT")
SEARCH_KEY = os.environ.get("SEARCH_KEY")
INDEX_NAME = os.environ.get("INDEX_NAME")

# Validate that required environment variables are set
if not SEARCH_ENDPOINT:
    raise ValueError("SEARCH_ENDPOINT environment variable is not set")
if not SEARCH_KEY:
    raise ValueError("SEARCH_KEY environment variable is not set")
if not INDEX_NAME:
    raise ValueError("INDEX_NAME environment variable is not set")

# Initialize Azure Cognitive Search client
credential = AzureKeyCredential(SEARCH_KEY)
search_client = SearchClient(
    endpoint=SEARCH_ENDPOINT,
    index_name=INDEX_NAME,
    credential=credential
)

# Main function to provide product recommendations with inventory check
def product_recommendations(question):
    """
    Input: 
        question (str): Natural language user query
    Output:
        products_with_inventory (list): Product json with product information
    """

    semantic_configuration_name = INDEX_NAME + "-semantic-configuration"
    
    # Step 1: Search
    search_results = search_client.search(
        search_text=question,
        query_type="semantic",
        semantic_configuration_name=semantic_configuration_name,
        top=8
    )

    print(search_results)

    # Step 2: Build response (optimized)
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
        for item in search_results
    ]
    return response
