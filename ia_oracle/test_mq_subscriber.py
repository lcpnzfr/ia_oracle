"""MQ Subscriber Test — Oracle Pipeline Output Validator.

Subscribes to intel.oracle.review and intel.oracle.resolved and prints
every message that arrives.  Run this BEFORE the publisher.

Usage (from ia_oracle service root):
    python ia_oracle/test_mq_subscriber.py             # compact summary, 120 s idle timeout
    python ia_oracle/test_mq_subscriber.py --json      # full JSON dump
    python ia_oracle/test_mq_subscriber.py --timeout 300

Press Ctrl-C to stop.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── environment ──────────────────────────────────────────────────────────────
THIS_FILE = Path(__file__).resolve()
SERVICE_ROOT = THIS_FILE.parents[1]

from dotenv import load_dotenv
load_dotenv(SERVICE_ROOT / ".env", override=False)
load_dotenv(override=False)

from forex_shared.env_config_manager import EnvConfigManager
try:
    EnvConfigManager.startup()
except Exception:
    pass  # cryptor not installed in test venv — ok

from forex_shared.logging.get_logger import get_logger, setup_logging
from forex_shared.providers.mq.mq_factory import MQFactory

# ── logging ───────────────────────────────────────────────────────────────────
setup_logging(level=logging.INFO)
log = get_logger(__name__)

# ── default topics ────────────────────────────────────────────────────────────
WATCH_TOPICS = [
    "intel.oracle.review",
    "intel.oracle.resolved",
]

# ── state ─────────────────────────────────────────────────────────────────────
_total_received = 0


def _fmt(payload: dict, *, verbose: bool) -> str:
    if verbose:
        return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    lines = [
        f"  event_id       : {payload.get('trigger_event_id', payload.get('id', '-'))}",
        f"  action         : {payload.get('action', '-')}",
        f"  confidence     : {payload.get('oracle_confidence', '-')}",
        f"  reasoning      : {str(payload.get('reasoning', ''))[:120]}",
        f"  tags_to_emit   : {payload.get('tags_to_emit', [])}",
    ]
    for key in ("title", "reason", "routing_reason", "domain", "source"):
        val = payload.get(key)
        if val:
            lines.append(f"  {key:<14} : {str(val)[:120]}")
    return "\n".join(lines)


def _make_handler(topic: str, *, verbose: bool, last_seen: list):
    import time
    async def _handler(payload: dict) -> None:
        global _total_received
        _total_received += 1
        last_seen[0] = time.monotonic()
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        log.info("[#%d] topic=%-32s  ts=%s", _total_received, topic, ts)
        print(_fmt(payload, verbose=verbose), flush=True)
        print(flush=True)
    return _handler


# ── main ──────────────────────────────────────────────────────────────────────

async def run(extra_topics: list[str], timeout_seconds: float, verbose: bool) -> None:
    import time
    all_topics = list(dict.fromkeys(WATCH_TOPICS + extra_topics))

    log.info("=== Oracle MQ Subscriber ===")
    log.info("Provider    : %s", os.getenv("MQ_PROVIDER", "RABBITMQ_ASYNC"))
    log.info("Topics      : %s", ", ".join(all_topics))
    log.info("Idle timeout: %.0f s (after first message)", timeout_seconds)

    mq = MQFactory.create_async_from_env()
    await mq.connect()
    log.info("MQ connected.")

    last_seen: list[float] = [time.monotonic()]
    stop = asyncio.Event()

    for topic in all_topics:
        await mq.subscribe_event(topic, _make_handler(topic, verbose=verbose, last_seen=last_seen))
        log.info("  subscribed: %s", topic)

    log.info("Waiting for messages... (Ctrl-C to quit)\n")

    async def _watchdog():
        # Only start the idle clock after at least one message arrives
        while not stop.is_set():
            await asyncio.sleep(5)
            if _total_received > 0:
                idle = time.monotonic() - last_seen[0]
                if idle >= timeout_seconds:
                    log.info("Idle %.0f s — stopping. Total received: %d", idle, _total_received)
                    stop.set()

    wdog = asyncio.create_task(_watchdog())
    consume = asyncio.create_task(mq.start_consuming())

    try:
        await stop.wait()
    except (asyncio.CancelledError, KeyboardInterrupt):
        log.info("Interrupted.")
    finally:
        wdog.cancel()
        await asyncio.gather(wdog, return_exceptions=True)
        try:
            await mq.stop_consuming()
        except Exception:
            pass
        consume.cancel()
        await asyncio.gather(consume, return_exceptions=True)
        try:
            await mq.disconnect()
        except Exception:
            pass

    log.info("Done. Total messages received: %d", _total_received)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Subscribe to Oracle MQ topics.")
    p.add_argument("--timeout", type=float, default=120.0, metavar="S",
                   help="Idle seconds after last msg before stopping (default 120).")
    p.add_argument("--topic", action="append", default=[], metavar="T",
                   help="Extra topic to subscribe to (repeatable).")
    p.add_argument("--json", dest="verbose", action="store_true",
                   help="Dump full JSON payload.")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        asyncio.run(run(extra_topics=args.topic, timeout_seconds=args.timeout, verbose=args.verbose))
    except KeyboardInterrupt:
        pass
