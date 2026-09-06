"""AI providers with role-based routing and quota-aware fallbacks.

This module centralises all LLM integrations used by the crypto pipeline and
implements the updated strategy for orchestrating models by speciality:

- Grok (xAI) is prioritised for orchestration, heavy quantitative work, and
    technical/on-chain analysis tasks.
- DeepSeek backs up Grok and takes over sentiment confirmation when Grok usage
    crosses a configurable quota threshold.
- Claude performs fundamentals synthesis, ethical auditing, and long-context
    reasoning.
- Perplexity monitors legal developments (French/EU crypto regulations).
- Mistral Le Chat validates and cross-checks legal/tax findings surfaced by
    Perplexity.

Key environment variables
-------------------------

- ``LLM_PRIMARY`` (default ``grok``)
- ``LLM_BACKUP``  (default ``deepseek``)
- ``LLM_ALTERNATES`` (comma-separated list, default ``perplexity,claude,mistral``)
- ``LLM_QUOTA_THRESHOLD`` (default ``0.8``) – ratio threshold over the last
    window of calls that triggers a switch from the primary sentiment model to
    the backup.
- ``LLM_USAGE_HISTORY_PATH`` (optional path for persisting usage counters).
- Provider specific keys, e.g. ``GROK_API_KEY``, ``DEEPSEEK_API_KEY``,
    ``ANTHROPIC_API_KEY`` (Claude), ``PERPLEXITY_API_KEY``, ``MISTRAL_API_KEY``.

Backward compatibility is preserved: if none of the specialised providers are
configured the client falls back to OpenRouter, HuggingFace, Ollama, and
finally a deterministic mock provider so tests and local runs remain safe.

Notes: POE public API is not officially documented; the adapter is still a stub
that raises ``NotImplementedError``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, TypedDict

import httpx
import structlog

from pipeline.flags import is_llm_post_facade_enabled
from pipeline.http import async_fetch_json, async_post_json

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
        model_hint: str | None = None,
        max_tokens: int = 800,
        metadata: dict[str, Any] | None = None,
    ) -> AIResult:  # pragma: no cover - interface only
        ...

    async def status(self) -> dict[str, Any]:  # pragma: no cover - interface only
        ...


@dataclass
class MockProvider:
    """Deterministic mock provider used as a last resort.

    Useful for local runs without API keys and for unit tests.
    """

    model: str = "mock-generic"

    @staticmethod
    def _truncate(text: str, limit: int = 200) -> str:
        if len(text) <= limit:
            return text
        return text[: limit - 1] + "…"

    async def generate(
        self,
        prompt: str,
        model_hint: str | None = None,
        max_tokens: int = 800,
        metadata: dict[str, Any] | None = None,
    ) -> AIResult:
        model = model_hint or self.model
        meta = {"mock": True}
        if metadata:
            meta.update({k: metadata[k] for k in metadata})
        content = f"[MOCK:{model}] {self._truncate(prompt)}"
        return AIResult(provider="mock", model=model, content=content, usage_tokens=None, meta=meta)

    async def status(self) -> dict[str, Any]:  # pragma: no cover - trivial
        return {"ok": True}


@dataclass
class OllamaProvider:
    host: str = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    model: str = os.getenv("OLLAMA_MODEL", "llama3.1")

    def is_configured(self) -> bool:
        return bool(self.host)

    async def generate(
        self, prompt: str, model_hint: str | None = None, max_tokens: int = 800, metadata: dict[str, Any] | None = None
    ) -> AIResult:
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
                return AIResult(
                    provider="ollama", model=model, content=content, usage_tokens=None, meta={"endpoint": url}
                )
        except Exception as e:
            logger.warning("ollama_generate_failed", error=str(e))
            raise

    async def status(self) -> dict[str, Any]:
        try:
            import os

            url = f"{self.host.rstrip('/')}/api/tags"
            retry_enabled = os.getenv("RETRY_HTTP_ENABLED", "1") == "1"
            async with httpx.AsyncClient(timeout=5) as client:
                if retry_enabled:
                    # Utilise la façade pour une détection d'état plus robuste
                    _ = await async_fetch_json(url, timeout=5, client=client)
                    return {"ok": True, "host": self.host}
                else:
                    r = await client.get(url)
                    return {"ok": (r.status_code == 200), "host": self.host}
        except Exception as e:  # pragma: no cover - depends on local env
            return {"ok": False, "host": self.host, "error": str(e)}


@dataclass
class OpenRouterProvider:
    api_key: str | None = os.getenv("OPENROUTER_API_KEY")
    model: str | None = os.getenv("OPENROUTER_MODEL")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def generate(
        self, prompt: str, model_hint: str | None = None, max_tokens: int = 800, metadata: dict[str, Any] | None = None
    ) -> AIResult:
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
        use_facade = is_llm_post_facade_enabled()
        async with httpx.AsyncClient(timeout=60) as client:
            if use_facade:
                data = await async_post_json(url, headers=headers, json=body, timeout=60, client=client)
            else:
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

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def generate(
        self, prompt: str, model_hint: str | None = None, max_tokens: int = 800, metadata: dict[str, Any] | None = None
    ) -> AIResult:
        if not self.api_key:
            raise RuntimeError("HUGGINGFACE_API_KEY missing")
        model = model_hint or self.model or "mistralai/Mistral-7B-Instruct-v0.3"
        url = f"https://api-inference.huggingface.co/models/{model}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        body = {"inputs": prompt, "parameters": {"max_new_tokens": max_tokens}}
        use_facade = is_llm_post_facade_enabled()
        async with httpx.AsyncClient(timeout=60) as client:
            if use_facade:
                data = await async_post_json(url, headers=headers, json=body, timeout=60, client=client)
            else:
                r = await client.post(url, headers=headers, json=body)
                r.raise_for_status()
                data = r.json()
            # responses are varied; attempt common shapes
            if isinstance(data, list) and data and "generated_text" in data[0]:
                content = data[0]["generated_text"]
            elif isinstance(data, dict) and "generated_text" in data:
                content = str(data["generated_text"])
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
class GrokProvider:
    api_key: str | None = os.getenv("GROK_API_KEY")
    model: str = os.getenv("GROK_MODEL", "grok-beta")
    api_base: str = os.getenv("GROK_API_BASE", "https://api.x.ai")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def generate(
        self,
        prompt: str,
        model_hint: str | None = None,
        max_tokens: int = 800,
        metadata: dict[str, Any] | None = None,
    ) -> AIResult:
        if not self.api_key:
            raise RuntimeError("GROK_API_KEY missing")
        model = model_hint or self.model
        url = f"{self.api_base.rstrip('/')}/v1/chat/completions"
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
            if is_llm_post_facade_enabled():
                data = await async_post_json(url, headers=headers, json=body, timeout=60, client=client)
            else:
                resp = await client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage", {}).get("total_tokens")
        return AIResult(provider="grok", model=model, content=content, usage_tokens=usage, meta={})

    async def status(self) -> dict[str, Any]:
        return {"ok": bool(self.api_key)}


@dataclass
class DeepSeekProvider:
    api_key: str | None = os.getenv("DEEPSEEK_API_KEY")
    model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    api_base: str = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def generate(
        self,
        prompt: str,
        model_hint: str | None = None,
        max_tokens: int = 800,
        metadata: dict[str, Any] | None = None,
    ) -> AIResult:
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY missing")
        model = model_hint or self.model
        url = f"{self.api_base.rstrip('/')}/chat/completions"
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
            if is_llm_post_facade_enabled():
                data = await async_post_json(url, headers=headers, json=body, timeout=60, client=client)
            else:
                resp = await client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage", {}).get("total_tokens")
        return AIResult(provider="deepseek", model=model, content=content, usage_tokens=usage, meta={})

    async def status(self) -> dict[str, Any]:
        return {"ok": bool(self.api_key)}


@dataclass
class ClaudeProvider:
    api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    model: str = os.getenv("ANTHROPIC_MODEL", "claude-3-haiku-20240307")
    api_base: str = os.getenv("ANTHROPIC_API_BASE", "https://api.anthropic.com")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def generate(
        self,
        prompt: str,
        model_hint: str | None = None,
        max_tokens: int = 800,
        metadata: dict[str, Any] | None = None,
    ) -> AIResult:
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY missing")
        model = model_hint or self.model
        url = f"{self.api_base.rstrip('/')}/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": float((metadata or {}).get("temperature", 0.2)),
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}],
                }
            ],
        }
        async with httpx.AsyncClient(timeout=60) as client:
            if is_llm_post_facade_enabled():
                data = await async_post_json(url, headers=headers, json=body, timeout=60, client=client)
            else:
                resp = await client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()
        content_parts = data.get("content") or []
        text = "".join(part.get("text", "") for part in content_parts if isinstance(part, dict))
        usage = data.get("usage", {}).get("total_tokens") if isinstance(data, dict) else None
        return AIResult(provider="claude", model=model, content=text.strip(), usage_tokens=usage, meta={})

    async def status(self) -> dict[str, Any]:
        return {"ok": bool(self.api_key)}


@dataclass
class PerplexityProvider:
    api_key: str | None = os.getenv("PERPLEXITY_API_KEY")
    model: str = os.getenv("PERPLEXITY_MODEL", "pplx-2")
    api_base: str = os.getenv("PERPLEXITY_API_BASE", "https://www.perplexity.ai")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def generate(
        self,
        prompt: str,
        model_hint: str | None = None,
        max_tokens: int = 800,
        metadata: dict[str, Any] | None = None,
    ) -> AIResult:
        if not self.api_key:
            raise RuntimeError("PERPLEXITY_API_KEY missing")
        model = model_hint or self.model
        url = f"{self.api_base.rstrip('/')}/api/openai/chat/completions"
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
            if is_llm_post_facade_enabled():
                data = await async_post_json(url, headers=headers, json=body, timeout=60, client=client)
            else:
                resp = await client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage", {}).get("total_tokens")
        return AIResult(provider="perplexity", model=model, content=content, usage_tokens=usage, meta={})

    async def status(self) -> dict[str, Any]:
        return {"ok": bool(self.api_key)}


@dataclass
class MistralProvider:
    api_key: str | None = os.getenv("MISTRAL_API_KEY")
    model: str = os.getenv("MISTRAL_MODEL", "mistral-large-latest")
    api_base: str = os.getenv("MISTRAL_API_BASE", "https://api.mistral.ai")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def generate(
        self,
        prompt: str,
        model_hint: str | None = None,
        max_tokens: int = 800,
        metadata: dict[str, Any] | None = None,
    ) -> AIResult:
        if not self.api_key:
            raise RuntimeError("MISTRAL_API_KEY missing")
        model = model_hint or self.model
        url = f"{self.api_base.rstrip('/')}/v1/chat/completions"
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
            if is_llm_post_facade_enabled():
                data = await async_post_json(url, headers=headers, json=body, timeout=60, client=client)
            else:
                resp = await client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage", {}).get("total_tokens")
        return AIResult(provider="mistral", model=model, content=content, usage_tokens=usage, meta={})

    async def status(self) -> dict[str, Any]:
        return {"ok": bool(self.api_key)}


@dataclass(slots=True)
class LLMUsageHistory:
    """Persisted usage metrics to drive quota-aware routing."""

    path: Path
    window: int = 50
    data: dict[str, Any] = field(init=False)

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = {"history": [], "totals": {}}
        self._load()

    def _load(self) -> None:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except Exception as exc:
            logger.warning("llm_usage_load_failed", error=str(exc))
            return
        try:
            loaded = json.loads(raw)
        except Exception:
            logger.warning("llm_usage_parse_failed")
            return
        if isinstance(loaded, dict):
            self.data.update({k: loaded.get(k, []) for k in ("history", "totals")})

    def _save(self) -> None:
        try:
            self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("llm_usage_save_failed", error=str(exc))

    def record(self, provider: str, task: str, success: bool = True, error: str | None = None) -> None:
        if not success:
            return
        history = self.data.setdefault("history", [])
        history.append(
            {
                "provider": provider,
                "task": task,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
        )
        self.data.setdefault("totals", {})
        totals = self.data["totals"]
        totals[provider] = int(totals.get(provider, 0)) + 1
        if len(history) > self.window:
            self.data["history"] = history[-self.window :]
        self._save()

    def recent_ratio(self, provider: str, lookback: int) -> float:
        history = self.data.get("history", [])[-lookback:]
        if not history:
            return 0.0
        count = sum(1 for item in history if item.get("provider") == provider)
        return count / len(history)

    def total(self, provider: str) -> int:
        return int(self.data.get("totals", {}).get(provider, 0))


@dataclass(slots=True)
class LLMConfig:
    primary: str = "grok"
    backup: str = "deepseek"
    alternates: list[str] = field(default_factory=lambda: ["perplexity", "claude", "mistral"])
    quota_threshold: float = 0.8
    usage_path: Path = field(
        default_factory=lambda: Path(os.getenv("LLM_USAGE_HISTORY_PATH", "run/llm_usage_history.json"))
    )

    @classmethod
    def from_env(cls) -> LLMConfig:
        primary = os.getenv("LLM_PRIMARY", "grok").strip().lower() or "grok"
        backup = os.getenv("LLM_BACKUP", "deepseek").strip().lower() or "deepseek"
        alternates_raw = os.getenv("LLM_ALTERNATES", "perplexity,claude,mistral")
        alternates = [item.strip().lower() for item in alternates_raw.split(",") if item.strip()]
        try:
            quota = float(os.getenv("LLM_QUOTA_THRESHOLD", "0.8"))
        except Exception:
            quota = 0.8
        usage_path = Path(os.getenv("LLM_USAGE_HISTORY_PATH", "run/llm_usage_history.json"))
        return cls(
            primary=primary,
            backup=backup,
            alternates=alternates,
            quota_threshold=max(0.1, min(0.95, quota)),
            usage_path=usage_path,
        )


TASK_PREFERENCES: dict[str, list[str]] = {
    "orchestration": ["grok", "deepseek"],
    "heavy_math": ["grok", "deepseek"],
    "onchain": ["grok", "deepseek"],
    "technical_indicators": ["grok", "deepseek"],
    "quant": ["grok", "deepseek"],
    "sentiment": ["grok", "deepseek"],
    "fundamentals": ["claude", "grok", "deepseek"],
    "strategy": ["claude", "grok", "deepseek"],
    "ethics": ["claude", "perplexity"],
    "long_context": ["claude", "grok"],
    "legal_monitor": ["perplexity", "mistral"],
    "legal_verify": ["mistral", "perplexity"],
    "legal": ["perplexity", "mistral"],
    "compliance": ["perplexity", "mistral", "claude"],
}


def _dedupe_preserve(order: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for name in order:
        key = name.lower()
        if key and key not in seen:
            seen.add(key)
            result.append(key)
    return result


def get_llm_route(task_type: str | None, config: LLMConfig, usage: LLMUsageHistory) -> list[str]:
    task = (task_type or "general").lower()
    if task == "general":
        base = [config.primary, config.backup, *config.alternates]
        base.extend(["openrouter", "huggingface", "ollama", "mock"])
        return _dedupe_preserve(base)
    if task == "sentiment":
        primary = config.primary or "grok"
        backup = config.backup or "deepseek"
        ratio = usage.recent_ratio(primary, lookback=6)
        if ratio >= config.quota_threshold and backup:
            logger.info(
                "llm_quota_threshold_hit",
                provider=primary,
                ratio=ratio,
                threshold=config.quota_threshold,
                reroute_to=backup,
            )
            base = [backup, primary]
        else:
            base = [primary, backup]
        base.extend(config.alternates)
        base.extend(["openrouter", "huggingface", "ollama", "mock"])
        return _dedupe_preserve(base)
    preferred = TASK_PREFERENCES.get(task, [])
    base = preferred + [
        config.primary,
        config.backup,
        *config.alternates,
        "openrouter",
        "huggingface",
        "ollama",
        "mock",
    ]
    return _dedupe_preserve(base)


@dataclass
class AIClient:
    """Role-aware AI client orchestrating all providers."""

    config: LLMConfig = field(default_factory=LLMConfig.from_env)
    usage_history: LLMUsageHistory | None = None
    providers: dict[str, AIProvider] = field(init=False)

    def __post_init__(self) -> None:
        history = self.usage_history or LLMUsageHistory(self.config.usage_path)
        self.usage_history = history
        self.providers = {
            "grok": GrokProvider(),
            "deepseek": DeepSeekProvider(),
            "claude": ClaudeProvider(),
            "perplexity": PerplexityProvider(),
            "mistral": MistralProvider(),
            "openrouter": OpenRouterProvider(),
            "huggingface": HuggingFaceProvider(),
            "ollama": OllamaProvider(),
            "mock": MockProvider(),
        }

    async def generate(
        self,
        prompt: str,
        model_hint: str | None = None,
        max_tokens: int = 800,
        metadata: dict[str, Any] | None = None,
        task_type: str | None = "general",
    ) -> AIResult:
        route = get_llm_route(task_type, self.config, self.usage_history)
        errors: list[str] = []
        for provider_name in route:
            provider = self.providers.get(provider_name)
            if not provider:
                continue
            status: dict[str, Any] | None = None
            try:
                status = await provider.status()
            except Exception as exc:
                logger.debug("llm_status_error", provider=provider_name, error=str(exc))
                errors.append(f"{provider_name}:status:{exc}")
                continue
            if status and not status.get("ok", False):
                errors.append(f"{provider_name}:not_configured")
                continue
            try:
                result = await provider.generate(prompt, model_hint, max_tokens, metadata)
                self.usage_history.record(provider_name, task_type or "general")
                if provider_name != route[0]:
                    logger.info(
                        "llm_fallback",
                        requested=route[0],
                        used=provider_name,
                        task=task_type,
                        errors=errors,
                    )
                return result
            except Exception as exc:  # pragma: no cover - depends on runtime providers
                logger.warning("llm_generate_failed", provider=provider_name, error=str(exc))
                errors.append(f"{provider_name}:{exc}")
                continue
        raise RuntimeError("All AI providers failed: " + "; ".join(errors))

    async def status(self) -> dict[str, Any]:
        report: dict[str, Any] = {}
        for name, provider in self.providers.items():
            try:
                report[name] = await provider.status()
            except Exception as exc:  # pragma: no cover - network failure path
                report[name] = {"ok": False, "error": str(exc)}
        return report


__all__ = [
    "AIProvider",
    "AIResult",
    "MockProvider",
    "OllamaProvider",
    "OpenRouterProvider",
    "HuggingFaceProvider",
    "PoeProvider",
    "GrokProvider",
    "DeepSeekProvider",
    "ClaudeProvider",
    "PerplexityProvider",
    "MistralProvider",
    "LLMConfig",
    "LLMUsageHistory",
    "get_llm_route",
    "AIClient",
]
