"""Configuration centralisée du logging structuré.

Objectifs:
- Unifier la configuration structlog (JSON line oriented)
- Ajouter run_id injecté via contextvars pour corrélation
- Support fichiers (rotatif + par run) et console
- Normaliser le champ d'évènement: toujours clé `event`

Utilisation:
    from pipeline.logging_config import setup_logging
    logger = setup_logging()  # appel idempotent

    logger.info("pipeline_started", extra_field=123)

Variables d'environnement reconnues:
    LOGS_DIR (default: logs)
    LOG_LEVEL (default: INFO)
    ENABLE_FILE_LOGS (1/0, default: 1) – active fichiers
    RUN_ID (optionnel) – sinon généré
"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from logging.handlers import TimedRotatingFileHandler
from typing import Any

import structlog
import structlog.contextvars as structlog_ctx
from structlog.typing import EventDict

_CONFIGURED = False

SENSITIVE_KEYS = ("api_key", "apikey", "secret", "token", "password", "passphrase", "key")


def _mask_value(val: Any) -> Any:
    if val is None:
        return val
    if isinstance(val, str):
        if len(val) <= 4:
            return "***"
        return val[:2] + "***" + val[-2:]
    return "***"


def mask_secrets_processor(
    logger: Any,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Processor structlog qui masque valeurs sensibles.

    Règles:
      - Clé exacte ou contenant un nom sensible (case-insensitive)
      - Valeur str > 4 chars -> garde 2 premiers + 2 derniers
    """
    lowered: dict[str, str] = {}
    for key in list(event_dict.keys()):
        if isinstance(key, str):
            lowered[key.lower()] = key
    for lk, original_key in lowered.items():
        for sk in SENSITIVE_KEYS:
            if sk in lk:
                try:
                    event_dict[original_key] = _mask_value(event_dict[original_key])
                except Exception:  # pragma: no cover
                    event_dict[original_key] = "***"
                break
    return event_dict


def _add_event_key(
    logger: Any,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    # structlog stdlib logger already passes the original event as "event" for JSONRenderer
    # mais si l'appel fournit déjà 'event', on ne modifie pas.
    if "event" not in event_dict and "msg" in event_dict:
        event_dict["event"] = event_dict.pop("msg")
    return event_dict


def setup_logging(simple: bool = False):
    """Initialise (une fois) la configuration logging/structlog.

    simple: mode léger (stdout uniquement, pas de fichiers) pour scripts isolés collectors.
    Retourne un logger structlog prêt.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return structlog.get_logger(__name__)

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, log_level, logging.INFO)

    run_id = os.getenv("RUN_ID") or uuid.uuid4().hex[:8]
    os.environ["RUN_ID"] = run_id
    structlog_ctx.clear_contextvars()
    structlog_ctx.bind_contextvars(run_id=run_id)

    handlers: list[logging.Handler] = []

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    handlers.append(console_handler)

    run_log_path: str | None = None

    if not simple and os.getenv("ENABLE_FILE_LOGS", "1") == "1":
        logs_dir = os.getenv("LOGS_DIR", "logs")
        os.makedirs(logs_dir, exist_ok=True)
        rotating_handler = TimedRotatingFileHandler(
            filename=os.path.join(logs_dir, "app.log"),
            when="midnight",
            interval=1,
            backupCount=7,
            encoding="utf-8",
        )
        rotating_handler.setLevel(level)
        rotating_handler.setFormatter(logging.Formatter("%(message)s"))
        run_log_path = os.path.join(logs_dir, f"run_{run_id}.log")
        run_handler = logging.FileHandler(run_log_path, mode="w", encoding="utf-8")
        run_handler.setLevel(level)
        run_handler.setFormatter(logging.Formatter("%(message)s"))
        handlers.extend([rotating_handler, run_handler])

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = handlers

    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog_ctx.merge_contextvars,
            structlog.processors.add_log_level,
            mask_secrets_processor,
            _add_event_key,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )

    _CONFIGURED = True
    logger = structlog.get_logger(__name__)
    logger.info(
        "logging_initialized",
        run_id=run_id,
        level=log_level,
        files=0 if simple else 1,
        run_log=run_log_path,
    )
    return logger


def _reset_logging_for_tests():  # pragma: no cover - utilisé uniquement par tests pour réinitialiser l'idempotence
    global _CONFIGURED
    _CONFIGURED = False
    # Purger handlers root pour éviter duplications
    root = logging.getLogger()
    for h in list(root.handlers):
        from contextlib import suppress

        with suppress(Exception):
            root.removeHandler(h)
    # Ne pas supprimer RUN_ID ici: laissé au test s'il veut simuler absence


__all__ = ["setup_logging"]
