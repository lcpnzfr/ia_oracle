"""StrategistStore — Persistence and aggregation for the Global Pulse (SITREP).

Collections:
    global_pulse  — time-bucketed synthesized snapshots (BLUF, Key Developments, Regional).
    intel_items   — read-only access for semantic aggregation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from forex_shared.mongo_manager import MongoManager
from forex_shared.worker_api.store import BaseStore
from forex_shared.logging.get_logger import get_logger

log = get_logger(__name__)

class StrategistStore(BaseStore):
    """Async MongoDB persistence for Global Pulse snapshots and aggregation."""

    COLLECTION_PULSE = "global_pulse"
    COLLECTION_INTEL = "intel_items"

    def __init__(self, mongo_manager: Optional[MongoManager] = None) -> None:
        super().__init__(mongo_manager)

    async def ensure_indexes(self) -> None:
        """Idempotent index creation for the Strategist."""
        # Pulse indexes
        await self._mongo.async_ensure_indexes(
            self.COLLECTION_PULSE,
            [
                [("timestamp", -1)],
                [("affected_currencies", 1)],
            ],
        )
        # Ensure we have the indexes on intel_items needed for fast aggregation
        # (Note: IntelMongoStore already handles its own indexes, but we ensure our needs here)
        await self._mongo.async_ensure_indexes(
            self.COLLECTION_INTEL,
            [
                [("event_type", 1), ("extra.oracle_review_candidate", 1), ("published_at", -1)],
            ],
        )
        log.info("StrategistStore: indexes ensured.")

    # ── Aggregation Logic ─────────────────────────────────────────────

    async def fetch_semantic_gems(self, hours: int = 6, limit: int = 100, min_danger: float = 0.5) -> List[Dict[str, Any]]:
        """Fetch recently enriched items ranked by danger and impact.
        
        Refinement #4: Semantic Gem Selection
        Filters for:
        - INTEL_ITEM_ENRICHED event type.
        - oracle_review_candidate = True.
        - danger_score >= min_danger.
        - Must have an analysis_summary.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        
        query = {
            "event_type": "INTEL_ITEM_ENRICHED",
            "extra.oracle_review_candidate": True,
            "danger_score": {"$gte": min_danger},
            "extra.analysis_summary": {"$exists": True, "$ne": ""},
            "created_at": {"$gte": cutoff}
        }
        
        # Sort by danger_score and impact_category weight (if we had it, fallback to danger)
        results = await self._mongo.async_find_many(
            self.COLLECTION_INTEL,
            query,
            sort=[("danger_score", -1), ("created_at", -1)],
            limit=limit
        )
        return results

    # ── Pulse Persistence ─────────────────────────────────────────────

    async def save_pulse(self, pulse_doc: Dict[str, Any]) -> str:
        """Store a new Global Pulse snapshot.
        
        Returns the generated document ID.
        """
        now = datetime.now(timezone.utc).isoformat()
        
        if "_id" not in pulse_doc:
            pulse_doc["_id"] = str(uuid.uuid4())
            
        if "timestamp" not in pulse_doc:
            pulse_doc["timestamp"] = now
            
        pulse_doc["created_at"] = now
        
        await self._mongo.async_replace_one(
            self.COLLECTION_PULSE,
            {"_id": pulse_doc["_id"]},
            pulse_doc,
            upsert=True
        )
        
        log.info("StrategistStore: saved new Global Pulse snapshot id=%s", pulse_doc["_id"])
        return pulse_doc["_id"]

    async def get_latest_pulse(self) -> Optional[Dict[str, Any]]:
        """Retrieve the most recent SITREP snapshot."""
        results = await self._mongo.async_find_many(
            self.COLLECTION_PULSE,
            {},
            sort=[("timestamp", -1)],
            limit=1
        )
        return results[0] if results else None

    async def get_pulse_for_currencies(self, currencies: List[str], hours: int = 24) -> Optional[Dict[str, Any]]:
        """Retrieve the latest pulse that affected any of the specified currencies."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        
        query = {
            "timestamp": {"$gte": cutoff},
            "affected_currencies": {"$in": [c.upper() for c in currencies]}
        }
        
        results = await self._mongo.async_find_many(
            self.COLLECTION_PULSE,
            query,
            sort=[("timestamp", -1)],
            limit=1
        )
        return results[0] if results else None
