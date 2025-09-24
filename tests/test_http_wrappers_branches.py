import pytest, httpx
from types import SimpleNamespace
import pipeline.http_wrappers as hw
from pipeline.errors import RateLimitError, UpstreamError, NotFoundError, EmptyDataError, NetworkError, TimeoutError_, SchemaError

# Helpers
class DummyResp:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data
    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=SimpleNamespace(url='u'), response=SimpleNamespace(status_code=self.status_code))
    def json(self):
        if isinstance(self._json, Exception):
            raise self._json
        return self._json


def patch_httpx(monkeypatch, resp_or_exc):
    def fake_get(url, headers=None, params=None, timeout=None):
        if isinstance(resp_or_exc, Exception):
            raise resp_or_exc
        return resp_or_exc
    monkeypatch.setattr(hw.httpx, 'get', fake_get)


def test_rate_limit(monkeypatch):
    patch_httpx(monkeypatch, DummyResp(status_code=429, json_data={"x":1}))
    with pytest.raises(RateLimitError):
        hw.http_get_json('http://x')

def test_upstream(monkeypatch):
    patch_httpx(monkeypatch, DummyResp(status_code=502, json_data={}))
    with pytest.raises(UpstreamError):
        hw.http_get_json('http://x')

def test_not_found(monkeypatch):
    patch_httpx(monkeypatch, DummyResp(status_code=404, json_data={}))
    with pytest.raises(NotFoundError):
        hw.http_get_json('http://x')

def test_empty_data(monkeypatch):
    patch_httpx(monkeypatch, DummyResp(status_code=200, json_data={}))
    with pytest.raises(EmptyDataError):
        hw.http_get_json('http://x')

def test_network(monkeypatch):
    patch_httpx(monkeypatch, httpx.RequestError('net', request=SimpleNamespace(url='u')))
    with pytest.raises(NetworkError):
        hw.http_get_json('http://x')

def test_timeout(monkeypatch):
    class FakeTimeout(httpx.TimeoutException):
        pass
    patch_httpx(monkeypatch, FakeTimeout('t'))
    with pytest.raises(TimeoutError_):
        hw.http_get_json('http://x')

def test_schema_error(monkeypatch):
    # Invalid JSON raising ValueError inside .json()
    patch_httpx(monkeypatch, DummyResp(status_code=200, json_data=ValueError('bad json')))
    with pytest.raises(SchemaError):
        hw.http_get_json('http://x')
