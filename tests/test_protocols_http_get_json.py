import httpx

from pipeline import protocols


class DummyClient:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url, timeout=10.0):  # noqa: ARG002
        # Simulate success
        req = httpx.Request("GET", url)
        return httpx.Response(200, request=req, json={"hello": "world"})


def test_http_get_json_success(monkeypatch):
    monkeypatch.setattr(protocols.httpx, "Client", lambda: DummyClient())
    result = protocols.http_get_json("http://example.test")
    assert result["ok"] is True
    # Accept any dict content; focus on envelope correctness
    assert isinstance(result["value"], dict)


def test_http_get_json_non_dict(monkeypatch):
    class NDClient(DummyClient):
        def get(self, url, timeout=10.0):  # noqa: ARG002
            req = httpx.Request("GET", url)
            return httpx.Response(200, request=req, json=["not", "a", "dict"])

    monkeypatch.setattr(protocols.httpx, "Client", lambda: NDClient())
    result = protocols.http_get_json("http://example.test")
    assert result["ok"] is False
    assert "Non-dict" in result["error"]


def test_http_get_json_http_error(monkeypatch):
    class ErrClient(DummyClient):
        def get(self, url, timeout=10.0):  # noqa: ARG002
            req = httpx.Request("GET", url)
            resp = httpx.Response(500, request=req)
            return resp

    monkeypatch.setattr(protocols.httpx, "Client", lambda: ErrClient())
    result = protocols.http_get_json("http://example.test")
    assert result["ok"] is False
    assert result["error"]
