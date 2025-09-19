"""
Crypto Monitor - Application principale (scheduler + legacy), sans API.

Cette version intègre:
- Scheduler centralisé avec jitter anti-rate-limit
- Orchestrateur pour exécution parallèle des collectors  
- Collectors basés sur BaseCollector pattern
"""

import asyncio
import contextlib
import logging
import os
import sys
import uuid
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

import structlog
import structlog.contextvars as structlog_ctx
from dotenv import load_dotenv
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # Only imported for type checking; avoids runtime stub dependency
    from tabulate import tabulate  # type: ignore
else:  # pragma: no cover
    from tabulate import tabulate  # type: ignore

from pipeline.collectors.defi import fetch_defillama_tvl, DefiTVLRecord
from pipeline.collectors.derivatives import fetch_bybit_long_short_ratio, fetch_bybit_oi

# Import collectors (existants)
from pipeline.collectors.market import fetch_macro, MacroRecord
from pipeline.collectors.onchain import (
    fetch_hashrate,
    fetch_sopr,
    fetch_txcount,
    TxCountRecord,
    HashrateRecord,
    SoprRecord,
)
from pipeline.collectors.sentiment import fetch_fear_greed, SentimentRecord
from pipeline.collectors.derivatives import (
    OpenInterestRecord,
    LongShortRatioRecord,
)
from typing import Union, List, Dict, Any

CollectorRecord = Union[
    MacroRecord,
    DefiTVLRecord,
    TxCountRecord,
    HashrateRecord,
    SoprRecord,
    OpenInterestRecord,
    LongShortRatioRecord,
    SentimentRecord,
    Dict[str, Any],  # legacy/unknown
]

# Import components Sprint 1
from pipeline.orchestrator import ParallelOrchestrator
from pipeline.scheduler import CryptoScheduler, get_collector_intervals_from_env

try:
    from scheduler.runner import build_scheduler
except Exception:
    build_scheduler = None  # fallback if module missing

# Configuration
load_dotenv()
logger = structlog.get_logger(__name__)

EXPORT_DIR = "exports"
os.makedirs(EXPORT_DIR, exist_ok=True)

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

def export_csv(data: list, filename: str):
    """Export des données en CSV compatible avec format existant"""
    import csv
    if not data:
        logger.warning("No data to export", filename=filename)
        return
    
    try:
        # Harmonise chaque dict selon EXPORT_FIELDS
        rows = []
        for d in data:
            row = {k: d.get(k, None) for k in EXPORT_FIELDS}
            rows.append(row)
        
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=EXPORT_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        
        logger.info("CSV export completed", filename=filename, rows=len(rows))
    except Exception as e:
        logger.error("CSV export failed", filename=filename, error=str(e))

async def run_legacy_collection():
    """Collection legacy pour compatibilité (mode fallback)"""
    logger.info("Running legacy collection mode")
    
    # API keys depuis environnement
    cmc_api_key = os.getenv("CMC_API_KEY", "")
    etherscan_api_key = os.getenv("ETHERSCAN_API_KEY", "")
    
    results: List[CollectorRecord] = []

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
    export_csv(results, os.path.join(EXPORT_DIR, "latest_export.csv"))
    run_id = os.getenv("RUN_ID", "")
    ts_name = f"pipeline_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if run_id:
        ts_name = f"{ts_name}_{run_id}"
    export_csv(results, os.path.join(EXPORT_DIR, f"{ts_name}.csv"))
    
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
        'sopr': LegacyCollectorWrapper('sopr', fetch_sopr, "BTC"),
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
                    export_csv(data_for_export, os.path.join(EXPORT_DIR, "latest_export.csv"))
                    run_id = os.getenv("RUN_ID", "")
                    ts_name = f"pipeline_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    if run_id:
                        ts_name = f"{ts_name}_{run_id}"
                    export_csv(data_for_export, os.path.join(EXPORT_DIR, f"{ts_name}.csv"))
            
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
    
    # Heartbeat task (optional visibility)
    async def heartbeat(period_secs: int = 30) -> None:
        while True:
            payload: dict[str, bool | float | int] = {"alive": True}
            try:
                import psutil  # type: ignore[import-untyped]  # pragma: no cover
                p = psutil.Process()
                payload.update({
                    "rss_mb": float(round(p.memory_info().rss / 1024 / 1024, 1)),
                    "cpu_percent": float(p.cpu_percent(interval=None)),
                })
            except Exception:
                pass
            logger.info("heartbeat", **payload)
            await asyncio.sleep(period_secs)

    hb_secs = int(os.getenv("HEARTBEAT_SECS", "60"))
    hb_task = asyncio.create_task(heartbeat(hb_secs))

    # Optional Prometheus metrics without API (if enabled and lib available)
    if os.getenv("ENABLE_METRICS", "0") == "1":
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
    mode = os.getenv('CRYPTO_MONITOR_MODE', 'scheduler')
    enable_sched = os.getenv('ENABLE_SCHEDULER', '1') == '1'
    sched_cfg = os.getenv('SCHEDULER_CONFIG', 'scheduler/jobs.yaml')
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
        async def heartbeat(period_secs: int = 30):
            while True:
                payload: dict[str, float | int | bool] = {"alive": True}
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

        hb_secs = int(os.getenv("HEARTBEAT_SECS", "60"))
        hb_task = asyncio.create_task(heartbeat(hb_secs))

        if os.getenv("ENABLE_METRICS", "0") == "1":
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
            try:
                import json
                import threading
                from http.server import BaseHTTPRequestHandler, HTTPServer

                class HealthHandler(BaseHTTPRequestHandler):
                    HEALTH_PORT: int | None = None
                    def log_message(self, format, *args):
                        # Silence default HTTP logs; we already have heartbeat
                        return

                    def do_GET(self) -> None:
                        try:
                            path = self.path.split("?")[0]
                            if path == "/metrics/ready":
                                from scheduler.runner import get_status_snapshot
                                snap = get_status_snapshot()
                                ready_val = 1 if snap.get("ready") else 0
                                ts_val = int(snap.get("ready_ts") or 0)
                                body = f"ready {ready_val}\nready_timestamp {ts_val}\n".encode()
                                self.send_response(200)
                                self.send_header("Content-Type", "text/plain; charset=utf-8")
                                self.send_header("Content-Length", str(len(body)))
                                self.end_headers()
                                self.wfile.write(body)
                                return
                            if path not in ("/health", "/ready", "/live"):
                                self.send_response(404)
                                self.end_headers()
                                return
                            from scheduler.runner import get_status_snapshot
                            snap = get_status_snapshot()
                            snap["run_id"] = os.getenv("RUN_ID", "")
                            snap["jobs"] = [j.id for j in scheduler.get_jobs()]
                            # Add ports and config path for easier remote debugging
                            enable_metrics = os.getenv("ENABLE_METRICS", "0") == "1"
                            metrics_port = int(os.getenv("METRICS_PORT", "9300")) if enable_metrics else None
                            snap["ports"] = {"metrics": metrics_port, "health": getattr(self, "HEALTH_PORT", None)}
                            snap["config_path"] = os.getenv("SCHEDULER_CONFIG", "scheduler/jobs.yaml")
                            payload = json.dumps(snap).encode("utf-8")
                            self.send_response(200)
                            self.send_header("Content-Type", "application/json")
                            self.send_header("Content-Length", str(len(payload)))
                            self.end_headers()
                            self.wfile.write(payload)
                        except Exception:
                            try:
                                self.send_response(500)
                                self.end_headers()
                            finally:
                                pass

                # Provide health port to handler for inclusion in payload
                HealthHandler.HEALTH_PORT = health_port
                health_server = HTTPServer(("0.0.0.0", health_port), HealthHandler)
                th = threading.Thread(target=health_server.serve_forever, name="health-http", daemon=True)
                th.start()
                logger.info("health_server_started", port=health_port)
            except Exception as e:
                logger.warning("health_server_failed", error=str(e))
        # Keep process alive
        try:
            while True:
                await asyncio.sleep(60)
        except KeyboardInterrupt:
            logger.info("Scheduler interrupted by user")
        finally:
            # Stop health server if any
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

    # Per-run log file (avoids conflicts with concurrent runs)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_log_path = os.path.join(logs_dir, f"run_{ts}.log")

    # Handlers
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(message)s"))

    rotating_handler = TimedRotatingFileHandler(
        filename=os.path.join(logs_dir, "app.log"),
        when="midnight",
        interval=1,
        backupCount=14,
        encoding="utf-8",
        utc=False,
    )
    rotating_handler.setLevel(logging.INFO)
    rotating_handler.setFormatter(logging.Formatter("%(message)s"))

    run_file_handler = logging.FileHandler(run_log_path, mode="w", encoding="utf-8")
    run_file_handler.setLevel(logging.INFO)
    run_file_handler.setFormatter(logging.Formatter("%(message)s"))

    # Root logger configuration
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Replace any existing handlers to prevent duplicate logs
    root.handlers = [console_handler, rotating_handler, run_file_handler]

    # Prepare run_id and bind into contextvars so it's present on all logs
    run_id = os.getenv("RUN_ID") or uuid.uuid4().hex[:8]
    os.environ["RUN_ID"] = run_id
    structlog_ctx.clear_contextvars()
    structlog_ctx.bind_contextvars(run_id=run_id)

    # Structlog configuration: JSON lines with timestamp and level and merged contextvars
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog_ctx.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )

    # Announce where logs are written
    with contextlib.suppress(Exception):
        structlog.get_logger(__name__).info(
            "Logging initialized",
            run_log=run_log_path,
            rotating_log=os.path.join(logs_dir, "app.log"),
            run_id=run_id,
        )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error("Application crashed", error=str(e), error_type=type(e).__name__)
        sys.exit(1)