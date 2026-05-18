"""
tools/base.py
Shared retry decorator for all API tools.
"""

import time
import logging
import functools
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    exceptions: tuple = (Exception,),
) -> Callable:
    """
    Retries the wrapped function up to max_retries times
    with exponential backoff.
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception = None
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    wait = base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        f"{func.__name__} attempt {attempt}/{max_retries} failed: {e}. "
                        f"Retrying in {wait:.1f}s..."
                    )
                    if attempt < max_retries:
                        time.sleep(wait)
            raise last_exception
        return wrapper
    return decorator