"""
Utility functions for the Quiz Generator system.
"""

import asyncio
import random
import functools
import time
from typing import Callable, Type, List, TypeVar, Any, Optional, Union
from logging_config import logger

T = TypeVar('T')

def with_retry(
    max_retries: int = 3,
    retry_delay: float = 1.0,
    exceptions_to_retry: List[Type[Exception]] = None,
    backoff_factor: float = 2.0,
    jitter_factor: float = 0.5,
    timeout: Optional[float] = None
) -> Callable:
    """
    A decorator that adds retry logic to any function.
    
    Args:
        max_retries: Maximum number of retry attempts.
        retry_delay: Initial delay between retries in seconds.
        exceptions_to_retry: List of exception types to retry on. 
                            If None, retries on all exceptions.
        backoff_factor: Factor to multiply delay by after each retry.
        jitter_factor: Maximum fraction of delay to add as random jitter.
        timeout: Optional timeout for each function call.
    
    Returns:
        The decorated function with retry logic.
    """
    exceptions_to_retry = exceptions_to_retry or [Exception]
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            error_messages = []
            
            for attempt in range(max_retries):
                try:
                    # Add timeout if specified
                    if timeout is not None:
                        return await asyncio.wait_for(func(*args, **kwargs), timeout=timeout)
                    else:
                        return await func(*args, **kwargs)
                        
                except tuple(exceptions_to_retry) as e:
                    error_messages.append(f"Attempt {attempt+1}: {type(e).__name__}: {str(e)}")
                    logger.warning(f"Attempt {attempt+1}/{max_retries} failed with error: {str(e)}")
                    
                    # Only retry if we have attempts left
                    if attempt < max_retries - 1:
                        # Calculate delay with exponential backoff and jitter
                        delay = retry_delay * (backoff_factor ** attempt)
                        jitter = random.uniform(0, jitter_factor * delay)
                        wait_time = delay + jitter
                        
                        logger.info(f"Retrying in {wait_time:.2f} seconds")
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"All {max_retries} attempts failed")
                        logger.error(f"Error summary: {'; '.join(error_messages)}")
                        raise
                except asyncio.TimeoutError:
                    error_messages.append(f"Attempt {attempt+1}: Timeout exceeded")
                    logger.warning(f"Attempt {attempt+1}/{max_retries} timed out")
                    
                    # Only retry if we have attempts left
                    if attempt < max_retries - 1:
                        # Calculate delay with exponential backoff and jitter
                        delay = retry_delay * (backoff_factor ** attempt)
                        jitter = random.uniform(0, jitter_factor * delay)
                        wait_time = delay + jitter
                        
                        logger.info(f"Retrying in {wait_time:.2f} seconds")
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"All {max_retries} attempts timed out")
                        logger.error(f"Error summary: {'; '.join(error_messages)}")
                        raise
        
        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            error_messages = []
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except tuple(exceptions_to_retry) as e:
                    error_messages.append(f"Attempt {attempt+1}: {type(e).__name__}: {str(e)}")
                    logger.warning(f"Attempt {attempt+1}/{max_retries} failed with error: {str(e)}")
                    
                    # Only retry if we have attempts left
                    if attempt < max_retries - 1:
                        # Calculate delay with exponential backoff and jitter
                        delay = retry_delay * (backoff_factor ** attempt)
                        jitter = random.uniform(0, jitter_factor * delay)
                        wait_time = delay + jitter
                        
                        logger.info(f"Retrying in {wait_time:.2f} seconds")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"All {max_retries} attempts failed")
                        logger.error(f"Error summary: {'; '.join(error_messages)}")
                        raise
        
        # Return appropriate wrapper based on whether the function is async or not
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator

# Example usage
if __name__ == "__main__":
    # Example with async function
    @with_retry(max_retries=3, retry_delay=1.0)
    async def example_async_func():
        # Simulating an API call that might fail
        if random.random() < 0.7:
            raise ConnectionError("Simulated connection error")
        return "Success"
    
    # Example with sync function
    @with_retry(max_retries=3, retry_delay=1.0)
    def example_sync_func():
        # Simulating an API call that might fail
        if random.random() < 0.7:
            raise ValueError("Simulated value error")
        return "Success"