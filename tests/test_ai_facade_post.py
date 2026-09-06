import os

import pytest

import integrations.ai_provider as ai


@pytest.mark.asyncio
async def test_openrouter_facade_post_used(monkeypatch):
    os.environ["AI_USE_HTTP_FACADE_POST"] = "1"

    # Arrange provider with dummy key
    prov = ai.OpenRouterProvider(api_key="k", model="openrouter/auto")

    async def fake_async_post_json(url, headers=None, json=None, timeout=None, client=None):  # noqa: A002 - json param
        assert url.startswith("https://openrouter.ai/api/v1/chat/completions")
        return {
            "choices": [{"message": {"content": "hello"}}],
            "usage": {"total_tokens": 7},
        }

    monkeypatch.setattr(ai, "async_post_json", fake_async_post_json)

    # Also patch httpx.AsyncClient to ensure it's instantiated without hitting network
    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(ai.httpx, "AsyncClient", lambda timeout=60: DummyClient())

    res = await prov.generate("hi")
    assert res["provider"] == "openrouter"
    assert res["content"] == "hello"
    assert res["usage_tokens"] == 7


@pytest.mark.asyncio
async def test_huggingface_facade_post_used(monkeypatch):
    os.environ["AI_USE_HTTP_FACADE_POST"] = "1"

    prov = ai.HuggingFaceProvider(api_key="k", model="mistralai/Mistral-7B-Instruct-v0.3")

    async def fake_async_post_json(url, headers=None, json=None, timeout=None, client=None):  # noqa: A002 - json param
        assert url.startswith("https://api-inference.huggingface.co/models/")
        return [{"generated_text": "ok"}]

    monkeypatch.setattr(ai, "async_post_json", fake_async_post_json)

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(ai.httpx, "AsyncClient", lambda timeout=60: DummyClient())

    res = await prov.generate("hi")
    assert res["provider"] == "huggingface"
    assert res["content"] == "ok"


@pytest.mark.asyncio
async def test_openrouter_legacy_post_when_flag_off(monkeypatch):
    os.environ.pop("AI_USE_HTTP_FACADE_POST", None)
    prov = ai.OpenRouterProvider(api_key="k", model="openrouter/auto")

    class DummyResp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "legacy"}}], "usage": {"total_tokens": 3}}

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, json=None):  # noqa: A002 - json param
            return DummyResp()

    monkeypatch.setattr(ai.httpx, "AsyncClient", lambda timeout=60: DummyClient())

    res = await prov.generate("hi")
    assert res["content"] == "legacy"
