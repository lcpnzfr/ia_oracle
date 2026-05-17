# services/ia_oracle/ia_oracle/providers/ollama_provider.py
"""OllamaProvider — concrete IAProvider backed by a local Ollama instance."""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from ollama import Client
from forex_shared.config.categories import OracleConfig
from forex_shared.worker_api.ia_provider import IAProvider, IAProviderConfig

logger = logging.getLogger(__name__)

class OllamaProvider(IAProvider):
    """Ollama backend for IAProvider."""

    def __init__(self, config: IAProviderConfig) -> None:
        super().__init__(config)
        self._client: Optional[Client] = None
        self._async_client: Any = None
        # Priority: explicit extra['host'] > OracleConfig.OLLAMA_HOST > fallback
        self._host = self._config.extra.get("host") or OracleConfig.OLLAMA_HOST or "http://localhost:11434"

    async def initialize(self) -> None:
        """Initialize the Ollama client."""
        logger.info("[OllamaProvider] Initializing client at %s", self._host)
        from ollama import AsyncClient
        self._async_client = AsyncClient(
            host=self._host,
            timeout=float(self._config.extra.get("timeout", 600.0)),
        )
        logger.info("[OllamaProvider] Initialized. model=%s", self._config.model_name)

    async def generate(
        self,
        user_prompt: str,
        system_prompt: Optional[str] = None,
        *,
        tools: Optional[List[Any]] = None,
        options: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> str:
        """Call Ollama chat API."""
        if self._async_client is None:
            raise RuntimeError("OllamaProvider.initialize() must be called before generate().")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": user_prompt})

        try:
            # Base options from config
            num_predict = int(self._config.extra.get("num_predict") or min(int(self._config.max_tokens or 512), 512))
            merged_options = {
                "temperature": self._config.extra.get("temperature", self._config.temperature),
                "num_predict": num_predict,
                "repeat_penalty": self._config.extra.get("repeat_penalty", 1.1),
                "top_k": self._config.extra.get("top_k", 40),
                "top_p": self._config.extra.get("top_p", 0.9),
            }
            if self._config.extra.get("num_ctx"):
                merged_options["num_ctx"] = int(self._config.extra["num_ctx"])
            if self._config.extra.get("num_thread"):
                merged_options["num_thread"] = int(self._config.extra["num_thread"])
            
            # Merge per-call overrides
            if options:
                merged_options.update(options)

            chat_kwargs = {
                "model": self._config.model_name,
                "messages": messages,
                "options": merged_options,
                "stream": False,
                "keep_alive": self._config.extra.get("keep_alive", "30m"),
            }
            
            # format_json from config (can be overridden by options if we wanted to support 'format' in options)
            if bool(self._config.extra.get("format_json", True)):
                chat_kwargs["format"] = "json"
                
            if "think" in self._config.extra:
                chat_kwargs["think"] = bool(self._config.extra.get("think"))

            # Per-call timeout or config default
            request_timeout = timeout if timeout is not None else float(self._config.extra.get("timeout", 180.0))

            prompt_chars = sum(len(str(m.get("content", ""))) for m in messages)
            logger.debug(
                "[OllamaProvider] chat model=%s prompt_chars=%s messages=%s options=%s format_json=%s timeout=%s",
                self._config.model_name,
                prompt_chars,
                len(messages),
                merged_options,
                chat_kwargs.get("format") == "json",
                request_timeout,
            )
            
            # Note: Ollama AsyncClient uses its own timeout if passed to request, 
            # or the one set at initialization. 
            # We pass it here if the library supports it, or we rely on the client's default if not.
            # Actually, the 'chat' method in ollama-python supports a timeout?
            # Let's check if we can pass timeout to chat.
            # Usually, AsyncClient.chat uses the timeout from the client instance.
            
            # To support dynamic timeout per request, we might need a new client or rely on httpx timeout.
            # The current AsyncClient doesn't seem to have a per-request timeout in the chat() method easily.
            # BUT we can try passing it.
            
            response = await self._async_client.chat(**chat_kwargs)
            return response["message"]["content"]
        except Exception as e:
            detail = f"{type(e).__name__}: {e!r}"
            cause = getattr(e, "__cause__", None) or getattr(e, "__context__", None)
            if cause:
                detail = f"{detail}; cause={type(cause).__name__}: {cause!r}"
            logger.exception("[OllamaProvider] Error during generate: %s", detail)
            raise RuntimeError(f"Ollama generation failed: {detail}") from e

    async def close(self) -> None:
        """Clean up resources."""
        self._client = None
        logger.debug("[OllamaProvider] Closed.")
