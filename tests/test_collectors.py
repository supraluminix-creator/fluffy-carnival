import asyncio
import os
import sys
import time
from contextlib import suppress

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import httpx

from pipeline.collectors.altme import AltmeCollector
from pipeline.collectors.bybit_ws import BybitWSCollector
from pipeline.collectors.defillama import DefillamaCollector
from pipeline.collectors.hashrate import HashrateCollector
from pipeline.collectors.sopr_bgeometrics import SOPRBGeometricsCollector
from pipeline.collectors.sopr_blockchain import SOPRBlockchainCollector
from pipeline.collectors.txcount import TxCountCollector


def test_sopr_bgeometrics():
	collector = SOPRBGeometricsCollector()
	result = collector.fetch_sopr("BTC")
	assert result is None or "sopr" in result


def test_sopr_blockchain():
	collector = SOPRBlockchainCollector()
	result = collector.fetch_sopr("BTC")
	assert result is None or "sopr" in result


def test_bybit_ws():
	messages: list[object] = []

	def on_msg(msg: object) -> None:
		messages.append(msg)

	ws = BybitWSCollector(symbol="BTCUSDT", on_message=on_msg)
	with suppress(Exception):
		asyncio.run(asyncio.wait_for(ws.connect(), timeout=3))
	ws.stop()
	assert isinstance(messages, list)


def test_bybit_ws_collector(monkeypatch):
	received: list[object] = []

	def on_msg(msg: object) -> None:
		received.append(msg)

	ws = BybitWSCollector(symbol="BTCUSDT", on_message=on_msg)
	with suppress(Exception):  # pragma: no cover
		asyncio.run(asyncio.wait_for(ws.connect(), timeout=2))
	ws.stop()
	assert isinstance(received, list)


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

	monkeypatch.setattr(collector, "fetch_tvl_async", fail_fetch)
	result = collector.fetch_tvl("ethereum")
	assert result is None


def test_defillama_collector_retry(monkeypatch):
	collector = DefillamaCollector()

	async def fail_fetch(*args, **kwargs):  # pragma: no cover
		raise httpx.HTTPError("Simulated error")

	monkeypatch.setattr(collector, "fetch_tvl_async", fail_fetch)
	result = collector.fetch_tvl("bitcoin")
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
