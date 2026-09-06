import csv
from datetime import UTC, datetime
from pathlib import Path

from pipeline.exporter import Exporter


def test_exporter_creates_files(tmp_path: Path):
    exp_dir = tmp_path / "exports"
    exporter = Exporter(export_dir=str(exp_dir))
    rows = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    fields = ["a", "b"]
    ts = datetime(2025, 9, 20, 12, 0, 0, tzinfo=UTC)
    latest = exporter.export(rows, fields, timestamp=ts)
    assert Path(latest).exists()
    # Dated file
    dated = exp_dir / "pipeline_export_20250920_120000_UTC.csv"
    assert dated.exists()
    with dated.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        data = list(reader)
    assert data[0]["a"] == "1" and data[1]["b"] == "4"
