import pipeline.circuit_breaker as cb


def test_circuit_breaker_open_skip_and_cooldown():
    # Reset internal state
    cb.reset()
    # Inject custom state with lower threshold & cooldown
    cb._STATES['unit'] = cb._State(threshold=2, cooldown=10)  # type: ignore[attr-defined]

    # Fail twice -> should open
    cb.record_failure('unit')
    cb.record_failure('unit')
    st = cb.breaker_status('unit')
    assert st['is_open'] == 1

    # While still within cooldown -> skip
    assert cb.should_skip('unit') is True

    # Force cooldown expiration by rewinding opened_at into past
    internal = cb._STATES['unit']  # type: ignore[attr-defined]
    assert internal.opened_at is not None
    internal.opened_at = internal.opened_at - (internal.cooldown + 1)

    # Now should_skip returns False (breaker auto-closes on cooldown expiry)
    assert cb.should_skip('unit') is False

    # Explicit success keeps it closed
    cb.record_success('unit')
    st2 = cb.breaker_status('unit')
    assert st2['is_open'] == 0
