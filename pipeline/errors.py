"""Classification normalisée des erreurs collecteurs.

Hiérarchie extensible et fonction `classify` tolérante aux exceptions
externes (httpx, json, etc.). Les catégories sont pensées pour des
dashboards analytiques stables (faible cardinalité):

  - network       : échecs de connexion / transport
  - timeout       : dépassement de délai
  - rate_limit    : 429 / quotas
  - not_found     : 404 ou ressource absente
  - upstream      : 5xx côté fournisseur
  - schema        : format inattendu / parsing
  - empty_data    : réponse vide considérée anormale (liste/dict vide)
  - unknown       : tout le reste
"""
from __future__ import annotations

class CollectorError(Exception):
    category = "unknown"

class NetworkError(CollectorError):
    category = "network"

class RateLimitError(CollectorError):
    category = "rate_limit"

class NotFoundError(CollectorError):
    category = "not_found"

class UpstreamError(CollectorError):
    category = "upstream"

class SchemaError(CollectorError):
    category = "schema"

class EmptyDataError(CollectorError):
    category = "empty_data"

class TimeoutError_(CollectorError):  # underscore pour éviter collision builtin
    category = "timeout"

def classify(exc: Exception) -> str:
    """Retourne la catégorie logique pour une exception.

    Règles heuristiques pour exceptions externes non wrap:
      - nom contient 'Rate' & 'Limit' => rate_limit
      - nom contient 'Timeout' => timeout
      - nom contient 'NotFound' ou '404' => not_found
      - nom contient 'Connect'/'Network'/ 'Proxy' / 'HTTP' => network
      - nom contient 'JSONDecode'/'ValueError'/'KeyError'/'Schema' => schema
    """
    if isinstance(exc, CollectorError):  # déjà catégorisée
        return exc.category

    # Détection basée sur un status_code HTTP si présent (ex: httpx.HTTPStatusError)
    try:
        resp = getattr(exc, 'response', None)
        status_code = getattr(resp, 'status_code', None)
        if isinstance(status_code, int):
            if status_code == 429:
                return "rate_limit"
            if status_code == 404:
                return "not_found"
            if 500 <= status_code < 600:
                return "upstream"
            # Autres 4xx pourraient être considérés comme network/transient pour agrégation
            if 400 <= status_code < 500:
                # on laisse heuristiques plus bas décider si autre cas (ex schema)
                pass
    except Exception:  # pragma: no cover - robustesse
        pass
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if ("rate" in name and "limit" in name) or "429" in msg or "ratelimit" in name:
        return "rate_limit"
    # Message explicite RateLimitExceeded (ex: API tiers) -> rate_limit
    if "ratelimitexceeded" in msg.replace("_", ""):
        return "rate_limit"
    if "too many requests" in msg:
        return "rate_limit"
    if any(k in name for k in ["timeout", "timedout"]):
        return "timeout"
    if "404" in msg or "notfound" in name:
        return "not_found"
    if any(k in name for k in ["connect", "network", "proxy"]):
        return "network"
    if any(k in name for k in ["http"]):  # http erreur générique => potentiellement réseau
        return "network"
    if any(k in name for k in ["jsondecode", "keyerror", "valueerror", "schema"]):
        return "schema"
    # Pas de heuristique simple pour empty_data / upstream sans wrap spécifique
    return "unknown"

__all__ = [
    "CollectorError",
    "NetworkError",
    "RateLimitError",
    "NotFoundError",
    "UpstreamError",
    "SchemaError",
    "EmptyDataError",
    "TimeoutError_",
    "classify",
]
