"""Exceptions spécifiques pour classification des erreurs collectors.

Chaque exception dérive de CollectorError afin de permettre un catch unifié.
"""
from __future__ import annotations

class CollectorError(Exception):
    """Base pour toutes les erreurs de collecte."""
    error_type = "collector_error"

class NetworkError(CollectorError):
    error_type = "network"

class RateLimitError(CollectorError):
    error_type = "rate_limit"

class NotFoundError(CollectorError):
    error_type = "not_found"

class SchemaError(CollectorError):
    error_type = "schema"

class EmptyDataError(CollectorError):
    error_type = "empty_data"

class UpstreamError(CollectorError):
    error_type = "upstream"

ERROR_CLASS_MAP = {
    404: NotFoundError,
    429: RateLimitError,
}

__all__ = [
    "CollectorError",
    "NetworkError",
    "RateLimitError",
    "NotFoundError",
    "SchemaError",
    "EmptyDataError",
    "UpstreamError",
    "ERROR_CLASS_MAP",
]
