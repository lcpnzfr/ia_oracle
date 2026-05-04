"""IA Oracle Worker process to manage multiple OracleSessions and MQ orchestration.

This module implements the `OracleWorker` via the `BaseSessionWorker` contract.
It receives commands over MQ, spins up an `OracleSession`, wires it to 
an `MQEventConsumer`, and publishes results back via an `MQEventPublisher`.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Mapping, Optional

from forex_shared.worker_api.session_worker import BaseSessionWorker, InMemorySessionPoolMixin
from forex_shared.worker_api.event_consumer import MQEventConsumer
from forex_shared.worker_api.event_publisher import MQEventPublisher
from forex_shared.domain.oracle import OracleReviewRequest

from ia_oracle.session import OracleSession
from ia_oracle.store import OracleMongoStore, OracleCache


class OracleWorker(BaseSessionWorker, InMemorySessionPoolMixin):
    """Distributed worker node running Oracle (Gemini LLM) sessions."""

    def __init__(self, worker_id: str, max_sessions: int = 1, control_topic: Optional[str] = None):
        self.worker_id = worker_id
        self.max_sessions = max_sessions
        self.control_topic = control_topic or f"worker.{self.worker_id}.control"
        
        self._sessions: Dict[str, Any] = {}
        self._consumers: Dict[str, MQEventConsumer] = {}
        
        self.publisher = MQEventPublisher(
            worker_count=2,
            queue_maxsize=1000,
            retry_attempts=3,
        )
        
        # Persistence
        self.store = OracleMongoStore()
        # Redis provider needs to be injected into OracleCache once connected
        self.cache: Optional[OracleCache] = None

        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Starts background tasks, publishers, and persistence."""
        # Start the publisher to ensure we can emit resolved tags/responses
        await self.publisher.start()
        
        # Ensure MongoDB indexes
        await self.store.ensure_indexes()
        
        # Redis initialization (We borrow RedisProvider from shared_lib)
        from forex_shared.providers.cache.redis_provider import RedisProvider
        redis = await RedisProvider.shared_from_env()
        self.cache = OracleCache(redis)

    async def stop(self) -> None:
        """Stops all sessions, consumers, and publishers gracefully."""
        self._stop_event.set()
        
        # Stop all running sessions
        session_ids = list(self._sessions.keys())
        for sid in session_ids:
            await self.stop_session(sid)
            
        # Drain and stop the publisher
        await self.publisher.stop(drain_timeout=15.0)

    async def run_forever(self) -> None:
        """Runs the worker indefinitely."""
        await self.start()
        await self._stop_event.wait()

    async def create_session(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        """Creates and starts an OracleSession and binds it to an MQ consumer.
        
        Expected payload:
        {
            "session_id": "oracle_instance_1",
            "input_topic": "intel.oracle.review",
            "output_topic": "intel.oracle.resolved"
        }
        """
        session_id = payload.get("session_id", f"oracle_{len(self._sessions)}")
        
        if session_id in self._sessions:
            return {"ok": False, "error": "Session already exists."}
            
        if not self.has_capacity:
            return {"ok": False, "error": "Worker at max capacity."}

        # 1. Instantiate the session
        session = OracleSession(session_id=session_id)
        await session.start()
        self._sessions[session_id] = session

        # 2. Setup message consumption routing
        input_topic = payload.get("input_topic", "intel.oracle.review")
        output_topic = payload.get("output_topic", "intel.oracle.resolved")

        async def _message_handler(raw_msg: Dict[str, Any]) -> None:
            # Parse MQ payload into Domain Contract
            request = OracleReviewRequest.from_dict(raw_msg)
            
            # Fast check: skip if we've already cached a response recently
            if self.cache:
                cached = await self.cache.load(request.trigger_event_id)
                if cached:
                    session.log.info(f"Skipping {request.trigger_event_id}; found in cache.")
                    return

            # Execute Gemini LLM Logic
            response = await session.process_message(request)
            
            # Publish back to MQ
            await self.publisher.publish(output_topic, response.to_dict())
            
            # Store Audit Trail in MongoDB
            audit_record = {
                "trigger_event_id": request.trigger_event_id,
                "request": request.to_dict(),
                "response": response.to_dict(),
                "worker_id": self.worker_id,
                "timestamp": response.resolved_at
            }
            await self.store.store_item(audit_record)
            
            # Save to Cache to prevent duplicate processing
            if self.cache:
                await self.cache.store({"status": "resolved", "action": response.action}, request.trigger_event_id)

        # 3. Create and start the consumer bound to the session's handler
        consumer = MQEventConsumer(
            topic=input_topic,
            callback=_message_handler
        )
        await consumer.start()
        self._consumers[session_id] = consumer

        return {"ok": True, "session_id": session_id, "status": "running"}

    async def stop_session(self, session_id: str) -> Dict[str, Any]:
        """Stops the session and unbinds its MQ consumer."""
        if session_id not in self._sessions:
            return {"ok": False, "error": "Session not found."}

        # Stop Consumer
        consumer = self._consumers.pop(session_id, None)
        if consumer:
            await consumer.stop()

        # Stop Session
        session = self._sessions.pop(session_id)
        await session.stop()

        return {"ok": True, "session_id": session_id, "status": "stopped"}

    async def list_sessions(self) -> List[Dict[str, Any]]:
        """Returns metadata about running sessions."""
        return self.session_snapshots()

    async def health_check(self) -> Dict[str, Any]:
        """Returns overall health of the worker, including publisher and consumer stats."""
        consumer_healths = {sid: c.health() for sid, c in self._consumers.items()}
        
        return {
            "worker_id": self.worker_id,
            "status": "alive" if not self._stop_event.is_set() else "stopping",
            "load": self.load,
            "sessions": len(self._sessions),
            "publisher": self.publisher.health(),
            "consumers": consumer_healths,
        }
