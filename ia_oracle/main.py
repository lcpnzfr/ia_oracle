"""Entrypoint for the IA Oracle service.

This script starts an OracleWorker in standalone mode or connects to a Broker 
cluster, ready to process `intel.oracle.review` requests via the Gemini LLM.
"""

import argparse
import asyncio
import logging
import signal
import sys
from typing import Optional

from forex_shared.env_config_manager import EnvConfigManager
from ia_oracle.worker import OracleWorker

# Setup basic logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("IAOracleMain")


async def run_worker(worker_id: str, max_sessions: int) -> None:
    """Starts a standalone Oracle Worker process."""
    
    logger.info(f"Starting OracleWorker: {worker_id} (Max Sessions: {max_sessions})")
    
    worker = OracleWorker(worker_id=worker_id, max_sessions=max_sessions)
    
    # Graceful shutdown handler
    loop = asyncio.get_running_loop()
    def request_stop():
        logger.info("Shutdown signal received. Stopping worker...")
        asyncio.create_task(worker.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_stop)
        except NotImplementedError:
            # Windows fallback
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(request_stop))

    # Start the worker runtime
    await worker.start()
    
    # Automatically bootstrap a session inside this worker so it immediately listens to MQ
    logger.info("Bootstrapping default OracleSession...")
    await worker.create_session({
        "session_id": "default_oracle_session",
        "input_topic": "intel.oracle.review",
        "output_topic": "intel.oracle.resolved"
    })
    
    # Run until stopped
    await worker.run_forever()


def main():
    parser = argparse.ArgumentParser(description="IA Oracle Worker Node")
    parser.add_argument("--worker-id", type=str, default="oracle_worker_1", help="Unique ID for this worker")
    parser.add_argument("--max-sessions", type=int, default=1, help="Max concurrent LLM sessions on this worker")
    
    args = parser.parse_args()

    # Bootstrap the unified configuration
    try:
        EnvConfigManager.startup()
    except Exception as e:
        logger.warning(f"Failed to sync with MongoDB EnvConfig: {e}")

    try:
        asyncio.run(run_worker(args.worker_id, args.max_sessions))
    except KeyboardInterrupt:
        logger.info("Exiting.")
    except Exception as e:
        logger.exception(f"Fatal error running OracleWorker: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
