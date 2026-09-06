from typing import Any

import requests

import pipeline.collectors.defi as defi


def test_defi_uses_facade_by_default(monkeypatch):
    calls = {"facade": 0}

    def fake_fetch_json(url: str, *a, **k) -> dict[str, Any]:
        calls["facade"] += 1
        return {"tvl": 123, "tvlPrevDay": 100, "tvlPrevWeek": 90, "tvlPrevMonth": 80}

    monkeypatch.setattr(defi, "fetch_json", fake_fetch_json, raising=True)
    rec = defi.fetch_defillama_tvl("ethereum")
    assert rec and rec["tvl"] == 123
    assert calls["facade"] == 1


def test_defi_falls_back_to_requests_if_monkeypatched(monkeypatch):
    # Simuler un monkeypatch tests.* sur requests.get
    def fake_get(url: str, timeout: int = 10):
        class DummyResp:
            def json(self):
                return {"tvl": 321, "tvlPrevDay": 310, "tvlPrevWeek": 300, "tvlPrevMonth": 290}

        return DummyResp()

    # Forcer __module__ de requests.get à ressembler à un patch de tests
    monkeypatch.setattr(requests, "get", fake_get)
    requests.get.__module__ = "tests.fake"

    rec = defi.fetch_defillama_tvl("ethereum")
    assert rec and rec["tvl"] == 321
