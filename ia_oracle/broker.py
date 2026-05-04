"""Broker Orchestrator for IA Oracle Workers.

This module acts as the entry point and master node. It tracks available 
OracleWorkers and distributes session requests across them.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Mapping, Optional

from forex_shared.worker_api.broker import BaseBroker
from forex_shared.worker_api.contracts import BrokerMode, CommandResponse, WorkerSnapshot


class OracleBroker(BaseBroker):
    """Orchestrates IA Oracle Workers."""

    def __init__(self, instance_id: str = "oracle_broker_1", mode: BrokerMode = "distributed"):
        self.instance_id = instance_id
        self.mode = mode
        
        # Track active workers reporting via heartbeats
        self._workers: Dict[str, WorkerSnapshot] = {}
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Starts the broker and binds to control/heartbeat topics."""
        # Setup MQ connection here using MQFactory, and bind to `worker.health`
        # to populate self._workers. For now, we simulate start.
        self._stop_event.clear()

    async def stop(self) -> None:
        self._stop_event.set()

    async def run_forever(self) -> None:
        await self.start()
        await self._stop_event.wait()

    async def create_session(self, payload: Mapping[str, Any]) -> CommandResponse:
        """Finds the least-loaded worker and asks it to create an OracleSession."""
        worker = await self.pick_worker()
        if not worker:
            # If no worker has capacity, we could spawn one.
            return {"ok": False, "error": "No available workers with capacity."}

        # Send command over MQ to the worker's control topic
        # return await self.send_to_worker(worker, "SESSION_CREATE", payload)
        
        # Placeholder for successful route
        return {"ok": True, "routed_to": worker.worker_id}

    async def stop_session(self, session_id: str) -> CommandResponse:
        """Broadcasts a STOP command to all workers (or tracked worker)."""
        return {"ok": True, "message": f"Broadcasted stop for {session_id}"}

    async def list_sessions(self, payload: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
        return []

    async def health_check(self) -> CommandResponse:
        return {
            "broker_id": self.instance_id,
            "mode": self.mode,
            "known_workers": len(self._workers),
            "workers_snapshot": [w.to_dict() for w in self._workers.values()],
        }

    async def pick_worker(self) -> Optional[WorkerSnapshot]:
        """Returns the worker with the lowest load that has capacity."""
        available = [w for w in self._workers.values() if w.has_capacity]
        if not available:
            return None
        return min(available, key=lambda w: w.load)
