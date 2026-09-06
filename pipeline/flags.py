"""Feature flags helpers.

Centralise la lecture dynamique des variables d'environnement utilisées pour
la migration façade HTTP afin de réduire la duplication et limiter les fautes
de frappe. Pas de caching volontaire: on veut qu'un export dynamique de var
pendant un process long soit reflété à l'appel suivant.
"""

from __future__ import annotations

import os


def is_forced_facade() -> bool:
    """Retourne True si la façade HTTP est globalement forcée.

    Lecture à chaque invocation (pas de mémoïsation) pour refléter des
    modifications live en environnement de test ou run long.
    """
    return os.getenv("FORCE_HTTP_FACADE", "0") == "1"


def is_dry_run_facade() -> bool:
    """Retourne True si le mode DRY-RUN de la façade HTTP est actif.

    DRY_RUN_FACADE=1 signifie: on évalue la faisabilité de la façade sans encore
    couper les chemins legacy. Les collectors peuvent alors:
        - Exécuter la façade (en best-effort) en parallèle ou juste marquer la gauge
        - Conserver le résultat legacy comme source officielle

    Implémentation initiale minimale: instrumentation uniquement (gauge), pas
    d'appel double pour éviter toute charge supplémentaire tant que non requis.
    """
    return os.getenv("DRY_RUN_FACADE", "0") == "1"


def is_llm_post_facade_enabled() -> bool:
    """Retourne True si la façade POST LLM/AI est activée.

    Harmonise les deux dénominations historiques:
      - LLM_USE_HTTP_FACADE_POST (nouveau)
      - AI_USE_HTTP_FACADE_POST (ancien)

    FORCE_HTTP_FACADE=1 est prioritaire et active aussi la façade POST.
    """
    if is_forced_facade():
        return True
    return os.getenv("LLM_USE_HTTP_FACADE_POST", "0") == "1" or os.getenv("AI_USE_HTTP_FACADE_POST", "0") == "1"


__all__ = ["is_forced_facade", "is_dry_run_facade", "is_llm_post_facade_enabled"]
