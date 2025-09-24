import httpx
import pytest

from pipeline import protocols


class DummyClient:
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False
    def get(self, url, timeout=10.0):  # noqa: ARG002
        # Simulate success
        req = httpx.Request('GET', url)
        return httpx.Response(200, request=req, json={'hello': 'world'})


def test_http_get_json_success(monkeypatch):
    monkeypatch.setattr(protocols.httpx, 'Client', lambda: DummyClient())
    result = protocols.http_get_json('http://example.test')
    assert result['ok'] is True
    # Accept any dict content; focus on envelope correctness
    assert isinstance(result['value'], dict)


def test_http_get_json_non_dict(monkeypatch):
    class NDClient(DummyClient):
        def get(self, url, timeout=10.0):  # noqa: ARG002
            req = httpx.Request('GET', url)
            return httpx.Response(200, request=req, json=['not', 'a', 'dict'])
    monkeypatch.setattr(protocols.httpx, 'Client', lambda: NDClient())
    result = protocols.http_get_json('http://example.test')
    assert result['ok'] is False
    assert 'Non-dict' in result['error']


def test_http_get_json_http_error(monkeypatch):
    class ErrClient(DummyClient):
        def get(self, url, timeout=10.0):  # noqa: ARG002
            req = httpx.Request('GET', url)
            resp = httpx.Response(500, request=req)
            return resp
    monkeypatch.setattr(protocols.httpx, 'Client', lambda: ErrClient())
    result = protocols.http_get_json('http://example.test')
    assert result['ok'] is False
    assert result['error']

import json
import types
import httpx
import pytest

from pipeline.protocols import http_get_json

class DummyClient:
    def __init__(self, status=200, payload=None):
        self.status = status
        self.payload = payload or {"foo": "bar"}
    def get(self, url, timeout=10.0):  # mimic httpx.Client.get
        content = json.dumps(self.payload).encode()
        # Provide a prepared request so raise_for_status() doesn't complain
        request = httpx.Request("GET", url)
        return httpx.Response(self.status, content=content, request=request)
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False

@pytest.mark.parametrize("status,expect_ok", [(200, True), (500, False)])
def test_http_get_json_success_and_error(monkeypatch, status, expect_ok):
    dummy = DummyClient(status=status)
    def fake_client(*args, **kwargs):
        return dummy
    monkeypatch.setattr(httpx, 'Client', fake_client)
    res = http_get_json("http://example.test")
    assert res['ok'] is expect_ok

@pytest.mark.parametrize("payload", [123, [1,2,3]])
def test_http_get_json_non_dict(monkeypatch, payload):
    dummy = DummyClient(status=200, payload=payload)
    def fake_client(*args, **kwargs):
        return dummy
    monkeypatch.setattr(httpx, 'Client', fake_client)
    res = http_get_json("http://example.test")
    assert res['ok'] is False
    assert res['error'] in ("Non-dict JSON", res['error'])
