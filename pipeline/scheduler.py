"""
Scheduler centralisé pour orchestrer les collectors avec jitter anti-rate-limit.

Ce module implémente un scheduler robuste basé sur APScheduler qui:
- Respecte les quotas API avec jitter aléatoire
- Gère graceful shutdown sur signaux système
- Évite les overlapping executions avec max_instances=1
- Log structuré pour observabilité
"""

import asyncio
import logging
import os
import random
import signal

import structlog
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = structlog.get_logger(__name__)

class CryptoScheduler:
    """Scheduler centralisé pour collectors avec jitter anti-rate-limit"""
    
    def __init__(self, jitter_percent: int = 10):
        """
        Initialise le scheduler.
        
        Args:
            jitter_percent: Pourcentage de jitter à appliquer (défaut 10%)
        """
        self.scheduler = AsyncIOScheduler()
        self.jitter_percent = jitter_percent
        self.running = False
        self.collectors: dict[str, object] = {}
        
        # Configuration logging APScheduler
        logging.getLogger('apscheduler').setLevel(logging.WARNING)
        
        # Écouter événements scheduler
        self.scheduler.add_listener(self._job_executed, EVENT_JOB_EXECUTED)
        self.scheduler.add_listener(self._job_error, EVENT_JOB_ERROR)
        
        logger.info("CryptoScheduler initialized", jitter_percent=jitter_percent)
    
    def add_collector(self, collector, interval_seconds: int, 
                     jitter_percent: int = None) -> None:
        """
        Ajoute un collector au scheduler avec jitter.
        
        Args:
            collector: Instance du collector à scheduler
            interval_seconds: Intervalle de base en secondes
            jitter_percent: Jitter spécifique (optionnel, utilise default)
        """
        jitter_pct = jitter_percent or self.jitter_percent
        jitter_range = interval_seconds * (jitter_pct / 100)
        
        # Jitter aléatoire ±10%
        jitter = random.uniform(-jitter_range, jitter_range)
        actual_interval = max(60, interval_seconds + jitter)  # Min 1 minute
        
        job_id = f"collector_{collector.name}"
        
        self.scheduler.add_job(
            func=self._safe_collect,
            args=[collector],
            trigger=IntervalTrigger(seconds=actual_interval),
            id=job_id,
            max_instances=1,  # Évite overlap
            coalesce=True,    # Regroupe jobs en retard
            misfire_grace_time=30  # Grace period 30s
        )
        
        self.collectors[collector.name] = collector
        
        logger.info(
            "Collector added to scheduler",
            collector=collector.name,
            base_interval=interval_seconds,
            actual_interval=round(actual_interval, 1),
            jitter=round(jitter, 1),
            job_id=job_id
        )
    
    async def _safe_collect(self, collector) -> None:
        """
        Wrapper sécurisé pour exécution collector avec logging.
        
        Args:
            collector: Instance du collector à exécuter
        """
        collector_name = collector.name
        start_time = asyncio.get_event_loop().time()
        
        try:
            logger.info("Starting collector execution", collector=collector_name)
            
            # Exécuter le collector
            result = await collector.collect()
            
            execution_time = asyncio.get_event_loop().time() - start_time
            
            logger.info(
                "Collector execution completed",
                collector=collector_name,
                execution_time_seconds=round(execution_time, 2),
                result_summary=str(result)[:100] if result else "None"
            )
            
        except Exception as e:
            execution_time = asyncio.get_event_loop().time() - start_time
            
            logger.error(
                "Collector execution failed",
                collector=collector_name,
                execution_time_seconds=round(execution_time, 2),
                error=str(e),
                error_type=type(e).__name__
            )
            # Ne pas re-raise pour éviter crash du scheduler
    
    def _job_executed(self, event):
        """Callback pour job exécuté avec succès"""
        logger.debug(
            "Scheduled job completed",
            job_id=event.job_id,
            scheduled_run_time=event.scheduled_run_time.isoformat()
        )
    
    def _job_error(self, event):
        """Callback pour job en erreur"""
        logger.error(
            "Scheduled job failed",
            job_id=event.job_id,
            scheduled_run_time=event.scheduled_run_time.isoformat(),
            exception=str(event.exception),
            traceback=event.traceback
        )
    
    async def start(self) -> None:
        """Démarre le scheduler"""
        if self.running:
            logger.warning("Scheduler already running")
            return
        
        self.scheduler.start()
        self.running = True
        
        # Setup graceful shutdown
        self._setup_signal_handlers()
        
        job_count = len(self.scheduler.get_jobs())
        logger.info(
            "CryptoScheduler started",
            job_count=job_count,
            collectors=list(self.collectors.keys())
        )
    
    async def shutdown(self, wait: bool = True) -> None:
        """
        Arrêt graceful du scheduler.
        
        Args:
            wait: Attendre la fin des jobs en cours
        """
        if not self.running:
            logger.warning("Scheduler not running")
            return
        
        logger.info("Shutting down scheduler gracefully", wait_for_jobs=wait)
        
        self.scheduler.shutdown(wait=wait)
        self.running = False
        
        logger.info("CryptoScheduler stopped")
    
    def _setup_signal_handlers(self) -> None:
        """Configure les handlers pour graceful shutdown"""
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating graceful shutdown")
            asyncio.create_task(self.shutdown())
        
        # Windows compatible signals
        signal.signal(signal.SIGINT, signal_handler)
        if hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, signal_handler)
    
    def get_scheduler_info(self) -> dict:
        """Retourne info sur l'état du scheduler"""
        jobs = self.scheduler.get_jobs()
        
        return {
            "running": self.running,
            "job_count": len(jobs),
            "collectors": list(self.collectors.keys()),
            "jobs": [
                {
                    "id": job.id,
                    "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                    "trigger": str(job.trigger)
                }
                for job in jobs
            ]
        }

def get_collector_intervals_from_env() -> dict[str, int]:
    """
    Récupère les intervalles des collectors depuis variables d'environnement.
    
    Returns:
        Dict mapping collector name -> interval en secondes
    """
    intervals = {
        'market': int(os.getenv('COLLECTOR_INTERVAL_MARKET', 300)),        # 5min
        'defillama': int(os.getenv('COLLECTOR_INTERVAL_DEFILLAMA', 900)),  # 15min  
        'onchain': int(os.getenv('COLLECTOR_INTERVAL_ONCHAIN', 1800)),     # 30min
        'derivatives': int(os.getenv('COLLECTOR_INTERVAL_DERIVATIVES', 300)), # 5min
        'sentiment': int(os.getenv('COLLECTOR_INTERVAL_SENTIMENT', 3600)), # 1h
    }
    
    logger.info("Collector intervals loaded from environment", intervals=intervals)
    return intervals