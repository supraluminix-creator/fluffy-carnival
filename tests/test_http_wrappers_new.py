from collections.abc import Mapping
from typing import Any

import httpx
import pytest

import pipeline.http_wrappers as hw
from pipeline.errors import EmptyDataError, NetworkError, TimeoutError_


def test_http_get_json_timeout(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        raise httpx.TimeoutException("t")

    # Patch uniquement la fonction get pour conserver les attributs (TimeoutException, etc.)
    monkeypatch.setattr(hw.httpx, "get", fake_get)
    with pytest.raises(TimeoutError_):
        hw.http_get_json("http://x")


def test_http_get_json_network(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        req = httpx.Request("GET", "http://x")
        raise httpx.RequestError("net", request=req)

    monkeypatch.setattr(hw.httpx, "get", fake_get)
    with pytest.raises(NetworkError):
        hw.http_get_json("http://x")


def test_http_get_json_empty(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        request = httpx.Request("GET", url)
        return httpx.Response(200, request=request, json={})

    monkeypatch.setattr(hw.httpx, "get", fake_get)
    with pytest.raises(EmptyDataError):
        hw.http_get_json("http://x")


@pytest.mark.asyncio
async def test_async_http_get_json_timeout(monkeypatch):
    class FakeAsyncClient:
        async def get(
            self,
            url: str,
            *,
            headers: Mapping[str, str] | None = None,
            params: Mapping[str, Any] | None = None,
            timeout: float | None = None,
            **kwargs: Any,
        ) -> object:
            raise httpx.TimeoutException("t")

    client = FakeAsyncClient()
    with pytest.raises(TimeoutError_):
        await hw.async_http_get_json(client, "http://x")
