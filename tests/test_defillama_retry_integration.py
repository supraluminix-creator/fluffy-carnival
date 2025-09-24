import asyncio
import json
import types
import pytest

from pipeline.collectors.defillama import get_chain_data
from pipeline import http_wrappers
from pipeline.metrics import HTTP_RETRIES_TOTAL

class DummyResp:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self._data = data
    def json(self):
        return self._data
    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("err", request=None, response=None)


@pytest.mark.asyncio
async def test_defillama_get_chain_data_retry(monkeypatch):
    monkeypatch.setenv("RETRY_HTTP_ENABLED", "1")
    monkeypatch.setenv("RETRY_FORCE_THREAD", "1")
    calls = {"n":0}
    # Patch httpx.get utilisé dans http_get_json -> get_json_with_retry (appel via to_thread)
    def fake_get(url, headers=None, params=None, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            # Simule 429 -> RateLimitError via status mapping
            class R:
                status_code = 429
                def json(self):
                    return {"err":"rate"}
                def raise_for_status(self):
                    pass
            return R()
        class R2:
            status_code = 200
            def json(self):
                return [{"name":"Ethereum","tvl":12345.6}]
            def raise_for_status(self):
                pass
        return R2()
    monkeypatch.setattr(http_wrappers.httpx, "get", fake_get)
    data = await get_chain_data("ethereum")
    assert data and data["name"].lower()=="ethereum"
    # Deux retries (appels 1 et 2) enregistrés
    # Nouveau label normalisé via endpoint_label -> 'llama/chains'
    assert HTTP_RETRIES_TOTAL.labels(endpoint="llama/chains", reason="RateLimitError")._value.get() == 2
    assert calls["n"] == 3
