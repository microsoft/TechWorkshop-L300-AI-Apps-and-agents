from dotenv import load_dotenv
load_dotenv()

def inventory_check(product_dict: dict) -> list:
    """
    Simulates checking for inventory details from Microsoft Fabric.

    Args:
        product_dict (dict): Keys are product names, values are product IDs.

    Returns:
        list: Each element is the matching row if the product ID is found, otherwise None.
    """

    # Simulated data
    product_inventory = {
        'PROD0001': {'ProductName': 'Pale Meadow', 'QuantityInStock': 312, 'Price': 29.99},
        'PROD0002': {'ProductName': 'Tranquil Lavender', 'QuantityInStock': 145, 'Price': 31.99},
        'PROD0003': {'ProductName': 'Whispering Blue', 'QuantityInStock': 487, 'Price': 47.99},
        'PROD0004': {'ProductName': 'Whispering Blush', 'QuantityInStock': 56, 'Price': 50.82},
        'PROD0005': {'ProductName': 'Ocean Mist', 'QuantityInStock': 221, 'Price': 84.83},
        'PROD0006': {'ProductName': 'Sunset Coral', 'QuantityInStock': 399, 'Price': 48.57},
        'PROD0007': {'ProductName': 'Forest Whisper', 'QuantityInStock': 78, 'Price': 43.09},
        'PROD0008': {'ProductName': 'Morning Dew', 'QuantityInStock': 305, 'Price': 81.94},
        'PROD0009': {'ProductName': 'Dusty Rose', 'QuantityInStock': 412, 'Price': 75.62},
        'PROD0010': {'ProductName': 'Sage Harmony', 'QuantityInStock': 67, 'Price': 33.26},
        'PROD0011': {'ProductName': 'Vanilla Dream', 'QuantityInStock': 254, 'Price': 54.66},
        'PROD0012': {'ProductName': 'Charcoal Storm', 'QuantityInStock': 188, 'Price': 43.45},
        'PROD0013': {'ProductName': 'Golden Wheat', 'QuantityInStock': 499, 'Price': 109.73},
        'PROD0014': {'ProductName': 'Soft Pebble', 'QuantityInStock': 321, 'Price': 110.92},
        'PROD0015': {'ProductName': 'Misty Gray', 'QuantityInStock': 92, 'Price': 96.04},
        'PROD0016': {'ProductName': 'Rustic Clay', 'QuantityInStock': 276, 'Price': 83.37},
        'PROD0017': {'ProductName': 'Ivory Pearl', 'QuantityInStock': 134, 'Price': 91.99},
        'PROD0018': {'ProductName': 'Deep Forest', 'QuantityInStock': 401, 'Price': 119.93},
        'PROD0019': {'ProductName': 'Autumn Spice', 'QuantityInStock': 58, 'Price': 30.34},
        'PROD0020': {'ProductName': 'Coastal Whisper', 'QuantityInStock': 215, 'Price': 39.99},
        'PROD0021': {'ProductName': 'Effervescent Jade', 'QuantityInStock': 362, 'Price': 42.99},
        'PROD0022': {'ProductName': 'Frosted Blue', 'QuantityInStock': 77, 'Price': 36.99},
        'PROD0023': {'ProductName': 'Frosted Lemon', 'QuantityInStock': 489, 'Price': 28.99},
        'PROD0024': {'ProductName': 'Honeydew Sunrise', 'QuantityInStock': 123, 'Price': 45.99},
        'PROD0025': {'ProductName': 'Lavender Whisper', 'QuantityInStock': 256, 'Price': 33.99},
        'PROD0026': {'ProductName': 'Lilac Mist', 'QuantityInStock': 411, 'Price': 55.99},
        'PROD0027': {'ProductName': 'Soft Creamsicle', 'QuantityInStock': 98, 'Price': 41.99},
        'PROD0028': {'ProductName': 'Whispering Blush', 'QuantityInStock': 312, 'Price': 26.99},
        'PROD0029': {'ProductName': 'Lavender Whisper', 'QuantityInStock': 75, 'Price': 33.99},
        'PROD0030': {'ProductName': 'Lilac Mist', 'QuantityInStock': 201, 'Price': 55.99},
        'PROD0031': {'ProductName': 'Soft Creamsicle', 'QuantityInStock': 487, 'Price': 41.99},
        'PROD0032': {'ProductName': 'Whispering Blush', 'QuantityInStock': 154, 'Price': 26.99},
        'PROD0033': {'ProductName': 'Cordless Airless Pro', 'QuantityInStock': 299, 'Price': 120.99},
        'PROD0034': {'ProductName': 'Cordless Compact Painter', 'QuantityInStock': 412, 'Price': 149.99},
        'PROD0035': {'ProductName': 'Electric Sprayer 350', 'QuantityInStock': 88, 'Price': 135.99},
        'PROD0036': {'ProductName': 'HVLP SuperFinish', 'QuantityInStock': 367, 'Price': 125.99},
        'PROD0037': {'ProductName': 'Handheld Airless 360', 'QuantityInStock': 210, 'Price': 130.99},
        'PROD0038': {'ProductName': 'Handheld HVLP Pro', 'QuantityInStock': 56, 'Price': 139.99},
        'PROD0039': {'ProductName': 'Paint Safe Drop Cloth', 'QuantityInStock': 478, 'Price': 55.99},
        'PROD0040': {'ProductName': 'Paint Guard Reusable Drop Cloth', 'QuantityInStock': 123, 'Price': 60.99},
        'PROD0041': {'ProductName': 'Fine Finish Paint Brush', 'QuantityInStock': 312, 'Price': 2.99},
        'PROD0042': {'ProductName': 'All-Purpose Wall Paint Brush', 'QuantityInStock': 145, 'Price': 3.99},
        'PROD0043': {'ProductName': 'Large Area Applicator Brush', 'QuantityInStock': 487, 'Price': 4.99},
        'PROD0044': {'ProductName': 'Classic Flat Sash Brush', 'QuantityInStock': 56, 'Price': 3.99},
        'PROD0045': {'ProductName': 'Standard Paint Tray', 'QuantityInStock': 221, 'Price': 10.99},
        'PROD0046': {'ProductName': 'Deep Well Paint Tray', 'QuantityInStock': 399, 'Price': 7.99},
        'PROD0047': {'ProductName': 'Compact Paint Tray', 'QuantityInStock': 78, 'Price': 8.99},
        'PROD0048': {'ProductName': 'Heavy-Duty Paint Tray with Grid', 'QuantityInStock': 305, 'Price': 135.99},
        'PROD0049': {'ProductName': "Blue Painter's Tape", 'QuantityInStock': 412, 'Price': 3.99},
        'PROD0050': {'ProductName': "Green Painter's Tape", 'QuantityInStock': 67, 'Price': 2.99},
        'PROD0051': {'ProductName': 'Standard Paint Roller', 'QuantityInStock': 254, 'Price': 15.99},
        'PROD0052': {'ProductName': 'Ergonomic Grip Paint Roller', 'QuantityInStock': 188, 'Price': 10.99},
        'PROD0053': {'ProductName': 'Classic Wood Handle Paint Roller', 'QuantityInStock': 499, 'Price': 9.99},
        'PROD0054': {'ProductName': 'Wooden Handle Paint Roller', 'QuantityInStock': 321, 'Price': 8.99},
    }

    results = [ product_inventory[v] for _,v in product_dict.items() ]
    return results
