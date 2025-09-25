import os

import prometheus_client

# Ce test force un appel legacy volontaire en patchant mark_legacy_http pour simuler un chemin legacy atteint
# alors que FORCE_HTTP_FACADE=1, et vérifie que facade_forced_leak passe à 1.

def test_forced_mode_leak_detection(monkeypatch):
    os.environ['FORCE_HTTP_FACADE'] = '1'
    # On patch is_forced_facade pour garantir la détection dans helper même si env déjà lu
    from pipeline import flags
    monkeypatch.setattr(flags, 'is_forced_facade', lambda: True)

    triggered = {}
    # Patch du helper pour juste appeler l'implémentation réelle puis marquer collector utilisé
    from pipeline.metrics import collectors as mc
    real = mc.mark_legacy_http
    def fake_mark(collector: str):
        real(collector)
        triggered[collector] = True
    monkeypatch.setattr(mc, 'mark_legacy_http', fake_mark)

    # Appel d'un collector en mode non façadé forcé: on déclenche volontairement la branche legacy
    # On choisit un collector dont le code legacy s'exécute seulement si force_facade == False -> ici on va
    # simuler en désactivant localement la partie forced pour une fonction interne : on réutilise market fallback direct
    # Plus simple: invoquer mark_legacy_http directement (équivaut à un chemin legacy). 
    fake_mark('market')  # simule un accès legacy imprévu

    leak = {}
    for fam in prometheus_client.REGISTRY.collect():
        if fam.name == 'facade_forced_leak':
            for s in fam.samples:
                leak[s.labels['collector']] = s.value
    assert leak.get('market') == 1, f"Leak gauge should be 1 for market (got {leak.get('market')})"
