# services/ia_oracle/ia_oracle/providers/__init__.py
"""Provider package exports with lazy loading for optional provider dependencies."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "OllamaProvider",
    "GeminiIAProvider",
    "OpenAIIAProvider",
    "IAServiceOpenAI",
    "IAServiceOpenAIConfigurationError",
    "IAServiceOpenAIError",
    "IAServiceOpenAIRequestError",
    "IAServiceOpenAIResult",
    "OpenAIResponseOptions",
    "OpenAIServiceConfig",
    "OpenAIWebSearchConfig",
]

_EXPORTS = {
    "OllamaProvider": (".ollama_provider", "OllamaProvider"),
    "GeminiIAProvider": (".gemini_provider", "GeminiIAProvider"),
    "OpenAIIAProvider": (".openai_provider", "OpenAIIAProvider"),
    "IAServiceOpenAI": (".ia_service_openai", "IAServiceOpenAI"),
    "IAServiceOpenAIConfigurationError": (
        ".ia_service_openai",
        "IAServiceOpenAIConfigurationError",
    ),
    "IAServiceOpenAIError": (".ia_service_openai", "IAServiceOpenAIError"),
    "IAServiceOpenAIRequestError": (
        ".ia_service_openai",
        "IAServiceOpenAIRequestError",
    ),
    "IAServiceOpenAIResult": (".ia_service_openai", "IAServiceOpenAIResult"),
    "OpenAIResponseOptions": (".ia_service_openai", "OpenAIResponseOptions"),
    "OpenAIServiceConfig": (".ia_service_openai", "OpenAIServiceConfig"),
    "OpenAIWebSearchConfig": (".ia_service_openai", "OpenAIWebSearchConfig"),
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    value = getattr(import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value
