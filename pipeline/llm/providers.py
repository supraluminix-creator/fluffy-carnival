from __future__ import annotations

import os
from typing import Any, cast

import httpx

# Importer le module pour que le monkeypatch tests sur "pipeline.http.post_json"
# prenne effet, plutôt qu'une référence figée importée par symbole.
from .. import http as http
from ..flags import is_llm_post_facade_enabled


def mock_generate(prompt: str, opts: dict[str, Any]) -> str:
    model = opts.get("model") or "mock"
    # réponse déterministe et courte pour tests
    return f"[MOCK:{model}] " + (prompt if len(prompt) <= 200 else prompt[:200] + "…")


def _extract_chat_completion_content(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise KeyError("choices missing")
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise KeyError("invalid choice payload")
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise KeyError("message missing")
    content = message.get("content")
    if not isinstance(content, str):
        raise KeyError("content missing")
    return content.strip()


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
    if is_llm_post_facade_enabled():
        data = cast(dict[str, Any], http.post_json(url, headers=headers, json=payload, timeout=30.0))
    else:
        with httpx.Client(timeout=30.0) as client:
            r = client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = cast(dict[str, Any], r.json())
    try:
        return _extract_chat_completion_content(data)
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
    if is_llm_post_facade_enabled():
        data = cast(dict[str, Any], http.post_json(url, headers=headers, json=payload, timeout=30.0))
    else:
        with httpx.Client(timeout=30.0) as client:
            r = client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = cast(dict[str, Any], r.json())
    try:
        return _extract_chat_completion_content(data)
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
    if is_llm_post_facade_enabled():
        data = cast(dict[str, Any], http.post_json(url, json=payload, timeout=60.0))
    else:
        with httpx.Client(timeout=60.0) as client:
            r = client.post(url, json=payload)
            r.raise_for_status()
            data = cast(dict[str, Any], r.json())
    try:
        response = data.get("response")
        if isinstance(response, str):
            return response.strip()
        output = data.get("output")
        if isinstance(output, str):
            return output.strip()
        raise KeyError("response")
    except Exception as e:  # pragma: no cover
        raise RuntimeError(f"Réponse Ollama invalide: {e}") from e


def anthropic_generate(prompt: str, opts: dict[str, Any]) -> str:
    """Génération Claude (Anthropic Messages API v1).

    Variables d'env:
      - ANTHROPIC_API_KEY (obligatoire)
      - ANTHROPIC_MODEL (optionnel, défaut: claude-3-haiku-20240307)
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    model = opts.get("model") or os.getenv("ANTHROPIC_MODEL", "claude-3-haiku-20240307")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY manquant")
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": int(opts.get("max_tokens", 512)),
        "temperature": float(opts.get("temperature", 0.2)),
        # Messages API v1 attend un tableau de blocs {type:"text", text:"..."}
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}],
            }
        ],
    }
    if is_llm_post_facade_enabled():
        data = cast(dict[str, Any], http.post_json(url, headers=headers, json=payload, timeout=30.0))
    else:
        with httpx.Client(timeout=30.0) as client:
            r = client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = cast(dict[str, Any], r.json())
    try:
        parts = data.get("content")
        if not isinstance(parts, list):
            raise KeyError("content missing")
        text_parts: list[str] = []
        for part in parts:
            if isinstance(part, dict):
                text_val = part.get("text")
                if isinstance(text_val, str):
                    text_parts.append(text_val)
        if not text_parts:
            raise KeyError("no text content")
        return "".join(text_parts).strip()
    except Exception as e:  # pragma: no cover
        raise RuntimeError(f"Réponse Anthropic invalide: {e}") from e


def gemini_generate(prompt: str, opts: dict[str, Any]) -> str:
    """Génération Gemini (Google Generative Language API).

    Variables d'env:
      - GOOGLE_API_KEY ou GEMINI_API_KEY (obligatoire)
      - GEMINI_MODEL (optionnel, défaut: gemini-1.5-flash)
    """
    api_key = (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
    model = opts.get("model") or os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY/GEMINI_API_KEY manquant")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ]
    }
    if is_llm_post_facade_enabled():
        data = cast(dict[str, Any], http.post_json(url, json=payload, timeout=30.0))
    else:
        with httpx.Client(timeout=30.0) as client:
            r = client.post(url, json=payload)
            r.raise_for_status()
            data = cast(dict[str, Any], r.json())
    try:
        cands = data.get("candidates")
        if not isinstance(cands, list) or not cands:
            raise KeyError("no candidates")
        first = cands[0]
        if not isinstance(first, dict):
            raise KeyError("invalid candidate payload")
        content = first.get("content")
        if not isinstance(content, dict):
            raise KeyError("invalid content payload")
        parts = content.get("parts")
        if not isinstance(parts, list):
            raise KeyError("parts missing")
        text_parts: list[str] = []
        for part in parts:
            if isinstance(part, dict):
                text_val = part.get("text")
                if isinstance(text_val, str):
                    text_parts.append(text_val)
        if not text_parts:
            raise KeyError("no text parts")
        return "".join(text_parts).strip()
    except Exception as e:  # pragma: no cover
        raise RuntimeError(f"Réponse Gemini invalide: {e}") from e


def deepseek_generate(prompt: str, opts: dict[str, Any]) -> str:
    """Génération Deepseek (API style OpenAI).

    Variables d'env:
      - DEEPSEEK_API_KEY (obligatoire)
      - DEEPSEEK_MODEL (optionnel, défaut: deepseek-chat)
    """
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    model = opts.get("model") or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY manquant")
    url = "https://api.deepseek.com/chat/completions"
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
    if is_llm_post_facade_enabled():
        data = cast(dict[str, Any], http.post_json(url, headers=headers, json=payload, timeout=30.0))
    else:
        with httpx.Client(timeout=30.0) as client:
            r = client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = cast(dict[str, Any], r.json())
    try:
        return _extract_chat_completion_content(data)
    except Exception as e:  # pragma: no cover
        raise RuntimeError(f"Réponse Deepseek invalide: {e}") from e
