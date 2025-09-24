import pytest
import httpx
from pipeline.http_wrappers import http_get_json, async_http_get_json
from pipeline.errors import SchemaError

class DummyResp:
    def __init__(self, status_code=200):
        self.status_code = status_code
    def raise_for_status(self):
        if self.status_code != 200:
            raise httpx.HTTPStatusError("err", request=None, response=None)  # pragma: no cover (not triggered here)
    def json(self):
        raise ValueError("bad json")

class DummyAsyncClient:
    def __init__(self, status_code=200):
        self._status = status_code
    async def get(self, *a, **k):
        return DummyResp(self._status)


def test_http_get_json_schema_error(monkeypatch):
    def fake_get(*a, **k):
        return DummyResp(200)
    monkeypatch.setattr(httpx, 'get', fake_get)
    with pytest.raises(SchemaError):
        http_get_json('https://x.test')

@pytest.mark.asyncio
async def test_async_http_get_json_schema_error():
    client = DummyAsyncClient(200)
    with pytest.raises(SchemaError):
        await async_http_get_json(client, 'https://x.test')
