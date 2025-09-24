from pathlib import Path
from pipeline.export_utils import EXPORT_FIELDS, export_csv_rows
import csv

SNAPSHOT_FILE = Path("tests/_snapshots/export_columns.txt")


def test_export_columns_snapshot():
    columns_current = list(EXPORT_FIELDS)
    assert SNAPSHOT_FILE.exists(), "Snapshot des colonnes manquant: crée le fichier tests/_snapshots/export_columns.txt"
    snapshot_columns = SNAPSHOT_FILE.read_text(encoding="utf-8").strip().splitlines()
    assert snapshot_columns == columns_current, (
        "Export columns contract changed.\n"
        f"Expected snapshot: {snapshot_columns}\nCurrent: {columns_current}\n"
        "Si le changement est intentionnel: mettre à jour le snapshot consciencieusement."
    )


def test_export_csv_row_order_and_header(tmp_path):
    rows = [
        {
            "timestamp": "2025-09-22T00:00:00Z",
            "asset": "BTC",
            "symbol": "BTCUSDT",
            "chain": "-",
            "metric_name": "open_interest",
            "value": 123.45,
            "source": "binance",
            "confidence_score": 0.9,
        }
    ]
    out = tmp_path / "out.csv"
    export_csv_rows(rows, out.as_posix())
    content = out.read_text(encoding="utf-8").splitlines()
    header = content[0].split(",")
    assert header == list(EXPORT_FIELDS)
    with open(out, newline="", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
    assert reader[0]["metric_name"] == "open_interest"
