import pytest

from integrations.ai_provider import AIClient


class _StubProvider:
    def __init__(self, provider: str, content: str) -> None:
        self.provider = provider
        self._content = content
        self.called = 0

    async def status(self):  # pragma: no cover - simple stub
        return {"ok": True}

    async def generate(self, prompt, model_hint=None, max_tokens=800, metadata=None):
        self.called += 1
        return {
            "provider": self.provider,
            "model": model_hint or self.provider,
            "content": self._content,
            "usage_tokens": 1,
            "meta": metadata or {},
        }


@pytest.mark.asyncio
async def test_aiclient_general_uses_primary_mock(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_USAGE_HISTORY_PATH", str(tmp_path / "history.json"))
    client = AIClient()
    client.config.primary = "mock"
    client.config.backup = "deepseek"
    client.providers["mock"] = _StubProvider("mock", "ok")

    result = await client.generate("hello world")
    assert result["provider"] == "mock"
    assert result["content"] == "ok"
