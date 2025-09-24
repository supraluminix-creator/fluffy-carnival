import os
import csv
import tempfile

from pipeline import metrics
from pipeline.export_utils import export_csv_rows


def test_export_rejection_negative_value(tmp_path):
    rows = [
        {
            'timestamp': '2025-09-22T00:00:00Z',
            'asset': 'BTC',
            'symbol': 'BTCUSDT',
            'chain': '-',
            'metric_name': 'price_usd',
            'value': -100.0,  # devrait être rejeté
            'source': 'test',
            'confidence_score': 0.9,
        },
        {
            'timestamp': '2025-09-22T00:00:01Z',
            'asset': 'BTC',
            'symbol': 'BTCUSDT',
            'chain': '-',
            'metric_name': 'price_usd',
            'value': 45000.0,  # valide
            'source': 'test',
            'confidence_score': 0.95,
        },
    ]
    target = tmp_path / 'out.csv'
    count = export_csv_rows(rows, str(target))
    assert count == 1

    # Vérifier que compteur rejet incrémenté
    rejected_neg = metrics.EXPORT_VALUE_NEGATIVE_TOTAL.labels(metric_name='price_usd')._value.get()  # type: ignore
    assert rejected_neg >= 1
    rejected_total = metrics.EXPORT_ROW_REJECTIONS_TOTAL.labels(reason='negative_value')._value.get()  # type: ignore
    assert rejected_total >= 1


def test_export_rejection_pydantic(tmp_path):
    rows = [
        {
            'timestamp': '2025-09-22T00:00:00Z',
            'asset': 'BTC',
            'symbol': 'BTCUSDT',
            'chain': '-',
            'metric_name': 'price_usd',
            'value': 45000.0,
            'source': 'test',
            'confidence_score': 2.5,  # invalide (>1)
        }
    ]
    target = tmp_path / 'out_invalid.csv'
    count = export_csv_rows(rows, str(target))
    assert count == 0
    rejected_pyd = metrics.EXPORT_ROW_REJECTIONS_TOTAL.labels(reason='pydantic')._value.get()  # type: ignore
    assert rejected_pyd >= 1
