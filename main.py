"""
Monitor - Application principale (scheduler + legacy), sans API.

Cette version intègre:
- Scheduler centralisé avec jitter anti-rate-limit
- Orchestrateur pour exécution parallèle des collectors  
- Collectors basés sur BaseCollector pattern
"""

import asyncio
import contextlib
import os
import subprocess
import sys
from collections.abc import Callable as _Callable
from typing import TYPE_CHECKING, Any
from typing import Any as _Any

import structlog
from dotenv import load_dotenv

if TYPE_CHECKING:  # Only imported for type checking; avoids runtime stub dependency
    from tabulate import tabulate  # type: ignore
else:  # pragma: no cover
    from tabulate import tabulate  # type: ignore


from pipeline.analysis.events import emit_signals
from pipeline.analysis.persist import save_analysis
from pipeline.analysis.runner import run_automatic_analyses
from pipeline.collectors.defi import DefiTVLRecord, fetch_defillama_tvl
from pipeline.collectors.derivatives import (
    LongShortRatioRecord,
    OpenInterestRecord,
    fetch_bybit_long_short_ratio,
    fetch_bybit_oi,
)

# Import collectors (existants)
from pipeline.collectors.market import MacroRecord, fetch_macro
from pipeline.collectors.onchain import (
    HashrateRecord,
    SoprRecord,
    TxCountRecord,
    fetch_hashrate,
    fetch_sopr,
    fetch_txcount,
)
from pipeline.collectors.sentiment import SentimentRecord, fetch_fear_greed
from pipeline.orchestrator import ParallelOrchestrator
from pipeline.scheduler import CryptoScheduler, get_collector_intervals_from_env

CollectorRecord = (
    MacroRecord |
    DefiTVLRecord |
    TxCountRecord |
    HashrateRecord |
    SoprRecord |
    OpenInterestRecord |
    LongShortRatioRecord |
    SentimentRecord |
    dict[str, Any]  # legacy/unknown
)

try:
    from scheduler.runner import build_scheduler as _imported_build_scheduler
except Exception:  # pragma: no cover - optional path
    _imported_build_scheduler = None  # type: ignore[assignment]
build_scheduler: _Callable[[], _Any] | None = _imported_build_scheduler

# Configuration
load_dotenv()
logger = structlog.get_logger(__name__)

EXPORT_DIR = "exports"
os.makedirs(EXPORT_DIR, exist_ok=True)

# Configuration centralisée (progressive)
try:  # Import non critique
    from pipeline.config import get_config
    _APP_CONFIG = get_config()
except Exception:  # pragma: no cover
    _APP_CONFIG = None  # type: ignore

EXPORT_FIELDS = [
    "timestamp",
    "asset", 
    "symbol",
    "chain",
    "metric_name",
    "value",
    "source",
    "confidence_score"
]

# -------------------- Helpers intégration optionnelle (WS, SOPR fallback) --------------------
def _ensure_bybit_ws_running() -> None:
    """Démarre le collector WS Bybit en processus séparé si activé et non déjà lancé.

    Activation via BYBIT_WS_AUTOSTART=1. Santé vérifiée via serveur Prometheus
    exposé par le collector (port configurable BYBIT_WS_PORT, défaut 8000).
    """
    if os.getenv("BYBIT_WS_AUTOSTART", "0") != "1":
        return
    port = int(os.getenv("BYBIT_WS_PORT", "8000"))
    health_port = int(os.getenv("BYBIT_WS_HEALTH_PORT", str(port)))
    # Vérifier si un collector WS tourne déjà (Prometheus exposé sur /)
    try:
        import httpx  # import local pour éviter coût à l'import tests
        # Priorité: health explicite si dispo, fallback vers racine Prometheus
        r = None
        try:
            r = httpx.get(f"http://127.0.0.1:{health_port}/health", timeout=0.6)
        except Exception:
            r = httpx.get(f"http://127.0.0.1:{port}/", timeout=0.6)
        if getattr(r, "status_code", 0) == 200:
            logger.info("bybit_ws_already_running", port=port, health_port=health_port)
            return
    except Exception:
        pass
    symbols = os.getenv("BYBIT_WS_SYMBOLS", "BTCUSDT,ETHUSDT")
    args = [
        sys.executable,
        "-m",
        "pipeline.collectors.bybit_ws",
        "--symbols",
        symbols,
        "--prometheus-port",
        str(port),
    ]
    # Expose health endpoint on same port by default (overridable)
    if health_port:
        args += ["--health-port", str(health_port)]
    db_path = os.getenv("BYBIT_WS_DB")
    parquet_dir = os.getenv("BYBIT_WS_PARQUET_DIR")
    if db_path:
        args += ["--db", db_path]
    if parquet_dir:
        args += ["--parquet-dir", parquet_dir]
    creationflags = 0
    # Sur Windows, ouvrir dans une nouvelle console pour séparer sortie
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    try:
        with open(os.devnull, "wb") as devnull:
            proc = subprocess.Popen(
                args,
                stdout=devnull,
                stderr=devnull,
                creationflags=creationflags,
            )
            logger.info("bybit_ws_started_subprocess", pid=proc.pid, port=port, health_port=health_port, symbols=symbols)
    except Exception as e:
        logger.warning("bybit_ws_autostart_failed", error=str(e))


async def _fetch_sopr_with_fallback(symbol: str = "BTC") -> SoprRecord | None:
    """Appelle le SOPR par défaut, puis fallback BGeometrics si activé et nécessaire.

    - Par défaut, comportement inchangé (fallback désactivé).
    - Activez via ENABLE_SOPR_FALLBACKS=1 et optionnellement BGEOMETRICS_API_KEY.
    """
    try:
        rec = await fetch_sopr(symbol)
    except Exception:
        rec = None
    if rec is not None:
        return rec
    if os.getenv("ENABLE_SOPR_FALLBACKS", "0") != "1":
        return None
    try:
        from pipeline.collectors.sopr import SOPRSource as _SOPRSource  # import local
        from pipeline.collectors.sopr import fetch_sopr as _fetch_alt
        api_key = os.getenv("BGEOMETRICS_API_KEY")
        # Exécuter la variante sync dans un thread pour ne pas bloquer l'event loop
        fb = await asyncio.to_thread(_fetch_alt, symbol=symbol, source=_SOPRSource.BGEOMETRICS, api_key=api_key)
        if not fb:
            return None
        # Convertir vers schéma onchain.SoprRecord attendu par l'export
        ts = fb.get("timestamp") if isinstance(fb, dict) else None
        val = fb.get("sopr") if isinstance(fb, dict) else None
        if val is None:
            return None
        try:
            fval = float(val)
        except Exception:
            return None
        source = "bgeometrics"
        return {
            "timestamp": ts if isinstance(ts, int | float) else None,
            "asset": symbol,
            "metric_name": "sopr",
            "value": fval,
            "source": source,
            "confidence_score": 0.8,
        }
    except Exception:
        return None

# Classes Collector compatibles avec nouveau système
class LegacyCollectorWrapper:
    """Wrapper pour adapter les fonctions collectors existantes au pattern BaseCollector"""
    
    def __init__(self, name: str, collect_func, *args, **kwargs):
        self.name: str = name
        self.collect_func = collect_func
        self.args = args
        self.kwargs = kwargs
        self.last_success_time: float | None = None
        self.last_error_time: float | None = None
    
    async def collect(self):
        """Exécute la fonction collector et gère les erreurs"""
        try:
            result = await self.collect_func(*self.args, **self.kwargs)
            self.last_success_time = float(asyncio.get_event_loop().time())
            return result
        except Exception as e:
            self.last_error_time = float(asyncio.get_event_loop().time())
            logger.error(f"Collector {self.name} failed", error=str(e))
            raise

def safe_print_table(title, data, headers):
    """Affichage sécurisé des tableaux"""
    print(f"\n[{title}]")
    try:
        if isinstance(data, list) and len(data) > 0:
            if headers == "keys" and isinstance(data[0], dict):
                headers = list(data[0].keys())
            print(tabulate(data, headers=headers, tablefmt="grid"))
        else:
            print("Aucune donnée disponible")
    except Exception as e:
        print(f"Erreur affichage : {e}")

def export_csv(data: list, filename: str):  # Compat historique (délégué utilitaire)
    from pipeline.export_utils import export_csv_rows
    if not data:
        logger.warning("No data to export", filename=filename)
        return
    export_csv_rows(data, filename)

async def run_legacy_collection():
    """Collection legacy pour compatibilité (mode fallback)"""
    logger.info("Running legacy collection mode")
    
    # API keys depuis environnement
    cmc_api_key = os.getenv("CMC_API_KEY") or os.getenv("COINMARKETCAP_API_KEY", "")
    etherscan_api_key = os.getenv("ETHERSCAN_API_KEY", "")
    
    results: list[CollectorRecord] = []

    # Macro
    macro = await fetch_macro("bitcoin", cmc_api_key=cmc_api_key)
    safe_print_table("Macro - CoinGecko/CMC", [macro] if macro else [], "keys")
    if macro:
        results.append(macro)

    # DeFi
    defi = fetch_defillama_tvl("ethereum")
    safe_print_table("DeFi - Defillama", [defi] if defi else [], "keys")
    if defi:
        results.append(defi)

    # On-chain
    txcount = await fetch_txcount("BTC", etherscan_api_key=etherscan_api_key)
    hashrate = await fetch_hashrate("BTC")
    sopr = await fetch_sopr("BTC")
    safe_print_table("On-chain - TxCount", [txcount] if txcount else [], "keys")
    safe_print_table("On-chain - Hashrate", [hashrate] if hashrate else [], "keys")
    safe_print_table("On-chain - SOPR", [sopr] if sopr else [], "keys")
    if txcount:
        results.append(txcount)
    if hashrate:
        results.append(hashrate)
    if sopr:
        results.append(sopr)

    # Dérivés - Open Interest
    bybit_oi = await fetch_bybit_oi("BTCUSDT")
    safe_print_table("Dérivés - Bybit OI", [bybit_oi] if bybit_oi else [], "keys")
    if bybit_oi:
        results.append(bybit_oi)

    # Dérivés - Long/Short Ratio Bybit
    bybit_lsr = await fetch_bybit_long_short_ratio("BTCUSDT")
    safe_print_table("Dérivés - Bybit Long/Short Ratio", [bybit_lsr] if bybit_lsr else [], "keys")
    if bybit_lsr:
        results.append(bybit_lsr)

    # Sentiment
    fg = await fetch_fear_greed()
    safe_print_table("Sentiment - Fear & Greed", [fg] if fg else [], "keys")
    if fg:
        results.append(fg)

    # Export CSV (consolidé + horodaté)
    from pipeline.export_utils import export_latest_and_timestamped
    export_latest_and_timestamped(results, EXPORT_DIR, run_id=os.getenv("RUN_ID"))
    
    return results

def create_collectors() -> dict[str, LegacyCollectorWrapper]:
    """Crée les collectors avec wrapper compatibility"""
    
    # API keys depuis environnement
    cmc_api_key = os.getenv("CMC_API_KEY", "")
    etherscan_api_key = os.getenv("ETHERSCAN_API_KEY", "")
    
    collectors = {
        'market': LegacyCollectorWrapper('market', fetch_macro, "bitcoin", cmc_api_key=cmc_api_key),
        'defillama': LegacyCollectorWrapper('defillama', fetch_defillama_tvl, "ethereum"),
        'txcount': LegacyCollectorWrapper('txcount', fetch_txcount, "BTC", etherscan_api_key=etherscan_api_key),
        'hashrate': LegacyCollectorWrapper('hashrate', fetch_hashrate, "BTC"),
        # SOPR: wrapper avec fallback optionnel (comportement par défaut inchangé)
        'sopr': LegacyCollectorWrapper('sopr', _fetch_sopr_with_fallback, "BTC"),
        'bybit_oi': LegacyCollectorWrapper('bybit_oi', fetch_bybit_oi, "BTCUSDT"),
        'bybit_lsr': LegacyCollectorWrapper('bybit_lsr', fetch_bybit_long_short_ratio, "BTCUSDT"),
        'sentiment': LegacyCollectorWrapper('sentiment', fetch_fear_greed)
    }
    
    logger.info("Collectors created", count=len(collectors), names=list(collectors.keys()))
    return collectors


async def run_scheduler_mode():
    """Mode principal avec scheduler centralisé"""
    logger.info("Starting crypto monitor in scheduler mode")
    
    # Créer collectors
    collectors = create_collectors()
    
    # Créer orchestrateur pour exécution parallèle
    orchestrator = ParallelOrchestrator(list(collectors.values()))
    
    # Créer scheduler
    jitter_percent = int(os.getenv('SCHEDULER_JITTER_PERCENT', 10))
    scheduler = CryptoScheduler(jitter_percent=jitter_percent)
    
    # API supprimée: pas d'enregistrement health
    
    # Configurer intervalles depuis environnement
    intervals = get_collector_intervals_from_env()
    
    # Ajouter collectors groupés au scheduler
    def create_batch_collector_job():
        """Job qui exécute tous les collectors en parallèle"""
        async def batch_collect():
            logger.info("Starting batch collection (parallel)")
            
            # Utiliser orchestrateur pour exécution parallèle
            results = await orchestrator.run_all_collectors(timeout=120)
            
            # Traiter les résultats pour export CSV
            if results.get('status') == 'completed':
                successful_results = results.get('successful_results', [])
                data_for_export = [r['result'] for r in successful_results if r.get('result')]
                
                # Export CSV
                if data_for_export:
                    from pipeline.export_utils import export_latest_and_timestamped
                    export_latest_and_timestamped(data_for_export, EXPORT_DIR, run_id=os.getenv("RUN_ID"))
                    # Option: analyses AI auto après export (MVP)
                    if os.getenv("ANALYSIS_AUTO_RUN", "1") == "1":
                        try:
                            out = run_automatic_analyses(os.path.join(EXPORT_DIR, "latest_export.csv"))
                            only_on_signals = os.getenv("ANALYSIS_ONLY_ON_SIGNALS", "0") == "1"
                            if (not only_on_signals) or (out.get("signals")):
                                save_analysis(out, EXPORT_DIR)
                                if os.getenv("ANALYSIS_EMIT_SIGNALS", "0") == "1" and out.get("signals"):
                                    emit_signals(out["signals"], EXPORT_DIR)
                            logger.info("auto_analysis_done", **out)
                        except Exception as e:
                            logger.warning("auto_analysis_failed", error=str(e))
            
            logger.info("Batch collection completed", **results)
            return results
        
        return batch_collect
    
    # Utiliser l'intervalle le plus court comme base (5min = 300s)
    base_interval = min(intervals.values())
    batch_collector = LegacyCollectorWrapper('batch_parallel', create_batch_collector_job())
    
    scheduler.add_collector(
        batch_collector,
        interval_seconds=base_interval,
        jitter_percent=jitter_percent
    )
    
    # Démarrer scheduler
    await scheduler.start()
    
    logger.info("Scheduler started successfully")

    # Lancer WS Bybit en parallèle si activé et non déjà lancé
    _ensure_bybit_ws_running()
    
    # Heartbeat task (optional visibility)
    async def heartbeat(period_secs: int = 30) -> None:
        while True:
            payload: dict[str, bool | float | int] = {"alive": True}
            try:
                import psutil  # pragma: no cover
                p = psutil.Process()
                payload.update({
                    "rss_mb": float(round(p.memory_info().rss / 1024 / 1024, 1)),
                    "cpu_percent": float(p.cpu_percent(interval=None)),
                })
            except Exception:
                pass
            logger.info("heartbeat", **payload)
            await asyncio.sleep(period_secs)

    hb_secs = _APP_CONFIG.heartbeat_secs if _APP_CONFIG else int(os.getenv("HEARTBEAT_SECS", "60"))
    hb_task = asyncio.create_task(heartbeat(hb_secs))

    # Optional Prometheus metrics without API (if enabled and lib available)
    if (_APP_CONFIG and _APP_CONFIG.enable_metrics) or os.getenv("ENABLE_METRICS", "0") == "1":
        try:
            from prometheus_client import start_http_server
            port = int(os.getenv("METRICS_PORT", "9300"))
            start_http_server(port)
            logger.info("metrics_server_started", port=port)
        except Exception as e:
            logger.warning("metrics_server_failed", error=str(e))

    # Garder le scheduler en vie
    try:
        while True:
            await asyncio.sleep(10)
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    finally:
        # Stop heartbeat
        try:
            hb_task.cancel()
            with contextlib.suppress(Exception):
                await hb_task
        except Exception:
            pass
        await scheduler.shutdown()

async def main():
    setup_logging()
    load_dotenv()
    mode = _APP_CONFIG.mode if _APP_CONFIG else os.getenv('CRYPTO_MONITOR_MODE', 'scheduler')
    enable_sched = (_APP_CONFIG.enable_scheduler if _APP_CONFIG else os.getenv('ENABLE_SCHEDULER', '1') == '1')
    sched_cfg = _APP_CONFIG.scheduler_config if _APP_CONFIG else os.getenv('SCHEDULER_CONFIG', 'scheduler/jobs.yaml')
    os.environ.setdefault('SCHEDULER_CONFIG', sched_cfg)
    logger.info("Starting Crypto Monitor", mode=mode, enable_sched=enable_sched, sched_cfg=sched_cfg)

    # (Removed unused 'tasks' list previously here)

    if enable_sched and build_scheduler is not None:
        scheduler = build_scheduler()
        # AsyncIOScheduler.start() is sync and returns None
        scheduler.start()
        logger.info("Scheduler started", jobs=[j.id for j in scheduler.get_jobs()])

        # Expose build info metric
        try:
            from scheduler.runner import set_build_info
            set_build_info(
                run_id=os.getenv("RUN_ID"),
                version=os.getenv("APP_VERSION", os.getenv("VERSION")),
                git_sha=os.getenv("GIT_SHA"),
            )
        except Exception:
            pass

        # Heartbeat and optional metrics in this mode too
        from pipeline.health import heartbeat as _heartbeat
        hb_secs = _APP_CONFIG.heartbeat_secs if _APP_CONFIG else int(os.getenv("HEARTBEAT_SECS", "60"))
        hb_task = asyncio.create_task(_heartbeat(hb_secs))

        if (_APP_CONFIG and _APP_CONFIG.enable_metrics) or os.getenv("ENABLE_METRICS", "0") == "1":
            try:
                from prometheus_client import start_http_server
                port = int(os.getenv("METRICS_PORT", "9300"))
                start_http_server(port)
                logger.info("metrics_server_started", port=port)
            except Exception as e:
                logger.warning("metrics_server_failed", error=str(e))

        # Optional lightweight health HTTP endpoint
        health_server = None
        health_port = int(os.getenv("HEALTH_PORT", "9310"))
        if os.getenv("ENABLE_HEALTH", "1") == "1":
            from pipeline.health import start_health_server
            health_server = start_health_server(health_port, scheduler_ref=scheduler)

        try:
            # Démarrer WS Bybit si activé et non déjà lancé (en parallèle)
            _ensure_bybit_ws_running()
            while True:
                await asyncio.sleep(60)
        except KeyboardInterrupt:
            logger.info("Scheduler interrupted by user")
        finally:
            with contextlib.suppress(Exception):
                if health_server is not None:
                    health_server.shutdown()
                    health_server.server_close()
            with contextlib.suppress(Exception):
                hb_task.cancel()
                await hb_task
            with contextlib.suppress(Exception):
                scheduler.shutdown(wait=False)
        return
    else:
        logger.warning("Scheduler disabled or builder missing")

    logger.warning("Nothing to run; exiting")
    sys.exit(0)

def setup_logging():
    """Configuration du logging structuré"""
    # Create logs directory
    logs_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(logs_dir, exist_ok=True)

    # Central logging setup (idempotent)
    from pipeline.logging_config import setup_logging
    setup_logging()
    # Metrics server (Prometheus) si activé
    try:
        from pipeline.metrics import init_metrics_if_enabled
        if init_metrics_if_enabled():
            logger.info("metrics_server_started", port=os.getenv("METRICS_PORT", "9300"))
    except Exception as e:
        logger.warning("metrics_init_failed", error=str(e))

if __name__ == "__main__":
    try:
        # Chargement facultatif de .env.local uniquement en exécution directe,
        # pour ne pas impacter les tests qui importent ce module.
        try:
            if os.path.exists(".env.local"):
                load_dotenv(dotenv_path=".env.local", override=True)
                logger.info("env_local_loaded", path=(os.path.abspath(".env.local")))
        except Exception:
            # Ne pas bloquer le démarrage si .env.local est invalide
            pass
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error("Application crashed", error=str(e), error_type=type(e).__name__)
        sys.exit(1)