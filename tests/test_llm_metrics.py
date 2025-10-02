from __future__ import annotations

import pytest
from prometheus_client import REGISTRY

from pipeline.llm.client import (
    LLM_FAILURES_TOTAL,
    LLM_FALLBACKS_TOTAL,
    LLM_REQUESTS_TOTAL,
    ClientLLM,
    ModelConfig,
    QuotaState,
)


def _collect_counter_value(name: str, labels: dict[str, str] | None = None) -> float:
    total = 0.0
    for metric in REGISTRY.collect():
        if metric.name != name:
            continue
        for sample in metric.samples:
            # Ignore creation timestamp samples
            if sample.name.endswith("_created"):
                continue
            if labels is None or all(sample.labels.get(k) == v for k, v in labels.items()):
                # For Counters, the exported sample name usually ends with _total
                total += float(sample.value)
    return total


def _collect_counter_value_any(names: list[str], labels: dict[str, str] | None = None) -> float:
    return sum(_collect_counter_value(n, labels) for n in names)


def test_llm_requests_and_failures_and_fallbacks():
    if not (LLM_REQUESTS_TOTAL and LLM_FAILURES_TOTAL and LLM_FALLBACKS_TOTAL):
        pytest.skip("LLM Prometheus counters not available in this environment")
    # Define two models: first fails, second succeeds
    def fail_model(prompt: str, opts):
        raise RuntimeError("boom")

    def ok_model(prompt: str, opts):
        return "ok"

    m1 = ModelConfig(name="m1", daily_calls_limit=10, priority=1, fn=fail_model)
    m2 = ModelConfig(name="m2", daily_calls_limit=10, priority=2, fn=ok_model)
    client = ClientLLM([m1, m2], QuotaState())

    # Supporte les deux conventions (avec ou sans suffixe _total)
    req_names = ["llm_requests_total", "llm_requests"]
    fail_names = ["llm_failures_total", "llm_failures"]
    fb_names = ["llm_fallbacks_total", "llm_fallbacks"]

    before_req_m1 = _collect_counter_value_any(req_names, {"model": "m1"})
    before_req_m2 = _collect_counter_value_any(req_names, {"model": "m2"})
    before_fail_m1 = _collect_counter_value_any(fail_names, {"model": "m1", "reason": "RuntimeError"})
    before_fb = _collect_counter_value_any(fb_names, {"from_model": "m1", "to_model": "m2"})

    out = client.generate("hello")
    assert out == "ok"

    # Requests should have incremented for m1 then m2
    assert _collect_counter_value_any(req_names, {"model": "m1"}) >= before_req_m1 + 1
    assert _collect_counter_value_any(req_names, {"model": "m2"}) >= before_req_m2 + 1
    # Failures for m1
    assert _collect_counter_value_any(fail_names, {"model": "m1", "reason": "RuntimeError"}) >= before_fail_m1 + 1
    # Fallback from m1 to m2 recorded
    assert _collect_counter_value_any(fb_names, {"from_model": "m1", "to_model": "m2"}) >= before_fb + 1
