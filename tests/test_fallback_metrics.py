import io
import json
import re

import httpx
import pytest
import structlog
from prometheus_client import generate_latest

from pipeline.collectors.derivatives import fetch_bybit_oi
from pipeline.collectors.market import fetch_market
from pipeline.collectors.onchain import cache, fetch_txcount
from pipeline.collectors.sentiment import fetch_fear_greed


@pytest.fixture
def log_buffer(monkeypatch):
    """Configure structlog pour écrire des lignes JSON dans un buffer mémoire isolé.

    On parse ensuite ces lignes pour assertions robustes, indépendantes de processors globaux.
    """
    buf = io.StringIO()
    structlog.reset_defaults()
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=lambda *a, **k: structlog.PrintLogger(buf),
        cache_logger_on_first_use=False,
    )
    # Ré-affecte les loggers déjà capturés dans les modules collectors vers le nouveau backend
    try:
        import pipeline.collectors.derivatives as _d
        import pipeline.collectors.market as _m
        import pipeline.collectors.onchain as _o
        import pipeline.collectors.sentiment as _s

        new_logger = structlog.get_logger("tests_fallback")
        for mod in (_m, _s, _o, _d):
            if hasattr(mod, "log"):
                monkeypatch.setattr(mod, "log", new_logger)
    except Exception:  # pragma: no cover - pure sûreté
        pass
    try:
        yield buf
    finally:
        structlog.reset_defaults()


def _parsed_events(buf: io.StringIO):
    lines = [line for line in buf.getvalue().splitlines() if line.strip()]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _fallback_metric_value(metrics_text: str, collector: str, status: str) -> float | None:
    # Recherche ligne correspondante et extrait la valeur numérique finale
    pattern = (
        rf'^fallback_invocations_total\{{[^}}]*collector="{collector}"[^}}]*status="{status}"[^}}]*\}} (\d+(?:\.\d+)?)$'
    )
    for line in metrics_text.splitlines():
        m = re.match(pattern, line)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
    return None


class DummyResp:
    def __init__(self, json_data=None, text=None, status=200):
        self._json = json_data
        self.text = text or ""
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)

    def json(self):
        return self._json


# --- MARKET fallback test (primary fail -> fallback success) ---


def test_market_fallback_metrics(monkeypatch, log_buffer):
    symbol = "bitcoinxx"
    cg_url = f"https://api.coingecko.com/api/v3/coins/{symbol}"
    cmc_url = f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest?symbol={symbol.upper()}"
    cache.clear()
    calls = []

    def fake_get(url, *a, **k):
        calls.append(url)
        if url == cg_url:
            raise RuntimeError("primary fail")
        if url == cmc_url:
            return DummyResp(
                json_data={
                    "data": {
                        symbol.upper(): {
                            "quote": {
                                "USD": {"price": 1.0, "volume_24h": 2.0, "market_cap": 3.0, "market_cap_dominance": 0.4}
                            }
                        }
                    }
                }
            )
        return DummyResp(json_data={})

    monkeypatch.setattr(httpx, "get", fake_get)
    res = fetch_market(symbol)
    assert res is not None and res["price"] == 1.0
    metrics_text = generate_latest().decode()
    val = _fallback_metric_value(metrics_text, "market", "success")
    assert val is not None and val >= 1
    events = _parsed_events(log_buffer)
    assert any(e.get("event") == "market_fallback_success" and e.get("fallback") == 1 for e in events)


# --- SENTIMENT fallback test ---
@pytest.mark.asyncio
async def test_sentiment_fallback_metrics(monkeypatch, log_buffer):
    cache.clear()
    alt_url = "https://api.alternative.me/fng/"

    def fake_async_client():
        class C:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url, timeout=10):
                if url == alt_url:
                    raise RuntimeError("alt fail")
                raise AssertionError("Unexpected URL")

        return C()

    monkeypatch.setattr(httpx, "AsyncClient", fake_async_client)
    rec = await fetch_fear_greed()
    assert rec is not None and rec["source"].startswith("tokenmetrics")
    metrics_text = generate_latest().decode()
    val = _fallback_metric_value(metrics_text, "sentiment", "success")
    assert val is not None and val >= 1
    events = _parsed_events(log_buffer)
    assert any(e.get("event") == "sentiment_fallback_success" and e.get("fallback") == 1 for e in events)


# --- ONCHAIN fallback test (BTC primary fail) ---
@pytest.mark.asyncio
async def test_onchain_txcount_fallback_metrics(monkeypatch, log_buffer):
    cache.clear()
    main_url = "https://api.blockchain.info/q/getblockcount"
    eth_fb = "https://api.etherscan.io/api?module=proxy&action=eth_blockNumber&apikey=KEY"

    def fake_async_client():
        class C:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url, timeout=10):
                if url == main_url:
                    raise RuntimeError("main down")
                if url == eth_fb:
                    return DummyResp(json_data={"result": hex(0x55)})
                raise AssertionError("Unexpected URL")

        return C()

    monkeypatch.setattr(httpx, "AsyncClient", fake_async_client)
    rec = await fetch_txcount("BTC", etherscan_api_key="KEY")
    assert rec is not None and rec["value"] == 0x55
    metrics_text = generate_latest().decode()
    val = _fallback_metric_value(metrics_text, "onchain_txcount", "success")
    assert val is not None and val >= 1
    events = _parsed_events(log_buffer)
    assert any(e.get("event") == "onchain_fallback_success" and e.get("fallback") == 1 for e in events)


# --- DERIVATIVES (open interest) fallback test ---
@pytest.mark.asyncio
async def test_derivatives_oi_fallback_metrics(monkeypatch, log_buffer):
    cache.clear()
    try:
        import pipeline.circuit_breaker as cb

        cb.reset("deriv_oi")  # Assure un état neutre (évite pollution de tests précédents)
    except Exception:
        pass
    bybit_url = "https://api.bybit.com/v5/market/open-interest"
    binance_url = "https://fapi.binance.com/futures/data/openInterestHist"

    class DummyResp:
        def __init__(self, json_data=None, status=200):
            self._json = json_data or {}
            self.status_code = status

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("boom", request=None, response=None)

        def json(self):
            return self._json

    # Async client mock
    def fake_async_client():
        class C:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url, params=None, timeout=10):
                if url == bybit_url:
                    raise RuntimeError("bybit down")
                if url == binance_url:
                    return DummyResp(json_data=[{"timestamp": 1234567890, "sumOpenInterest": "4567.89"}])
                raise AssertionError("Unexpected URL")

        return C()

    monkeypatch.setattr(httpx, "AsyncClient", fake_async_client)

    rec = await fetch_bybit_oi("BTCUSDT")
    assert rec is not None and rec["value"] == 4567.89 and rec["source"] == "binance"
    metrics_text = generate_latest().decode()
    val = _fallback_metric_value(metrics_text, "deriv_oi", "success")
    assert val is not None and val >= 1
    events = _parsed_events(log_buffer)
    assert any(e.get("event") == "deriv_fallback_success" and e.get("fallback") == 1 for e in events)


# --- MARKET fallback error (double échec) ---
def test_market_fallback_error_metrics(monkeypatch, log_buffer):
    symbol = "brokenasset"
    cg_url = f"https://api.coingecko.com/api/v3/coins/{symbol}"
    cmc_url = f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest?symbol={symbol.upper()}"
    cache.clear()

    def fake_get(url, *a, **k):
        if url in (cg_url, cmc_url):
            raise RuntimeError("both fail")
        raise AssertionError("Unexpected URL")

    monkeypatch.setattr(httpx, "get", fake_get)
    res = fetch_market(symbol)
    assert res is None
    metrics_text = generate_latest().decode()
    val = _fallback_metric_value(metrics_text, "market", "error")
    assert val is not None and val >= 1
    events = _parsed_events(log_buffer)
    assert any(e.get("event") == "market_fallback_error" and e.get("fallback") == 1 for e in events)


# --- DERIVATIVES open interest fallback error ---
@pytest.mark.asyncio
async def test_derivatives_oi_fallback_error_metrics(monkeypatch, log_buffer):
    cache.clear()
    bybit_url = "https://api.bybit.com/v5/market/open-interest"
    binance_url = "https://fapi.binance.com/futures/data/openInterestHist"

    def fake_async_client():
        class C:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url, params=None, timeout=10):
                if url in (bybit_url, binance_url):
                    raise RuntimeError("down")
                raise AssertionError("Unexpected URL")

        return C()

    monkeypatch.setattr(httpx, "AsyncClient", fake_async_client)
    rec = await fetch_bybit_oi("ETHUSDT")
    assert rec is None
    metrics_text = generate_latest().decode()
    val = _fallback_metric_value(metrics_text, "deriv_oi", "error")
    assert val is not None and val >= 1
    events = _parsed_events(log_buffer)
    assert any(e.get("event") == "deriv_fallback_error" and e.get("fallback") == 1 for e in events)
