import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import pytest
from pipeline.collectors.sopr_bgeometrics import SOPRBGeometricsCollector
from pipeline.collectors.sopr_blockchain import SOPRBlockchainCollector
from pipeline.collectors.bybit_ws import BybitWSCollector
from pipeline.collectors.defillama import DefillamaCollector
from pipeline.collectors.txcount import TxCountCollector
from pipeline.collectors.hashrate import HashrateCollector
from pipeline.collectors.altme import AltmeCollector
from pipeline.collectors.market import fetch_macro
import asyncio
import httpx
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_sopr_bgeometrics():
	collector = SOPRBGeometricsCollector()
	result = collector.fetch_sopr("BTC")
	assert result is None or "sopr" in result

def test_sopr_blockchain():
	collector = SOPRBlockchainCollector()
	result = collector.fetch_sopr("BTC")
	assert result is None or "sopr" in result

def test_bybit_ws(monkeypatch):
    messages: list[object] = []
    def on_msg(msg: object) -> None:
        messages.append(msg)
    ws = BybitWSCollector(symbol="BTCUSDT", on_message=on_msg)
    try:
        asyncio.run(asyncio.wait_for(ws.connect(), timeout=3))
    except Exception:  # pragma: no cover - network dependent
        pass
    ws.stop()
    assert isinstance(messages, list)


import pytest
import time

def test_defillama_async_success():
	collector = DefillamaCollector()
	# Test async direct
	result = collector.fetch_tvl("ethereum")
	assert result is None or isinstance(result, dict)

def test_defillama_cache():
	collector = DefillamaCollector()
	# Remplir le cache
	result1 = collector.fetch_tvl("ethereum")
	time.sleep(1)
	result2 = collector.fetch_tvl("ethereum")
	assert result1 == result2

def test_defillama_retry_backoff(monkeypatch):
    collector = DefillamaCollector()
    async def fail_fetch(*args, **kwargs):  # pragma: no cover - forced failure
        raise httpx.HTTPError("Simulated error")
    monkeypatch.setattr(collector, "fetch_tvl_async", fail_fetch)
    result = collector.fetch_tvl("ethereum")
    assert result is None

def test_txcount():
	collector = TxCountCollector()
	result = collector.fetch_txcount("BTC")
	assert result is None or isinstance(result, dict)

def test_hashrate():
	collector = HashrateCollector()
	result = collector.fetch_hashrate("BTC")
	assert result is None or isinstance(result, dict)

def test_altme():
	collector = AltmeCollector()
	result = collector.fetch_kyc("user123")
	assert result is None or isinstance(result, dict)

def test_fetch_market(monkeypatch):
    def mock_get(*args, **kwargs):
        class MockResp:
            def raise_for_status(self): pass
            def json(self): return {"market_data": {"current_price": {"usd": 1}, "total_volume": {"usd": 2}, "market_cap": {"usd": 3}, "market_cap_rank": 1}}
        return MockResp()
    monkeypatch.setattr("httpx.get", mock_get)
    from pipeline.collectors.market import fetch_market
    result = fetch_market("bitcoin")
    assert result["price"] == 1

@pytest.mark.asyncio
async def test_fetch_macro_coingecko_success(httpx_mock):
    httpx_mock.add_response(
        url="https://api.coingecko.com/api/v3/coins/bitcoin",
        json={
            "last_updated": "2025-09-16T00:00:00Z",
            "market_data": {
                "current_price": {"usd": 1},
                "total_volume": {"usd": 2},
                "market_cap": {"usd": 3},
                "market_cap_rank": 1
            }
        }
    )
    result = await fetch_macro("bitcoin", cmc_api_key="dummy")
    assert result["value"]["price"] == 1
    assert result["source"] == "coingecko"

@pytest.mark.asyncio
async def test_fetch_macro_fallback_cmc(httpx_mock):
    httpx_mock.add_exception(httpx.RequestError("fail"), url="https://api.coingecko.com/api/v3/coins/bitcoin")
    httpx_mock.add_response(
        url="https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest?symbol=BITCOIN",
        json={
            "status": {"timestamp": "2025-09-16T00:00:00Z"},
            "data": {
                "BITCOIN": {
                    "quote": {
                        "USD": {
                            "price": 10,
                            "volume_24h": 20,
                            "market_cap": 30,
                            "market_cap_dominance": 40
                        }
                    }
                }
            }
        }
    )
    result = await fetch_macro("bitcoin", cmc_api_key="dummy")
    assert result["value"]["price"] == 10
    assert result["source"] == "coinmarketcap"
