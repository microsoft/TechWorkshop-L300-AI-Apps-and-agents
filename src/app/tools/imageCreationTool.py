import base64
import requests
from io import BytesIO
from PIL import Image
from azure.storage.blob import BlobServiceClient, ContentSettings
import os
from dotenv import load_dotenv
from uuid import uuid4
import sys
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from utils.storage_utils import get_storage_manager

load_dotenv()

storage_account_name = os.getenv("storage_account_name", "")
container_name = os.getenv("storage_container_name", "")
# NOTE: These environment variables should be set in your .env file
# if you have access to the GPT-image-1 model and wish to use this tool.
endpoint = os.getenv("gpt-image-1-endpoint")
deployment = os.getenv("gpt-image-1-deployment")
api_version = os.getenv("gpt-image-1-api_version")
subscription_key = os.getenv("subscription_key")

HEXCODES = "\n\n Hexcodes to strictly follow for paint: \n Pale Meadow: #b6c9bb, Tranquil Lavender: #bdb4bf, Whispering Blue: #9fbbc2, Whispering Blush: #d4b9a4, Ocean Mist: #aec3b7, Sunset Coral: #d25e2e, Forest Whisper: #788c6f, Morning Dew: #596c76, Dusty Rose: #ac9187, Sage Harmony: #bec7be, Vanilla Dream: #a39b8b, Charcoal Storm: #6b6c6a, Golden Wheat: #cfac5b, Soft Pebble: #bfb8a9, Misty Gray: #9da2a3, Rustic Clay: #a78982, Ivory Pearl: #937c6e, Deep Forest: #4a5846, Autumn Spice: #bc8567, Coastal Whisper: #acb7b9, Effervescent Jade: #586e57, Frosted Blue: #cacec8, Frosted Lemon: #d2ce8d, Honeydew Sunrise: #d6ca9d, Lavender Whisper: #dbdadf, Lilac Mist: #cdcddb, Soft Creamsicle: #ddbba6. \n\n If image is outside of these colors or something different is asked, please reject the request and ask for a different color or theme. \n\n"

def create_image(text, image_url):
    """
    Creates an edited image using the Azure OpenAI gpt-image-1 model based on a given text prompt and an input image, uploads the resulting image to Azure Blob Storage, and returns the URL to the uploaded image.

    Args:
        text (str): The prompt describing the desired edit or transformation to apply to the input image.
        image_url (str): The source of the input image. Can be a URL (http/https), a base64-encoded data URI, or a local file path.

    Returns:
        str or None: The URL of the uploaded, edited image in Azure Blob Storage if successful; otherwise, None if an error occurs at any step.
    """
    
    def upload_image_to_blob(pil_image):
        try:
            img_byte_arr = BytesIO()
            pil_image.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)

            # Use StorageManager with Managed Identity authentication
            storage_manager = get_storage_manager()

            blob_name = f"image_{uuid4().hex}.png"
            
            blob_url = storage_manager.upload_blob(
                blob_name=blob_name,
                data=img_byte_arr,
                content_type='image/png'
            )

            return blob_url
        except Exception as e:
            print("Error uploading image to blob:", e)
            return None

    def decode_and_save_image(b64_data):
        image = Image.open(BytesIO(base64.b64decode(b64_data)))
        return upload_image_to_blob(image)

    def save_all_images_from_response(response_data):
        image = None
        for item in response_data['data']:
            b64_img = item['b64_json']
            image = decode_and_save_image(b64_img)
        return image

    base_path = f'openai/deployments/{deployment}/images'
    params = f'?api-version={api_version}'

    edit_url = f"{endpoint}{base_path}/edits{params}"
    edit_body = {
        "prompt": text + HEXCODES,
        "n": 1,
        "size": "1536x1024",
        "quality": "medium"
    }

    if image_url.startswith("http"):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/114.0.0.0 Safari/537.36"
            }
            response = requests.get(image_url, headers=headers)
            response.raise_for_status()
            image_bytes = BytesIO(response.content)
            files = {
                "image": ("image.png", image_bytes, "image/png"),
            }
        except Exception as e:
            print("Failed to download image from URL:", e)
            return None
    elif image_url.startswith("data:image"):
        b64_data = image_url.split(",")[1]
        image_bytes = BytesIO(base64.b64decode(b64_data))
        files = {
            "image": ("image.png", image_bytes, "image/png"),
        }
    else:
        try:
            if not os.path.isabs(image_url):
                image_url = os.path.abspath(image_url)
            files = {
                "image": (image_url, open(image_url, "rb"), "image/png"),
            }
        except Exception as e:
            print("Failed to read local image file:", e)
            return None

    edit_response = requests.post(
        edit_url,
        headers={'Api-Key': subscription_key},
        data=edit_body,
        files=files
    ).json()
    
    url = save_all_images_from_response(edit_response)
    return url