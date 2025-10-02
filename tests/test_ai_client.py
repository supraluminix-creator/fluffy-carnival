import pytest

from integrations.ai_provider import AIClient


@pytest.mark.asyncio
async def test_aiclient_status_only(monkeypatch):
    client = AIClient()

    async def ok_status():
        return {"ok": True}

    async def fail_status():
        return {"ok": False}

    # Force ollama off, primary openrouter ok
    monkeypatch.setattr(client.ollama, "status", fail_status)
    monkeypatch.setattr(client.openrouter, "status", ok_status)

    async def fake_generate(prompt, model_hint=None, max_tokens=800, metadata=None):
        return {"provider": "openrouter", "model": "auto", "content": "ok", "usage_tokens": 1, "meta": {}}

    monkeypatch.setattr(client.openrouter, "generate", fake_generate)
    res = await client.generate("hello")
    assert res["provider"] == "openrouter"
    assert res["content"] == "ok"
