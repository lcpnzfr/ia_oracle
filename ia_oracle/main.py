"""Entrypoint for the IA Oracle service.

This script starts an OracleWorker in standalone mode or connects to a Broker
cluster, ready to process `intel.oracle.review` requests via the configured IA provider.
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from forex_shared.env_config_manager import EnvConfigManager
from forex_shared.logging.get_logger import get_logger, setup_logging

# Setup basic logging
setup_logging(level=logging.DEBUG)
logger = get_logger(__name__)

try:
    EnvConfigManager.startup()
except Exception as e:
    logger.exception(f"Failed to sync with MongoDB EnvConfig: {e}")
    # Don't fail here if we have local .env overrides
    pass

# Debug current environment before override
logger.info(f"PRE-OVERRIDE os.environ['OLLAMA_HOST']: {os.environ.get('OLLAMA_HOST')}")

# Load local .env AFTER startup to OVERRIDE MongoDB/os.environ
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)
logger.info(f"Loaded .env from: {env_path} (exists: {env_path.exists()}, override=True)")

# Debug current environment after override
logger.info(f"POST-OVERRIDE os.environ['OLLAMA_HOST']: {os.environ.get('OLLAMA_HOST')}")

from forex_shared.config.categories import OracleConfig
logger.info(f"RESOLVED OLLAMA_HOST: {OracleConfig.OLLAMA_HOST}")

from ia_oracle.worker import OracleWorker
from ia_oracle.store import OracleMongoStore

DEFAULT_OUTPUT_FILE = Path(__file__).resolve().parent / "data" / "oracle_output_results.json"

async def run_worker(
    worker_id: str,
    max_sessions: int,
    enable_mongo: bool = True,
    output_file: Optional[Path] = DEFAULT_OUTPUT_FILE,
    reset_output_file: bool = True,
) -> None:
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

    worker = OracleWorker(
        worker_id=worker_id,
        max_sessions=max_sessions,
        store=store,
        output_file=output_file,
        reset_output_file=reset_output_file,
    )
    
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
    parser.add_argument(
        "--max-sessions",
        type=int,
        default=OracleConfig.CONCURRENCY,
        help="Max concurrent LLM sessions on this worker",
    )
    parser.add_argument("--no-mongo", action="store_true", help="Disable MongoDB persistence (dry-run mode)")
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="IA provider override: GEMINI, OPENAI, OPENAI_NATIVE, CLAUDE, or AZURE",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Provider model override, for example gpt-4.1 or gemini-2.5-pro",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        default=DEFAULT_OUTPUT_FILE,
        help=f"Write resolved responses incrementally after MQ publish (default: {DEFAULT_OUTPUT_FILE})",
    )
    parser.add_argument(
        "--no-output-file",
        action="store_true",
        help="Disable validation output file writes.",
    )
    parser.add_argument(
        "--append-output",
        action="store_true",
        help="Append to the output file instead of resetting it at startup.",
    )
    
    args = parser.parse_args()

    if args.provider:
        os.environ["IA_PROVIDER"] = args.provider.strip().upper().replace("-", "_")
        logger.info("IA provider override enabled: %s", os.environ["IA_PROVIDER"])
    if args.model:
        os.environ["ORACLE_MODEL"] = args.model.strip()
        logger.info("Oracle model override enabled: %s", os.environ["ORACLE_MODEL"])

    try:
        output_file = None if args.no_output_file else args.output_file
        asyncio.run(
            run_worker(
                args.worker_id,
                args.max_sessions,
                enable_mongo=not args.no_mongo,
                output_file=output_file,
                reset_output_file=not args.append_output,
            )
        )
    except KeyboardInterrupt:
        logger.info("Exiting.")
    except Exception as e:
        logger.exception(f"Fatal error running OracleWorker: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
