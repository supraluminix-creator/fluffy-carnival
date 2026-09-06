from types import SimpleNamespace

import pipeline.protocols as pmod


class DummyClient:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, timeout=10):  # pragma: no cover (exercised)
        return SimpleNamespace(status_code=200, json=lambda: {"k": 1}, raise_for_status=lambda: None)


def test_http_get_json_success(monkeypatch):
    monkeypatch.setattr(pmod, "httpx", SimpleNamespace(Client=lambda: DummyClient()))
    r = pmod.http_get_json("http://x")
    assert r["ok"] and r["value"] == {"k": 1}


def test_http_get_json_invalid_type(monkeypatch):
    class DummyBad(DummyClient):
        def get(self, url, timeout=10):
            return SimpleNamespace(status_code=200, json=lambda: [1, 2], raise_for_status=lambda: None)

    monkeypatch.setattr(pmod, "httpx", SimpleNamespace(Client=lambda: DummyBad()))
    r = pmod.http_get_json("http://x")
    assert not r["ok"] and "Non-dict" in r["error"]
