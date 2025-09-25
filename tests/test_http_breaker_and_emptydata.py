import httpx
import pytest

from pipeline import http_wrappers
from pipeline.http_wrappers import RateLimitError, endpoint_label, http_get_json_retry
from pipeline.metrics import (
    HTTP_BREAKER_OPEN_SECONDS,
    HTTP_BREAKER_OPENS_TOTAL,
    HTTP_BREAKER_SKIPS_TOTAL,
    HTTP_BREAKER_STATE,
    HTTP_RETRIES_TOTAL,
)


class DummyResp:
    def __init__(self, status_code:int, payload):
        self.status_code = status_code
        self._payload = payload
    def json(self):
        return self._payload
    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)

@pytest.fixture(autouse=True)
def _env_setup(monkeypatch):
    # configure breaker for quick open
    monkeypatch.setenv("HTTP_BREAKER_WINDOW", "5")
    monkeypatch.setenv("HTTP_BREAKER_THRESHOLD", "3")
    monkeypatch.setenv("HTTP_BREAKER_COOLDOWN", "30")
    monkeypatch.setenv("RETRY_HTTP_ENABLED", "1")
    yield


def test_breaker_opens_and_short_circuits(monkeypatch):
    calls = {"n":0}
    # 3 premières réponses -> 429, ensuite (si appel) 200
    def fake_get(url, headers=None, params=None, timeout=None):
        calls["n"] += 1
        if calls["n"] <= 3:
            return DummyResp(429, {"err":"rate"})
        return DummyResp(200, {"ok":True})
    monkeypatch.setattr(http_wrappers.httpx, "get", fake_get)
    url = "https://api.test/breaker"
    # Première tentative fera plusieurs retries internes jusqu'à succès ou breaker ouverture.
    # On limite retries élevés pour observer ouverture après 3 événements.
    with pytest.raises(RateLimitError):
        # Configure peu de retries pour forcer sortie après ouverture breaker (retries=2 -> 3 tentatives: attempts 1,2,3)
        http_get_json_retry(url, retries=2, backoff_base=0.001)
    label = endpoint_label(url)
    # Breaker devrait s'être ouvert (compteur >=1)
    val = HTTP_BREAKER_OPENS_TOTAL.labels(endpoint=label)._value.get()
    assert val >= 1
    # Deuxième appel immédiat doit être court-circuité (breaker_open RateLimitError) sans passer par httpx.get
    prev_calls = calls["n"]
    with pytest.raises(RateLimitError):
        http_get_json_retry(url, retries=0, backoff_base=0.001)
    # Aucun nouvel appel réseau (short-circuit)
    assert calls["n"] == prev_calls
    # Vérifie métriques skips et state
    assert HTTP_BREAKER_SKIPS_TOTAL.labels(endpoint=label)._value.get() >= 1
    # State devrait être 1 tant que cooldown non expiré
    assert HTTP_BREAKER_STATE.labels(endpoint=label)._value.get() == 1
    # Open seconds >=0
    assert HTTP_BREAKER_OPEN_SECONDS.labels(endpoint=label)._value.get() >= 0


def test_empty_payload_raises(monkeypatch):
    # Une 200 avec payload vide doit générer EmptyDataError et ne pas être retriable
    # (pas d'incrément http_retries_total)
    from pipeline.http_wrappers import EmptyDataError
    def fake_get(url, headers=None, params=None, timeout=None):
        return DummyResp(200, {})  # empty dict
    monkeypatch.setattr(http_wrappers.httpx, "get", fake_get)
    url = "https://api.test/empty"
    with pytest.raises(EmptyDataError):
        http_get_json_retry(url, retries=2, backoff_base=0.001)
    label = endpoint_label(url)
    # Aucun retry enregistré pour EmptyDataError (non retriable)
    assert HTTP_RETRIES_TOTAL.labels(endpoint=label, reason="EmptyDataError")._value.get() == 0
