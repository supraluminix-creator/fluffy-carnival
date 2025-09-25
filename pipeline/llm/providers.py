from __future__ import annotations

import os
from typing import Any

import httpx


def mock_generate(prompt: str, opts: dict[str, Any]) -> str:
    model = opts.get("model") or "mock"
    # réponse déterministe et courte pour tests
    return f"[MOCK:{model}] " + (prompt if len(prompt) <= 200 else prompt[:200] + "…")


def openai_generate(prompt: str, opts: dict[str, Any]) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = opts.get("model") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY manquant")
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": float(opts.get("temperature", 0.2)),
        "max_tokens": int(opts.get("max_tokens", 256)),
    }
    with httpx.Client(timeout=30.0) as client:
        r = client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
        try:
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:  # pragma: no cover - structure inattendue
            raise RuntimeError(f"Réponse OpenAI invalide: {e}") from e


def openrouter_generate(prompt: str, opts: dict[str, Any]) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    model = opts.get("model") or os.getenv("OPENROUTER_MODEL", "openrouter/auto")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY manquant")
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": float(opts.get("temperature", 0.2)),
        "max_tokens": int(opts.get("max_tokens", 256)),
    }
    with httpx.Client(timeout=30.0) as client:
        r = client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
        try:
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:  # pragma: no cover
            raise RuntimeError(f"Réponse OpenRouter invalide: {e}") from e


def ollama_generate(prompt: str, opts: dict[str, Any]) -> str:
    # autorisé par le test http car localhost/127.0.0.1
    host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    model = opts.get("model") or os.getenv("OLLAMA_MODEL", "llama3.1")
    url = f"{host.rstrip('/')}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": float(opts.get("temperature", 0.2))},
    }
    with httpx.Client(timeout=60.0) as client:
        r = client.post(url, json=payload)
        r.raise_for_status()
        data = r.json()
        try:
            return (data.get("response") or data.get("output") or "").strip()
        except Exception as e:  # pragma: no cover
            raise RuntimeError(f"Réponse Ollama invalide: {e}") from e
