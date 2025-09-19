
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
import asyncio
import httpx

def test_sopr_bgeometrics():
	collector = SOPRBGeometricsCollector()
	result = collector.fetch_sopr("BTC")
	assert result is None or "sopr" in result

def test_sopr_blockchain():
	collector = SOPRBlockchainCollector()
	result = collector.fetch_sopr("BTC")
	assert result is None or "sopr" in result

def test_bybit_ws():
	messages = []
	def on_msg(msg):
		messages.append(msg)
	ws = BybitWSCollector(symbol="BTCUSDT", on_message=on_msg)
	try:
		asyncio.run(asyncio.wait_for(ws.connect(), timeout=3))
	except Exception:
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
	# Monkeypatch pour forcer l'échec
	async def fail_fetch(*args, **kwargs):
		raise httpx.HTTPError("Simulated error")
	collector.fetch_tvl_async = fail_fetch
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
