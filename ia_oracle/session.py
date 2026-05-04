"""IA Oracle Session logic for LLM review processing.

This module defines the OracleSession, which receives an `OracleReviewRequest`, 
interacts with the Gemini API (with a concurrency semaphore to avoid rate limits), 
and publishes the `OracleReviewResponse`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from google import genai
from google.genai import types

from forex_shared.worker_api.session import BaseSession
from forex_shared.domain.oracle import OracleReviewRequest, OracleReviewResponse

# For production, you could inject this. We use a module-level lock for simple rate limiting.
_GEMINI_SEMAPHORE = asyncio.Semaphore(int(os.getenv("ORACLE_CONCURRENCY", "2")))


class OracleSession(BaseSession):
    """Processes intelligence items via the Gemini LLM for market impact review."""

    def __init__(self, session_id: str, metadata: Optional[Dict[str, Any]] = None):
        self.session_id = session_id
        self.session_name = f"oracle_{session_id}"
        self.status = "stopped"
        self.kind = "oracle_reviewer"
        self.metadata = metadata or {}
        
        self.log = logging.getLogger(f"OracleSession.{session_id}")
        self._running = False
        
        load_dotenv(override=True)
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not defined in the environment.")
        
        self.client = genai.Client(api_key=api_key)
        self.model_name = os.getenv("ORACLE_MODEL", "gemini-pro-latest")
        
        self.prompt_template = self._load_prompt()
        self.config = self._build_gemini_config()

    def _load_prompt(self) -> str:
        prompt_path = Path(__file__).parent / "prompts" / "ia_trend_oracle.md"
        if not prompt_path.exists():
            self.log.warning(f"Prompt file not found at {prompt_path}, using minimal fallback.")
            return "You are an IA Trend Oracle. Evaluate the event and return valid JSON."
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()

    def _build_gemini_config(self) -> types.GenerateContentConfig:
        tools: List[types.Tool] = []
        # In a real scenario, toggle these based on EnvConfigManager
        if os.getenv("ORACLE_ENABLE_URL_CONTEXT", "true").lower() == "true":
            tools.append(types.Tool(url_context=types.UrlContext()))
        
        return types.GenerateContentConfig(
            temperature=0.2,
            top_p=0.95,
            max_output_tokens=8192,
            tools=tools,
            response_mime_type="application/json",
            system_instruction=[types.Part.from_text(text=self.prompt_template)],
        )

    async def start(self) -> None:
        self._running = True
        self.status = "running"
        self.log.info("OracleSession started.")

    async def stop(self) -> None:
        self._running = False
        self.status = "stopped"
        self.log.info("OracleSession stopped.")

    async def process_message(self, request: OracleReviewRequest) -> OracleReviewResponse:
        """Processes a single OracleReviewRequest via the Gemini API."""
        
        self.log.info(f"Processing Oracle review for event: {request.trigger_event_id}")
        
        user_prompt = json.dumps(
            {
                "instruction": "Evaluate this IA Trend Oracle request. Return only valid JSON.",
                "oracle_request": request.to_dict(),
            },
            ensure_ascii=False,
            indent=2,
        )

        raw_response = None
        parsed_json = None
        
        async with _GEMINI_SEMAPHORE:
            # We use asyncio.to_thread because the genai Client generate_content might block
            try:
                response = await asyncio.to_thread(
                    self.client.models.generate_content,
                    model=self.model_name,
                    contents=user_prompt,
                    config=self.config,
                )
                raw_response = response.text
                parsed_json = self._parse_llm_json(raw_response)
            except Exception as e:
                self.log.error(f"Gemini API call failed: {e}", exc_info=True)
        
        if not parsed_json:
            self.log.warning(f"Failed to parse LLM response for {request.trigger_event_id}. Defaulting to DISCARD.")
            return OracleReviewResponse(
                trigger_event_id=request.trigger_event_id,
                action="DISCARD",
                oracle_confidence=0.0,
                reasoning=f"Parse error or empty response. Raw: {raw_response}",
            )

        # Map the LLM output to our standard OracleReviewResponse
        decision_block = parsed_json.get("oracle_decision", {})
        
        action = "DISCARD"
        if decision_block.get("create_tag"):
            action = "EMIT"
        elif decision_block.get("review_only"):
            action = "HOLD"

        # The prompt might not return an explicit 'oracle_confidence', we infer from the tags or set default
        tags_to_emit = parsed_json.get("directives", [])
        
        return OracleReviewResponse(
            trigger_event_id=request.trigger_event_id,
            action=action,
            oracle_confidence=1.0, # Could be derived from model uncertainty output
            reasoning=decision_block.get("decision_reason", ""),
            tags_to_emit=tags_to_emit,
        )

    def _parse_llm_json(self, text: str | None) -> Dict[str, Any] | None:
        """Robustly extracts JSON from an LLM output string."""
        if not text:
            return None

        raw = text.strip()
        fence_match = re.search(r"```(?:json)?\s*(.*?)```", raw, flags=re.DOTALL | re.IGNORECASE)
        if fence_match:
            raw = fence_match.group(1).strip()

        try:
            return json.loads(raw)
        except Exception:
            pass

        start = raw.find("{")
        if start >= 0:
            # Check if there is a closing brace. If not, try to forcibly close the JSON.
            end = raw.rfind("}")
            if end > start:
                try:
                    return json.loads(raw[start : end + 1])
                except Exception:
                    pass
            
            # Very aggressive fallback: Gemini sometimes truncates the end of JSON
            try:
                import ast
                # Not perfect, but can salvage truncated JSON arrays at the very end
                salvaged = raw[start:]
                if not salvaged.endswith("}"):
                    # Let's see if adding standard closing blocks works
                    for suffix in ['}', ']}', ']}', '"]}']:
                        try:
                            return json.loads(salvaged + suffix)
                        except:
                            pass
            except Exception:
                pass

        return None
