import pytest
import httpx
from types import SimpleNamespace

import pipeline.http_wrappers as hw
from pipeline.errors import TimeoutError_, NetworkError, EmptyDataError


def test_http_get_json_timeout(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        raise httpx.TimeoutException('t')
    # Patch uniquement la fonction get pour conserver les attributs (TimeoutException, etc.)
    monkeypatch.setattr(hw.httpx, 'get', fake_get)
    with pytest.raises(TimeoutError_):
        hw.http_get_json('http://x')


def test_http_get_json_network(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        raise httpx.RequestError('net', request=SimpleNamespace(url='u'))
    monkeypatch.setattr(hw.httpx, 'get', fake_get)
    with pytest.raises(NetworkError):
        hw.http_get_json('http://x')


def test_http_get_json_empty(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        return SimpleNamespace(status_code=200, json=lambda: {}, raise_for_status=lambda: None)
    monkeypatch.setattr(hw.httpx, 'get', fake_get)
    with pytest.raises(EmptyDataError):
        hw.http_get_json('http://x')


@pytest.mark.asyncio
async def test_async_http_get_json_timeout(monkeypatch):
    class FakeAsyncClient:
        async def get(self, url, headers=None, params=None, timeout=None):
            raise httpx.TimeoutException('t')
    client = FakeAsyncClient()
    with pytest.raises(TimeoutError_):
        await hw.async_http_get_json(client, 'http://x')
