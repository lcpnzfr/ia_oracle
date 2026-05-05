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
from forex_shared.logging.get_logger import get_logger, setup_logging

# Setup basic logging
setup_logging(level=logging.DEBUG)
logger = get_logger(__name__)

try:
    EnvConfigManager.startup()
except Exception as e:
    logger.exception(f"Failed to sync with MongoDB EnvConfig: {e}")
    raise Exception(f"Failed to sync with MongoDB EnvConfig: {e}")
    sys.exit(1)

from ia_oracle.worker import OracleWorker
from ia_oracle.store import OracleMongoStore

async def run_worker(worker_id: str, max_sessions: int, enable_mongo: bool = True) -> None:
    """Starts a standalone Oracle Worker process."""

    logger.info(f"Starting OracleWorker: {worker_id} (Max Sessions: {max_sessions})")

    # ── MongoDB store (optional — graceful degradation) ───────────────
    store: OracleMongoStore | None = None
    if enable_mongo:
        try:
            store = OracleMongoStore()
            await store.ensure_indexes()
            logger.info("MongoDB persistence enabled (collection: oracle_resolved)")
        except Exception as exc:
            logger.warning("MongoDB unavailable — persistence skipped: %s", exc)
            store = None

    worker = OracleWorker(worker_id=worker_id, max_sessions=max_sessions, store=store)
    
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
    parser.add_argument("--no-mongo", action="store_true", help="Disable MongoDB persistence (dry-run mode)")
    
    args = parser.parse_args()

    try:
        asyncio.run(run_worker(args.worker_id, args.max_sessions, enable_mongo=not args.no_mongo))
    except KeyboardInterrupt:
        logger.info("Exiting.")
    except Exception as e:
        logger.exception(f"Fatal error running OracleWorker: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
