"""GeminiIAProvider — concrete IAProvider backed by Google Gemini (google-genai).

Model discovery & rotation
---------------------------
On ``initialize()``, the provider queries the Gemini API for all models that
support ``generateContent``, applies the ``ORACLE_MODEL_ALLOWLIST`` /
``ORACLE_MODEL_DENYLIST`` / ``ORACLE_INCLUDE_ROBOTICS_MODELS`` filters, and
builds a sorted chain.  The primary model from ``ORACLE_MODEL`` is always
inserted at position 0.

On ``429 RESOURCE_EXHAUSTED`` the provider:
  1. Rotates ``_model_index`` to the next entry in the chain.
  2. If it completes a full cycle (back to index 0), sleeps 10 s.
  3. Otherwise sleeps 2 s between rotations.
  4. If ``MAX_RETRIES`` is exhausted across all models, re-raises.

``web_search`` / ``url_context`` are **disabled by default** (env
``ORACLE_ENABLE_URL_CONTEXT=false``, ``ORACLE_ENABLE_GOOGLE_SEARCH=false``).

Dependencies::

    pip install google-genai aiofiles

Environment variables (all optional unless noted):
    GEMINI_API_KEY                    – REQUIRED
    ORACLE_MODEL                      – primary model, default gemini-2.5-pro-preview-05-06
    ORACLE_CONCURRENCY                – semaphore slots, default 1
    ORACLE_MAX_RETRIES                – total rotation attempts, default 15
    ORACLE_TEMPERATURE                – default 0.2
    ORACLE_MAX_TOKENS                 – default 22000
    ORACLE_THINKING_LEVEL             – HIGH | MEDIUM | LOW | NONE, default HIGH
    ORACLE_ENABLE_URL_CONTEXT         – true|false, default false
    ORACLE_ENABLE_GOOGLE_SEARCH       – true|false, default false
    ORACLE_INCLUDE_ROBOTICS_MODELS    – true|false, default true
    ORACLE_MODEL_ALLOWLIST            – comma-separated; empty = allow all
    ORACLE_MODEL_DENYLIST             – comma-separated; empty = deny none
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, List, Optional

from forex_shared.worker_api.ia_provider import IAProvider, IAProviderConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fallback static chain — used when the API discovery call fails or returns 0
# ---------------------------------------------------------------------------

_STATIC_FALLBACK_CHAIN: List[str] = [
    "gemini-2.5-pro-preview-05-06",
    "gemini-2.5-flash-preview-04-17",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-1.5-pro",
]

# Expose for the factory default
GEMINI_MODEL_CHAIN: List[str] = _STATIC_FALLBACK_CHAIN

_QUOTA_KEYWORDS = frozenset({"resource_exhausted", "quota", "rate limit", "too many requests"})
_NOT_FOUND_KEYWORDS = frozenset({"not_found", "not found", "is not found"})
_THINKING_UNSUPPORTED = frozenset({"thinking level is not supported", "thinking is not supported"})
_FEATURE_UNSUPPORTED = frozenset({"media resolution is not enabled", "response schema is not supported"})
_ROTATE_CODES = frozenset({429, 503, 404})


def _is_thinking_error(exc: BaseException) -> bool:
    """True if the model doesn't support ThinkingConfig."""
    msg = str(exc).lower()
    return any(kw in msg for kw in _THINKING_UNSUPPORTED)


def _is_feature_error(exc: BaseException) -> bool:
    """True if the model lacks a GenerateContent feature (media_resolution etc.)."""
    msg = str(exc).lower()
    return any(kw in msg for kw in _FEATURE_UNSUPPORTED)

def _should_rotate_model(exc: BaseException) -> bool:
    """True if *exc* signals that we should try the next model in the chain.

    Rotates on:
    - 429 RESOURCE_EXHAUSTED (quota)
    - 503 (transient unavailability)
    - 404 NOT_FOUND (model not available for this API version)
    """
    msg = str(exc).lower()
    if any(kw in msg for kw in _QUOTA_KEYWORDS):
        return True
    if any(kw in msg for kw in _NOT_FOUND_KEYWORDS):
        return True
    if "429" in msg:
        return True
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    try:
        return int(code) in _ROTATE_CODES
    except (TypeError, ValueError):
        return False


# Keep legacy alias for any external references
_is_quota_error = _should_rotate_model


class GeminiIAProvider(IAProvider):
    """Google Gemini backend for ``IAProvider``.

    Key behaviours
    ~~~~~~~~~~~~~~
    * **Dynamic model discovery** — queries ``client.models.list()`` on startup
      and builds the rotation chain from live API data.
    * **Allowlist / denylist** — controlled via env vars, forwarded through
      ``IAProviderConfig.extra``.
    * **Automatic rotation** — on quota error, advances the model index and
      retries; full-cycle reset triggers a 10 s safety pause.
    * **Thinking config** — ``thinking_level`` maps to the Gemini
      ``ThinkingConfig``; default HIGH.
    * **Web search off** — ``url_context`` and ``googleSearch`` tools are
      disabled by default.
    """

    def __init__(self, config: IAProviderConfig) -> None:
        super().__init__(config)

        try:
            from google import genai  # type: ignore
            from google.genai import types  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "GeminiIAProvider requires 'google-genai'. "
                "Install it with: pip install google-genai"
            ) from exc

        self._genai = genai
        self._types = types

        self._client: Any = None
        self._gemini_config: Any = None
        self._semaphore: asyncio.Semaphore | None = None
        self._default_system_prompt: Optional[str] = None

        # Runtime state
        self._model_chain: List[str] = []
        self._model_index: int = 0
        self._max_retries: int = 15

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create the client, discover models from the API, build config."""
        concurrency = int(self._config.extra.get("concurrency", 1))
        self._semaphore = asyncio.Semaphore(concurrency)
        self._max_retries = int(self._config.extra.get("max_retries", 15))

        self._client = self._genai.Client(api_key=self._config.api_key)

        # Build the model chain from live API
        self._model_chain = await self._discover_model_chain()
        self._model_index = 0
        self._gemini_config = self._build_genai_config()

        logger.info(
            "[GeminiIAProvider] Initialized. primary=%s chain=%d concurrency=%d max_retries=%d "
            "url_context=%s google_search=%s thinking=%s",
            self._model_chain[0] if self._model_chain else "none",
            len(self._model_chain),
            concurrency,
            self._max_retries,
            self._config.extra.get("enable_url_context", False),
            self._config.extra.get("enable_google_search", False),
            self._config.extra.get("thinking_level", "HIGH"),
        )
        logger.debug("[GeminiIAProvider] Full model chain: %s", self._model_chain)

    async def close(self) -> None:
        logger.debug("[GeminiIAProvider] Closed.")

    # ------------------------------------------------------------------
    # Core generation — async native + model rotation
    # ------------------------------------------------------------------

    async def generate(
        self,
        user_prompt: str,
        system_prompt: Optional[str] = None,
        *,
        tools: Optional[List[Any]] = None,
    ) -> str:
        """Generate a response, rotating models on quota errors.

        Uses ``client.aio.models.generate_content`` (native async) — no
        ``asyncio.to_thread`` wrapper needed.
        """
        if self._client is None or self._semaphore is None:
            raise RuntimeError("GeminiIAProvider.initialize() must be called before generate().")

        config = self._build_genai_config(system_prompt) if system_prompt else self._gemini_config
        # Track per-model feature fallbacks
        _thinking_disabled_for: set = set()
        _media_res_disabled_for: set = set()

        async with self._semaphore:
            last_exc: Optional[BaseException] = None
            total = len(self._model_chain)

            for attempt in range(self._max_retries):
                # Rotate through the chain using attempt index modulo chain length
                index_atual = self._model_index % total
                modelo_atual = self._model_chain[index_atual]

                logger.debug(
                    "[GeminiIAProvider] attempt=%d/%d model=%s",
                    attempt + 1,
                    self._max_retries,
                    modelo_atual,
                )

                try:
                    response = await self._client.aio.models.generate_content(
                        model=modelo_atual,
                        contents=user_prompt,
                        config=config,
                    )

                    # Safety / blocklist check
                    if response.candidates:
                        finish = response.candidates[0].finish_reason
                        safety = self._types.FinishReason.SAFETY
                        blocklist = self._types.FinishReason.BLOCKLIST
                        if finish in (safety, blocklist):
                            logger.warning(
                                "[GeminiIAProvider] Blocked by safety policy. model=%s", modelo_atual
                            )
                            raise ValueError(f"Blocked by safety policy on model {modelo_atual}")

                    if attempt > 0 or self._model_index != 0:
                        logger.info(
                            "[GeminiIAProvider] ✅ Succeeded on model=%s (attempt=%d)",
                            modelo_atual,
                            attempt + 1,
                        )

                    # Cool-down after every successful call
                    await asyncio.sleep(1.0)
                    return response.text or ""

                except Exception as exc:
                    last_exc = exc

                    # ── thinking not supported → retry same model without thinking ──
                    if _is_thinking_error(exc) and modelo_atual not in _thinking_disabled_for:
                        _thinking_disabled_for.add(modelo_atual)
                        logger.warning(
                            "[GeminiIAProvider] ThinkingConfig not supported on model=%s → retrying without thinking.",
                            modelo_atual,
                        )
                        config = self._build_genai_config(
                            system_prompt,
                            force_no_thinking=True,
                            force_no_media_resolution=modelo_atual in _media_res_disabled_for,
                        )
                        continue  # same model, same attempt slot

                    # ── media_resolution not supported → retry same model without it ──
                    if _is_feature_error(exc) and modelo_atual not in _media_res_disabled_for:
                        _media_res_disabled_for.add(modelo_atual)
                        logger.warning(
                            "[GeminiIAProvider] media_resolution not supported on model=%s → retrying without it.",
                            modelo_atual,
                        )
                        config = self._build_genai_config(
                            system_prompt,
                            force_no_thinking=modelo_atual in _thinking_disabled_for,
                            force_no_media_resolution=True,
                        )
                        continue  # same model, same attempt slot

                    if _should_rotate_model(exc):
                        if attempt < self._max_retries - 1:
                            proximo_index = (index_atual + 1) % total
                            proximo_modelo = self._model_chain[proximo_index]
                            self._model_index = proximo_index

                            logger.warning(
                                "[GeminiIAProvider] ⚠️ Quota on model=%s → rotating to %s (attempt %d/%d)",
                                modelo_atual,
                                proximo_modelo,
                                attempt + 1,
                                self._max_retries,
                            )

                            if proximo_index == 0:
                                # Full cycle complete — safety pause
                                logger.warning(
                                    "[GeminiIAProvider] 🔄 Full cycle! Safety pause 10 s..."
                                )
                                await asyncio.sleep(10.0)
                            else:
                                await asyncio.sleep(2.0)

                            continue

                        logger.error(
                            "[GeminiIAProvider] ❌ All %d models exhausted after %d retries.",
                            total,
                            self._max_retries,
                        )
                        break

                    # Non-quota/non-404 error — re-raise immediately
                    logger.error(
                        "[GeminiIAProvider] Non-quota error on model=%s: %s",
                        modelo_atual,
                        exc,
                        exc_info=True,
                    )
                    raise

            raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------
    # System-prompt binding (called by OracleSession)
    # ------------------------------------------------------------------

    def set_default_system_prompt(self, prompt: str) -> None:
        """Rebuild the GenerateContentConfig with the given system prompt."""
        self._default_system_prompt = prompt
        self._gemini_config = self._build_genai_config()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def model_name(self) -> str:
        """Currently active model (may differ after rotation)."""
        if self._model_chain:
            return self._model_chain[self._model_index % len(self._model_chain)]
        return self._config.model_name

    @property
    def model_chain(self) -> List[str]:
        """Full ordered fallback chain."""
        return list(self._model_chain)

    # ------------------------------------------------------------------
    # Private — model discovery
    # ------------------------------------------------------------------

    async def _discover_model_chain(self) -> List[str]:
        """Query Gemini API for available models and apply filters.

        Falls back to ``_STATIC_FALLBACK_CHAIN`` on any error.
        """
        allowlist: List[str] = self._config.extra.get("model_allowlist") or []
        denylist: List[str] = self._config.extra.get("model_denylist") or []
        include_robotics: bool = self._config.extra.get("include_robotics_models", True)
        primary: str = self._config.model_name.strip()

        try:
            logger.info("[GeminiIAProvider] Querying available Gemini models...")
            response = self._client.models.list()
            valid: List[str] = []

            for model in response:
                supported = getattr(model, "supported_actions", []) or []
                name = getattr(model, "name", "")

                if "generateContent" not in supported:
                    continue
                if not name.startswith("models/gemini-"):
                    continue

                clean = name.replace("models/", "")

                if allowlist and clean not in allowlist:
                    continue
                if any(deny in clean for deny in denylist):
                    continue
                if not include_robotics and "robotics" in clean:
                    continue
                if "image" in clean:
                    continue
                # Exclude specialty models (TTS, video, embedding)
                if any(tag in clean for tag in ("-tts", "veo-", "-embed", "-aqa")):
                    continue

                valid.append(clean)

            valid = list(dict.fromkeys(valid))  # deduplicate, preserve API order
            logger.info("[GeminiIAProvider] Discovered %d models from API.", len(valid))

            if not valid:
                raise ValueError("No valid models returned by API.")

        except Exception as exc:
            logger.warning(
                "[GeminiIAProvider] Model discovery failed (%s). Using static fallback chain.", exc
            )
            valid = list(_STATIC_FALLBACK_CHAIN)

        # Primary model always first
        chain = [primary] + [m for m in valid if m != primary]
        return chain

    # ------------------------------------------------------------------
    # Private — config builders
    # ------------------------------------------------------------------

    def _build_genai_config(
        self,
        system_prompt: Optional[str] = None,
        *,
        force_no_thinking: bool = False,
        force_no_media_resolution: bool = False,
    ) -> Any:
        """Build ``GenerateContentConfig`` from current provider settings.

        Args:
            system_prompt: Optional system instruction override.
            force_no_thinking: If True, omit ThinkingConfig regardless of
                               ``thinking_level`` env var. Used when a model
                               returns 400 INVALID_ARGUMENT for thinking.
            force_no_media_resolution: If True, omit ``media_resolution``
                               field. Used when a model returns 400
                               INVALID_ARGUMENT for that feature.
        """
        tool_list = self._build_tool_list()
        sp = system_prompt or self._default_system_prompt

        thinking_cfg = None
        if not force_no_thinking:
            thinking_level = self._config.extra.get("thinking_level", "HIGH").upper()
            if thinking_level != "NONE":
                thinking_cfg = self._types.ThinkingConfig(thinking_level=thinking_level)

        system_parts = [self._types.Part.from_text(text=sp)] if sp else None

        return self._types.GenerateContentConfig(
            temperature=self._config.temperature,
            top_p=0.95,
            max_output_tokens=self._config.max_tokens,
            thinking_config=thinking_cfg,
            media_resolution=None if force_no_media_resolution else "MEDIA_RESOLUTION_MEDIUM",
            tools=tool_list or None,
            response_mime_type="application/json",
            system_instruction=system_parts,
        )

    def _build_tool_list(self) -> List[Any]:
        """Build the tools list based on enable_url_context / enable_google_search flags."""
        tools: List[Any] = []
        if self._config.extra.get("enable_url_context", False):
            tools.append(self._types.Tool(url_context=self._types.UrlContext()))
        if self._config.extra.get("enable_google_search", False):
            tools.append(self._types.Tool(googleSearch=self._types.GoogleSearch()))
        return tools
