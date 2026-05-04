"""MQ Subscriber Test — Oracle Pipeline Output Validator.

Subscribes to the ``intel.oracle.resolved`` topic and prints every message
that arrives.  Run this in a separate terminal BEFORE the publisher or the
full worker so you can watch oracle responses land in real time.

Also subscribes to ``intel.oracle.review`` in passthrough mode so you can
confirm the publisher is reaching the broker.

Usage:
    # From the ia_oracle service root (Terminal 1):
    python ia_oracle/test_mq_subscriber.py

    # In Terminal 2, run the publisher or the full worker:
    python ia_oracle/test_mq_publisher.py --count 3

Flags:
    --timeout N     Stop after N seconds without a new message (default: 120)
    --topic TOPIC   Extra topic pattern to subscribe to (can repeat)
    --json          Dump each payload as indented JSON (default: compact summary)

Environment:
    Standard MQ env-vars (MQ_PROVIDER, MQ_HOST, etc.) must be set or in .env
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

THIS_FILE = Path(__file__).resolve()
SERVICE_ROOT = THIS_FILE.parents[1]

load_dotenv(SERVICE_ROOT / ".env", override=False)
load_dotenv(override=False)

from forex_shared.env_config_manager import EnvConfigManager  # noqa: E402

try:
    EnvConfigManager.startup()
except Exception as _e:
    import logging as _l
    _l.getLogger(__name__).warning("EnvConfigManager.startup() skipped: %s", _e)

from forex_shared.providers.mq.mq_factory import MQFactory  # noqa: E402

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
log = logging.getLogger("test_mq_subscriber")

# ---------------------------------------------------------------------------
# Default topics to watch
# ---------------------------------------------------------------------------

WATCH_TOPICS = [
    "intel.oracle.review",      # inbound: requests published by GlobalTagEmitter/publisher test
    "intel.oracle.resolved",    # outbound: oracle decisions
]

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_received_count = 0
_last_received_at: float = 0.0
_stop_event: asyncio.Event | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fmt_payload(payload: dict, *, verbose: bool) -> str:
    """Format a payload for console output."""
    if verbose:
        return json.dumps(payload, ensure_ascii=False, indent=2, default=str)

    # Compact summary
    lines = [
        f"  action        : {payload.get('action', '—')}",
        f"  event_id      : {payload.get('trigger_event_id', payload.get('id', '—'))}",
        f"  confidence    : {payload.get('oracle_confidence', '—')}",
        f"  reasoning     : {str(payload.get('reasoning', ''))[:120]}",
        f"  tags_to_emit  : {payload.get('tags_to_emit', [])}",
        f"  resolved_at   : {payload.get('resolved_at', '—')}",
    ]
    # Show a few extra keys if present (review-side payload)
    for key in ("title", "reason", "domain", "source"):
        val = payload.get(key)
        if val:
            lines.append(f"  {key:<13} : {str(val)[:120]}")
    return "\n".join(lines)


def _make_handler(topic: str, *, verbose: bool):
    """Return a coroutine handler that logs received messages."""
    global _received_count, _last_received_at

    async def _handler(payload: dict) -> None:
        global _received_count, _last_received_at
        import time

        _received_count += 1
        _last_received_at = time.monotonic()
        log.info(
            "▶ #%d  topic=%-30s  ts=%s",
            _received_count,
            topic,
            _utc_now(),
        )
        formatted = _fmt_payload(payload, verbose=verbose)
        print(formatted)
        print()

    return _handler


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run(
    extra_topics: list[str],
    timeout_seconds: float,
    verbose: bool,
) -> None:
    global _stop_event
    _stop_event = asyncio.Event()

    all_topics = list(dict.fromkeys(WATCH_TOPICS + extra_topics))  # dedup, preserve order

    log.info("=== Oracle MQ Subscriber ===")
    log.info("Provider   : %s", os.getenv("MQ_PROVIDER", "RABBITMQ_ASYNC"))
    log.info("Topics     : %s", ", ".join(all_topics))
    log.info("Idle timeout: %.0f s", timeout_seconds)
    log.info("Verbose JSON: %s", verbose)

    mq = MQFactory.create_async_from_env()
    await mq.connect()
    log.info("MQ connected. Subscribing…")

    for topic in all_topics:
        await mq.subscribe_event(topic, _make_handler(topic, verbose=verbose))
        log.info("  ✓ Subscribed to: %s", topic)

    log.info("Waiting for messages (Ctrl-C to quit)…\n")

    loop = asyncio.get_running_loop()

    def _signal_handler(*_) -> None:
        log.info("Shutdown signal received.")
        _stop_event.set()  # type: ignore[union-attr]

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except (NotImplementedError, RuntimeError):
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(_signal_handler))

    # Idle-timeout watchdog
    async def _idle_watchdog() -> None:
        import time

        while not _stop_event.is_set():  # type: ignore[union-attr]
            await asyncio.sleep(5)
            if _last_received_at > 0:
                idle = time.monotonic() - _last_received_at
                if idle >= timeout_seconds:
                    log.info(
                        "Idle for %.0f s (received %d total). Stopping.",
                        idle,
                        _received_count,
                    )
                    _stop_event.set()  # type: ignore[union-attr]

    watchdog = asyncio.create_task(_idle_watchdog(), name="idle-watchdog")

    try:
        # Start consuming (non-blocking: returns when stop_event fires or broker disconnects)
        consume_task = asyncio.create_task(mq.start_consuming(), name="mq-consume")
        done, _ = await asyncio.wait(
            [asyncio.create_task(_stop_event.wait()), consume_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        watchdog.cancel()
        await asyncio.gather(watchdog, return_exceptions=True)

        log.info("Stopping consumer…")
        try:
            await mq.stop_consuming()
        except Exception:
            pass
        try:
            await mq.disconnect()
        except Exception:
            pass

    log.info("Done. Total messages received: %d", _received_count)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Subscribe to Oracle MQ topics and print received payloads.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        metavar="SECONDS",
        help="Stop after this many idle seconds without a new message (default: 120).",
    )
    parser.add_argument(
        "--topic",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Additional topic pattern to subscribe to (can repeat). "
             "Default topics: " + ", ".join(WATCH_TOPICS),
    )
    parser.add_argument(
        "--json",
        dest="verbose",
        action="store_true",
        help="Dump each message as indented JSON instead of a compact summary.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(
        run(
            extra_topics=args.topic,
            timeout_seconds=args.timeout,
            verbose=args.verbose,
        )
    )
