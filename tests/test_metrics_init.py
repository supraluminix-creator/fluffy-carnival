import importlib
from pipeline import metrics


def test_metrics_objects_exist():
    # Vérifie existence de quelques métriques clefs
    assert hasattr(metrics, 'EXPORT_ROWS_TOTAL')
    assert hasattr(metrics, 'CIRCUIT_BREAKER_OPEN_TOTAL')
    assert hasattr(metrics, 'CB_RESETS_TOTAL')
    # Reload pour idempotence et couvrir code top-level potentiellement protégé
    importlib.reload(metrics)
    assert hasattr(metrics, 'HEARTBEAT_TICKS_TOTAL')
import os
import os


def test_metrics_init_disabled(monkeypatch):
    from pipeline import metrics as metrics_mod
    monkeypatch.setenv('ENABLE_METRICS', '0')
    assert metrics_mod.init_metrics_if_enabled() is False


def test_metrics_init_enabled_success(monkeypatch):
    from pipeline import metrics as metrics_mod
    monkeypatch.setenv('ENABLE_METRICS', '1')
    monkeypatch.setenv('METRICS_PORT', '9405')
    assert metrics_mod.init_metrics_if_enabled() is True


def test_metrics_init_port_in_use(monkeypatch):
    from pipeline import metrics as metrics_mod
    monkeypatch.setenv('ENABLE_METRICS', '1')
    monkeypatch.setenv('METRICS_PORT', '9505')
    calls = {'n': 0}

    def fake_start(port):  # noqa: D401
        calls['n'] += 1
        if calls['n'] > 1:
            raise OSError('already bound')

    monkeypatch.setattr(metrics_mod, 'start_http_server', fake_start)
    assert metrics_mod.init_metrics_if_enabled() is True
    # Second call should swallow OSError and still return True
    assert metrics_mod.init_metrics_if_enabled() is True
