"""IA Oracle Session logic for LLM review processing.

This module defines OracleSession, which receives an ``OracleReviewRequest``,
delegates LLM interaction to an ``IAProvider`` (default: GeminiIAProvider via
IAProviderFactory), and returns an ``OracleReviewResponse``.

The session is now LLM-agnostic: swapping Gemini for OpenAI or Claude only
requires changing the ``IA_PROVIDER`` environment variable — no code changes.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from forex_shared.worker_api.session import BaseSession
from forex_shared.worker_api.ia_factory import IAProviderFactory
from forex_shared.worker_api.ia_provider import IAProvider
from forex_shared.domain.oracle import OracleReviewRequest, OracleReviewResponse


class OracleSession(BaseSession):
    """Processes intelligence items via an LLM provider for market impact review.

    The session is intentionally provider-agnostic.  By default it uses
    ``IAProviderFactory.create_from_env()`` which reads the ``IA_PROVIDER``
    env-var (default: GEMINI).  You can also inject a provider directly for
    testing::

        provider = GeminiIAProvider(config)
        session = OracleSession("s1", ia_provider=provider)
    """

    def __init__(
        self,
        session_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        *,
        ia_provider: Optional[IAProvider] = None,
    ) -> None:
        self.session_id = session_id
        self.session_name = f"oracle_{session_id}"
        self.status = "stopped"
        self.kind = "oracle_reviewer"
        self.metadata = metadata or {}

        self.log = logging.getLogger(f"OracleSession.{session_id}")
        self._running = False

        load_dotenv(override=True)

        # Provider injection — fallback to factory
        if ia_provider is not None:
            self._provider: IAProvider = ia_provider
        else:
            self._provider = IAProviderFactory.create_from_env()

        self._prompt_template = self._load_prompt()

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------

    def _load_prompt(self) -> str:
        prompt_path = Path(__file__).parent / "prompts" / "ia_trend_oracle.md"
        if not prompt_path.exists():
            self.log.warning(
                "Prompt file not found at %s, using minimal fallback.", prompt_path
            )
            return "You are an IA Trend Oracle. Evaluate the event and return valid JSON."
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        # Initialize the provider (create client, semaphore, load config)
        await self._provider.initialize()

        # Attach the system prompt to providers that support it
        if hasattr(self._provider, "set_default_system_prompt"):
            self._provider.set_default_system_prompt(self._prompt_template)

        self._running = True
        self.status = "running"
        self.log.info("OracleSession started. provider=%s", self._provider)

    async def stop(self) -> None:
        await self._provider.close()
        self._running = False
        self.status = "stopped"
        self.log.info("OracleSession stopped.")

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    async def process_message(self, request: OracleReviewRequest) -> OracleReviewResponse:
        """Processes a single OracleReviewRequest via the configured IAProvider."""
        self.log.info("Processing Oracle review for event: %s", request.trigger_event_id)

        user_prompt = json.dumps(
            {
                "instruction": "Evaluate this IA Trend Oracle request. Return only valid JSON.",
                "oracle_request": request.to_dict(),
            },
            ensure_ascii=False,
            indent=2,
        )

        raw_response: Optional[str] = None
        parsed_json: Optional[Dict[str, Any]] = None

        try:
            raw_response = await self._provider.generate(user_prompt)
            parsed_json = self._parse_llm_json(raw_response)
        except Exception as exc:
            self.log.error("IAProvider.generate() failed: %s", exc, exc_info=True)

        if not parsed_json:
            self.log.warning(
                "Failed to parse LLM response for %s. Defaulting to DISCARD.",
                request.trigger_event_id,
            )
            return OracleReviewResponse(
                trigger_event_id=request.trigger_event_id,
                action="DISCARD",
                oracle_confidence=0.0,
                reasoning=f"Parse error or empty response. Raw: {raw_response}",
            )

        decision_block = parsed_json.get("oracle_decision", {})

        action = "DISCARD"
        if decision_block.get("create_tag"):
            action = "EMIT"
        elif decision_block.get("review_only"):
            action = "HOLD"

        tags_to_emit = parsed_json.get("directives", [])

        return OracleReviewResponse(
            trigger_event_id=request.trigger_event_id,
            action=action,
            oracle_confidence=1.0,
            reasoning=decision_block.get("decision_reason", ""),
            tags_to_emit=tags_to_emit,
        )

    # ------------------------------------------------------------------
    # JSON parsing (model-agnostic)
    # ------------------------------------------------------------------

    def _parse_llm_json(self, text: Optional[str]) -> Optional[Dict[str, Any]]:
        """Robustly extracts JSON from an LLM output string."""
        if not text:
            return None

        raw = text.strip()

        # Strip markdown code fences
        fence_match = re.search(r"```(?:json)?\s*(.*?)```", raw, flags=re.DOTALL | re.IGNORECASE)
        if fence_match:
            raw = fence_match.group(1).strip()

        try:
            return json.loads(raw)
        except Exception:
            pass

        start = raw.find("{")
        if start >= 0:
            end = raw.rfind("}")
            if end > start:
                try:
                    return json.loads(raw[start : end + 1])
                except Exception:
                    pass

            # Aggressive fallback for truncated Gemini JSON
            salvaged = raw[start:]
            for suffix in ["}", "]}", "]}", '"]}']:
                try:
                    return json.loads(salvaged + suffix)
                except Exception:
                    pass

        return None
