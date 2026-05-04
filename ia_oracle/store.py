import asyncio
from typing import Any, Dict, Optional

from forex_shared.worker_api.store import BaseStore
from forex_shared.worker_api.cache import BaseCache


class OracleMongoStore(BaseStore):
    """MongoDB storage for IA Oracle reviews and resolutions."""
    COLLECTION = "oracle_reviews"

    async def ensure_indexes(self) -> None:
        await self._mongo.async_ensure_indexes(self.COLLECTION, [
            [("trigger_event_id", 1)],
            [("resolved_at", -1)],
            [("action", 1)],
        ])

    async def store_item(self, item: Dict[str, Any]) -> Any:
        event_id = item.get("trigger_event_id")
        if not event_id:
            self.log.warning("Cannot store item without trigger_event_id")
            return None
            
        return await self._mongo.async_replace_one(
            self.COLLECTION, 
            {"trigger_event_id": event_id}, 
            item, 
            upsert=True
        )

    async def get_item(self, query: Dict[str, Any]) -> Optional[Any]:
        results = await self._mongo.async_find_many(self.COLLECTION, query, limit=1)
        return results[0] if results else None


class OracleCache(BaseCache):
    """Redis cache for fast deduplication of processed Oracle requests."""
    
    def _k(self, event_id: str) -> str:
        return f"oracle:review:{event_id}"

    async def store(self, item: Dict[str, Any], key: str, ttl: Optional[int] = 86400 * 7) -> None:
        """Stores the result for 7 days by default to prevent redundant LLM calls."""
        await self._r.set_json_raw(self._k(key), item, ttl=ttl)

    async def load(self, key: str) -> Optional[Any]:
        return await self._r.get_json_raw(self._k(key))
