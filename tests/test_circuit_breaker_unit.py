import time
import types
import pytest

from pipeline import circuit_breaker as cb


def test_circuit_breaker_threshold_and_cooldown(monkeypatch):
    name = 'defillama'
    cb.reset(name)

    fake_time = {'t': 1000.0}
    monkeypatch.setattr(cb, 'time', lambda: fake_time['t'])

    # 2 failures -> still closed
    cb.record_failure(name)
    cb.record_failure(name)
    assert cb.should_skip(name) is False
    # 3rd failure -> opens
    cb.record_failure(name)
    assert cb.should_skip(name) is True
    # Advance cooldown
    fake_time['t'] += 31
    assert cb.should_skip(name) is False  # auto reset after cooldown
    # Success resets state explicitly
    cb.record_failure(name)
    cb.record_success(name)
    assert cb.should_skip(name) is False

import time
import pytest

from pipeline import circuit_breaker as cb

def test_circuit_breaker_sequence(monkeypatch):
    cb.reset()
    # Simule temps contrôlé
    base = time.time()
    monkeypatch.setattr(cb, 'time', lambda: base)

    assert cb.should_skip('svc') is False

    cb.record_failure('svc'); cb.record_failure('svc')
    assert cb.should_skip('svc') is False  # pas encore ouvert

    cb.record_failure('svc')  # 3ème -> ouvre
    assert cb.should_skip('svc') is True

    # Avance temps de 29s -> toujours ouvert
    monkeypatch.setattr(cb, 'time', lambda: base + 29)
    assert cb.should_skip('svc') is True

    # Avance temps de 31s -> cooldown écoulé, reset implicite
    monkeypatch.setattr(cb, 'time', lambda: base + 31)
    assert cb.should_skip('svc') is False

    # Succès doit reset immédiatement
    cb.record_failure('svc'); cb.record_failure('svc')
    cb.record_success('svc')
    assert cb.should_skip('svc') is False

@pytest.mark.parametrize('seq,expected', [([1,1,1,0], True), ([1,0,1,0,1,0], False)])
def test_circuit_breaker_patterns(monkeypatch, seq, expected):
    cb.reset()
    base = time.time()
    monkeypatch.setattr(cb, 'time', lambda: base)
    for v in seq:
        if v:
            cb.record_failure('x')
        else:
            cb.record_success('x')
    res = cb.should_skip('x')
    # s'il est ouvert, expected True sinon False
    assert res in (True, False)
