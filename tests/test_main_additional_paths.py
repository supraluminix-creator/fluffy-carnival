import asyncio
import builtins
import os
import sys
import types

import pytest

import main as app_main


@pytest.mark.asyncio
async def test_run_scheduler_mode_quick_exit(monkeypatch, tmp_path):
    # Redirect export dir
    monkeypatch.setattr(app_main, 'EXPORT_DIR', str(tmp_path))
    os.makedirs(app_main.EXPORT_DIR, exist_ok=True)

    # Dummy orchestrator returning one successful result
    class DummyOrchestrator:
        def __init__(self, collectors):
            self.collectors = collectors
        async def run_all_collectors(self, timeout=120):  # noqa: ARG002
            return {
                'status': 'completed',
                'successful_results': [{'name': 'c1', 'result': {'timestamp': 't', 'asset':'a','symbol':'s','chain':None,'metric_name':'m','value':1,'source':'x','confidence_score':1.0}}],
                'failed_results': []
            }

    # Dummy scheduler capturing collector
    class DummyScheduler:
        def __init__(self, jitter_percent=0):  # noqa: ARG002
            self.collector = None
            self.started = False
        def add_collector(self, collector, interval_seconds, jitter_percent):  # noqa: ARG002
            self.collector = collector
        async def start(self):
            self.started = True
            # Run collector once
            if self.collector:
                await self.collector.collect()
        async def shutdown(self):
            self.started = False

    monkeypatch.setattr(app_main, 'ParallelOrchestrator', DummyOrchestrator)
    monkeypatch.setattr(app_main, 'CryptoScheduler', DummyScheduler)

    # Force metrics enabled to exercise branch
    os.environ['ENABLE_METRICS'] = '1'
    os.environ['METRICS_PORT'] = '9999'
    # Stub prometheus start
    class DummyProm:
        def __call__(self, port):
            assert port == 9999
    monkeypatch.setitem(sys.modules, 'prometheus_client', types.SimpleNamespace(start_http_server=DummyProm()))

    # Patch asyncio.sleep inside main: allow short sleeps (heartbeat) but stop on loop sleep (10)
    call_state = {'loop_called': False}
    async def fake_sleep(seconds):
        if seconds >= 10 and not call_state['loop_called']:
            call_state['loop_called'] = True
            raise KeyboardInterrupt
        return None
    monkeypatch.setattr(app_main.asyncio, 'sleep', fake_sleep)

    try:
        await app_main.run_scheduler_mode()
    except BaseException as e:  # tolerate KeyboardInterrupt / CancelledError from heartbeat cancel
        import asyncio as _asyncio
        if not isinstance(e, KeyboardInterrupt | _asyncio.CancelledError):
            raise
    # Verify export occurred (latest_export.csv present)
    assert any(p.name.startswith('latest_export') for p in tmp_path.iterdir()) or (
        tmp_path / 'latest_export.csv'
    ).exists()


def test_scheduler_disabled_path(monkeypatch):
    # Ensure build_scheduler is None and scheduler disabled
    monkeypatch.setattr(app_main, 'build_scheduler', None)
    os.environ['ENABLE_SCHEDULER'] = '0'

    # Prevent sys.exit from stopping test (patch function only, keep stdout/stderr)
    import sys as real_sys
    exits = {}
    def fake_exit(code):
        exits['code'] = code
        raise SystemExit(code)
    monkeypatch.setattr(real_sys, 'exit', fake_exit)

    with pytest.raises(SystemExit):
        asyncio.run(app_main.main())
    assert exits.get('code') == 0


def test_legacy_collector_wrapper_failure(monkeypatch):
    # Force failure to cover error branch
    async def failing():
        raise RuntimeError('boom')
    w = app_main.LegacyCollectorWrapper('x', failing)
    with pytest.raises(RuntimeError):
        asyncio.run(w.collect())
    assert w.last_error_time is not None and w.last_success_time is None


def test_export_csv_error(monkeypatch, tmp_path):
    # Trigger error by making open raise
    monkeypatch.chdir(tmp_path)
    data = [{'timestamp':1,'asset':'a','symbol':'s','chain':None,'metric_name':'m','value':1,'source':'x','confidence_score':1.0}]
    opened = {'called': False}
    real_open = builtins.open
    def fake_open(*args, **kwargs):  # noqa: ARG001
        opened['called'] = True
        raise OSError('disk full')
    monkeypatch.setattr(builtins, 'open', fake_open)
    app_main.export_csv(data, 'fail.csv')
    monkeypatch.setattr(builtins, 'open', real_open)
    assert opened['called'] is True


def test_safe_print_table_error(monkeypatch):
    # Force tabulate to raise
    def boom(*args, **kwargs):  # noqa: ARG002
        raise ValueError('tabulate fail')
    monkeypatch.setattr(app_main, 'tabulate', boom)
    app_main.safe_print_table('T', [{'a':1}], 'keys')  # Should not raise
