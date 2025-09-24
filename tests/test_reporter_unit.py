from io import StringIO
from pipeline.reporter import Reporter


def test_reporter_basic_output():
    rep = Reporter()
    fake_data = {
        'global': {
            'total_market_cap': {'usd': 2_000_000_000_000},
            'total_volume': {'usd': 40_000_000_000},
            'market_cap_percentage': {'btc': 52.3},
            'market_cap_change_percentage_24h_usd': 1.23,
        },
        'coins': {
            'bitcoin': {
                'usd': 100000,
                'usd_24h_change': 2.5,
                'usd_24h_vol': 15_000_000_000,
                'usd_market_cap': 1_000_000_000_000,
            },
            'ethereum': {
                'usd': 6000,
                'usd_24h_change': -1.0,
                'usd_24h_vol': 5_000_000_000,
                'usd_market_cap': 300_000_000_000,
            },
        },
    }
    additional = {
        'onchain': {
            'BTC': {'transaction_count': 100000, 'hash_rate': 250},
            'ETH': {'transaction_count': 500000, 'hash_rate': 800},
        },
        'derivatives': {
            'BTC': {'funding_rate': 0.01, 'open_interest': 123456},
            'ETH': {'funding_rate': -0.005, 'open_interest': 654321},
        }
    }
    signals = {'accumulation_signal': 1, 'leverage_signal': -1, 'liquidity_signal': 0}
    fgi = {'value': '55', 'value_classification': 'Neutral'}

    buf = StringIO()
    rep.display_summary(fake_data, fgi_data=fgi, additional_data=additional, signals=signals, stream=buf)
    out = buf.getvalue()
    # Assertions clés
    assert 'MACRO' in out
    assert 'BTC' in out and 'ETH' in out
    assert 'SIGNALS' in out
    assert 'SENTIMENT' in out

def test_reporter_dune_and_stablecoins():
    rep = Reporter()
    fake_data = {
        'global': {
            'total_market_cap': {'usd': 1},
            'total_volume': {'usd': 1},
            'market_cap_percentage': {'btc': 50},
            'market_cap_change_percentage_24h_usd': 0,
        },
        'coins': {},
    }
    dune_df_like = __import__('pandas').DataFrame([{'net_flow': 123}])
    dune_reserves = __import__('pandas').DataFrame([{'reserves': 456}])
    dune = {
        'exchange_flows_ethereum': dune_df_like,
        'bitcoin_cex_reserves': dune_reserves,
        'ethereum_cex_reserves': dune_reserves,
        'link_cex_reserves': dune_reserves,
    }
    additional = {
        'stablecoins': {
            'total_supply': 10_000_000_000,
            'usdt_dominance': 60.0,
            'usdc_dominance': 30.0,
        }
    }
    buf = __import__('io').StringIO()
    rep.display_summary(fake_data, dune_data=dune, additional_data=additional, stream=buf)
    out = buf.getvalue()
    assert 'Stablecoins' in out
    assert 'Flux nets Ethereum' in out
