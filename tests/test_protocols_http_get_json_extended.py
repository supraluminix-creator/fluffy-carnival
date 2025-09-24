import types
import httpx
import pytest

from pipeline import protocols


class DummyResponse:
    def __init__(self, json_payload, status_code=200, raise_http=False):
        self._json_payload = json_payload
        self.status_code = status_code
        self._raise_http = raise_http

    def raise_for_status(self):
        if self._raise_http:
            raise httpx.HTTPStatusError("boom", request=None, response=None)  # type: ignore[arg-type]

    def json(self):
        return self._json_payload


class DummyClient:
    def __init__(self, response: DummyResponse):
        self._response = response
        self.get_called = False
        self.closed = False

    def get(self, url, timeout=10):  # noqa: D401
        self.get_called = True
        return self._response

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.closed = True


def _patch_client(monkeypatch, resp: DummyResponse):
    def fake_client():
        return DummyClient(resp)

    monkeypatch.setattr(protocols.httpx, "Client", fake_client)


def test_http_get_json_success(monkeypatch):
    _patch_client(monkeypatch, DummyResponse({"a": 1}))
    res = protocols.http_get_json("http://x")
    assert res["ok"] is True and res["value"] == {"a": 1}


def test_http_get_json_non_dict(monkeypatch):
    _patch_client(monkeypatch, DummyResponse([1, 2, 3]))
    res = protocols.http_get_json("http://x")
    assert res["ok"] is False and res["error"] == "Non-dict JSON"


def test_http_get_json_http_error(monkeypatch):
    _patch_client(monkeypatch, DummyResponse({"a": 1}, raise_http=True))
    res = protocols.http_get_json("http://x")
    assert res["ok"] is False and "boom" in (res["error"] or "")


def test_http_get_json_network_exception(monkeypatch):
    class Boom(Exception):
        pass

    class BrokenClient(DummyClient):
        def get(self, url, timeout=10):
            raise Boom("net down")

    def fake_client():
        return BrokenClient(DummyResponse({}))

    monkeypatch.setattr(protocols.httpx, "Client", fake_client)
    res = protocols.http_get_json("http://x")
    assert res["ok"] is False and "net down" in (res["error"] or "")
