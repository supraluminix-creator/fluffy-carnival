"""Job d'export batch orchestré.

Ce module fournit une fonction `perform_export_batch` invoquée par le scheduler
via `scheduler/jobs.yaml` (id: export_batch) pour:
 - Exécuter un sous-ensemble de collectors (macro, onchain, dérivés, sentiment, defi)
 - Agréger les résultats non nuls
 - Exporter latest + timestamped via `export_latest_and_timestamped`
 - Instrumenter succès / erreurs (compteurs EXPORTS_TOTAL déjà gérés dans utilitaire)
 - Renvoyer un bref résumé (utile pour debug dans logs APScheduler)

Prod-safe: toute exception est propagée afin que le scheduler marque
le job en échec (CRYPTO_TASK_ERR) — indispensable pour ne pas compter
un export vide comme success.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Awaitable, Callable
import structlog

from pipeline.export_utils import export_latest_and_timestamped
from pipeline.collectors.market import fetch_macro
from pipeline.collectors.onchain import fetch_txcount, fetch_hashrate, fetch_sopr
from pipeline.collectors.derivatives import (
    fetch_bybit_oi,
    fetch_bybit_long_short_ratio,
)
from pipeline.collectors.defillama import fetch_defillama_tvl
from pipeline.collectors.sentiment import fetch_fear_greed

log = structlog.get_logger(__name__)


async def _maybe_await(res: Any) -> Any:
    if asyncio.iscoroutine(res) or isinstance(res, Awaitable):
        return await res  # type: ignore[arg-type]
    return res


async def perform_export_batch(symbol: str = "bitcoin") -> dict[str, Any]:
    """Collecte orchestrée + export CSV.

    Paramètres
    ----------
    symbol: str
        Actif pour les collectors macro/market (par défaut 'bitcoin').

    Retour
    ------
    dict: résumé (counts, paths) pour logging.
    """
    cmc_api_key = os.getenv("CMC_API_KEY") or None
    etherscan_api_key = os.getenv("ETHERSCAN_API_KEY") or None
    run_id = os.getenv("RUN_ID") or None
    export_dir = os.getenv("EXPORT_DIR", "exports")

    # Tableau des callables (nom logique, fonction, *args, **kwargs)
    tasks: list[tuple[str, Callable[..., Any], tuple, dict]] = [
        ("macro", fetch_macro, (symbol,), {"cmc_api_key": cmc_api_key}),
        ("txcount", fetch_txcount, ("BTC",), {"etherscan_api_key": etherscan_api_key}),
        ("hashrate", fetch_hashrate, ("BTC",), {}),
        ("sopr", fetch_sopr, ("BTC",), {}),
        ("bybit_oi", fetch_bybit_oi, ("BTCUSDT",), {}),
        ("bybit_lsr", fetch_bybit_long_short_ratio, ("BTCUSDT",), {}),
        ("defillama", fetch_defillama_tvl, ("ethereum",), {}),
        ("sentiment", fetch_fear_greed, tuple(), {}),
    ]

    results: list[dict[str, Any]] = []
    errors: list[str] = []

    for name, fn, args, kwargs in tasks:
        try:
            res = await _maybe_await(fn(*args, **kwargs))
            if isinstance(res, dict) and res:  # collector record
                results.append(res)  # type: ignore[arg-type]
        except Exception as e:  # pragma: no cover - granular tests peuvent cibler chaque collector séparément
            errors.append(f"{name}:{type(e).__name__}")
            log.error("export_batch_collect_error", collector=name, error=str(e), error_type=type(e).__name__)

    latest_path = ts_path = None
    if results:
        latest_path, ts_path = export_latest_and_timestamped(results, export_dir, run_id=run_id)
        log.info(
            "export_batch_completed",
            collectors=len(tasks),
            success=len(results),
            errors=len(errors),
            latest_path=latest_path,
            ts_path=ts_path,
        )
    else:
        # Pas de données => lever pour marquer échec (évite faux positifs readiness)
        msg = "No data collected during export batch"
        log.error("export_batch_no_data", collectors=len(tasks), errors=errors)
        raise RuntimeError(msg)

    return {
        "records": len(results),
        "errors": errors,
        "latest": latest_path,
        "timestamped": ts_path,
    }

__all__ = ["perform_export_batch"]
