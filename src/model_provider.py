from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ProviderConfig:
    """Provider configuration shared by the agents.

    Required providers for this lab:
    - openai
    - custom (OpenAI-compatible base URL)
    - gemini
    - anthropic
    - ollama
    - openrouter
    """

    provider: str
    model_name: str
    temperature: float = 0.0
    api_key: str | None = None
    base_url: str | None = None


def normalize_provider(value: str) -> str:
    """Map provider names and common aliases to canonical provider names."""
    val = value.strip().lower()
    mapping = {
        "openai": "openai",
        "custom": "custom",
        "gemini": "gemini",
        "google": "gemini",
        "gemini-pro": "gemini",
        "anthropic": "anthropic",
        "anthorpic": "anthropic",
        "claude": "anthropic",
        "ollama": "ollama",
        "local": "ollama",
        "openrouter": "openrouter",
        "open-router": "openrouter",
    }
    return mapping.get(val, val)


def build_chat_model(config: ProviderConfig) -> Any:
    """Instantiate the chat model for the selected provider."""
    provider = normalize_provider(config.provider)

    if provider == "openai":
        try:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=config.model_name,
                temperature=config.temperature,
                api_key=config.api_key,
            )
        except ImportError:
            raise ImportError("Please install langchain-openai: pip install langchain-openai")

    elif provider == "custom":
        try:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=config.model_name,
                temperature=config.temperature,
                api_key=config.api_key or "EMPTY",
                base_url=config.base_url,
            )
        except ImportError:
            raise ImportError("Please install langchain-openai: pip install langchain-openai")

    elif provider == "gemini":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(
                model=config.model_name,
                temperature=config.temperature,
                google_api_key=config.api_key,
            )
        except ImportError:
            raise ImportError("Please install langchain-google-genai: pip install langchain-google-genai")

    elif provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(
                model_name=config.model_name,
                temperature=config.temperature,
                api_key=config.api_key,
            )
        except ImportError:
            raise ImportError("Please install langchain-anthropic: pip install langchain-anthropic")

    elif provider == "ollama":
        try:
            from langchain_ollama import ChatOllama
            return ChatOllama(
                model=config.model_name,
                temperature=config.temperature,
                base_url=config.base_url or "http://localhost:11434",
            )
        except ImportError:
            raise ImportError("Please install langchain-ollama: pip install langchain-ollama")

    elif provider == "openrouter":
        try:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=config.model_name,
                temperature=config.temperature,
                api_key=config.api_key,
                base_url=config.base_url or "https://openrouter.ai/api/v1",
            )
        except ImportError:
            raise ImportError("Please install langchain-openai: pip install langchain-openai")

    else:
        raise ValueError(f"Unsupported provider: {config.provider}")
