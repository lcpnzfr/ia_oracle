"""OpenAIIAProvider - concrete IAProvider backed by native OpenAI.

Uses the OpenAI Responses API through the async Python SDK. The implementation
mirrors the Gemini provider's runtime intelligence: live model discovery,
model rotation, provider-specific feature fallbacks, optional web search, and
structured JSON enforcement for decision-pipeline workloads.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, List, Optional

from forex_shared.worker_api.ia_provider import IAProvider, IAProviderConfig

logger = logging.getLogger(__name__)

_STATIC_FALLBACK_CHAIN: List[str] = [
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5-mini",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4o",
    "gpt-4o-mini",
]

OPENAI_MODEL_CHAIN: List[str] = _STATIC_FALLBACK_CHAIN

ORACLE_REVIEW_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "oracle_confidence", "reasoning", "tags_to_emit"],
    "properties": {
        "action": {
            "type": "string",
            "enum": ["EMIT", "DISCARD", "HOLD"],
        },
        "oracle_confidence": {
            "type": "number",
        },
        "reasoning": {"type": "string"},
        "tags_to_emit": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "asset",
                    "bias",
                    "confidence",
                    "risk_score",
                    "volatility_duration_minutes",
                    "reason",
                    "transmission_channel",
                ],
                "properties": {
                    "asset": {"type": "string"},
                    "bias": {
                        "type": "string",
                        "enum": [
                            "strong_bullish",
                            "bullish",
                            "neutral",
                            "bearish",
                            "strong_bearish",
                        ],
                    },
                    "confidence": {
                        "type": "number",
                    },
                    "risk_score": {
                        "type": "number",
                    },
                    "volatility_duration_minutes": {
                        "type": "integer",
                    },
                    "reason": {"type": "string"},
                    "transmission_channel": {"type": "string"},
                },
            },
        },
    },
}

_ROTATE_CODES = frozenset({408, 409, 429, 500, 502, 503, 504})
_MODEL_UNAVAILABLE_KEYWORDS = frozenset(
    {
        "model_not_found",
        "does not exist",
        "not found",
        "unsupported model",
        "rate limit",
        "quota",
        "temporarily unavailable",
        "overloaded",
    }
)
_EXCLUDED_MODEL_PARTS = frozenset(
    {
        "audio",
        "dall-e",
        "embedding",
        "image",
        "moderation",
        "realtime",
        "search-api",
        "search-preview",
        "speech",
        "tts",
        "transcribe",
        "whisper",
    }
)
_REASONING_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")
_OPENAI_REASONING_EFFORT = {
    "NONE": "none",
    "MINIMAL": "minimal",
    "LOW": "low",
    "MEDIUM": "medium",
    "HIGH": "high",
    "XHIGH": "xhigh",
}


def _should_rotate_model(exc: BaseException) -> bool:
    """Return True when another configured model may succeed."""

    msg = str(exc).lower()
    if any(keyword in msg for keyword in _MODEL_UNAVAILABLE_KEYWORDS):
        return True

    status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    try:
        return int(status_code) in _ROTATE_CODES
    except (TypeError, ValueError):
        return False


def _unsupported_feature(exc: BaseException) -> str | None:
    """Best-effort mapping from OpenAI API errors to feature fallbacks."""

    msg = str(exc).lower()
    unsupported = any(
        token in msg
        for token in (
            "unsupported",
            "not supported",
            "unrecognized",
            "unknown parameter",
            "invalid parameter",
            "invalid_request_error",
        )
    )
    if not unsupported:
        return None

    if "reasoning" in msg:
        return "reasoning"
    if "web_search" in msg or "tool" in msg or "tools" in msg:
        return "tools"
    if "json_object" in msg:
        return "json_object"
    if "json_schema" in msg or "text.format" in msg or "response_format" in msg:
        return "json_schema"
    if "temperature" in msg:
        return "temperature"
    return None


class OpenAIIAProvider(IAProvider):
    """Native OpenAI backend for ``IAProvider``."""

    def __init__(self, config: IAProviderConfig) -> None:
        super().__init__(config)

        try:
            from openai import AsyncOpenAI  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "OpenAIIAProvider requires 'openai'. Install it with: pip install openai"
            ) from exc

        self._openai_cls = AsyncOpenAI
        self._client: Any = None
        self._semaphore: asyncio.Semaphore | None = None
        self._default_system_prompt: Optional[str] = None
        self._model_chain: List[str] = []
        self._model_index: int = 0
        self._max_retries: int = 5

    async def initialize(self) -> None:
        concurrency = int(self._config.extra.get("concurrency", 1))
        self._max_retries = int(self._config.extra.get("max_retries", 5))
        timeout = float(self._config.extra.get("timeout_seconds", 120.0))
        base_url = self._config.extra.get("base_url") or None

        client_kwargs: dict[str, Any] = {
            "api_key": self._config.api_key,
            "timeout": timeout,
        }
        if base_url:
            client_kwargs["base_url"] = str(base_url).rstrip("/")

        self._client = self._openai_cls(**client_kwargs)
        self._semaphore = asyncio.Semaphore(max(1, concurrency))
        self._model_chain = await self._discover_model_chain()
        self._model_index = 0

        logger.info(
            "[OpenAIIAProvider] Initialized. primary=%s chain=%d concurrency=%d max_retries=%d "
            "reasoning=%s web_search=%s structured_json=%s",
            self.model_name,
            len(self._model_chain),
            concurrency,
            self._max_retries,
            self._config.extra.get("thinking_level", "HIGH"),
            self._web_search_enabled(),
            self._structured_json_enabled(),
        )
        logger.debug("[OpenAIIAProvider] Full model chain: %s", self._model_chain)

    async def close(self) -> None:
        if self._client is not None and hasattr(self._client, "close"):
            await self._client.close()
        logger.debug("[OpenAIIAProvider] Closed.")

    async def generate(
        self,
        user_prompt: str,
        system_prompt: Optional[str] = None,
        *,
        tools: Optional[List[Any]] = None,
    ) -> str:
        if self._client is None or self._semaphore is None:
            raise RuntimeError("OpenAIIAProvider.initialize() must be called before generate().")

        instructions = system_prompt or self._default_system_prompt

        async with self._semaphore:
            last_exc: Optional[BaseException] = None
            total = len(self._model_chain)
            max_attempts = self._max_retries + 4
            disabled: dict[str, set[str]] = {
                "reasoning": set(),
                "tools": set(),
                "json_schema": set(),
                "temperature": set(),
            }

            for attempt in range(max_attempts):
                index = self._model_index % total
                model = self._model_chain[index]

                try:
                    response = await self._client.responses.create(
                        **self._build_request_kwargs(
                            model=model,
                            instructions=instructions,
                            user_prompt=user_prompt,
                            tools=tools,
                            disabled=disabled,
                        )
                    )
                    if attempt > 0 or self._model_index != 0:
                        logger.info(
                            "[OpenAIIAProvider] Succeeded on model=%s attempt=%d",
                            model,
                            attempt + 1,
                        )
                    return self._extract_text(response)

                except Exception as exc:
                    last_exc = exc
                    feature = _unsupported_feature(exc)
                    if feature and self._disable_feature_for_model(feature, model, disabled):
                        logger.warning(
                            "[OpenAIIAProvider] %s unsupported on model=%s; retrying with fallback.",
                            feature,
                            model,
                        )
                        continue

                    if not _should_rotate_model(exc) or attempt >= max_attempts - 1:
                        logger.error(
                            "[OpenAIIAProvider] Generation failed on model=%s: %s",
                            model,
                            exc,
                            exc_info=True,
                        )
                        raise

                    next_index = (index + 1) % total
                    next_model = self._model_chain[next_index]
                    self._model_index = next_index
                    delay = 10.0 if next_index == 0 else min(2.0 * (attempt + 1), 10.0)

                    logger.warning(
                        "[OpenAIIAProvider] Rotating model %s -> %s after error: %s",
                        model,
                        next_model,
                        exc,
                    )
                    await asyncio.sleep(delay)

            raise last_exc  # type: ignore[misc]

    def set_default_system_prompt(self, prompt: str) -> None:
        self._default_system_prompt = prompt

    @property
    def model_name(self) -> str:
        if self._model_chain:
            return self._model_chain[self._model_index % len(self._model_chain)]
        return self._config.model_name

    @property
    def model_chain(self) -> List[str]:
        return list(self._model_chain)

    async def _discover_model_chain(self) -> List[str]:
        allowlist: List[str] = self._config.extra.get("model_allowlist") or []
        denylist: List[str] = self._config.extra.get("model_denylist") or []
        primary = self._config.model_name.strip() or _STATIC_FALLBACK_CHAIN[0]

        try:
            logger.info("[OpenAIIAProvider] Querying available OpenAI models...")
            discovered: list[tuple[str, int]] = []
            async for model in self._client.models.list():
                model_id = str(getattr(model, "id", "")).strip()
                created = int(getattr(model, "created", 0) or 0)
                if self._is_candidate_model(model_id):
                    discovered.append((model_id, created))

            valid = self._sort_models(discovered)
            logger.info("[OpenAIIAProvider] Discovered %d candidate models.", len(valid))

            if not valid:
                raise ValueError("No valid text models returned by OpenAI model list.")

        except Exception as exc:
            logger.warning(
                "[OpenAIIAProvider] Model discovery failed (%s). Using static fallback chain.",
                exc,
            )
            valid = list(_STATIC_FALLBACK_CHAIN)

        valid = self._apply_model_filters(valid, allowlist=allowlist, denylist=denylist)
        chain = [primary] + [model for model in valid if model != primary]
        return list(dict.fromkeys(chain)) or [primary]

    def _build_request_kwargs(
        self,
        *,
        model: str,
        instructions: Optional[str],
        user_prompt: str,
        tools: Optional[List[Any]],
        disabled: dict[str, set[str]],
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": instructions,
            "input": user_prompt,
            "max_output_tokens": self._config.max_tokens,
        }

        if model not in disabled["temperature"]:
            kwargs["temperature"] = self._config.temperature

        reasoning = self._build_reasoning(model)
        if reasoning and model not in disabled["reasoning"]:
            kwargs["reasoning"] = reasoning

        text_config = self._build_text_config(model, disabled)
        if text_config:
            kwargs["text"] = text_config

        request_tools = self._build_tool_list(tools)
        if request_tools and model not in disabled["tools"]:
            kwargs["tools"] = request_tools
            kwargs["tool_choice"] = self._config.extra.get("tool_choice", "auto")

        if (
            request_tools
            and self._has_web_search_tool(request_tools)
            and self._config.extra.get("include_web_search_sources", True)
        ):
            kwargs["include"] = ["web_search_call.action.sources"]

        return kwargs

    def _build_reasoning(self, model: str) -> dict[str, str] | None:
        level = str(self._config.extra.get("thinking_level", "HIGH")).strip().upper()
        effort = _OPENAI_REASONING_EFFORT.get(level, "high")
        if effort == "none" and not self._is_reasoning_model(model):
            return None
        if not self._is_reasoning_model(model):
            return None

        reasoning: dict[str, str] = {"effort": effort}
        summary = str(self._config.extra.get("reasoning_summary", "")).strip().lower()
        if summary in {"auto", "concise", "detailed"}:
            reasoning["summary"] = summary
        return reasoning

    def _build_text_config(
        self,
        model: str,
        disabled: dict[str, set[str]],
    ) -> dict[str, Any] | None:
        if not self._structured_json_enabled():
            return None

        schema = self._config.extra.get("json_schema") or ORACLE_REVIEW_RESPONSE_SCHEMA
        schema_name = str(self._config.extra.get("json_schema_name", "oracle_review_response"))

        if model not in disabled["json_schema"]:
            return {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": schema,
                    "strict": bool(self._config.extra.get("json_schema_strict", True)),
                }
            }

        if bool(self._config.extra.get("json_mode_fallback", True)):
            return {"format": {"type": "json_object"}}

        return None

    def _build_tool_list(self, explicit_tools: Optional[List[Any]]) -> List[Any]:
        tools: List[Any] = list(explicit_tools or self._config.extra.get("tools") or [])
        if not self._web_search_enabled():
            return tools

        web_tool: dict[str, Any] = {
            "type": self._config.extra.get("web_search_type", "web_search"),
            "search_context_size": self._config.extra.get("web_search_context_size", "low"),
        }

        if "web_search_external_access" in self._config.extra:
            web_tool["external_web_access"] = bool(self._config.extra["web_search_external_access"])

        allowed = self._config.extra.get("web_search_allowed_domains") or []
        blocked = self._config.extra.get("web_search_blocked_domains") or []
        filters: dict[str, Any] = {}
        if allowed:
            filters["allowed_domains"] = list(allowed)
        if blocked:
            filters["blocked_domains"] = list(blocked)
        if filters:
            web_tool["filters"] = filters

        user_location = self._config.extra.get("web_search_user_location")
        if isinstance(user_location, dict) and user_location:
            web_tool["user_location"] = {"type": "approximate", **user_location}

        tools.append(web_tool)
        return tools

    def _disable_feature_for_model(
        self,
        feature: str,
        model: str,
        disabled: dict[str, set[str]],
    ) -> bool:
        if feature == "json_object":
            return False
        if feature not in disabled:
            return False
        if model in disabled[feature]:
            return False
        disabled[feature].add(model)
        return True

    @staticmethod
    def _extract_text(response: Any) -> str:
        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str):
            return output_text

        chunks: list[str] = []
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                text = getattr(content, "text", None)
                if isinstance(text, str):
                    chunks.append(text)
        return "".join(chunks)

    @staticmethod
    def _is_candidate_model(model_id: str) -> bool:
        model = model_id.strip().lower()
        if not model:
            return False
        if any(part in model for part in _EXCLUDED_MODEL_PARTS):
            return False
        return model.startswith(("gpt-", "o1", "o3", "o4"))

    @staticmethod
    def _sort_models(discovered: list[tuple[str, int]]) -> list[str]:
        priority = {model: index for index, model in enumerate(_STATIC_FALLBACK_CHAIN)}

        def sort_key(item: tuple[str, int]) -> tuple[int, int, str]:
            model_id, created = item
            return (priority.get(model_id, len(priority)), -created, model_id)

        return [model_id for model_id, _ in sorted(discovered, key=sort_key)]

    @staticmethod
    def _apply_model_filters(
        models: list[str],
        *,
        allowlist: list[str],
        denylist: list[str],
    ) -> list[str]:
        filtered = list(models)
        if allowlist:
            filtered = [model for model in filtered if model in allowlist]
        if denylist:
            filtered = [
                model for model in filtered if not any(denied in model for denied in denylist)
            ]
        return filtered

    @staticmethod
    def _is_reasoning_model(model: str) -> bool:
        return model.lower().startswith(_REASONING_MODEL_PREFIXES)

    def _structured_json_enabled(self) -> bool:
        return bool(self._config.extra.get("structured_json", False))

    def _web_search_enabled(self) -> bool:
        return bool(
            self._config.extra.get("enable_web_search", False)
            or self._config.extra.get("enable_google_search", False)
        )

    @staticmethod
    def _has_web_search_tool(tools: list[Any]) -> bool:
        for tool in tools:
            if isinstance(tool, dict) and str(tool.get("type", "")).startswith("web_search"):
                return True
        return False
