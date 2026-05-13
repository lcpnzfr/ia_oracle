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
        # Priority: explicit extra['host'] > OracleConfig.OLLAMA_HOST > fallback
        self._host = self._config.extra.get("host") or OracleConfig.OLLAMA_HOST or "http://localhost:11434"

    async def initialize(self) -> None:
        """Initialize the Ollama client."""
        logger.info("[OllamaProvider] Initializing client at %s", self._host)
        self._client = Client(host=self._host)
        # Check if model is available? Ollama usually pulls on demand or fails.
        logger.info("[OllamaProvider] Initialized. model=%s", self._config.model_name)

    async def generate(
        self,
        user_prompt: str,
        system_prompt: Optional[str] = None,
        *,
        tools: Optional[List[Any]] = None,
    ) -> str:
        """Call Ollama chat API."""
        if self._client is None:
            raise RuntimeError("OllamaProvider.initialize() must be called before generate().")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": user_prompt})

        try:
            # ollama.Client.chat is synchronous, but we can run it in a thread or 
            # if the library supports async we should use it. 
            # The official 'ollama' library has an AsyncClient.
            from ollama import AsyncClient
            
            async_client = AsyncClient(host=self._host)
            response = await async_client.chat(
                model=self._config.model_name,
                messages=messages,
                options={
                    "temperature": self._config.temperature,
                    "num_predict": self._config.max_tokens,
                }
            )
            return response["message"]["content"]
        except Exception as e:
            logger.error("[OllamaProvider] Error during generate: %s", e)
            raise RuntimeError(f"Ollama generation failed: {e}") from e

    async def close(self) -> None:
        """Clean up resources."""
        self._client = None
        logger.debug("[OllamaProvider] Closed.")
