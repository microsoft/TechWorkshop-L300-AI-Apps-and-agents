import random
import orjson

IMAGE_UPLOAD_MESSAGES = [
    "Thank you for your image upload! Let me take a look at it.",
    "Got your image! Analyzing it now...",
    "Image received. I'll check it out for you.",
    "Thanks for sharing the image! Let me review it.",
    "Your image is in! Let me see what I can find."
]
IMAGE_CREATE_MESSAGES = [
    "Hold on while I create the image...",
    "Creating your image now, please wait...",
    "Working on generating your image...",
    "Let me create that image for you...",
    "Image creation in progress..."
]
IMAGE_ANALYSIS_MESSAGES = [
    "I've analyzed the image. Here's what I found:",
    "Image analysis complete!",
    "Done reviewing your image.",
    "I've taken a look at your image.",
    "Image processed!"
]

def get_rotating_message(pool):
    return random.choice(pool) 

# Optimized JSON serialization function
def fast_json_dumps(obj, **kwargs):
    """Use orjson for faster JSON serialization."""
    return orjson.dumps(obj, **kwargs).decode('utf-8')