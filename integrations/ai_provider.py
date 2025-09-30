"""AI providers: common interface and concrete adapters with fallback logic.

Design goals
- Minimal, safe defaults (no network if keys missing)
- Clear interface for prompt generation calls
- Fallback chain: local (Ollama) -> primary -> aggregator -> last resort

Environment variables
- OLLAMA_HOST (default http://127.0.0.1:11434)
- OPENROUTER_API_KEY
- OPENROUTER_MODEL (optional)
- HUGGINGFACE_API_KEY
- HUGGINGFACE_MODEL (optional)
- AI_PRIMARY (optional: openrouter|huggingface)

Notes: POE public API is not officially documented; adapter is a stub with NotImplementedError.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, TypedDict, Optional
import os
import asyncio
import json

import httpx
import structlog

logger = structlog.get_logger(__name__)


class AIResult(TypedDict, total=False):
    provider: str
    model: str | None
    content: str
    usage_tokens: int | None
    meta: dict[str, Any]


class AIProvider(Protocol):
    async def generate(
        self,
        prompt: str,
        model_hint: Optional[str] = None,
        max_tokens: int = 800,
        metadata: Optional[dict[str, Any]] = None,
    ) -> AIResult:  # pragma: no cover - interface only
        ...

    async def status(self) -> dict[str, Any]:  # pragma: no cover - interface only
        ...


@dataclass
class OllamaProvider:
    host: str = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    model: str = os.getenv("OLLAMA_MODEL", "llama3.1")

    async def generate(self, prompt: str, model_hint: str | None = None, max_tokens: int = 800, metadata: dict[str, Any] | None = None) -> AIResult:
        url = f"{self.host.rstrip('/')}/api/generate"
        model = model_hint or self.model
        payload = {"model": model, "prompt": prompt, "options": {"num_predict": max_tokens}}
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(url, json=payload)
                r.raise_for_status()
                # Ollama streams by default; endpoint /generate returns JSON lines; handle both
                text = r.text
                content = ""
                for line in text.splitlines():
                    try:
                        obj = json.loads(line)
                        content += obj.get("response", "")
                    except Exception:
                        content = text
                        break
                return AIResult(provider="ollama", model=model, content=content, usage_tokens=None, meta={"endpoint": url})
        except Exception as e:
            logger.warning("ollama_generate_failed", error=str(e))
            raise

    async def status(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{self.host.rstrip('/')}/api/tags")
                ok = r.status_code == 200
                return {"ok": ok, "host": self.host}
        except Exception as e:  # pragma: no cover - depends on local env
            return {"ok": False, "host": self.host, "error": str(e)}


@dataclass
class OpenRouterProvider:
    api_key: str | None = os.getenv("OPENROUTER_API_KEY")
    model: str | None = os.getenv("OPENROUTER_MODEL")

    async def generate(self, prompt: str, model_hint: str | None = None, max_tokens: int = 800, metadata: dict[str, Any] | None = None) -> AIResult:
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY missing")
        url = "https://openrouter.ai/api/v1/chat/completions"
        model = model_hint or self.model or "openrouter/auto"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = data.get("usage", {}).get("total_tokens")
            return AIResult(provider="openrouter", model=model, content=content, usage_tokens=usage, meta={})

    async def status(self) -> dict[str, Any]:
        return {"ok": bool(self.api_key)}


@dataclass
class HuggingFaceProvider:
    api_key: str | None = os.getenv("HUGGINGFACE_API_KEY")
    model: str | None = os.getenv("HUGGINGFACE_MODEL")

    async def generate(self, prompt: str, model_hint: str | None = None, max_tokens: int = 800, metadata: dict[str, Any] | None = None) -> AIResult:
        if not self.api_key:
            raise RuntimeError("HUGGINGFACE_API_KEY missing")
        model = model_hint or self.model or "mistralai/Mistral-7B-Instruct-v0.3"
        url = f"https://api-inference.huggingface.co/models/{model}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        body = {"inputs": prompt, "parameters": {"max_new_tokens": max_tokens}}
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
            # responses are varied; attempt common shapes
            if isinstance(data, list) and data and "generated_text" in data[0]:
                content = data[0]["generated_text"]
            elif isinstance(data, dict) and "generated_text" in data:
                content = str(data["generated_text"])  # type: ignore[assignment]
            else:
                content = json.dumps(data)
            return AIResult(provider="huggingface", model=model, content=content, usage_tokens=None, meta={})

    async def status(self) -> dict[str, Any]:
        return {"ok": bool(self.api_key)}


class PoeProvider:
    async def generate(self, *args: Any, **kwargs: Any) -> AIResult:  # pragma: no cover - stub
        raise NotImplementedError("POE provider is not implemented (no public API)")

    async def status(self) -> dict[str, Any]:  # pragma: no cover - stub
        return {"ok": False, "reason": "No official API"}


@dataclass
class AIClient:
    """Composite client with fallback chain.

    Order: local (Ollama) -> primary (env AI_PRIMARY) -> aggregator (OpenRouter) -> HuggingFace
    """

    primary: str = field(default_factory=lambda: os.getenv("AI_PRIMARY", "openrouter"))
    ollama: OllamaProvider = field(default_factory=OllamaProvider)
    openrouter: OpenRouterProvider = field(default_factory=OpenRouterProvider)
    huggingface: HuggingFaceProvider = field(default_factory=HuggingFaceProvider)

    async def generate(self, prompt: str, model_hint: str | None = None, max_tokens: int = 800, metadata: dict[str, Any] | None = None) -> AIResult:
        errors: list[str] = []
        # 1) Local first
        try:
            st = await self.ollama.status()
            if st.get("ok"):
                return await self.ollama.generate(prompt, model_hint, max_tokens, metadata)
        except Exception as e:
            errors.append(f"ollama:{e}")
        # 2) Primary
        primary = self.primary.lower()
        candidates: list[AIProvider] = []
        if primary == "openrouter":
            candidates = [self.openrouter, self.huggingface]
        elif primary == "huggingface":
            candidates = [self.huggingface, self.openrouter]
        else:
            candidates = [self.openrouter, self.huggingface]
        for prov in candidates:
            try:
                st = await prov.status()
                if st.get("ok", False):
                    return await prov.generate(prompt, model_hint, max_tokens, metadata)
            except Exception as e:
                errors.append(f"{type(prov).__name__}:{e}")
                continue
        raise RuntimeError("All AI providers failed: " + "; ".join(errors))


__all__ = [
    "AIProvider",
    "AIResult",
    "OllamaProvider",
    "OpenRouterProvider",
    "HuggingFaceProvider",
    "PoeProvider",
    "AIClient",
]
