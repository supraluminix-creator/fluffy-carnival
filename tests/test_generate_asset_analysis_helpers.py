from __future__ import annotations

import pandas as pd
import pytest

from scripts.generate_asset_analysis import (
    _compute_rsi,
    _format_orderbook_zone,
    _lsr_note,
    _pct_change,
    _rsi_note,
    _sopr_note,
)


def test_pct_change_basic():
    assert _pct_change(120.0, 100.0) == pytest.approx(20.0)
    assert _pct_change(80.0, 100.0) == pytest.approx(-20.0)
    assert _pct_change(100.0, 0.0) is None
    assert _pct_change(None, 100.0) is None


def test_compute_rsi_trending_up():
    series = pd.Series(range(1, 60), dtype=float)
    value = _compute_rsi(series, length=14)
    assert value is not None
    assert 50 < value <= 100


def test_format_orderbook_zone():
    zone = {"top": 101.0, "tail": 100.0, "levels": 3}
    text = _format_orderbook_zone(zone, 150_000.0)
    assert "150.00K" in text
    assert "3 lvls" in text
    assert "100.00-101.00" in text


def test_rsi_note_buckets():
    assert "sur-achat" in _rsi_note(75.0)
    assert "sur-vente" in _rsi_note(20.0)
    assert _rsi_note(None) == "N/A"


def test_lsr_note_dominance():
    record = {"value": {"buy_ratio": 65, "sell_ratio": 35}}
    note, buy, sell = _lsr_note(record)
    assert "dominance longs" in note
    assert buy == pytest.approx(65.0)
    assert sell == pytest.approx(35.0)


def test_lsr_note_missing():
    note, buy, sell = _lsr_note(None)
    assert note == "Bybit L/S: N/A"
    assert buy is None and sell is None


def test_sopr_note_ranges():
    hot_note, hot_val = _sopr_note(1.05)
    cold_note, cold_val = _sopr_note(0.95)
    flat_note, flat_val = _sopr_note(1.0)
    assert "prise de profit" in hot_note
    assert "capitulation" in cold_note
    assert "neutre" in flat_note
    assert hot_val == pytest.approx(1.05)
    assert cold_val == pytest.approx(0.95)
    assert flat_val == pytest.approx(1.0)
