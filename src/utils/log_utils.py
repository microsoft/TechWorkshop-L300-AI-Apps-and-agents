import datetime
import time
import logging

logger = logging.getLogger(__name__)

# Timing utility function with structured logging
def log_timing(operation_name: str, start_time: float, additional_info: str = ""):
    """Log timing information for operations using structured logging."""
    elapsed_time = time.time() - start_time
    timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    log_message = f"[TIMING] {timestamp} - {operation_name}: {elapsed_time:.3f}s"
    if additional_info:
        log_message += f" | {additional_info}"
    logger.info(log_message)
    return elapsed_time

def log_cache_status(image_cache: dict, current_url: str = ""):
    """Log the current status of the image cache using structured logging."""
    cache_size = len(image_cache)
    cache_keys = list(image_cache.keys())
    logger.info("Image cache status", extra={
        "cache_size": cache_size,
        "cache_keys": [url[:30] + '...' for url in cache_keys],
        "current_url_in_cache": current_url in image_cache if current_url else None
    })
