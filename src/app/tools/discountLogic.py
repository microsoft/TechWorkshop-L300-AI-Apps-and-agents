import os
import pandas as pd
from openai import AzureOpenAI
from dotenv import load_dotenv
load_dotenv()

from opentelemetry import trace
from azure.monitor.opentelemetry import configure_azure_monitor
from azure.ai.agents.telemetry import trace_function
import time
from opentelemetry.instrumentation.openai_v2 import OpenAIInstrumentor

# Enable Azure Monitor tracing
application_insights_connection_string = os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"]
configure_azure_monitor(connection_string=application_insights_connection_string)
OpenAIInstrumentor().instrument()

# scenario = os.path.basename(__file__)
# tracer = trace.get_tracer(__name__)

#Azure OpenAI
endpoint = os.getenv("gpt_endpoint")
deployment = os.getenv("gpt_deployment")
api_key = os.getenv("gpt_api_key")
api_version = os.getenv("gpt_api_version")

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))  # Go up 2 levels from src/tools/ to root
PROMPT_PATH = os.path.join(project_root, 'prompts', 'DiscountLogicPrompt.txt')
with open(PROMPT_PATH, 'r') as file:
    PROMPT = file.read()

@trace_function()
def calculate_discount(CustomerID):
    print(f"calculate_discount function:{CustomerID}")
    """
    Calculate the discount based on customer data.

    Args:
        CustomerID (str): The ID of the customer.
    
    Returns:
        float: The calculated discount amount and percentage.
    """

    start_time = time.time()
    # @trace_function()
    def get_transaction_data(CustomerID):
        start_time = time.time()
        time.sleep(2)  # Simulating a delay for demonstration purposes
        """
        Simulates connecting to Azure SQL database. Returns the total price for a given customer ID from the transaction data.
        
        Parameters:
            CustomerID (str): The ID of the customer.
            
        Returns:
            float: The total price of purchases for the given customer.
        """
        
        # Adding attributes to the current span
        span = trace.get_current_span()
        span.set_attribute("Customer ID Detected", CustomerID)
        
        try:
            # This simulates reading transactional data from a database.
            if CustomerID == "CUST001":
                result = "524.21"
            else:
                result = "121.53"
        except Exception as e:
            print(f"Error: {e}")
            result = "0.0"
        end_time = time.time()
        print(f"get_transaction_data Execution Time: {end_time - start_time} seconds")
        return result
    # @trace_function()    
    def fetch_loyalty_profile_data(CustomerID:str):
        start_time = time.time()
        """
        Simulates connecting to Microsoft Fabric SQL endpoint.
        Fetches all data from the 'customer_loyalty_profile' table.

        Returns:
            DataFrame containing the query results.
        """
        # This simulates connecting to a Fabric lakehouse to retrieve customer data.
        time.sleep(2)  
        # Adding attributes to the current span
        span = trace.get_current_span()
        span.set_attribute("data_fetch_id", CustomerID)

        if CustomerID == 'CUST001':
            df = pd.DataFrame({
                'CustomerID': ['CUST001'],
                'CustomerName': ['Bruno'],
                'CustomerEmail': ['bruno70@gmail.com'],
                'LoyaltyTier': ['Platinum'],
                'LoyaltyDiscount': [0.324],
                'TotalAmountSpent': [2156.5],
                'TotalAmountSpentThisYear': [524.21],
                'Tenure': [5],
                'Churn': [0]
            })
        else:
            df = pd.DataFrame({
                'CustomerID': [CustomerID],
                'CustomerName': ['The Other Person'],
                'CustomerEmail': ['otherperson@example.com'],
                'LoyaltyTier': ['Silver'],
                'LoyaltyDiscount': [0.075],
                'TotalAmountSpent': [225.5],
                'TotalAmountSpentThisYear': [121.53],
                'Tenure': [2],
                'Churn': [0.3]
            })
        return df  
    # @trace_function()
    def discount_logic_using_model(transaction_info,loyalty_info):
        start_time = time.time()
        """
        Calculates the discount percentage for a customer based on transaction and loyalty data.

        Args:
            transaction_info (float or int): Includes total price for a given customer ID from the transaction data.
            loyalty_info (dict): Includes customer tenure, churn risk score,lifetime value and loyalty tier or program eligibility.
            InvoiceValue (float or int): The amount the customer is spending in the current purchase.

        Returns:
            float: Discount amount to be applied based on the business logic.
        """
        # Initialize client
        client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )
        # print(f"loyalty_info is:{loyalty_info}, invoice value: {InvoiceValue} and transaction_info is:{transaction_info}")
        prompt= "Bruno's total transaction price in this year"+ transaction_info + "and his data"+str(loyalty_info)
        # print(f"prompt:{prompt}")
        # print(f"Prompt for agent:{PROMPT}")
        # Define chat prompt
        chat_prompt = [
            {
                "role": "developer",
                "content": [
                    {
                        "type": "text",
                        "text": PROMPT
                    }
                ]
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }
        ]

        # Generate chat completion
        completion = client.chat.completions.create(
            model=deployment,
            messages=chat_prompt,
            max_completion_tokens=5000,
            stop=None,
            stream=False
        )
        response_dict = completion.model_dump()
        response_message = response_dict["choices"][0]["message"]["content"]
        # Adding attributes to the current span
        span = trace.get_current_span()
        span.set_attribute("discount_logic_response", response_message)
        end_time = time.time()
        print(f"discount_logic_using_model Execution Time: {end_time - start_time} seconds")
        return response_message

    transaction_info=get_transaction_data(CustomerID)
    # print(f"transaction_info{transaction_info}")
    loyalty_info=fetch_loyalty_profile_data(CustomerID)
    # print(f"loyalty_info :{loyalty_info}")
    discount_info=discount_logic_using_model(transaction_info,loyalty_info)
    end_time = time.time()
    # print(f"calculate_discount Execution Time: {end_time - start_time} seconds")
    return discount_info
