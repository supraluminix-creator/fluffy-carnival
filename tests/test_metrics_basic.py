import pytest

from pipeline.metrics import (
    COLLECTOR_RUNS_TOTAL,
    FALLBACK_TIER_LATENCY_SECONDS,
    collector_timing,
    fallback_tier_timing,
)


def test_collector_timing_success():
    before = (
        COLLECTOR_RUNS_TOTAL.labels(collector='x', status='success')._value.get()
        if ('x', 'success') in COLLECTOR_RUNS_TOTAL._metrics
        else 0
    )
    with collector_timing('x'):
        pass
    after = COLLECTOR_RUNS_TOTAL.labels(collector='x', status='success')._value.get()
    assert after == before + 1


def test_collector_timing_error():
    before_err = (
        COLLECTOR_RUNS_TOTAL.labels(collector='y', status='error')._value.get()
        if ('y', 'error') in COLLECTOR_RUNS_TOTAL._metrics
        else 0
    )
    with pytest.raises(RuntimeError), collector_timing('y'):
        raise RuntimeError('boom')
    after_err = COLLECTOR_RUNS_TOTAL.labels(collector='y', status='error')._value.get()
    assert after_err == before_err + 1


def test_fallback_tier_timing_success_and_error():
    # Pour histogram on se contente de comparer la somme totale (latences cumulées)
    before_success_sum = (
        FALLBACK_TIER_LATENCY_SECONDS.labels(collector='macro', tier='1', status='success')._sum.get()
        if ('macro', '1', 'success') in FALLBACK_TIER_LATENCY_SECONDS._metrics
        else 0
    )
    with fallback_tier_timing('macro', 1):
        pass
    after_success_sum = FALLBACK_TIER_LATENCY_SECONDS.labels(collector='macro', tier='1', status='success')._sum.get()
    assert after_success_sum >= before_success_sum

    before_error_sum = (
        FALLBACK_TIER_LATENCY_SECONDS.labels(collector='macro', tier='2', status='error')._sum.get()
        if ('macro', '2', 'error') in FALLBACK_TIER_LATENCY_SECONDS._metrics
        else 0
    )
    with pytest.raises(ValueError), fallback_tier_timing('macro', 2):
        raise ValueError('x')
    after_error_sum = FALLBACK_TIER_LATENCY_SECONDS.labels(collector='macro', tier='2', status='error')._sum.get()
    assert after_error_sum >= before_error_sum
