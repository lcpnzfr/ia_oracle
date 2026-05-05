"""OracleWorker — IA Oracle MQ worker.

Consumes ``intel.oracle.review`` messages, sends each to the Gemini LLM
via ``GeminiIAProvider`` (with automatic model rotation on quota), and
publishes the resolved ``OracleReviewResponse`` to ``intel.oracle.resolved``.

Usage (via main.py):
    python ia_oracle/main.py --worker-id oracle_1 --max-sessions 1

Or directly:
    from ia_oracle.worker import OracleWorker
    worker = OracleWorker()
    await worker.start()
    await worker.run_forever()
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from forex_shared.domain.oracle import OracleReviewRequest, OracleReviewResponse
from forex_shared.logging.loggable import Loggable
from forex_shared.providers.mq.mq_factory import MQFactory
from forex_shared.worker_api.ia_factory import IAProviderFactory

# ── topic constants ───────────────────────────────────────────────────────────
INPUT_TOPIC = "intel.oracle.review"
OUTPUT_TOPIC = "intel.oracle.resolved"

# ── prompt ────────────────────────────────────────────────────────────────────
_PROMPT_FILE = Path(__file__).parent / "prompts" / "ia_trend_oracle.md"


def _load_system_prompt() -> str:
    if _PROMPT_FILE.exists():
        return _PROMPT_FILE.read_text(encoding="utf-8")
    return (
        "You are an expert geopolitical and financial analyst. "
        "Analyse the event provided and return a JSON object with keys: "
        "action (EMIT|DISCARD|HOLD), oracle_confidence (0.0-1.0), "
        "reasoning (string), tags_to_emit (list)."
    )


def _build_user_prompt(req: OracleReviewRequest) -> str:
    return json.dumps(
        {
            "trigger_event_id": req.trigger_event_id,
            "title": req.title,
            "body": req.body,
            "domain": req.domain,
            "source": req.source,
            "reason": req.reason,
            "scores": req.scores,
            "trade_emit_score": req.trade_emit_score,
            "candidate_directives": req.candidate_directives,
        },
        ensure_ascii=False,
        indent=2,
    )


def _parse_response(raw: str, event_id: str) -> OracleReviewResponse:
    """Parse LLM JSON response → OracleReviewResponse.

    Supports two schemas:
      - ia_trend_oracle_v1 (nested: oracle_decision, directives, audit)
      - Legacy flat schema (action, oracle_confidence, reasoning)
    """
    try:
        # Strip markdown fences if present
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        data = json.loads(text)

        # ── ia_trend_oracle_v1 schema ─────────────────────────────────────
        if data.get("oracle_version") == "ia_trend_oracle_v1" or "oracle_decision" in data:
            decision = data.get("oracle_decision", {})
            directives = data.get("directives", [])
            audit = data.get("audit", {})

            # action
            if decision.get("ignore"):
                action = "DISCARD"
            elif decision.get("review_only"):
                action = "HOLD"
            elif decision.get("create_tag"):
                action = "EMIT"
            else:
                action = "DISCARD"

            # confidence — average of directive confidences, or oracle_review_score
            if directives:
                confidence = sum(float(d.get("confidence", 0.0)) for d in directives) / len(directives)
            else:
                confidence = float(
                    data.get("input_assessment", {}).get("oracle_review_score", 0.0)
                )

            reasoning = str(
                audit.get("reasoning_summary")
                or decision.get("decision_reason")
                or ""
            )

            tags_to_emit = [
                {
                    "asset": d.get("asset", ""),
                    "bias": d.get("bias", ""),
                    "confidence": float(d.get("confidence", 0.0)),
                    "risk_score": float(d.get("risk_score", 0.0)),
                    "volatility_duration_minutes": int(d.get("volatility_duration_minutes", 0)),
                    "reason": d.get("reason", ""),
                    "transmission_channel": d.get("transmission_channel", ""),
                }
                for d in directives
            ]

            return OracleReviewResponse(
                trigger_event_id=event_id,
                action=action,
                oracle_confidence=round(min(max(confidence, 0.0), 1.0), 4),
                reasoning=reasoning,
                tags_to_emit=tags_to_emit,
            )

        # ── Legacy flat schema ────────────────────────────────────────────
        return OracleReviewResponse(
            trigger_event_id=event_id,
            action=data.get("action", "DISCARD").upper(),
            oracle_confidence=float(data.get("oracle_confidence", 0.0)),
            reasoning=str(data.get("reasoning", "")),
            tags_to_emit=data.get("tags_to_emit", []),
        )

    except Exception as exc:
        return OracleReviewResponse(
            trigger_event_id=event_id,
            action="DISCARD",
            oracle_confidence=0.0,
            reasoning=f"[parse error] {exc} — raw: {raw[:200]}",
        )


class OracleWorker(Loggable):
    """MQ-driven IA Oracle worker.

    Lifecycle:
        await worker.start()          # initialize provider + MQ
        await worker.run_forever()    # block until stop() called
        await worker.stop()           # graceful shutdown
    """

    def __init__(self, worker_id: str = "oracle_worker_1", max_sessions: int = 1) -> None:
        self.worker_id = worker_id
        self.max_sessions = max_sessions
        self._mq = None
        self._provider = None
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._stop_event = asyncio.Event()
        self._system_prompt = _load_system_prompt()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self.log.info("[OracleWorker:%s] Starting...", self.worker_id)

        # Initialize Gemini provider
        self._provider = IAProviderFactory.create_from_env()
        await self._provider.initialize()

        # Set system prompt if provider supports it
        if hasattr(self._provider, "set_default_system_prompt"):
            self._provider.set_default_system_prompt(self._system_prompt)

        self.log.info(
            "[OracleWorker:%s] Provider ready: %s | model=%s",
            self.worker_id,
            self._provider.provider_type,
            self._provider.model_name,
        )

        # Connect MQ
        self._mq = MQFactory.create_async_from_env()
        await self._mq.connect()
        self.log.info("[OracleWorker:%s] MQ connected.", self.worker_id)

        # Subscribe to input topic
        await self._mq.subscribe_event(INPUT_TOPIC, self._handle_review)
        self.log.info("[OracleWorker:%s] Subscribed to %s", self.worker_id, INPUT_TOPIC)

        self._semaphore = asyncio.Semaphore(self.max_sessions)
        self.log.info("[OracleWorker:%s] Ready. concurrency=%d", self.worker_id, self.max_sessions)

    async def stop(self) -> None:
        self.log.info("[OracleWorker:%s] Stopping...", self.worker_id)
        self._stop_event.set()
        if self._mq:
            try:
                await self._mq.stop_consuming()
            except Exception:
                pass
            try:
                await self._mq.disconnect()
            except Exception:
                pass
        if self._provider:
            try:
                await self._provider.close()
            except Exception:
                pass
        self.log.info("[OracleWorker:%s] Stopped.", self.worker_id)

    async def run_forever(self) -> None:
        """Block until stop() is called."""
        self.log.info("[OracleWorker:%s] Running. Waiting for messages...", self.worker_id)
        consume_task = asyncio.create_task(self._mq.start_consuming())
        try:
            await self._stop_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            consume_task.cancel()
            await asyncio.gather(consume_task, return_exceptions=True)

    # ------------------------------------------------------------------
    # MQ handler
    # ------------------------------------------------------------------

    async def _handle_review(self, payload: Dict[str, Any]) -> None:
        """Called by MQ consumer for each intel.oracle.review message."""
        req = OracleReviewRequest.from_dict(payload)
        event_id = req.trigger_event_id

        self.log.info(
            "[OracleWorker:%s] Received review  id=%s  title=%.80s",
            self.worker_id,
            event_id,
            req.title or "(no title)",
        )

        async with self._semaphore:
            try:
                user_prompt = _build_user_prompt(req)
                self.log.info(
                    "[OracleWorker:%s] Calling Gemini for id=%s  model=%s",
                    self.worker_id,
                    event_id,
                    self._provider.model_name,
                )

                raw = await self._provider.generate(user_prompt)

                response = _parse_response(raw, event_id)

                self.log.info(
                    "[OracleWorker:%s] Gemini resolved  id=%s  action=%s  confidence=%.2f  reasoning=%.100s",
                    self.worker_id,
                    event_id,
                    response.action,
                    response.oracle_confidence,
                    response.reasoning,
                )

                # Publish to intel.oracle.resolved
                ok = await self._mq.publish_event(OUTPUT_TOPIC, response.to_dict())
                if ok:
                    self.log.info(
                        "[OracleWorker:%s] Published resolved  id=%s  topic=%s",
                        self.worker_id,
                        event_id,
                        OUTPUT_TOPIC,
                    )
                else:
                    self.log.warning(
                        "[OracleWorker:%s] Failed to publish resolved id=%s", self.worker_id, event_id
                    )

            except Exception as exc:
                self.log.error(
                    "[OracleWorker:%s] Error processing id=%s: %s",
                    self.worker_id,
                    event_id,
                    exc,
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # Compat shim for main.py (which calls create_session)
    # ------------------------------------------------------------------

    async def create_session(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """No-op — OracleWorker has a single built-in session."""
        self.log.debug("[OracleWorker:%s] create_session called (no-op): %s", self.worker_id, payload)
        return {"status": "ok", "session_id": payload.get("session_id", "default")}
