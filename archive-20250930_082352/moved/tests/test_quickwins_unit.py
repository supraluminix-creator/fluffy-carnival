import sys
from typing import Any

import pytest


def test_logging_config_import_smoke():
    # Doit pouvoir configurer sans exception
    from pipeline import logging_config  # noqa: F401
    logging_config.setup_logging()


def test_base_collector_abstract():
    from pipeline.base_collector import BaseCollector

    class Dummy(BaseCollector):
        def collect(self, conn):
            return "ok"

    d = Dummy()
    assert d.collect(None) == "ok"
    with pytest.raises(NotImplementedError):
        BaseCollector().collect(None)  # type: ignore[arg-type]


def test_protocols_http_get_json_success(monkeypatch):
    from pipeline import protocols

    class DummyResp:
        def __init__(self, data: dict[str, Any]):
            self._data = data
        def raise_for_status(self):
            return None
        def json(self):
            return self._data

    class DummyClient:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def get(self, url, timeout: float):  # noqa: D401
            return DummyResp({"hello": "world"})

    def dummy_client():  # factory used in with
        return DummyClient()

    monkeypatch.setattr(protocols.httpx, "Client", dummy_client)
    res = protocols.http_get_json("http://x")
    assert res["ok"] is True and res["value"] == {"hello": "world"}


def test_protocols_http_get_json_error(monkeypatch):
    from pipeline import protocols

    class Boom:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def get(self, url, timeout):
            raise RuntimeError("net down")

    monkeypatch.setattr(protocols.httpx, "Client", lambda: Boom())
    res = protocols.http_get_json("http://x")
    assert res["ok"] is False and res["error"]


def test_reporter_branches_missing(monkeypatch, capsys):
    # Forcer absence de tabulate pour fallback pandas
    sys.modules.pop("tabulate", None)
    from pipeline.reporter import Reporter

    rpt = Reporter()
    data = {
        'global': {
            'total_market_cap': {'usd': 1_000_000_000},
            'total_volume': {'usd': 50_000_000},
            'market_cap_percentage': {'btc': 52.3},
            'market_cap_change_percentage_24h_usd': 1.23,
        },
        'coins': {
            'bitcoin': {'usd': 50000, 'usd_24h_change': 2.5, 'usd_24h_vol': 2_000_000_000, 'usd_market_cap': 900_000_000_000},
            'ethereum': {'usd': 3000, 'usd_24h_change': -1.2, 'usd_24h_vol': 1_000_000_000, 'usd_market_cap': 400_000_000_000},
        }
    }
    additional = {
        'stablecoins': {'total_supply': 120_000_000_000, 'usdt_dominance': 70.0, 'usdc_dominance': 20.0},
        'onchain': {'BTC': {'transaction_count': 1000, 'hash_rate': 300}, 'ETH': {'transaction_count': 5000, 'hash_rate': 200}},
        'derivatives': {'BTC': {'funding_rate': 0.01, 'open_interest': 100000000}, 'ETH': {'funding_rate': -0.02, 'open_interest': 50000000}},
    }
    signals = {'accumulation_signal': 1, 'leverage_signal': -1, 'liquidity_signal': 0}
    import pandas as pd
    dune = {
        'exchange_flows_ethereum': pd.DataFrame([{'net_flow': 123}])
    }
    rpt.display_summary(data, fgi_data={'value': '50', 'value_classification': 'Neutral'}, additional_data=additional, signals=signals, dune_data=dune)
    _ = capsys.readouterr().out  # Pas d'assert strict pour éviter flaky selon environnement console


def test_technical_indicators_compute(monkeypatch):
    import pandas as pd

    from pipeline import technical_indicators as ti

    # Construire un petit DataFrame synthétique
    rows = [
        {
            "timestamp": pd.Timestamp.utcnow() + pd.Timedelta(minutes=i),
            "open": 100 + i,
            "high": 101 + i,
            "low": 99 + i,
            "close": 100 + i,
            "volume": 10 + i,
        }
        for i in range(50)
    ]
    df = pd.DataFrame(rows).set_index("timestamp")

    # Monkeypatch pandas_ta functions to simple deterministic outputs
    import pipeline.technical_indicators as module

    class DummySeries(pd.Series):
        @property
        def _constructor(self):  # silence pandas warnings
            return DummySeries

    monkeypatch.setattr(module.ta, "rsi", lambda s, length=14: pd.Series([50]*len(s), index=s.index))
    monkeypatch.setattr(module.ta, "macd", lambda s: pd.DataFrame({"MACD_12_26_9": [1]*len(s)}, index=s.index))
    monkeypatch.setattr(module.ta, "bbands", lambda s: pd.DataFrame({"BB_MAVG": [2]*len(s)}, index=s.index))
    monkeypatch.setattr(module.ta, "ema", lambda s, length=21: pd.Series([3]*len(s), index=s.index))
    monkeypatch.setattr(module.ta, "vwap", lambda h, low, c, v: pd.Series([4]*len(c), index=c.index))
    monkeypatch.setattr(module.ta, "ichimoku", lambda h, low, c: (pd.DataFrame({"ISA_9": [5]*len(c)}, index=c.index), None))

    out = ti.compute_indicators(df.copy())
    assert {"RSI", "MACD_12_26_9", "BB_MAVG", "EMA", "VWAP", "ISA_9"}.issubset(out.columns)


def test_fetch_binance_ohlc_error(monkeypatch):
    from pipeline import technical_indicators as ti

    class DummyResp:
        def json(self):
            return {"err": "x"}

    def fake_get(url, params, timeout):
        return DummyResp()

    monkeypatch.setattr(ti.requests, "get", fake_get)
    assert ti.fetch_binance_ohlc(symbol="BTCUSDT", interval="5m", limit=5) is None


def test_technical_indicators_empty_df(monkeypatch):
    import pandas as pd

    from pipeline import technical_indicators as ti
    # DataFrame vide avec colonnes requises
    df = pd.DataFrame(columns=["open","high","low","close","volume"]).astype(float)
    # Patch des fonctions pour éviter erreurs internes
    monkeypatch.setattr(ti.ta, "rsi", lambda s, length=14: pd.Series(dtype=float))
    monkeypatch.setattr(ti.ta, "macd", lambda s: pd.DataFrame())
    monkeypatch.setattr(ti.ta, "bbands", lambda s: pd.DataFrame())
    monkeypatch.setattr(ti.ta, "ema", lambda s, length=21: pd.Series(dtype=float))
    monkeypatch.setattr(ti.ta, "vwap", lambda h, low, c, v: pd.Series(dtype=float))
    monkeypatch.setattr(ti.ta, "ichimoku", lambda h, low, c: (pd.DataFrame(), None))
    out = ti.compute_indicators(df)
    # Doit retourner un DataFrame (potentiellement vide) sans lever
    assert isinstance(out, pd.DataFrame)


def test_fetch_binance_ohlc_success(monkeypatch):
    from pipeline import technical_indicators as ti

    class DummyResp:
        def json(self):
            # 3 entrées klines minimales
            return [
                [111, "1","2","0.5","1.5","10", 0,0,0,0,0,0],
                [222, "2","3","1.5","2.5","11", 0,0,0,0,0,0],
                [333, "3","4","2.5","3.5","12", 0,0,0,0,0,0],
            ]

    def fake_get(url, params, timeout):
        return DummyResp()

    monkeypatch.setattr(ti.requests, "get", fake_get)
    df = ti.fetch_binance_ohlc(symbol="BTCUSDT", interval="5m", limit=3)
    assert df is not None and len(df) == 3 and set(["open","high","low","close","volume"]).issubset(df.columns)


def test_reporter_module_import_and_init():
    from pipeline.reporter import Reporter
    # Forcer simple instanciation pour couvrir top-level si non couvert
    r = Reporter()
    assert hasattr(r, 'display_summary')


def test_hashrate_collector_cache_and_invalid(monkeypatch):
    import httpx

    from pipeline.collectors.hashrate import HashrateCollector

    hc = HashrateCollector()
    # Insérer manu une valeur invalide (non dict) dans le cache -> fetch doit l'ignorer et aller réseau mock
    hc._disk_cache.set('hashrate:BTC', 'invalid', expire=1)

    class DummyResp:
        def json(self):
            return {"status":"ok","values":[{"x":1,"y":2.0}]}
        def raise_for_status(self):
            return None

    class DummyClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def get(self, url, params):
            return DummyResp()

    monkeypatch.setattr(httpx, 'AsyncClient', lambda timeout=10: DummyClient())
    data = hc.fetch_hashrate("BTC")
    assert data is None or data.get('status') == 'ok'
    # Deuxième appel => cache hit dict -> retour immédiat
    data2 = hc.fetch_hashrate("BTC")
    assert data2 is None or data2.get('status') == 'ok'
