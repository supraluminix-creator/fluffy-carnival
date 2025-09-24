from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Callable, Dict, List, Any, Tuple

try:
    # métriques optionnelles (ne doit pas casser si non disponibles au test)
    from prometheus_client import Counter

    LLM_REQUESTS_TOTAL = Counter(
        "llm_requests_total", "Total requêtes LLM", ["model"]
    )
    LLM_FAILURES_TOTAL = Counter(
        "llm_failures_total", "Echecs LLM", ["model", "reason"]
    )
    LLM_FALLBACKS_TOTAL = Counter(
        "llm_fallbacks_total", "Fallbacks LLM", ["from_model", "to_model"]
    )
except Exception:  # pragma: no cover
    LLM_REQUESTS_TOTAL = None  # type: ignore
    LLM_FAILURES_TOTAL = None  # type: ignore
    LLM_FALLBACKS_TOTAL = None  # type: ignore


GenFn = Callable[[str, Dict[str, Any]], str]


@dataclass
class ModelConfig:
    name: str
    daily_calls_limit: int
    priority: int  # plus petit = plus prioritaire
    fn: GenFn


class QuotaState:
    def __init__(self) -> None:
        self.usage: Dict[Tuple[int, str], int] = {}

    def increment(self, model: str) -> None:
        key = (int(time() // 86400), model)
        self.usage[key] = self.usage.get(key, 0) + 1

    def remaining(self, cfg: ModelConfig) -> int:
        key = (int(time() // 86400), cfg.name)
        return cfg.daily_calls_limit - self.usage.get(key, 0)


class ClientLLM:
    def __init__(self, models: List[ModelConfig], quota: QuotaState) -> None:
        # tri par priorité, le plus faible d'abord
        self.models = sorted(models, key=lambda m: m.priority)
        self.quota = quota

    def generate(self, prompt: str, **opts: Any) -> str:
        errors: List[Tuple[str, str]] = []
        last_model: str | None = None
        for m in self.models:
            if self.quota.remaining(m) <= 0:
                continue
            try:
                if LLM_REQUESTS_TOTAL:
                    LLM_REQUESTS_TOTAL.labels(model=m.name).inc()
                out = m.fn(prompt, opts)
                self.quota.increment(m.name)
                if last_model and last_model != m.name and LLM_FALLBACKS_TOTAL:
                    LLM_FALLBACKS_TOTAL.labels(from_model=last_model, to_model=m.name).inc()
                return out
            except Exception as e:  # pragma: no cover - cas d'échec volontaire en tests
                if LLM_FAILURES_TOTAL:
                    LLM_FAILURES_TOTAL.labels(model=m.name, reason=type(e).__name__).inc()
                errors.append((m.name, str(e)))
                last_model = m.name
                continue
        raise RuntimeError(f"All models failed or quotas exhausted: {errors}")
