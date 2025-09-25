"""SQLite Adapter centralisé.

Objectifs prod-safe:
- Point unique de création connexion (pragmas cohérents, WAL optionnel)
- Contexte transaction simple
- Factory read-only compatible future sandbox
- Instrumentation légère potentielle (ajout ultérieur de hooks métriques)

Variables d'environnement:
  SQLITE_JOURNAL_MODE (defaut: WAL)
  SQLITE_SYNCHRONOUS (defaut: NORMAL)
  SQLITE_CACHE_SIZE (optionnel, ex: -20000 pour 20k pages)
"""
from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

# On n'emploie plus de flag global; chaque connexion applique les pragmas
# pour permettre aux tests (et au runtime) de modifier dynamiquement les
# variables d'environnement entre deux connections.
_PRAGMAS_APPLIED = False  # conservé pour rétro (non utilisé logiquement)


def _apply_pragmas(conn: sqlite3.Connection) -> None:
	cur = conn.cursor()
	journal = os.getenv("SQLITE_JOURNAL_MODE", "WAL")
	synchronous = os.getenv("SQLITE_SYNCHRONOUS", "NORMAL")
	cache_size = os.getenv("SQLITE_CACHE_SIZE")  # ex: -20000
	try:
		# journal_mode renvoie la valeur effective; on ne dépend pas de ce retour ici
		cur.execute(f"PRAGMA journal_mode={journal}")
		cur.execute(f"PRAGMA synchronous={synchronous}")
		if cache_size:
			cur.execute(f"PRAGMA cache_size={cache_size}")
	except Exception:  # pragma: no cover - pragmas best effort
		pass


def get_connection(path: str = "data/crypto.db", *, readonly: bool = False) -> sqlite3.Connection:
	"""Obtenir une connexion SQLite avec pragmas appliqués (si non read-only)."""
	uri = path
	if readonly:
		uri = f"file:{path}?mode=ro"
	conn = sqlite3.connect(uri, uri=readonly, check_same_thread=False)
	if not readonly:
		_apply_pragmas(conn)
	return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Cursor]:
	cur = conn.cursor()
	try:
		yield cur
		conn.commit()
	except Exception:
		conn.rollback()
		raise


__all__ = ["get_connection", "transaction"]
