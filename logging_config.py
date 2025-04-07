"""
Centralized logging configuration for the Quiz Generator system.
This module configures logging for all components of the system.
"""

import logging
import sys
import os

def configure_logging(log_level=None):
    """
    Configure logging for the entire application.
    
    Args:
        log_level: Optional override for the log level. If None, uses the environment variable
                  LOG_LEVEL or defaults to INFO.
    
    Returns:
        The configured logger
    """
    # Determine log level from environment or parameter
    if log_level is None:
        log_level_str = os.environ.get("LOG_LEVEL", "INFO").upper()
        try:
            log_level = getattr(logging, log_level_str)
        except AttributeError:
            print(f"Invalid log level: {log_level_str}. Using INFO.")
            log_level = logging.INFO
    
    # Create handlers with immediate flushing
    file_handler = logging.FileHandler("quiz_generator.log")
    file_handler.setLevel(log_level)
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    
    # Configure the format
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Configure the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove any existing handlers to avoid duplicates when called multiple times
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Add the handlers
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Return the root logger
    return root_logger

# Configure logging when this module is imported
logger = configure_logging()