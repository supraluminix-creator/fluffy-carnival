from __future__ import annotations

import pytest

from pipeline.llm.client import ClientLLM, ModelConfig, QuotaState


def test_fallback_when_first_model_fails():
    calls = {"b": 0}

    def model_a(prompt, opts):
        raise RuntimeError("model A down")

    def model_b(prompt, opts):
        calls["b"] += 1
        return f"ok:{prompt}"

    quota = QuotaState()
    client = ClientLLM(
        [
            ModelConfig("A", daily_calls_limit=10, priority=0, fn=model_a),
            ModelConfig("B", daily_calls_limit=10, priority=1, fn=model_b),
        ],
        quota,
    )

    out = client.generate("ping")
    assert out == "ok:ping"
    assert calls["b"] == 1


def test_quota_exhaustion_skips_model():
    calls = {"a": 0, "b": 0}

    def model_a(prompt, opts):
        calls["a"] += 1
        return "A"

    def model_b(prompt, opts):
        calls["b"] += 1
        return "B"

    quota = QuotaState()
    client = ClientLLM(
        [
            ModelConfig("A", daily_calls_limit=1, priority=0, fn=model_a),
            ModelConfig("B", daily_calls_limit=10, priority=1, fn=model_b),
        ],
        quota,
    )

    # première utilisation: A
    assert client.generate("x") == "A"
    # quota A épuisé, bascule vers B
    assert client.generate("y") == "B"
    assert calls["a"] == 1
    assert calls["b"] == 1


def test_all_models_exhausted_raises():
    def ok(prompt, opts):
        return "OK"

    quota = QuotaState()
    client = ClientLLM(
        [ModelConfig("A", daily_calls_limit=0, priority=0, fn=ok)], quota
    )

    with pytest.raises(RuntimeError):
        client.generate("z")
