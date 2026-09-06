from datetime import UTC, datetime

import pytest

from pipeline.exporter import Exporter


def test_exporter_no_rows(tmp_path):
    ex = Exporter(export_dir=str(tmp_path))
    with pytest.raises(ValueError):
        ex.export([], fieldnames=["a"])


def test_exporter_no_fieldnames(tmp_path):
    ex = Exporter(export_dir=str(tmp_path))
    with pytest.raises(ValueError):
        ex.export([{"a": 1}], fieldnames=[])


def test_exporter_success(tmp_path):
    ex = Exporter(export_dir=str(tmp_path))
    path = ex.export([{"a": 1}], fieldnames=["a"], timestamp=datetime(2025, 1, 1, tzinfo=UTC))
    assert "latest_export.csv" in path
