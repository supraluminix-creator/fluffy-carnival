import httpx
import pytest

from pipeline import http_wrappers as hw
from pipeline.errors import EmptyDataError, NotFoundError, RateLimitError, SchemaError, UpstreamError


class DummyResp:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {"ok":1}
        self.request = httpx.Request('GET','http://dummy')
    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                'err',
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )
    def json(self):
        if self._json == 'INVALID':
            raise ValueError('bad json')
        return self._json

# Sync tests

def test_http_get_json_success(monkeypatch):
    monkeypatch.setattr(httpx, 'get', lambda url, headers=None, params=None, timeout=10: DummyResp(200,{"a":1}))
    data = hw.http_get_json('http://x')
    assert data['a'] == 1

@pytest.mark.parametrize('code,exc', [(429,RateLimitError),(404,NotFoundError),(502,UpstreamError)])
def test_http_get_json_status_errors(monkeypatch, code, exc):
    monkeypatch.setattr(httpx, 'get', lambda *a, **k: DummyResp(code,{"err":1}))
    with pytest.raises(exc):
        hw.http_get_json('http://x')

def test_http_get_json_empty(monkeypatch):
    monkeypatch.setattr(httpx, 'get', lambda *a, **k: DummyResp(200,{}))
    with pytest.raises(EmptyDataError):
        hw.http_get_json('http://x')

def test_http_get_json_invalid_json(monkeypatch):
    monkeypatch.setattr(httpx, 'get', lambda *a, **k: DummyResp(200,'INVALID'))
    with pytest.raises(SchemaError):
        hw.http_get_json('http://x')

# Async tests

class DummyAsyncClient:
    def __init__(self, resp: DummyResp):
        self._resp = resp
    async def __aenter__(self): return self
    async def __aexit__(self, exc_type, exc, tb): return False
    async def get(self, url, headers=None, params=None, timeout=10):
        return self._resp

@pytest.mark.asyncio
async def test_async_http_get_json_success():
    client = DummyAsyncClient(DummyResp(200,{"b":2}))
    data = await hw.async_http_get_json(client,'http://x')
    assert data['b'] == 2

@pytest.mark.asyncio
async def test_async_http_get_json_empty():
    client = DummyAsyncClient(DummyResp(200,{}))
    with pytest.raises(EmptyDataError):
        await hw.async_http_get_json(client,'http://x')
