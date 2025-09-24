from pathlib import Path
from pipeline.export_utils import export_csv_rows


def test_export_validation_success(tmp_path):
    rows = [
        {
            "timestamp": "2025-09-22T00:00:00Z",
            "asset": "BTC",
            "symbol": "BTCUSDT",
            "chain": "-",
            "metric_name": "open_interest",
            "value": 123.45,
            "source": "binance",
            "confidence_score": 0.85,
        }
    ]
    out = tmp_path / "ok.csv"
    written = export_csv_rows(rows, out.as_posix())
    assert written == 1
    assert out.exists()


def test_export_validation_filters_invalid(tmp_path):
    rows = [
        {  # invalid confidence_score >1
            "timestamp": "2025-09-22T00:00:00Z",
            "asset": "BTC",
            "symbol": "BTCUSDT",
            "chain": "-",
            "metric_name": "open_interest",
            "value": 123.45,
            "source": "binance",
            "confidence_score": 1.5,
        }
    ]
    out = tmp_path / "invalid.csv"
    written = export_csv_rows(rows, out.as_posix())
    assert written == 0
    assert not out.exists() or out.read_text(encoding="utf-8").strip() == ""