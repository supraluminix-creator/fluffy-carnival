import csv

from pipeline.export_utils import export_csv_rows


def test_export_normalization_infers_asset_symbol_from_chain(tmp_path):
    rows = [
        {
            # timestamp intentionally missing -> should be auto-filled
            # asset/symbol missing -> should be inferred from chain
            "chain": "Ethereum",
            "metric_name": "defi_tvl",
            "value": {"tvl": 1234.56},
            # source missing -> should default to metric_name
            # confidence_score missing -> default 1.0
        }
    ]
    out = tmp_path / "norm_chain.csv"
    written = export_csv_rows(rows, out.as_posix())
    assert written == 1
    assert out.exists()

    with out.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        recs = list(reader)
    assert len(recs) == 1
    rec = recs[0]
    assert rec["asset"] == "Ethereum"
    assert rec["symbol"] == "Ethereum"
    assert rec["chain"] == "Ethereum"
    assert rec["metric_name"] == "defi_tvl"
    assert float(rec["value"]) == 1234.56
    # source defaulted from metric_name
    assert rec["source"] == "defi_tvl"
    # confidence_score defaulted to 1.0
    assert float(rec["confidence_score"]) == 1.0


def test_export_normalization_defaults_btc_for_fear_greed(tmp_path):
    rows = [
        {
            # all of asset/symbol/chain missing -> should default to BTC for fear/greed metrics
            "metric_name": "fear_greed_index",
            "value": {"value": "45"},  # numeric string in nested dict
            "timestamp": "2025-09-22T00:00:00Z",
        }
    ]
    out = tmp_path / "norm_btc.csv"
    written = export_csv_rows(rows, out.as_posix())
    assert written == 1
    assert out.exists()

    with out.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        recs = list(reader)
    assert len(recs) == 1
    rec = recs[0]
    assert rec["asset"] == "BTC"
    assert rec["symbol"] == "BTC"
    assert rec["chain"] == "-"  # default when chain absent
    assert rec["metric_name"] == "fear_greed_index"
    assert float(rec["value"]) == 45.0
    assert rec["source"] == "fear_greed_index"
    assert float(rec["confidence_score"]) == 1.0
