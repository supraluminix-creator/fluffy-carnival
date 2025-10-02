from pipeline import circuit_breaker


def test_circuit_breaker_cooldown(monkeypatch):
    circuit_breaker.reset()
    base_time = [1000.0]

    def fake_time():
        return base_time[0]

    # Monkeypatch le symbole time utilisé à l'import dans circuit_breaker (module time)
    monkeypatch.setattr(circuit_breaker, 'time', fake_time)

    for _ in range(3):
        circuit_breaker.record_failure('cool')
    assert circuit_breaker.should_skip('cool') is True

    # Avancer le temps au-delà du cooldown
    base_time[0] += 31
    # should_skip doit réinitialiser
    assert circuit_breaker.should_skip('cool') is False
    circuit_breaker.record_success('cool')
    assert circuit_breaker.should_skip('cool') is False
