from prometheus_client import REGISTRY

# Test dédié à la couverture de la catégorie d'erreur 'unknown'
# On force une exception générique dans _http_get pour vérifier l'incrément du compteur.

def _metric_value(collector: str, error_type: str) -> float:
    m = REGISTRY._names_to_collectors.get('collector_error_types_total')
    if not m:
        return 0.0
    total = 0.0
    for fam in m.collect():
        for s in fam.samples:
            if s.name == 'collector_error_types_total' and s.labels.get('collector')==collector and s.labels.get('error_type')==error_type:
                total += s.value
    return total


def test_unknown_error_category(monkeypatch):
    # Sauvegarde latente de la fonction interne si besoin
    from pipeline.collectors import binance as b

    def fake_http_get(url, params=None, timeout=5):  # pragma: no cover - trivial
        raise Exception("some totally random failure pattern that is not classified")

    monkeypatch.setattr(b, '_http_get', fake_http_get)
    before = _metric_value('binance_spot','unknown')
    rec = b.fetch_binance_spot_price('BTCUSDT')
    assert rec is None
    after = _metric_value('binance_spot','unknown')
    assert after == before + 1, "Le compteur unknown n'a pas été incrémenté"