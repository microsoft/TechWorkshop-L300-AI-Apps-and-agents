import json
import re
import orjson
from utils.message_utils import fast_json_dumps

def extract_bot_reply(msg) -> str:
    """Extract the bot reply from the agent processor message."""
    msg = str(msg)
    match = re.search(r"'value':\s*'([^']*)'", msg)
    if match:
        result = match.group(1)
        return result
    return msg

def extract_product_names_from_response(response_data) -> str:
    """Extract product names from response data and format them."""
    try:
        # Handle string response data
        if isinstance(response_data, str):
            try:
                response_data = orjson.loads(response_data)
            except (orjson.JSONDecodeError, TypeError):
                return ""
        
        # Handle dictionary response
        if isinstance(response_data, dict):
            products = response_data.get("products")
            if products:
                # Handle products as string (JSON)
                if isinstance(products, str):
                    try:
                        products_list = orjson.loads(products)
                    except (orjson.JSONDecodeError, TypeError):
                        return ""
                # Handle products as list
                elif isinstance(products, list):
                    products_list = products
                else:
                    return ""
                
                # Extract names from products
                if products_list and isinstance(products_list, list):
                    names = []
                    for product in products_list:
                        if isinstance(product, dict) and "name" in product:
                            names.append(product["name"])
                    if names:
                        return f" [Products Mentioned: {', '.join(names)}]"
        
        return ""
    except Exception:
        return ""

def parse_agent_response(response: str) -> dict:
    """
    Parse agent response to check if it's JSON format.
    Handles JSON inside code blocks (```json ... ```),
    both objects and arrays, and also plain JSON strings.
    If it's JSON, map the fields accordingly.
    If it's not JSON, return it as "answer" with other fields empty.
    """
    # Try to extract JSON (object or array) from code block
    codeblock_match = re.search(r'```(?:json)?\s*([\[{].*[\]}])\s*```', response, re.DOTALL)
    if codeblock_match:
        response = codeblock_match.group(1).strip()
    else:
        # If not in code block, try to extract a JSON object or array from the string
        json_match = re.search(r'([\[{].*[\]}])', response, re.DOTALL)
        if json_match:
            response = json_match.group(1).strip()
    try:
        parsed_response = json.loads(response)
        if isinstance(parsed_response, list) and len(parsed_response) > 0:
            first_item = parsed_response[0]
            if isinstance(first_item, dict):
                answer = first_item.get("answer", "")
                products = first_item.get("products", "")
                image_output = first_item.get("image_output", "")
                discount_percentage = first_item.get("discount_percentage", "")
                cart = first_item.get("cart", [])
                if products and not isinstance(products, str):
                    products = json.dumps(products)
                return {
                    "answer": answer,
                    "agent": "",
                    "products": products,
                    "discount_percentage": str(discount_percentage) if discount_percentage else "",
                    "image_url": image_output,
                    "additional_data": "",
                    "cart": cart
                }
            else:
                return {
                    "answer": str(parsed_response),
                    "agent": "",
                    "products": "",
                    "discount_percentage": "",
                    "image_url": "",
                    "additional_data": ""
                }
        elif isinstance(parsed_response, dict):
            answer = parsed_response.get("answer", "")
            if isinstance(answer, str) and answer.startswith('[') and answer.endswith(']'):
                try:
                    nested_json = json.loads(answer)
                    if isinstance(nested_json, list) and len(nested_json) > 0:
                        first_item = nested_json[0]
                        if isinstance(first_item, dict) and "answer" in first_item:
                            answer = first_item["answer"]
                except json.JSONDecodeError:
                    pass
            return {
                "answer": answer,
                "agent": parsed_response.get("agent", ""),
                "products": parsed_response.get("products", ""),
                "discount_percentage": str(parsed_response.get("discount_percentage", "")) if parsed_response.get("discount_percentage") else "",
                "image_url": parsed_response.get("image_url", ""),
                "additional_data": parsed_response.get("additional_data", ""),
                "cart": parsed_response.get("cart", [])
            }
        else:
            return {
                "answer": str(parsed_response),
                "agent": "",
                "products": "",
                "discount_percentage": "",
                "image_url": "",
                "additional_data": "",
                "cart": []
            }
    except (json.JSONDecodeError, TypeError) as e:
        return {
            "answer": str(response),
            "agent": "",
            "products": "",
            "discount_percentage": "",
            "image_url": "",
            "additional_data": "",
            "cart": []
        }
