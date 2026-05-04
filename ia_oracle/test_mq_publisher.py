"""MQ Publisher Test — Oracle Pipeline End-to-End Validation.

Reads the existing mock data file, selects a configurable subset of items,
maps each one to an ``OracleReviewRequest``, and publishes them to the
``intel.oracle.review`` MQ topic — exactly as the ``GlobalTagEmitter`` would.

This is the SENDER half of the MQ integration test.  Run the subscriber
(``test_mq_subscriber.py``) in a second terminal first, then run this script.

Usage:
    # From the ia_oracle service root:
    python ia_oracle/test_mq_publisher.py               # publish first 3 items
    python ia_oracle/test_mq_publisher.py --count 10    # publish first 10 items
    python ia_oracle/test_mq_publisher.py --all         # publish all items in mock file

Environment:
    Standard MQ env-vars (MQ_PROVIDER, MQ_HOST, etc.) must be set or in .env
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Environment setup — must happen before importing shared_lib
# ---------------------------------------------------------------------------

THIS_FILE = Path(__file__).resolve()
SERVICE_ROOT = THIS_FILE.parents[1]
PACKAGE_ROOT = THIS_FILE.parent

load_dotenv(SERVICE_ROOT / ".env", override=False)
load_dotenv(override=False)

from forex_shared.env_config_manager import EnvConfigManager  # noqa: E402

try:
    EnvConfigManager.startup()
except Exception as _e:
    import logging as _l
    _l.getLogger(__name__).warning("EnvConfigManager.startup() skipped: %s", _e)

from forex_shared.providers.mq.mq_factory import MQFactory  # noqa: E402
from forex_shared.domain.oracle import OracleReviewRequest  # noqa: E402

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
log = logging.getLogger("test_mq_publisher")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MOCK_FILE = PACKAGE_ROOT / "data" / "mock_intel_items_big_process_result.json"
INPUT_TOPIC = "intel.oracle.review"
DEFAULT_COUNT = 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _build_request(item: dict) -> OracleReviewRequest:
    """Maps a mock GlobalIntel ProcessedEvent → OracleReviewRequest.

    Handles both the wrapped format (``item["oracle_request"]``) and bare
    IntelItem payloads, mirroring the logic in TestOracleOrchestrator.
    """
    if "oracle_request" in item:
        req_data = item["oracle_request"]
        enriched = req_data.get("enriched_event", {})
        routing = req_data.get("routing", {})
        return OracleReviewRequest(
            trigger_event_id=req_data.get("trigger_event_id", enriched.get("id", "unknown")),
            reason=routing.get("routing_reason", "mq_test_publisher"),
            title=enriched.get("title", ""),
            body=enriched.get("body", ""),
            published_at=enriched.get("published_at", _utc_now()),
            source=enriched.get("source", "telegram"),
            domain=enriched.get("domain", "geopolitical"),
            danger_score_legacy=routing.get("scores_snapshot", {}).get("danger_score_legacy", 0.0),
            impact_category=enriched.get("extra", {}).get("impact_category", "generic"),
            scores=routing.get("scores_snapshot", {}),
            trade_emit_score=routing.get("local_final_decision", {}).get("trade_emit_score", 0.0),
            candidate_directives=routing.get("candidate_directives", []),
            score_breakdown=enriched.get("extra", {}).get("score_breakdown", {}),
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run(count: int, mock_file: Path, delay_seconds: float) -> None:
    log.info("=== Oracle MQ Publisher Test ===")
    log.info("Mock file  : %s", mock_file)
    log.info("Topic      : %s", INPUT_TOPIC)
    log.info("Count      : %d items", count)
    log.info("Delay      : %.1f s between messages", delay_seconds)

    # Load mock data
    if not mock_file.exists():
        raise FileNotFoundError(f"Mock data not found: {mock_file}")
    items: list[dict] = json.loads(mock_file.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        raise ValueError("Mock file must contain a JSON array at the root.")
    items = items[:count]
    log.info("Loaded %d items (file has %d total)", len(items), count)

    # Connect MQ
    log.info("Connecting to MQ (provider=%s)…", os.getenv("MQ_PROVIDER", "RABBITMQ_ASYNC"))
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
                    "[%d/%d] Published → topic=%s  id=%s  title=%.70s",
                    i,
                    len(items),
                    INPUT_TOPIC,
                    request.trigger_event_id,
                    request.title or "(no title)",
                )
            else:
                log.warning("[%d/%d] FAILED to publish id=%s", i, len(items), request.trigger_event_id)

            if delay_seconds > 0 and i < len(items):
                await asyncio.sleep(delay_seconds)

        log.info("Publisher finished. %d/%d messages published.", published, len(items))
    finally:
        await mq.disconnect()
        log.info("MQ disconnected.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish oracle review requests to MQ from mock data for pipeline validation.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=DEFAULT_COUNT,
        metavar="N",
        help=f"Number of mock items to publish (default: {DEFAULT_COUNT}).",
    )
    parser.add_argument(
        "--all",
        dest="publish_all",
        action="store_true",
        help="Publish all items in the mock file (overrides --count).",
    )
    parser.add_argument(
        "--mock-file",
        type=Path,
        default=DEFAULT_MOCK_FILE,
        metavar="PATH",
        help=f"Path to the mock JSON array file (default: {DEFAULT_MOCK_FILE.name}).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        metavar="SECONDS",
        help="Seconds between published messages (default: 0.5).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    count = 999_999 if args.publish_all else args.count

    # Load actual length to respect --all
    try:
        raw = json.loads(args.mock_file.read_text(encoding="utf-8"))
        total = len(raw) if isinstance(raw, list) else 0
    except Exception:
        total = count
    count = min(count, total)

    asyncio.run(run(count=count, mock_file=args.mock_file, delay_seconds=args.delay))
