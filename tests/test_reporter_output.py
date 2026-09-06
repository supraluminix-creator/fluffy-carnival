import io

import pandas as pd

import pipeline.reporter as reporter_module
from pipeline.reporter import Reporter


def test_reporter_display_summary(monkeypatch):
    monkeypatch.setattr(reporter_module, "tabulate", None)
    reporter = Reporter()
    buffer = io.StringIO()

    data = {
        "global": {
            "total_market_cap": {"usd": 2_000_000_000_000},
            "total_volume": {"usd": 120_000_000_000},
            "market_cap_percentage": {"btc": 52.3},
            "market_cap_change_percentage_24h_usd": 1.7,
        },
        "coins": {
            "bitcoin": {
                "usd": 42800,
                "usd_24h_change": 2.5,
                "usd_24h_vol": 58_000_000_000,
                "usd_market_cap": 830_000_000_000,
            },
            "ethereum": {
                "usd": 3200,
                "usd_24h_change": -1.2,
                "usd_24h_vol": 24_000_000_000,
                "usd_market_cap": 380_000_000_000,
            },
            "solana": {
                "usd": 150,
                "usd_24h_change": 0.8,
                "usd_24h_vol": 4_500_000_000,
                "usd_market_cap": 60_000_000_000,
            },
            "chainlink": {
                "usd": 12.5,
                "usd_24h_change": -0.4,
                "usd_24h_vol": 1_200_000_000,
                "usd_market_cap": 8_000_000_000,
            },
        },
    }

    additional_data = {
        "stablecoins": {"total_supply": 132_000_000_000, "usdt_dominance": 74.3, "usdc_dominance": 18.5},
        "onchain": {"BTC": {"transaction_count": 312000, "hash_rate": 435.2}},
        "derivatives": {"BTC": {"funding_rate": 0.015, "open_interest": 12_400_000_000}},
    }

    dune_data = {
        "exchange_flows_ethereum": pd.DataFrame([{"net_flow": "15M"}]),
        "bitcoin_cex_reserves": pd.DataFrame([{"reserves": "25k"}]),
    }

    signals = {
        "accumulation_signal": 2,
        "leverage_signal": -3,
        "liquidity_signal": 0,
    }

    fgi_data = {"value": "80", "value_classification": "Extreme Greed"}

    reporter.display_summary(
        data,
        fgi_data=fgi_data,
        additional_data=additional_data,
        signals=signals,
        dune_data=dune_data,
        stream=buffer,
    )

    output = buffer.getvalue()
    assert "CRYPTO MONITOR" in output
    assert "Stablecoins" in output
    assert "Flux nets Ethereum" in output
    assert "Réserves BTC CEX" in output
    assert "🚦 SIGNALS" in output
    assert "🎭 SENTIMENT" in output
    assert "BTC Dominance" in output


def test_reporter_signal_emoji_values():
    reporter = Reporter()
    assert reporter.get_signal_emoji(2) == "🟢"
    assert reporter.get_signal_emoji(-1) == "🔴"
    assert reporter.get_signal_emoji(0) == "🟡"
