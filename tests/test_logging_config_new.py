import os
import json
import structlog
import pytest

from pipeline.logging_config import setup_logging, _reset_logging_for_tests


def test_setup_logging_idempotent(monkeypatch, capsys):
    _reset_logging_for_tests()
    monkeypatch.setenv('LOG_LEVEL', 'INFO')
    logger1 = setup_logging(simple=True)
    run_id = os.getenv('RUN_ID')
    logger2 = setup_logging(simple=True)
    assert logger1 is not None and logger2 is not None
    assert os.getenv('RUN_ID') == run_id


def test_logging_event_key(monkeypatch, capsys):
    _reset_logging_for_tests()
    logger = setup_logging(simple=True)
    logger.info('custom_event', answer=42)
    captured = capsys.readouterr().out.strip().splitlines()
    # Dernière ligne JSON doit contenir "event":"custom_event"
    assert any('"event": "custom_event"' in line for line in captured)
