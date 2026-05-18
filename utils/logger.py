import logging
import os
import sys
from datetime import datetime

class NexusLogger:
    """
    NEXUS SOVEREIGN LOGGING 1.0
    Provides high-fidelity, colored, and multi-sink logging.
    """
    
    # ANSI Colors
    CYAN = "\033[96m"
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    @staticmethod
    def setup(root_dir: str, level: int = logging.INFO):
        log_dir = os.path.join(root_dir, "logs", "sessions")
        os.makedirs(log_dir, exist_ok=True)
        
        log_file = os.path.join(log_dir, f"nexus_{datetime.now().strftime('%Y%m%d')}.log")
        
        # Formatter
        format_str = "%(asctime)s | %(name)-12s | %(levelname)-8s | %(message)s"
        
        logging.basicConfig(
            level=level,
            format=format_str,
            handlers=[
                logging.FileHandler(log_file, encoding="utf-8"),
                logging.StreamHandler(sys.stdout)
            ]
        )
        
        # Suppress noisy libraries
        for noisy in ["huggingface_hub", "transformers", "urllib3"]:
            logging.getLogger(noisy).setLevel(logging.WARNING)

    @staticmethod
    def info(msg: str):
        logging.info(msg)

    @staticmethod
    def success(msg: str):
        logging.info(f"{NexusLogger.GREEN}[SUCCESS]{NexusLogger.RESET} {msg}")

    @staticmethod
    def error(msg: str):
        logging.error(f"{NexusLogger.RED}[ERROR]{NexusLogger.RESET} {msg}")

    @staticmethod
    def warning(msg: str):
        logging.warning(f"{NexusLogger.YELLOW}[WARNING]{NexusLogger.RESET} {msg}")
