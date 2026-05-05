"""MQ Publisher Test — Oracle Pipeline End-to-End Validation.

Reads the mock oracle_messages file and publishes each item to
``intel.oracle.review`` via RabbitMQ — exactly as GlobalTagEmitter would.

Usage (from ia_oracle service root):
    python ia_oracle/test_mq_publisher.py            # publish first 3 items
    python ia_oracle/test_mq_publisher.py --all      # publish all items
    python ia_oracle/test_mq_publisher.py --count 5  # publish first 5 items

Environment: MQ_PROVIDER, MQ_HOST, etc. must be set or in .env
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
PACKAGE_ROOT = THIS_FILE.parent

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
from forex_shared.domain.oracle import OracleReviewRequest

# ── logging ───────────────────────────────────────────────────────────────────
setup_logging(level=logging.INFO)
log = get_logger(__name__)

# ── constants ─────────────────────────────────────────────────────────────────
DEFAULT_MOCK_FILE = PACKAGE_ROOT / "data" / "mock_intel_items_big_process_result.json"
INPUT_TOPIC = "intel.oracle.review"
DEFAULT_COUNT = 3


# ── helpers ───────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _build_request(item: dict) -> OracleReviewRequest:
    """Map a mock oracle_messages item → OracleReviewRequest."""
    # Items from oracle_messages have oracle_request embedded
    if "oracle_request" in item:
        req_data = item["oracle_request"]
        enriched = req_data.get("enriched_event", {})
        routing = req_data.get("routing", {})
        extra = enriched.get("extra", {}) if isinstance(enriched.get("extra"), dict) else {}
        return OracleReviewRequest(
            trigger_event_id=req_data.get("trigger_event_id", enriched.get("id", "unknown")),
            reason=routing.get("routing_reason", "mq_test_publisher"),
            title=enriched.get("title", ""),
            body=enriched.get("body", ""),
            published_at=enriched.get("published_at", _utc_now()),
            source=enriched.get("source", "telegram"),
            domain=enriched.get("domain", "geopolitical"),
            danger_score_legacy=routing.get("scores_snapshot", {}).get("danger_score_legacy", 0.0),
            impact_category=extra.get("impact_category", "generic"),
            scores=routing.get("scores_snapshot", {}),
            trade_emit_score=routing.get("local_final_decision", {}).get("trade_emit_score", 0.0),
            candidate_directives=routing.get("candidate_directives", []),
            score_breakdown=extra.get("score_breakdown", {}),
        )

    # Bare IntelItem fallback
    return OracleReviewRequest(
        trigger_event_id=item.get("id", f"test_{_utc_now()}"),
        reason="mq_test_publisher_fallback",
        title=item.get("title", ""),
        body=item.get("body", ""),
        published_at=item.get("published_at", _utc_now()),
        source=item.get("source", "telegram"),
        domain=item.get("domain", "geopolitical"),
    )


# ── main ──────────────────────────────────────────────────────────────────────

async def run(count: int, mock_file: Path, delay_seconds: float) -> None:
    log.info("=== Oracle MQ Publisher Test ===")
    log.info("Mock file : %s", mock_file)
    log.info("Topic     : %s", INPUT_TOPIC)
    log.info("Count     : %d items", count)
    log.info("Delay     : %.1f s between messages", delay_seconds)

    if not mock_file.exists():
        log.error("Mock file not found: %s", mock_file)
        return

    items: list[dict] = json.loads(mock_file.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        log.error("Mock file must be a JSON array.")
        return

    items = items[:count]
    log.info("Loaded %d items", len(items))

    log.info("Connecting to MQ (provider=%s)...", os.getenv("MQ_PROVIDER", "RABBITMQ_ASYNC"))
    mq = MQFactory.create_async_from_env()
    await mq.connect()
    log.info("MQ connected.")

    try:
        published = 0
        for i, item in enumerate(items, start=1):
            request = _build_request(item)
            payload = request.to_dict()
            ok = await mq.publish_event(INPUT_TOPIC, payload)
            if ok:
                published += 1
                log.info(
                    "[%d/%d] Published  id=%-38s  title=%.60s",
                    i, len(items),
                    request.trigger_event_id,
                    request.title or "(no title)",
                )
            else:
                log.warning("[%d/%d] FAILED id=%s", i, len(items), request.trigger_event_id)

            if delay_seconds > 0 and i < len(items):
                await asyncio.sleep(delay_seconds)

        log.info("Done. %d/%d published.", published, len(items))
    finally:
        await mq.disconnect()
        log.info("MQ disconnected.")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Publish oracle review requests to MQ.")
    p.add_argument("--count", type=int, default=DEFAULT_COUNT, metavar="N",
                   help=f"Number of items to publish (default {DEFAULT_COUNT}).")
    p.add_argument("--all", dest="publish_all", action="store_true",
                   help="Publish all items in mock file.")
    p.add_argument("--mock-file", type=Path, default=DEFAULT_MOCK_FILE, metavar="PATH")
    p.add_argument("--delay", type=float, default=0.5, metavar="S",
                   help="Seconds between messages (default 0.5).")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    count = 999_999 if args.publish_all else args.count
    try:
        raw = json.loads(args.mock_file.read_text(encoding="utf-8"))
        count = min(count, len(raw) if isinstance(raw, list) else count)
    except Exception:
        pass
    asyncio.run(run(count=count, mock_file=args.mock_file, delay_seconds=args.delay))
