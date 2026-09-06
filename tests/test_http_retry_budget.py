import pytest

from pipeline import http_wrappers
from pipeline.errors import TimeoutError_
from pipeline.metrics import (
    RETRY_BUDGET_EXHAUSTED_TOTAL,
    RETRY_BUDGET_REMAINING_SECONDS,
)


class Dummy429:
    status_code = 429

    def json(self):
        return {"err": "rate"}

    def raise_for_status(self):
        pass


@pytest.mark.parametrize("max_cumulative", [0.2])
def test_http_retry_budget_exhaustion(monkeypatch, max_cumulative):
    # Forcer environnement
    monkeypatch.setenv("RETRY_MAX_CUMULATIVE_SLEEP_SEC", str(max_cumulative))
    monkeypatch.setenv("RETRY_HTTP_ENABLED", "1")
    # Rendre les délais déterministes
    monkeypatch.setattr(http_wrappers.random, "uniform", lambda a, b: 1.0)
    # Pas de vraie attente
    monkeypatch.setattr(http_wrappers.time, "sleep", lambda s: None)

    # Retourne toujours 429 pour déclencher retry jusqu'à épuisement budget
    calls = {"n": 0}

    def fake_get(url, headers=None, params=None, timeout=None):
        calls["n"] += 1
        return Dummy429()

    monkeypatch.setattr(http_wrappers.httpx, "get", fake_get)

    endpoint_url = "https://api.llama.fi/chains"
    ep_label = http_wrappers.endpoint_label(endpoint_url)

    # Baselines
    exhausted_before = RETRY_BUDGET_EXHAUSTED_TOTAL.labels(endpoint=ep_label)._value.get()
    # remaining gauge peut ne pas exister avant premier set -> accéder après import

    with pytest.raises(TimeoutError_):
        http_wrappers.http_get_json_retry(
            endpoint_url,
            retries=5,  # assez grand pour que budget se consomme avant limite de retries
            backoff_base=0.3,  # delay théorique 0.3 -> sleep_for=min(0.3, max_remaining=0.2) = 0.2
            classify_endpoint=http_wrappers.endpoint_label,
        )

    exhausted_after = RETRY_BUDGET_EXHAUSTED_TOTAL.labels(endpoint=ep_label)._value.get()
    assert exhausted_after - exhausted_before == 1, "Le counter d'épuisement doit incrémenter de 1"

    remaining = RETRY_BUDGET_REMAINING_SECONDS.labels(endpoint=ep_label)._value.get()
    assert remaining == 0.0, "Le budget restant doit être 0 après épuisement"
    assert calls["n"] >= 1
