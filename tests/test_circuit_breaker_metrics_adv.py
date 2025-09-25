import time

from pipeline import circuit_breaker as cb


class DummyMetric:
    def __init__(self):
        self.values = {}

    def labels(self, **labels):  # noqa: D401
        key = tuple(sorted(labels.items()))
        metric = self

        class _L:
            def inc(self_inner, amount=1):
                metric.values[key] = metric.values.get(key, 0) + amount

            def set(self_inner, val):
                metric.values[key] = val

        return _L()


def test_circuit_breaker_open_skip_reset(monkeypatch):
    # Patch métriques utilisées dans module
    open_total = DummyMetric()
    skips_total = DummyMetric()
    state_g = DummyMetric()
    open_seconds = DummyMetric()
    last_open = DummyMetric()
    resets_total = DummyMetric()

    monkeypatch.setattr(cb, "CIRCUIT_BREAKER_OPEN_TOTAL", open_total)
    monkeypatch.setattr(cb, "CIRCUIT_BREAKER_SKIPS_TOTAL", skips_total)
    monkeypatch.setattr(cb, "CIRCUIT_BREAKER_STATE", state_g)
    monkeypatch.setattr(cb, "CIRCUIT_BREAKER_OPEN_SECONDS", open_seconds)
    monkeypatch.setattr(cb, "CB_LAST_OPEN_TIMESTAMP", last_open)
    monkeypatch.setattr(cb, "CB_RESETS_TOTAL", resets_total)

    cb.reset()
    name = "adv"
    # Déclenche ouverture après 3 échecs
    cb.record_failure(name)
    cb.record_failure(name)
    assert cb.breaker_status(name)["is_open"] == 0
    cb.record_failure(name)
    assert cb.breaker_status(name)["is_open"] == 1

    # open_total incrementé
    assert any(v == 1 for v in open_total.values.values())
    assert any(v == 1 for v in state_g.values.values())  # state=1
    # Simuler temps qui passe pour open_seconds: avancer opened_at dans le passé
    st = cb._STATES[name]  # type: ignore[attr-defined]
    st.opened_at = time.time() - 5
    # Appel should_skip -> skip + met à jour durée
    assert cb.should_skip(name) is True
    assert any(v == 1 for v in skips_total.values.values())
    # open_seconds >=5 approx (val exact ~5)
    assert any(v >= 5 for v in open_seconds.values.values())

    # Succès -> reset métriques state=0, open_seconds=0 et resets_total inc
    cb.record_success(name)
    assert any(v == 0 for v in state_g.values.values())
    assert any(v == 0 for v in open_seconds.values.values())
    assert any(v == 1 for v in resets_total.values.values())
