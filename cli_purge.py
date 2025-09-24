"""CLI utilitaire pour lancer purge & vacuum.

Usage exemples:
  python -m cli_purge --db data/crypto.db --retention 45 --dry-run
  python -m cli_purge --db data/crypto.db --retention 30 --vacuum
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from pipeline.purge_job import purge_liquidations
from pipeline.db_stats import update_db_metrics, vacuum_and_update_metrics


def main() -> int:
    parser = argparse.ArgumentParser(description="Purge historique liquidations + vacuum optionnel")
    parser.add_argument("--db", default="data/crypto.db", help="Chemin base SQLite")
    parser.add_argument("--retention", type=int, default=30, help="Nombre de jours à conserver")
    parser.add_argument("--dry-run", action="store_true", help="Ne supprime pas réellement")
    parser.add_argument("--vacuum", action="store_true", help="Exécute VACUUM après purge")
    args = parser.parse_args()

    os.environ["LIQ_RETENTION_DAYS"] = str(args.retention)
    os.environ["LIQ_PURGE_DRY_RUN"] = "1" if args.dry_run else "0"

    stats = purge_liquidations(args.db)
    mode = "DRY-RUN" if args.dry_run else "REAL"
    print(f"Purge mode={mode} retention={args.retention}d stats={stats}")

    if args.vacuum and not args.dry_run:
        vacuum_and_update_metrics(args.db)
        print("VACUUM exécuté + métriques mises à jour")
    else:
        update_db_metrics(args.db)

    return 0


if __name__ == "__main__":  # pragma: no cover - exécution manuelle
    raise SystemExit(main())