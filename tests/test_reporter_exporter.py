
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from pipeline.reporter import Reporter
from pipeline.exporter import Exporter
from datetime import datetime
import os

# Dummy data for reporter
DATA = {
    'global': {
        'total_market_cap': {'usd': 2_000_000_000_000},
        'total_volume': {'usd': 100_000_000_000},
        'market_cap_percentage': {'btc': 52.3},
        'market_cap_change_percentage_24h_usd': 1.25
    },
    'coins': {
        'bitcoin': {'usd': 26000, 'usd_24h_change': 2.5, 'usd_24h_vol': 5000000000, 'usd_market_cap': 500000000000},
        'ethereum': {'usd': 1600, 'usd_24h_change': -1.2, 'usd_24h_vol': 3000000000, 'usd_market_cap': 200000000000}
    }
}
FGI_DATA = {'value': '60', 'value_classification': 'Greed'}
ADDITIONAL_DATA = {
    'stablecoins': {'total_supply': 120_000_000_000, 'usdt_dominance': 70.1, 'usdc_dominance': 20.2},
    'onchain': {'BTC': {'transaction_count': 250000, 'hash_rate': 120}, 'ETH': {'transaction_count': 120000, 'hash_rate': 80}},
    'derivatives': {'BTC': {'funding_rate': 0.0002, 'open_interest': 10000000}, 'ETH': {'funding_rate': -0.0001, 'open_interest': 5000000}}
}
SIGNALS = {'accumulation_signal': 1, 'leverage_signal': -1, 'liquidity_signal': 1}
DUNE_DATA = {}



import io

def test_reporter_display_summary():
    reporter = Reporter()
    buf = io.StringIO()
    reporter.display_summary(DATA, FGI_DATA, ADDITIONAL_DATA, SIGNALS, DUNE_DATA, stream=buf)
    output = buf.getvalue()
    assert "CRYPTO MONITOR" in output
    assert "BTC" in output
    assert "ETH" in output
    assert "Greed" in output
    assert "SIGNALS" in output


def test_exporter_csv(tmp_path):
    exporter = Exporter(export_dir=str(tmp_path))
    rows = [
        {'timestamp': '2025-09-15T12:00:00', 'symbol': 'BTC', 'price': 26000},
        {'timestamp': '2025-09-15T12:00:00', 'symbol': 'ETH', 'price': 1600}
    ]
    fieldnames = ['timestamp', 'symbol', 'price']
    ts = datetime(2025, 9, 15, 12, 0, 0)
    latest_path = exporter.export(rows, fieldnames, timestamp=ts)
    assert os.path.exists(latest_path)
    with open(latest_path, encoding='utf-8') as f:
        content = f.read()
        assert 'BTC' in content
        assert 'ETH' in content
        assert 'timestamp' in content
