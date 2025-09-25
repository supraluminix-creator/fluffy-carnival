import pytest
from prometheus_client import generate_latest

from pipeline.circuit_breaker import record_failure, record_success, reset, should_skip


def _metric_text():
    return generate_latest().decode()


def test_breaker_open_close_metrics(monkeypatch):
    reset()
    name = "market"
    # Force threshold=2 for faster test by patching internal state after first failure
    from pipeline.circuit_breaker import _get
    st = _get(name)
    st.threshold = 2
    # first failure (not open yet)
    record_failure(name)
    assert not should_skip(name)
    # second failure triggers open
    record_failure(name)
    assert should_skip(name)
    txt = _metric_text()
    assert f'circuit_breaker_open_total{{breaker="{name}"}} 1.0' in txt
    assert f'circuit_breaker_state{{breaker="{name}"}} 1.0' in txt
    # skip increments
    should_skip(name)
    txt2 = _metric_text()
    assert f'circuit_breaker_skips_total{{breaker="{name}"}} 2.0' in txt2 or f'circuit_breaker_skips_total{{breaker="{name}"}} 1.0' in txt2
    # close
    record_success(name)
    assert not should_skip(name)
    txt3 = _metric_text()
    assert f'circuit_breaker_state{{breaker="{name}"}} 0.0' in txt3


def test_breaker_open_seconds_progress(monkeypatch):
    reset()
    name = "deriv_oi"
    from pipeline.circuit_breaker import _get
    st = _get(name)
    st.threshold = 1
    record_failure(name)  # opens immediately
    assert should_skip(name)
    # simulate time passage
    opened_at = st.opened_at
    assert opened_at is not None
    # manually set opened_at in past
    st.opened_at -= 5  # type: ignore
    should_skip(name)
    txt = _metric_text()
    # value should be >=5 seconds now
    import re
    m = re.search(rf'circuit_breaker_open_seconds{{breaker="{name}"}} (\d+\.\d+)', txt)
    assert m, txt
    val = float(m.group(1))
    assert val >= 5


@pytest.mark.parametrize("grace,expect_ready", [(0, False), (9999, True)])
def test_readiness_blocked_by_breaker(monkeypatch, grace, expect_ready):
    # Patch env before importing runner internals
    monkeypatch.setenv("BREAKER_CRITICAL_LIST", "market")
    monkeypatch.setenv("BREAKER_OPEN_GRACE_SECONDS", str(grace))
    # Force fresh import of readiness helpers
    import importlib

    from pipeline import circuit_breaker as cb
    cb.reset()
    from pipeline.circuit_breaker import _get
    st = _get("market")
    st.threshold = 1
    record_failure("market")  # opens
    assert should_skip("market")
    # Re-import runner to re-evaluate env-based policy
    from scheduler import runner
    importlib.reload(runner)
    # Simulate first task success attempt triggering readiness logic
    # Access readiness metric indirectly via policy check
    # readiness only set if not blocked
    # call internal private function if available else simulate event by calling _breaker_blocks_readiness
    blocked = runner._breaker_blocks_readiness()
    if expect_ready:
        assert not blocked
    else:
        assert blocked

