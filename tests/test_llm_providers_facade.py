from typing import Any

import pytest

from pipeline.llm import providers as prov


@pytest.fixture(autouse=True)
def _restore_env(monkeypatch):
    # Ensure flag is enabled by default for these tests
    monkeypatch.setenv("LLM_USE_HTTP_FACADE_POST", "1")
    # Clear FORCE_HTTP_FACADE to avoid unintended side-effects from other tests
    monkeypatch.delenv("FORCE_HTTP_FACADE", raising=False)
    yield


def _set_env(monkeypatch, mapping: dict[str, str]):
    for k, v in mapping.items():
        monkeypatch.setenv(k, v)


def test_openai_generate_uses_facade(monkeypatch):
    _set_env(monkeypatch, {"OPENAI_API_KEY": "x", "OPENAI_MODEL": "gpt-4o-mini"})

    def fake_post_json(url: str, *, headers=None, json=None, timeout: float | None = None) -> Any:
        assert "openai.com" in url
        return {"choices": [{"message": {"content": "hello"}}]}

    monkeypatch.setattr("pipeline.http.post_json", fake_post_json)
    out = prov.openai_generate("hi", {"max_tokens": 16})
    assert out == "hello"


def test_openrouter_generate_uses_facade(monkeypatch):
    _set_env(monkeypatch, {"OPENROUTER_API_KEY": "x", "OPENROUTER_MODEL": "openrouter/auto"})

    def fake_post_json(url: str, *, headers=None, json=None, timeout: float | None = None) -> Any:
        assert "openrouter.ai" in url
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr("pipeline.http.post_json", fake_post_json)
    out = prov.openrouter_generate("hi", {})
    assert out == "ok"


def test_ollama_generate_uses_facade(monkeypatch):
    _set_env(monkeypatch, {"OLLAMA_HOST": "http://127.0.0.1:11434", "OLLAMA_MODEL": "llama3.1"})

    def fake_post_json(url: str, *, headers=None, json=None, timeout: float | None = None) -> Any:
        assert url.endswith("/api/generate")
        return {"response": "LOCAL"}

    monkeypatch.setattr("pipeline.http.post_json", fake_post_json)
    out = prov.ollama_generate("hi", {})
    assert out == "LOCAL"


def test_anthropic_generate_uses_facade(monkeypatch):
    _set_env(monkeypatch, {"ANTHROPIC_API_KEY": "x", "ANTHROPIC_MODEL": "claude-3-haiku-20240307"})

    def fake_post_json(url: str, *, headers=None, json=None, timeout: float | None = None) -> Any:
        assert "anthropic.com" in url
        return {"content": [{"type": "text", "text": "claude"}]}

    monkeypatch.setattr("pipeline.http.post_json", fake_post_json)
    out = prov.anthropic_generate("hi", {"max_tokens": 8})
    assert out == "claude"


def test_gemini_generate_uses_facade(monkeypatch):
    _set_env(monkeypatch, {"GOOGLE_API_KEY": "x", "GEMINI_MODEL": "gemini-1.5-flash"})

    def fake_post_json(url: str, *, headers=None, json=None, timeout: float | None = None) -> Any:
        assert "generativelanguage.googleapis.com" in url
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "a"},
                            {"text": "b"},
                        ]
                    }
                }
            ]
        }

    monkeypatch.setattr("pipeline.http.post_json", fake_post_json)
    out = prov.gemini_generate("hi", {})
    assert out == "ab"


def test_deepseek_generate_uses_facade(monkeypatch):
    _set_env(monkeypatch, {"DEEPSEEK_API_KEY": "x", "DEEPSEEK_MODEL": "deepseek-chat"})

    def fake_post_json(url: str, *, headers=None, json=None, timeout: float | None = None) -> Any:
        assert "deepseek.com" in url
        return {"choices": [{"message": {"content": "deep"}}]}

    monkeypatch.setattr("pipeline.http.post_json", fake_post_json)
    out = prov.deepseek_generate("hi", {"max_tokens": 16})
    assert out == "deep"
