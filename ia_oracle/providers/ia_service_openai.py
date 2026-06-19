"""Reusable async OpenAI service built on the Responses API.

``IAServiceOpenAI`` is intentionally independent from the pipeline-specific
``IAProvider`` interface so FastAPI apps, workers, and scripts can share one
production-oriented OpenAI client wrapper. It avoids the deprecated Assistants
API and exposes the major Responses API controls: model selection/fallbacks,
reasoning, text/JSON output formatting, hosted tools such as web search,
streaming, metadata, and retry/backoff behavior.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

logger = logging.getLogger(__name__)

ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh"]
ReasoningSummary = Literal["auto", "concise", "detailed"]
ToolChoice = Literal["auto", "none", "required"]
OutputVerbosity = Literal["low", "medium", "high"]

DEFAULT_OPENAI_MODEL = "gpt-5.5"
DEFAULT_FALLBACK_MODELS: tuple[str, ...] = (
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5-mini",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4o",
    "gpt-4o-mini",
)

_RETRYABLE_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504})
_UNSUPPORTED_FEATURE_MARKERS = (
    "unsupported",
    "not supported",
    "unrecognized",
    "unknown parameter",
    "invalid parameter",
    "invalid_request_error",
)
_REASONING_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")


class IAServiceOpenAIError(RuntimeError):
    """Base exception raised by ``IAServiceOpenAI``."""


class IAServiceOpenAIConfigurationError(IAServiceOpenAIError):
    """Raised when the service is misconfigured or used before startup."""


class IAServiceOpenAIRequestError(IAServiceOpenAIError):
    """Raised after OpenAI request retries/fallbacks are exhausted."""

    def __init__(
        self, message: str, *, attempts: int, last_error: BaseException | None
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.last_error = last_error


@dataclass(frozen=True, slots=True)
class OpenAIWebSearchConfig:
    """Configuration for OpenAI hosted web search tools."""

    enabled: bool = False
    search_context_size: Literal["low", "medium", "high"] = "low"
    allowed_domains: Sequence[str] = field(default_factory=tuple)
    blocked_domains: Sequence[str] = field(default_factory=tuple)
    user_location: Mapping[str, Any] | None = None
    include_sources: bool = True
    tool_type: str = "web_search"


@dataclass(frozen=True, slots=True)
class OpenAIResponseOptions:
    """Per-call knobs for Responses API generation behavior."""

    model: str | None = None
    fallback_models: Sequence[str] | None = None
    instructions: str | None = None
    max_output_tokens: int = 4096
    temperature: float | None = 0.2
    top_p: float | None = None
    reasoning_enabled: bool = True
    reasoning_effort: ReasoningEffort = "medium"
    reasoning_summary: ReasoningSummary | None = None
    tools: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    tool_choice: ToolChoice | Mapping[str, Any] | None = "auto"
    web_search: OpenAIWebSearchConfig = field(default_factory=OpenAIWebSearchConfig)
    json_schema: Mapping[str, Any] | None = None
    json_schema_name: str = "response_schema"
    json_schema_strict: bool = True
    json_mode: bool = False
    metadata: Mapping[str, str] | None = None
    store: bool | None = None
    previous_response_id: str | None = None
    parallel_tool_calls: bool | None = None
    truncation: Literal["auto", "disabled"] | None = None
    text_verbosity: OutputVerbosity | None = None
    extra_body: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OpenAIServiceConfig:
    """Service-wide OpenAI client and resilience settings."""

    api_key: str | None = None
    organization: str | None = None
    project: str | None = None
    base_url: str | None = None
    timeout_seconds: float = 120.0
    max_retries: int = 3
    retry_base_delay_seconds: float = 0.75
    retry_max_delay_seconds: float = 10.0
    concurrency: int = 8
    default_options: OpenAIResponseOptions = field(
        default_factory=OpenAIResponseOptions
    )


@dataclass(frozen=True, slots=True)
class IAServiceOpenAIResult:
    """Normalized result returned by ``generate``."""

    text: str
    response: Any
    model: str
    attempts: int
    response_id: str | None = None
    usage: Any = None


class IAServiceOpenAI:
    """Enterprise-oriented async OpenAI Responses API service.

    Use one instance per process/app lifespan. In FastAPI, create it during
    startup, inject it through dependencies, and call ``await close()`` during
    shutdown. Per-request behavior can be overridden with
    ``OpenAIResponseOptions`` or direct keyword arguments to ``generate``.
    """

    def __init__(
        self, config: OpenAIServiceConfig | None = None, **client_overrides: Any
    ) -> None:
        self._config = config or OpenAIServiceConfig()
        client_kwargs: dict[str, Any] = {
            "api_key": self._config.api_key,
            "organization": self._config.organization,
            "project": self._config.project,
            "timeout": self._config.timeout_seconds,
            **client_overrides,
        }
        if self._config.base_url:
            client_kwargs["base_url"] = self._config.base_url.rstrip("/")
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            **{k: v for k, v in client_kwargs.items() if v is not None}
        )
        self._semaphore = asyncio.Semaphore(max(1, self._config.concurrency))
        self._closed = False

    async def __aenter__(self) -> "IAServiceOpenAI":
        self._ensure_open()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP resources."""

        if not self._closed:
            await self._client.close()
            self._closed = True

    async def generate(
        self,
        input: str | Sequence[Mapping[str, Any]],
        *,
        options: OpenAIResponseOptions | None = None,
        model: str | None = None,
        instructions: str | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        enable_web_search: bool | None = None,
        reasoning_enabled: bool | None = None,
        reasoning_effort: ReasoningEffort | None = None,
        json_schema: Mapping[str, Any] | None = None,
        json_mode: bool | None = None,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        **request_overrides: Any,
    ) -> IAServiceOpenAIResult:
        """Create a non-streaming response with retries and model fallback."""

        self._ensure_open()
        call_options = self._merge_options(
            options,
            model=model,
            instructions=instructions,
            tools=tools,
            enable_web_search=enable_web_search,
            reasoning_enabled=reasoning_enabled,
            reasoning_effort=reasoning_effort,
            json_schema=json_schema,
            json_mode=json_mode,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
        )
        attempts = 0
        last_error: BaseException | None = None
        disabled: dict[str, set[str]] = {
            "reasoning": set(),
            "tools": set(),
            "json_schema": set(),
            "temperature": set(),
        }

        async with self._semaphore:
            for model_name in self._model_chain(call_options):
                while True:
                    attempts += 1
                    try:
                        kwargs = self._build_request_kwargs(
                            input, call_options, model_name, disabled
                        )
                        kwargs.update(request_overrides)
                        response = await self._client.responses.create(**kwargs)
                        return IAServiceOpenAIResult(
                            text=self.extract_text(response),
                            response=response,
                            model=model_name,
                            attempts=attempts,
                            response_id=getattr(response, "id", None),
                            usage=getattr(response, "usage", None),
                        )
                    except (
                        Exception
                    ) as exc:  # OpenAI SDK raises typed exceptions with status_code when available.
                        last_error = exc
                        feature = self._unsupported_feature(exc)
                        if feature and self._disable_feature(
                            feature, model_name, disabled
                        ):
                            logger.warning(
                                "OpenAI model %s rejected %s; retrying without it.",
                                model_name,
                                feature,
                            )
                            continue
                        if (
                            attempts > self._config.max_retries
                            or not self._is_retryable(exc)
                        ):
                            logger.warning(
                                "OpenAI model %s failed after attempt %d: %s",
                                model_name,
                                attempts,
                                exc,
                            )
                            break
                        await asyncio.sleep(self._retry_delay(attempts))

        raise IAServiceOpenAIRequestError(
            "OpenAI request failed after retries and model fallbacks were exhausted.",
            attempts=attempts,
            last_error=last_error,
        )

    async def stream(
        self,
        input: str | Sequence[Mapping[str, Any]],
        *,
        options: OpenAIResponseOptions | None = None,
        **request_overrides: Any,
    ) -> AsyncIterator[Any]:
        """Yield raw Responses API streaming events.

        Consumers can translate events to Server-Sent Events in FastAPI without
        this service depending on a web framework.
        """

        self._ensure_open()
        call_options = options or self._config.default_options
        model_name = next(iter(self._model_chain(call_options)))
        disabled: dict[str, set[str]] = {
            "reasoning": set(),
            "tools": set(),
            "json_schema": set(),
            "temperature": set(),
        }
        kwargs = self._build_request_kwargs(input, call_options, model_name, disabled)
        kwargs.update(request_overrides)
        kwargs["stream"] = True
        async with self._semaphore:
            stream = await self._client.responses.create(**kwargs)
            async for event in stream:
                yield event

    @staticmethod
    def extract_text(response: Any) -> str:
        """Best-effort text extraction across OpenAI SDK response shapes."""

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

    def _ensure_open(self) -> None:
        if self._closed:
            raise IAServiceOpenAIConfigurationError("IAServiceOpenAI is closed.")

    def _merge_options(
        self, options: OpenAIResponseOptions | None, **overrides: Any
    ) -> OpenAIResponseOptions:
        merged = options or self._config.default_options
        changes: dict[str, Any] = {
            k: v
            for k, v in overrides.items()
            if v is not None and k != "enable_web_search"
        }
        if overrides.get("tools") is not None:
            changes["tools"] = tuple(overrides["tools"])
        if overrides.get("enable_web_search") is not None:
            changes["web_search"] = replace(
                merged.web_search, enabled=bool(overrides["enable_web_search"])
            )
        return replace(merged, **changes) if changes else merged

    def _model_chain(self, options: OpenAIResponseOptions) -> tuple[str, ...]:
        primary = options.model or DEFAULT_OPENAI_MODEL
        fallbacks = tuple(options.fallback_models or DEFAULT_FALLBACK_MODELS)
        return tuple(dict.fromkeys((primary, *fallbacks)))

    def _build_request_kwargs(
        self,
        input: str | Sequence[Mapping[str, Any]],
        options: OpenAIResponseOptions,
        model: str,
        disabled: dict[str, set[str]],
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "input": input,
            "max_output_tokens": options.max_output_tokens,
        }
        if options.instructions:
            kwargs["instructions"] = options.instructions
        if options.temperature is not None and model not in disabled["temperature"]:
            kwargs["temperature"] = options.temperature
        if options.top_p is not None:
            kwargs["top_p"] = options.top_p
        if (
            options.reasoning_enabled
            and self._supports_reasoning(model)
            and model not in disabled["reasoning"]
        ):
            reasoning: dict[str, str] = {"effort": options.reasoning_effort}
            if options.reasoning_summary:
                reasoning["summary"] = options.reasoning_summary
            kwargs["reasoning"] = reasoning
        text = self._text_config(options, model, disabled)
        if text:
            kwargs["text"] = text
        request_tools = self._tools(options)
        if request_tools and model not in disabled["tools"]:
            kwargs["tools"] = request_tools
            if options.tool_choice is not None:
                kwargs["tool_choice"] = options.tool_choice
            if options.parallel_tool_calls is not None:
                kwargs["parallel_tool_calls"] = options.parallel_tool_calls
        if self._has_web_search(request_tools) and options.web_search.include_sources:
            kwargs["include"] = ["web_search_call.action.sources"]
        for key in ("metadata", "store", "previous_response_id", "truncation"):
            value = getattr(options, key)
            if value is not None:
                kwargs[key] = value
        kwargs.update(dict(options.extra_body))
        return kwargs

    def _text_config(
        self, options: OpenAIResponseOptions, model: str, disabled: dict[str, set[str]]
    ) -> dict[str, Any] | None:
        text: dict[str, Any] = {}
        if options.text_verbosity:
            text["verbosity"] = options.text_verbosity
        if options.json_schema and model not in disabled["json_schema"]:
            text["format"] = {
                "type": "json_schema",
                "name": options.json_schema_name,
                "schema": dict(options.json_schema),
                "strict": options.json_schema_strict,
            }
        elif options.json_mode:
            text["format"] = {"type": "json_object"}
        return text or None

    def _tools(self, options: OpenAIResponseOptions) -> list[dict[str, Any]]:
        tools = [dict(tool) for tool in options.tools]
        if options.web_search.enabled:
            web_tool: dict[str, Any] = {
                "type": options.web_search.tool_type,
                "search_context_size": options.web_search.search_context_size,
            }
            filters: dict[str, Any] = {}
            if options.web_search.allowed_domains:
                filters["allowed_domains"] = list(options.web_search.allowed_domains)
            if options.web_search.blocked_domains:
                filters["blocked_domains"] = list(options.web_search.blocked_domains)
            if filters:
                web_tool["filters"] = filters
            if options.web_search.user_location:
                web_tool["user_location"] = {
                    "type": "approximate",
                    **dict(options.web_search.user_location),
                }
            tools.append(web_tool)
        return tools

    @staticmethod
    def _supports_reasoning(model: str) -> bool:
        return model.lower().startswith(_REASONING_MODEL_PREFIXES)

    @staticmethod
    def _has_web_search(tools: Sequence[Mapping[str, Any]]) -> bool:
        return any(str(tool.get("type", "")).startswith("web_search") for tool in tools)

    @staticmethod
    def _is_retryable(exc: BaseException) -> bool:
        status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
        try:
            return int(status_code) in _RETRYABLE_STATUS_CODES
        except (TypeError, ValueError):
            message = str(exc).lower()
            return any(
                token in message
                for token in ("timeout", "rate limit", "temporarily", "overloaded")
            )

    @staticmethod
    def _unsupported_feature(exc: BaseException) -> str | None:
        message = str(exc).lower()
        if not any(marker in message for marker in _UNSUPPORTED_FEATURE_MARKERS):
            return None
        if "reasoning" in message:
            return "reasoning"
        if "tool" in message or "web_search" in message:
            return "tools"
        if (
            "json_schema" in message
            or "text.format" in message
            or "response_format" in message
        ):
            return "json_schema"
        if "temperature" in message:
            return "temperature"
        return None

    @staticmethod
    def _disable_feature(
        feature: str, model: str, disabled: dict[str, set[str]]
    ) -> bool:
        if feature not in disabled or model in disabled[feature]:
            return False
        disabled[feature].add(model)
        return True

    def _retry_delay(self, attempt: int) -> float:
        cap = min(
            self._config.retry_max_delay_seconds,
            self._config.retry_base_delay_seconds * (2 ** max(0, attempt - 1)),
        )
        return cap * (0.75 + random.random() * 0.5)
