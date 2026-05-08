import logging
import signal
import sys
from typing import Optional

from forex_shared.env_config_manager import EnvConfigManager
from forex_shared.logging.get_logger import get_logger, setup_logging

# Setup basic logging
setup_logging(level=logging.INFO)
logger = get_logger(__name__)

try:
    EnvConfigManager.startup()
except Exception as e:
    logger.exception(f"Failed to sync with MongoDB EnvConfig: {e}")
    sys.exit(1)

logger.info(f"OK! Environment config loaded.")

