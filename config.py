"""
Centralized configuration for the Quiz Generator system.
This module loads configuration from environment variables
and provides defaults for all configurable parameters.
"""

import os
from dotenv import load_dotenv
from typing import Dict, Any

# Load environment variables from .env file
load_dotenv()

class Config:
    """
    Configuration class for the Quiz Generator.
    Loads configuration from environment variables with sensible defaults.
    """
    
    # API configuration
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-3-7-sonnet-20250219")
    
    # Retry configuration
    MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "5"))
    RETRY_DELAY = float(os.environ.get("RETRY_DELAY", "2.0"))
    
    # Timeout configuration
    API_TIMEOUT = int(os.environ.get("API_TIMEOUT", "240"))  # seconds
    BATCH_TIMEOUT = int(os.environ.get("BATCH_TIMEOUT", "360"))  # seconds
    
    # Concurrency configuration
    MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "5"))
    
    # File paths
    DATA_DIR = os.environ.get("DATA_DIR", "")  # Empty string means current directory
    LESSONS_FILE = os.path.join(DATA_DIR, os.environ.get("LESSONS_FILE", "lang_lessons.json"))
    PASSAGES_FILE = os.path.join(DATA_DIR, os.environ.get("PASSAGES_FILE", "lang_passages.json"))
    EXAMPLES_FILE = os.path.join(DATA_DIR, os.environ.get("EXAMPLES_FILE", "lang_examples.json"))
    QC_PROMPTS_FILE = os.path.join(DATA_DIR, os.environ.get("QC_PROMPTS_FILE", "lang-question-qc.json"))
    EXPLANATIONS_EXAMPLES_FILE = os.path.join(DATA_DIR, os.environ.get("EXPLANATIONS_EXAMPLES_FILE", "lang_explanations_examples.json"))
    LOG_FILE = os.environ.get("LOG_FILE", "quiz_generator.log")
    
    # Difficulty level mappings
    DIFFICULTY_LEVELS = {
        1: {"easy": (2, 5), "medium": (2, 5), "hard": (1, 2)},  # min, max for each level
        2: {"easy": (2, 3), "medium": (2, 5), "hard": (2, 4)},
        3: {"easy": (1, 2), "medium": (2, 4), "hard": (2, 6)}
    }
    
    # Mapping difficulty level strings to internal representations
    DIFFICULTY_MAP = {
        "easy": "1",
        "medium": "2", 
        "hard": "3"
    }
    
    @classmethod
    def get_config_dict(cls) -> Dict[str, Any]:
        """
        Returns the configuration as a dictionary.
        
        Returns:
            Dictionary of configuration values
        """
        return {
            key: value for key, value in cls.__dict__.items() 
            if not key.startswith('__') and not callable(value)
        }
    
    @classmethod
    def log_config(cls, logger):
        """
        Log the configuration values.
        
        Args:
            logger: Logger to use for logging
        """
        logger.info("=== Configuration ===")
        for key, value in cls.get_config_dict().items():
            # Don't log the full API key
            if key == "ANTHROPIC_API_KEY" and value:
                value_to_log = f"{value[:4]}...{value[-4:]}" if len(value) > 8 else "[Not Set]"
                logger.info(f"{key}: {value_to_log}")
            elif not key.startswith('__') and not callable(value):
                logger.info(f"{key}: {value}")
        logger.info("====================")

# Create a singleton instance
config = Config()

# Example usage:
# from config import config
# print(config.MAX_RETRIES)