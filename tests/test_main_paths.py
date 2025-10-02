import os

import pytest

import main as app_main
from pipeline.logging_config import _reset_logging_for_tests


@pytest.mark.asyncio
async def test_run_legacy_collection_monkeypatched(monkeypatch, tmp_path):
    # Patch all network / external collectors imported in main
    async def fake_async_record(*args, **kwargs):
        return {"metric_name": "m", "value": 1, "timestamp": 0}
    def fake_sync_record(*args, **kwargs):
        return {"metric_name": "s", "value": 2, "timestamp": 0}

    monkeypatch.setattr(app_main, 'fetch_macro', fake_async_record)
    monkeypatch.setattr(app_main, 'fetch_txcount', fake_async_record)
    monkeypatch.setattr(app_main, 'fetch_hashrate', fake_async_record)
    monkeypatch.setattr(app_main, 'fetch_sopr', fake_async_record)
    monkeypatch.setattr(app_main, 'fetch_fear_greed', fake_async_record)
    monkeypatch.setattr(app_main, 'fetch_bybit_oi', fake_async_record)
    monkeypatch.setattr(app_main, 'fetch_bybit_long_short_ratio', fake_async_record)
    monkeypatch.setattr(app_main, 'fetch_defillama_tvl', fake_sync_record)

    # Redirect export dir to temp
    monkeypatch.setattr(app_main, 'EXPORT_DIR', str(tmp_path))
    os.makedirs(app_main.EXPORT_DIR, exist_ok=True)

    results = await app_main.run_legacy_collection()
    assert isinstance(results, list)
    assert any(r.get('metric_name') for r in results)


@pytest.mark.asyncio
async def test_main_scheduler_quick_exit(monkeypatch):
    # Force scheduler mode with a dummy build_scheduler
    os.environ['ENABLE_SCHEDULER'] = '1'
    os.environ['CRYPTO_MONITOR_MODE'] = 'scheduler'

    class DummyJob:  # minimal job object
        id = 'job1'

    class DummyScheduler:
        def __init__(self):
            self.started = False
        def start(self):
            self.started = True
        def get_jobs(self):
            return [DummyJob()]
        def shutdown(self, wait=False):
            self.started = False

    monkeypatch.setattr(app_main, 'build_scheduler', lambda: DummyScheduler())

    # Monkeypatch asyncio.sleep inside main module to raise KeyboardInterrupt after first call
    call_state = {'called': False}
    async def fake_sleep(seconds):
        if not call_state['called']:
            call_state['called'] = True
            raise KeyboardInterrupt
        return None
    # Instead of replacing the whole asyncio module (which caused scoping issues),
    # patch only the sleep function that main() calls.
    monkeypatch.setattr(app_main.asyncio, 'sleep', fake_sleep)

    # Run main() and ensure it completes (KeyboardInterrupt path exercised)
    try:
        await app_main.main()
    except BaseException as e:  # CancelledError inherits BaseException in 3.11+
        import asyncio
        if not isinstance(e, KeyboardInterrupt | asyncio.CancelledError):
            raise
    assert call_state['called'] is True


def test_setup_logging(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app_main.setup_logging()
    _reset_logging_for_tests()
    os.environ.pop('RUN_ID', None)
    app_main.setup_logging()
    assert (tmp_path / 'logs').exists()
    assert os.getenv('RUN_ID')
