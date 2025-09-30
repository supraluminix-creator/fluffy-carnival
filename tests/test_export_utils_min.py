from __future__ import annotations

from pipeline.export_utils import export_csv_rows


def test_export_csv_rows_coercion(tmp_path):
    rows = [
        {"metric_name": "macro_price_usd", "value": {"price": 123.45}, "asset": "BTC", "symbol": "BTC", "source": "t"},
        {"metric_name": "fear_greed", "value": {"value": "60"}, "asset": "BTC", "symbol": "BTC", "source": "t"},
    ]
    out = tmp_path / "out.csv"
    n = export_csv_rows(rows, str(out))
    assert n == 2
    content = out.read_text(encoding="utf-8")
    assert "macro_price_usd" in content
    assert "fear_greed" in content
