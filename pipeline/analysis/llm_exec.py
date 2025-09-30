"""Moteur d'exécution d'analyses LLM (plug-able providers).

MVP: mock par défaut; OpenAI/OpenRouter/Ollama si clés présentes.
"""
from __future__ import annotations

import os
from typing import Any

from pipeline.llm.providers import mock_generate, ollama_generate, openai_generate, openrouter_generate


def choose_provider() -> str:
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("OPENROUTER_API_KEY"):
        return "openrouter"
    if os.getenv("OLLAMA_HOST"):
        return "ollama"
    return "mock"


def run_llm_analysis(prompt: str, *, model: str | None = None, temperature: float = 0.2, max_tokens: int = 256) -> str:
    provider = choose_provider()
    opts: dict[str, Any] = {"model": model, "temperature": temperature, "max_tokens": max_tokens}
    if provider == "openai":
        return openai_generate(prompt, opts)
    if provider == "openrouter":
        return openrouter_generate(prompt, opts)
    if provider == "ollama":
        return ollama_generate(prompt, opts)
    return mock_generate(prompt, opts)
