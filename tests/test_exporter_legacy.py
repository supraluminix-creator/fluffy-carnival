from datetime import UTC, datetime

import pandas as pd
import pytest

from pipeline.exporter import Exporter


def test_exporter_writes_latest_and_timestamped(tmp_path):
    exporter = Exporter(str(tmp_path))
    ts = datetime(2024, 1, 1, 12, 30, 0, tzinfo=UTC)
    rows = [
        {"asset": "BTC", "value": 42000},
        {"asset": "ETH", "value": 3200},
    ]
    fieldnames = ["asset", "value"]

    latest_path = exporter.export(rows, fieldnames, timestamp=ts)

    assert latest_path == str(tmp_path / "latest_export.csv")
    latest_df = pd.read_csv(latest_path)
    assert list(latest_df.columns) == fieldnames
    assert latest_df.shape == (2, 2)

    dated_name = f"pipeline_export_{ts.strftime('%Y%m%d_%H%M%S_UTC')}.csv"
    dated_path = tmp_path / dated_name
    assert dated_path.exists()
    dated_df = pd.read_csv(dated_path)
    assert dated_df.equals(latest_df)


def test_exporter_requires_rows(tmp_path):
    exporter = Exporter(str(tmp_path))
    with pytest.raises(ValueError):
        exporter.export([], ["col"])


def test_exporter_requires_fieldnames(tmp_path):
    exporter = Exporter(str(tmp_path))
    rows = [{"col": "value"}]
    with pytest.raises(ValueError):
        exporter.export(rows, [])


def test_exporter_defaults_timestamp(tmp_path):
    exporter = Exporter(str(tmp_path))
    rows = [{"asset": "BTC", "value": 1}]
    fieldnames = ["asset", "value"]

    path = exporter.export(rows, fieldnames)

    assert path == str(tmp_path / "latest_export.csv")
    dated_files = list(tmp_path.glob("pipeline_export_*.csv"))
    assert dated_files, "timestamped export should be created"
