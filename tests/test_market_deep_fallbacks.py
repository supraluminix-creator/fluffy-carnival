import os
import pytest
import httpx
from types import SimpleNamespace
from pipeline.collectors import market as market_mod
from pipeline.collectors.market import fetch_market, fetch_macro, fetch_macro_orchestrated
from pipeline.circuit_breaker import _STATES as BREAKER_STATE  # correct internal mapping

# Helpers
class DummyResp:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data if data is not None else {}
    def raise_for_status(self):
        if self.status_code != 200:
            raise httpx.HTTPStatusError("err", request=None, response=None)
    def json(self):
        return self._data

class DummyAsyncClient:
    def __init__(self, scenario):
        self.scenario = scenario
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc, tb):
        return False
    async def get(self, url, headers=None, timeout=10, params=None):
        # Scenario mapping for macro orchestrated tiers
        if self.scenario == 'cg_ok' and 'coingecko' in url:
            return DummyResp(200, {"market_data": {"current_price": {"usd": 100}, "total_volume": {"usd": 10}, "market_cap": {"usd": 1000}, "market_cap_rank": 1}, "last_updated": "t"})
        if self.scenario == 'cg_fail' and 'coingecko' in url:
            raise httpx.RequestError("cg fail")
        if self.scenario == 'cmc_ok' and 'coinmarketcap' in url:
            return DummyResp(200, {"status": {"timestamp": "t"}, "data": {"BTC": {"quote": {"USD": {"price": 101, "volume_24h": 11, "market_cap": 1100}}}}})
        if self.scenario == 'binance_macro_ok' and 'macro' in url:
            return DummyResp(200, {"price": 102})
        return DummyResp(200, {})

@pytest.fixture(autouse=True)
def clear_cache_and_breaker():
    market_mod.cache.clear()
    BREAKER_STATE.clear()
    yield
    market_mod.cache.clear()
    BREAKER_STATE.clear()

# 1) Breaker skip branch
def test_market_breaker_skip(monkeypatch):
    monkeypatch.setattr(market_mod, 'should_skip', lambda name: True)
    assert fetch_market('bitcoin') is None

# 2) Cache hit branch
def test_market_cache_hit(monkeypatch):
    # Pré-insère dans le cache
    market_mod.cache.set('market_bitcoin', {"symbol": "bitcoin", "price": 1, "volume_24h": 0, "marketcap": 0, "dominance": 1})
    # should_skip False
    monkeypatch.setattr(market_mod, 'should_skip', lambda name: False)
    # httpx.get ne doit pas être appelé -> on met une fonction qui lèverait si appelée
    def fail_get(*a, **k):
        raise AssertionError('should not call network')
    monkeypatch.setattr(httpx, 'get', fail_get)
    res = fetch_market('bitcoin')
    assert res['price'] == 1

# 3) Primary SchemaError (KeyError path) then fallback success
def test_market_primary_keyerror_to_schema_then_fallback_success(monkeypatch):
    monkeypatch.setattr(market_mod, 'should_skip', lambda name: False)
    # Primary renvoie dict sans market_data -> provoque KeyError access plus loin? Fournissons objet provoquant exception explicite
    class BadResp(DummyResp):
        def json(self):
            return {'bad': 'structure'}  # no market_data -> keys access yield empty values but not KeyError, so force KeyError by raising
    def bad_get(url, timeout=10):
        raise KeyError('missing market_data')
    # Fallback CMC success
    def cmc_get(url, timeout=10):
        return DummyResp(200, {"data": {"BITCOIN": {"quote": {"USD": {"price": 123, "volume_24h": 1, "market_cap": 10}}}}})
    # First call raises KeyError, second call fallback
    calls = {'n':0}
    def seq_get(url, timeout=10):
        calls['n'] += 1
        if calls['n'] == 1:
            return bad_get(url, timeout=10)
        return cmc_get(url, timeout=10)
    monkeypatch.setattr(httpx, 'get', seq_get)
    res = fetch_market('bitcoin')
    assert res['price'] == 123

# 4) Fallback error path (CMC KeyError) -> returns None
def test_market_fallback_keyerror(monkeypatch):
    monkeypatch.setattr(market_mod, 'should_skip', lambda name: False)
    # Primary fails
    def primary_fail(url, timeout=10):
        raise httpx.RequestError('cg net fail')
    # Fallback also KeyError
    def cmc_fail(url, timeout=10):
        raise KeyError('missing data')
    calls = {'n':0}
    def seq_get(url, timeout=10):
        calls['n'] += 1
        if calls['n'] == 1:
            return primary_fail(url, timeout=10)
        return cmc_fail(url, timeout=10)
    monkeypatch.setattr(httpx, 'get', seq_get)
    assert fetch_market('bitcoin') is None

# 5) Fallback status_code != 200 branch
def test_market_fallback_status_code_non_200(monkeypatch):
    monkeypatch.setattr(market_mod, 'should_skip', lambda name: False)
    def primary_fail(url, timeout=10):
        raise httpx.RequestError('cg fail')
    class RespNon200(DummyResp):
        def __init__(self):
            super().__init__(status_code=500, data={})
    def cmc_500(url, timeout=10):
        return RespNon200()
    calls={'n':0}
    def seq_get(url, timeout=10):
        calls['n']+=1
        if calls['n'] == 1:
            return primary_fail(url, timeout=10)
        return cmc_500(url, timeout=10)
    monkeypatch.setattr(httpx, 'get', seq_get)
    assert fetch_market('bitcoin') is None

# 6) Macro binance macro simple flag success path (CG fail -> CMC fail -> binance macro)
@pytest.mark.asyncio
async def test_macro_binance_macro_flag_success(monkeypatch):
    monkeypatch.setenv('ENABLE_BINANCE_MACRO_FALLBACK', '1')
    monkeypatch.setattr(market_mod, 'should_skip', lambda name: False)
    # Force CG fail & CMC fail to reach binance macro simple
    class RespFail:
        status_code = 500
        def raise_for_status(self):
            raise httpx.HTTPStatusError('e', request=None, response=None)
        def json(self):
            return {}
    def get_fail(*a, **k):
        raise httpx.RequestError('cg fail')
    monkeypatch.setattr(httpx, 'get', get_fail)
    # Patch async client for binance macro simple tier
    class AsyncClientBinance:
        async def __aenter__(self): return self
        async def __aexit__(self, *exc): return False
        async def get(self, url, headers=None, timeout=5):
            return DummyResp(200, {"price": 999})
    monkeypatch.setattr(market_mod.httpx, 'AsyncClient', AsyncClientBinance)
    out = await fetch_macro('bitcoin')
    assert isinstance(out, dict) and ('macro_price_usd' in out or 'value' in out)

# 7) Orchestrated macro success via first tier
@pytest.mark.asyncio
async def test_macro_orchestrated_first_tier_success(monkeypatch):
    # Accepte désormais les kwargs passés à AsyncClient (timeout, etc.)
    monkeypatch.setattr(market_mod.httpx, 'AsyncClient', lambda *a, **k: DummyAsyncClient('cg_ok'))
    res = await fetch_macro_orchestrated('bitcoin')
    assert res and res.get('source') == 'coingecko'

# 8) Orchestrated macro success via binance macro simple (CG & spot & CMC fail)
@pytest.mark.asyncio
async def test_macro_orchestrated_binance_macro(monkeypatch):
    monkeypatch.setenv('ENABLE_BINANCE_MACRO_FALLBACK', '1')
    # Fail CG + spot + CMC, then succeed binance macro
    class AsyncClientFailing:
        calls = 0
        async def __aenter__(self): return self
        async def __aexit__(self,*a): return False
        async def get(self, url, headers=None, timeout=10, params=None):
            AsyncClientFailing.calls += 1
            if 'coingecko' in url:
                raise httpx.RequestError('cg fail')
            if 'coinmarketcap' in url:
                raise httpx.RequestError('cmc fail')
            if 'macro' in url:
                return DummyResp(200, {"price": 222})
            return DummyResp(200, {})
    monkeypatch.setattr(market_mod.httpx, 'AsyncClient', lambda : AsyncClientFailing())
    # Rendre compatible avec les kwargs
    monkeypatch.setattr(market_mod.httpx, 'AsyncClient', lambda *a, **k: AsyncClientFailing())
    res = await fetch_macro_orchestrated('bitcoin')
    assert res and ('macro_price_usd' in res or res.get('source')=='coingecko')
