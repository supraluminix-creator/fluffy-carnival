import time
from pipeline import circuit_breaker as cb


def test_half_open_transition(monkeypatch):
    cb.reset()
    name = "defillama"
    st = cb._get(name)  # type: ignore[attr-defined]
    st.threshold = 2
    st.cooldown = 0  # cooldown immédiat pour test
    # deux échecs -> open
    cb.record_failure(name)
    cb.record_failure(name)
    assert st.opened_at is not None
    # Après should_skip (cooldown 0) -> half-open, première tentative autorisée
    skip = cb.should_skip(name)
    assert skip is False
    status = cb.breaker_status(name)
    assert status["half_open"] == 1
    # Deuxième appel should_skip avant résultat -> skip car probe déjà tentée
    assert cb.should_skip(name) is True
    # Probe échoue -> record_failure -> retour open
    cb.record_failure(name)
    assert st.half_open is False and st.opened_at is not None
    # Cooldown (0s) -> next should_skip enclenche half-open à nouveau
    skip = cb.should_skip(name)
    assert skip is False and st.half_open is True
    # Cette fois succès -> record_success -> fermé
    cb.record_success(name)
    status = cb.breaker_status(name)
    assert status["half_open"] == 0 and status["is_open"] == 0
