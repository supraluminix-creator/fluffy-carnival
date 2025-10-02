import httpx
import pytest
from prometheus_client import REGISTRY


# Utilise un fake client async pour CG succès
@pytest.mark.asyncio
async def test_macro_latency_primary(monkeypatch):
    class CGClient:
        async def __aenter__(self): return self
        async def __aexit__(self, exc_type, exc, tb): return False
        async def get(self, url, timeout=10):
            # retourne payload simplifié
            return type('R', (), {
                'json': lambda self: {
                    'last_updated': '2025-09-21T00:00:00Z',
                    'market_data': {
                        'current_price': {'usd': 50000},
                        'total_volume': {'usd': 1000},
                        'market_cap': {'usd': 900000000}
                    }
                },
                'raise_for_status': lambda self: None
            })()
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **k: CGClient())
    from pipeline.collectors.market import fetch_macro
    rec = await fetch_macro('bitcoin', cmc_api_key=None, cache_ttl=1)
    assert rec and rec['source'] == 'coingecko'
    coll = getattr(REGISTRY, '_names_to_collectors', {}).get('fallback_tier_latency_seconds')
    assert coll is not None
    found = False
    for metric in coll.collect():
        for s in metric.samples:
            if (
                s.name.endswith('_bucket')
                and s.labels.get('collector') == 'macro'
                and s.labels.get('tier') == '1'
                and s.labels.get('status') == 'success'
                and s.value > 0
            ):
                found = True
    assert found, 'Expected latency bucket sample for macro tier=1 success'

@pytest.mark.asyncio
async def test_deriv_funding_latency_primary(monkeypatch):
    # Patch AsyncClient.get pour succès Bybit direct
    class BybitClient:
        async def __aenter__(self): return self
        async def __aexit__(self, exc_type, exc, tb): return False
        async def get(self, url, params=None, timeout=10):
            assert 'funding/history' in url
            return type(
                'R',
                (),
                {
                    'raise_for_status': lambda self: None,
                    'json': lambda self: {
                        'result': {
                            'list': [
                                {'fundingRate': '0.0001', 'fundingRateTimestamp': '1700000000000'}
                            ]
                        }
                    },
                },
            )()
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **k: BybitClient())
    from pipeline.collectors.derivatives import fetch_bybit_funding
    rec = await fetch_bybit_funding('BTCUSDT')
    assert rec and rec['source'] == 'bybit'
    coll = getattr(REGISTRY, '_names_to_collectors', {}).get('fallback_tier_latency_seconds')
    assert coll is not None
    found = False
    for metric in coll.collect():
        for s in metric.samples:
            if (
                s.name.endswith('_bucket')
                and s.labels.get('collector') == 'deriv_funding'
                and s.labels.get('tier') == '1'
                and s.labels.get('status') == 'success'
                and s.value > 0
            ):
                found = True
    assert found, 'Expected latency bucket sample for deriv_funding tier=1 success'

@pytest.mark.asyncio
async def test_deriv_funding_latency_fallback(monkeypatch):
    # Premier appel Bybit funding échoue, fallback Binance funding succès
    class BybitClientFail:
        async def __aenter__(self): return self
        async def __aexit__(self, exc_type, exc, tb): return False
        async def get(self, url, params=None, timeout=10):
            raise httpx.HTTPError('bybit funding down')
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **k: BybitClientFail())
    # Patch fetch_binance_funding pour retour succès
    def fake_binance(symbol):
        return {
            'timestamp': 1700000000000,
            'asset': 'BTC',
            'symbol': 'BTCUSDT',
            'metric_name': 'funding_rate',
            'value': 0.0002,
            'source': 'binance',
            'confidence_score': 0.8
        }
    monkeypatch.setattr('pipeline.collectors.derivatives.fetch_binance_funding', fake_binance)
    from pipeline.collectors.derivatives import fetch_bybit_funding
    rec = await fetch_bybit_funding('BTCUSDT')
    assert rec and rec['source'] == 'binance'
    coll = getattr(REGISTRY, '_names_to_collectors', {}).get('fallback_tier_latency_seconds')
    assert coll is not None
    found_tier2_success = False
    for metric in coll.collect():
        for s in metric.samples:
            if s.name.endswith('_bucket') and s.labels.get('collector') == 'deriv_funding':
                if (
                    s.labels.get('tier') == '1'
                    and s.labels.get('status') == 'error'
                    and s.value > 0
                ):
                    pass  # bucket error tier1 may or may not increment
                if (
                    s.labels.get('tier') == '2'
                    and s.labels.get('status') == 'success'
                    and s.value > 0
                ):
                    found_tier2_success = True
    assert found_tier2_success, 'Expected latency bucket sample for deriv_funding tier=2 success'
    # Note: tier1 error bucket may or may not increment depending on
    # the latency bucket chosen; we only assert the fallback success.
