"""OracleWorker — IA Oracle MQ worker (production).

Pipeline:
    intel.oracle.review  →  [Gemini LLM]  →  intel.oracle.resolved  (audit)
                                           →  intel.global_tags       (if EMIT, one GlobalTag per directive)

The GlobalTag published to intel.global_tags is consumed by:
    - session_manager   → injects intel bias into strategy additional_data
    - executor_trading  → applies confidence penalty / blocks contra-trend orders
    - api_gateway       → WebSocket streaming of active tags

Architecture matches EventDrivenTradingSession:
    - One MQ connection (own instance via MQFactory)
    - Subscribes to input topic  → _handle_review()
    - Publishes to two output topics inside the same handler

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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from forex_shared.domain.intel import GlobalTag
from forex_shared.domain.oracle import OracleReviewRequest, OracleReviewResponse
from forex_shared.logging.loggable import Loggable
from ia_oracle.store import OracleMongoStore
from forex_shared.providers.mq.mq_factory import MQFactory
from forex_shared.providers.mq.topics import IntelTopics
from forex_shared.worker_api.ia_factory import IAProviderFactory

# ── topic constants (via shared IntelTopics) ──────────────────────────────────
INPUT_TOPIC  = IntelTopics.ORACLE_REVIEW    # intel.oracle.review
OUTPUT_TOPIC = IntelTopics.ORACLE_RESOLVED  # intel.oracle.resolved
TAGS_TOPIC   = IntelTopics.GLOBAL_TAGS      # intel.global_tags

# ── default TTL when directive has no volatility_duration_minutes ─────────────
_DEFAULT_TAG_TTL_MINUTES = 240  # 4 hours

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
            "trigger_event_id":   req.trigger_event_id,
            "title":              req.title,
            "body":               req.body,
            "domain":             req.domain,
            "source":             req.source,
            "reason":             req.reason,
            "scores":             req.scores,
            "trade_emit_score":   req.trade_emit_score,
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
            decision   = data.get("oracle_decision", {})
            directives = data.get("directives", [])
            audit      = data.get("audit", {})

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
                    "asset":                      d.get("asset", ""),
                    "bias":                       d.get("bias", ""),
                    "confidence":                 float(d.get("confidence", 0.0)),
                    "risk_score":                 float(d.get("risk_score", 0.0)),
                    "volatility_duration_minutes": int(d.get("volatility_duration_minutes", 0)),
                    "reason":                     d.get("reason", ""),
                    "transmission_channel":       d.get("transmission_channel", ""),
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


def _build_global_tags(
    response: OracleReviewResponse,
) -> List[GlobalTag]:
    """Convert OracleReviewResponse directives → list of GlobalTag objects.

    Only called when action == EMIT and tags_to_emit is non-empty.
    TTL defaults to _DEFAULT_TAG_TTL_MINUTES when directive has no duration.
    """
    now = datetime.now(timezone.utc)
    tags: List[GlobalTag] = []

    for directive in response.tags_to_emit:
        asset = directive.get("asset", "").strip()
        if not asset:
            continue

        ttl_minutes = int(directive.get("volatility_duration_minutes", 0)) or _DEFAULT_TAG_TTL_MINUTES
        expires_at  = (now + timedelta(minutes=ttl_minutes)).isoformat()

        tags.append(
            GlobalTag(
                asset=asset,
                bias=directive.get("bias", "neutral"),
                risk_score=float(directive.get("risk_score", response.oracle_confidence)),
                trigger_event_id=response.trigger_event_id,
                established_at=now.isoformat(),
                expires_at=expires_at,
                active=True,
            )
        )

    return tags


class OracleWorker(Loggable):
    """MQ-driven IA Oracle worker — production class.

    Subscribes to ``intel.oracle.review``, processes with Gemini LLM, and:

    1. Publishes resolved decision to ``intel.oracle.resolved``  (audit / monitoring)
    2. If action == EMIT: publishes one ``GlobalTag`` per directive to
       ``intel.global_tags``  → consumed by session_manager & executor_trading

    Lifecycle::

        worker = OracleWorker(worker_id="oracle_1", max_sessions=2)
        await worker.start()
        await worker.run_forever()   # blocks; Ctrl-C / SIGTERM triggers stop()
        await worker.stop()
    """

    def __init__(
        self,
        worker_id: str = "oracle_worker_1",
        max_sessions: int = 1,
        store: Optional[OracleMongoStore] = None,
    ) -> None:
        self.worker_id    = worker_id
        self.max_sessions = max_sessions
        self._mq          = None
        self._provider    = None
        self._store: Optional[OracleMongoStore] = store  # None = MongoDB disabled
        self._semaphore:  Optional[asyncio.Semaphore] = None
        self._stop_event  = asyncio.Event()
        self._system_prompt = _load_system_prompt()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self.log.info("[OracleWorker:%s] Starting...", self.worker_id)

        # ── Gemini provider ───────────────────────────────────────────
        self._provider = IAProviderFactory.create_from_env()
        await self._provider.initialize()

        if hasattr(self._provider, "set_default_system_prompt"):
            self._provider.set_default_system_prompt(self._system_prompt)

        self.log.info(
            "[OracleWorker:%s] Provider ready: %s | model=%s",
            self.worker_id,
            self._provider.provider_type,
            self._provider.model_name,
        )

        # ── MQ — one connection, both subscribe and publish ───────────
        self._mq = MQFactory.create_async_from_env()
        await self._mq.connect()
        self.log.info("[OracleWorker:%s] MQ connected.", self.worker_id)

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
        """Block until stop() is called (SIGTERM / KeyboardInterrupt)."""
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
    # MQ handler — core production logic
    # ------------------------------------------------------------------

    async def _handle_review(self, payload: Dict[str, Any]) -> None:
        """Called by the MQ consumer for each intel.oracle.review message.

        Flow:
            1. Deserialize OracleReviewRequest from payload
            2. Build user prompt
            3. Call Gemini (with model rotation + feature fallbacks)
            4. Parse response → OracleReviewResponse
            5. Publish audit to intel.oracle.resolved
            6. If action == EMIT: publish GlobalTag(s) to intel.global_tags
        """
        req      = OracleReviewRequest.from_dict(payload)
        event_id = req.trigger_event_id

        self.log.info(
            "[OracleWorker:%s] Received review  id=%s  title=%.80s",
            self.worker_id,
            event_id,
            req.title or "(no title)",
        )

        async with self._semaphore:
            try:
                # ── Step 2-4: prompt → Gemini → parse ────────────────
                user_prompt = _build_user_prompt(req)
                self.log.info(
                    "[OracleWorker:%s] Calling Gemini for id=%s  model=%s",
                    self.worker_id,
                    event_id,
                    self._provider.model_name,
                )

                raw      = await self._provider.generate(user_prompt)
                response = _parse_response(raw, event_id)

                self.log.info(
                    "[OracleWorker:%s] Resolved  id=%s  action=%s  confidence=%.2f  reasoning=%.100s",
                    self.worker_id,
                    event_id,
                    response.action,
                    response.oracle_confidence,
                    response.reasoning,
                )

                # ── Step 5: publish audit ─────────────────────────────
                await self._publish_resolved(response)

                # ── Step 6: emit GlobalTag(s) if EMIT ────────────────
                if response.action == "EMIT":
                    await self._emit_global_tags(response)

                # ── Step 7: persist to MongoDB (optional) ─────────────
                await self._persist(response)

            except Exception as exc:
                self.log.error(
                    "[OracleWorker:%s] Error processing id=%s: %s",
                    self.worker_id,
                    event_id,
                    exc,
                    exc_info=True,
                )

    async def _publish_resolved(self, response: OracleReviewResponse) -> None:
        """Publish resolved decision to intel.oracle.resolved (audit topic)."""
        ok = await self._mq.publish_event(OUTPUT_TOPIC, response.to_dict())
        if ok:
            self.log.info(
                "[OracleWorker:%s] Published resolved  id=%s  topic=%s",
                self.worker_id,
                response.trigger_event_id,
                OUTPUT_TOPIC,
            )
        else:
            self.log.warning(
                "[OracleWorker:%s] Failed to publish resolved id=%s",
                self.worker_id,
                response.trigger_event_id,
            )

    async def _emit_global_tags(self, response: OracleReviewResponse) -> None:
        """Build GlobalTag(s) from EMIT directives and publish to intel.global_tags.

        Each directive in tags_to_emit becomes one GlobalTag.
        Directives without an 'asset' field are silently skipped.
        TTL = directive.volatility_duration_minutes (default: 240 min / 4h).
        """
        tags = _build_global_tags(response)
        if not tags:
            self.log.debug(
                "[OracleWorker:%s] EMIT with no emittable directives for id=%s",
                self.worker_id,
                response.trigger_event_id,
            )
            return

        for tag in tags:
            payload = tag.to_mq_payload(event_type="GLOBAL_TAG_UPDATED")
            ok = await self._mq.publish_event(TAGS_TOPIC, payload)
            if ok:
                self.log.info(
                    "[OracleWorker:%s] GlobalTag emitted  asset=%s  bias=%s  "
                    "risk=%.2f  ttl_until=%s  topic=%s",
                    self.worker_id,
                    tag.asset,
                    tag.bias,
                    tag.risk_score,
                    tag.expires_at,
                    TAGS_TOPIC,
                )
            else:
                self.log.warning(
                    "[OracleWorker:%s] Failed to emit GlobalTag for asset=%s",
                    self.worker_id,
                    tag.asset,
                )

    async def _persist(self, response: OracleReviewResponse) -> None:
        """Persist resolved response to MongoDB (graceful — skipped if store is None).

        MongoDB failure logs a warning but never interrupts the MQ pipeline.
        Store is set at startup by main.py; None means MongoDB is disabled/unavailable.
        """
        if self._store is None:
            return
        try:
            outcome = await self._store.store_item(response)
            self.log.debug(
                "[OracleWorker:%s] MongoDB %s  id=%s",
                self.worker_id,
                outcome,
                response.trigger_event_id,
            )
        except Exception as exc:
            self.log.warning(
                "[OracleWorker:%s] MongoDB persistence failed for id=%s: %s",
                self.worker_id,
                response.trigger_event_id,
                exc,
            )

    # ------------------------------------------------------------------
    # Compat shim for main.py (which calls create_session on broker mode)
    # ------------------------------------------------------------------

    async def create_session(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """No-op — OracleWorker has a single built-in session."""
        self.log.debug(
            "[OracleWorker:%s] create_session called (no-op): %s",
            self.worker_id,
            payload,
        )
        return {"status": "ok", "session_id": payload.get("session_id", "default")}
