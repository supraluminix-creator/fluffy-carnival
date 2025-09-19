"""
Orchestrateur pour l'exécution parallèle des collectors.

Ce module gère l'exécution concurrente des collectors avec:
- Exécution parallèle via asyncio.gather()
- Gestion individuelle des erreurs
- Logging structuré des performances
- Métriques agrégées
"""

import asyncio
import time
from typing import Any

import structlog
from prometheus_client import Counter, Histogram

logger = structlog.get_logger(__name__)

# Métriques Prometheus pour l'orchestrateur
orchestrator_executions = Counter(
    'orchestrator_executions_total',
    'Total orchestrator executions',
    ['success']
)

orchestrator_duration = Histogram(
    'orchestrator_duration_seconds',
    'Orchestrator execution duration'
)

class ParallelOrchestrator:
    """Orchestrateur pour exécution parallèle des collectors"""
    
    def __init__(self, collectors: list[Any] = None):
        """
        Initialise l'orchestrateur.
        
        Args:
            collectors: Liste des collectors à gérer
        """
        self.collectors = collectors or []
        self.execution_stats: dict[str, Any] = {
            'total_executions': 0,
            'successful_executions': 0,
            'failed_executions': 0,
            'last_execution_time': 0.0,
            'last_execution_duration': 0.0
        }
        
        logger.info(
            "ParallelOrchestrator initialized",
            collectors_count=len(self.collectors)
        )
    
    def add_collector(self, collector) -> None:
        """Ajoute un collector à l'orchestrateur"""
        self.collectors.append(collector)
        logger.info(
            "Collector added to orchestrator",
            collector=collector.name,
            total_collectors=len(self.collectors)
        )
    
    def remove_collector(self, collector_name: str) -> bool:
        """
        Retire un collector par nom.
        
        Returns:
            True si retiré, False si non trouvé
        """
        for i, collector in enumerate(self.collectors):
            if collector.name == collector_name:
                self.collectors.pop(i)
                logger.info(
                    "Collector removed from orchestrator",
                    collector=collector_name,
                    total_collectors=len(self.collectors)
                )
                return True
        return False
    
    async def run_all_collectors(self, timeout: float | None = None) -> dict[str, Any]:
        """
        Exécute tous les collectors en parallèle.
        
        Args:
            timeout: Timeout global en secondes (optionnel)
            
        Returns:
            Dict avec résultats d'exécution
        """
        if not self.collectors:
            logger.warning("No collectors to execute")
            return {
                'status': 'skipped',
                'reason': 'no_collectors',
                'results': {}
            }
        
        start_time = time.time()
        execution_id = f"exec_{int(start_time)}"
        
        logger.info(
            "Starting parallel collectors execution",
            execution_id=execution_id,
            collectors_count=len(self.collectors),
            collectors=[c.name for c in self.collectors],
            timeout=timeout
        )
        
        try:
            # Métriques début
            self.execution_stats['total_executions'] += 1
            
            # Exécution parallèle avec timeout
            results = await asyncio.wait_for(
                asyncio.gather(
                    *[self._safe_collect(collector, execution_id) for collector in self.collectors],
                    return_exceptions=True
                ),
                timeout=timeout
            )
            
            # Analyser les résultats
            execution_summary = self._analyze_results(results, execution_id)
            
            # Calculer durée totale
            execution_time = time.time() - start_time
            execution_summary['execution_time_seconds'] = round(execution_time, 2)
            
            # Mettre à jour stats
            # Store as float for clarity (mypy):
            self.execution_stats['last_execution_time'] = float(start_time)
            self.execution_stats['last_execution_duration'] = float(execution_time)
            
            if execution_summary['successful_count'] > 0:
                self.execution_stats['successful_executions'] += 1
                orchestrator_executions.labels(success='true').inc()
            else:
                self.execution_stats['failed_executions'] += 1
                orchestrator_executions.labels(success='false').inc()
            
            # Métrique durée
            orchestrator_duration.observe(execution_time)
            
            logger.info(
                "Parallel collectors execution completed",
                execution_id=execution_id,
                **execution_summary
            )
            
            return {
                'status': 'completed',
                'execution_id': execution_id,
                **execution_summary
            }
            
        except TimeoutError:
            execution_time = time.time() - start_time
            
            logger.error(
                "Parallel collectors execution timed out",
                execution_id=execution_id,
                timeout_seconds=timeout,
                partial_execution_time=round(execution_time, 2)
            )
            
            self.execution_stats['failed_executions'] += 1
            orchestrator_executions.labels(success='false').inc()
            
            return {
                'status': 'timeout',
                'execution_id': execution_id,
                'timeout_seconds': timeout,
                'partial_execution_time': round(execution_time, 2)
            }
            
        except Exception as e:
            execution_time = time.time() - start_time
            
            logger.error(
                "Parallel collectors execution failed",
                execution_id=execution_id,
                error=str(e),
                error_type=type(e).__name__,
                execution_time=round(execution_time, 2)
            )
            
            self.execution_stats['failed_executions'] += 1
            orchestrator_executions.labels(success='false').inc()
            
            return {
                'status': 'error',
                'execution_id': execution_id,
                'error': str(e),
                'execution_time': round(execution_time, 2)
            }
    
    async def _safe_collect(self, collector, execution_id: str) -> dict[str, Any]:
        """
        Wrapper sécurisé pour exécution collector avec logging détaillé.
        
        Args:
            collector: Instance du collector
            execution_id: ID unique de l'exécution
            
        Returns:
            Dict avec résultat ou erreur
        """
        collector_name = collector.name
        start_time = time.time()
        
        try:
            logger.info(
                "Starting collector execution",
                collector=collector_name,
                execution_id=execution_id
            )
            
            # Exécuter le collector
            result = await collector.collect()
            
            execution_time = time.time() - start_time
            
            # Analyse du résultat
            result_summary = self._summarize_result(result)
            
            logger.info(
                "Collector execution succeeded",
                collector=collector_name,
                execution_id=execution_id,
                execution_time_seconds=round(execution_time, 2),
                **result_summary
            )
            
            return {
                'collector': collector_name,
                'status': 'success',
                'execution_time': round(execution_time, 2),
                'result': result,
                'result_summary': result_summary
            }
            
        except Exception as e:
            execution_time = time.time() - start_time
            
            logger.error(
                "Collector execution failed",
                collector=collector_name,
                execution_id=execution_id,
                execution_time_seconds=round(execution_time, 2),
                error=str(e),
                error_type=type(e).__name__
            )
            
            return {
                'collector': collector_name,
                'status': 'error',
                'execution_time': round(execution_time, 2),
                'error': str(e),
                'error_type': type(e).__name__
            }
    
    def _analyze_results(self, results: list, execution_id: str) -> dict[str, Any]:
        """Analyse les résultats d'exécution parallèle"""
        successful_results = []
        failed_results = []
        
        for result in results:
            if isinstance(result, Exception):
                failed_results.append({
                    'error': str(result),
                    'error_type': type(result).__name__
                })
            elif isinstance(result, dict):
                if result.get('status') == 'success':
                    successful_results.append(result)
                else:
                    failed_results.append(result)
            else:
                # Résultat direct (legacy)
                successful_results.append({
                    'collector': 'unknown',
                    'status': 'success',
                    'result': result
                })
        
        total_count = len(results)
        successful_count = len(successful_results)
        failed_count = len(failed_results)
        
        # Calculer temps d'exécution par collector
        execution_times = [
            r.get('execution_time', 0) for r in successful_results + failed_results
            if isinstance(r, dict) and 'execution_time' in r
        ]
        
        avg_execution_time = (
            round(sum(execution_times) / len(execution_times), 2)
            if execution_times else 0
        )
        
        return {
            'total_count': total_count,
            'successful_count': successful_count,
            'failed_count': failed_count,
            'success_rate': round((successful_count / total_count) * 100, 1) if total_count > 0 else 0,
            'avg_execution_time_seconds': avg_execution_time,
            'successful_results': successful_results,
            'failed_results': failed_results
        }
    
    def _summarize_result(self, result: Any) -> dict[str, Any]:
        """Crée un résumé du résultat pour logging"""
        if result is None:
            return {'type': 'none'}
        
        if isinstance(result, dict):
            return {
                'type': 'dict',
                'keys_count': len(result.keys()),
                'sample_keys': list(result.keys())[:3]
            }
        
        if isinstance(result, list):
            return {
                'type': 'list',
                'length': len(result),
                'sample_items': str(result[:2]) if len(result) > 0 else 'empty'
            }
        
        if isinstance(result, str):
            return {
                'type': 'string',
                'length': len(result),
                'preview': result[:50] + '...' if len(result) > 50 else result
            }
        
        return {
            'type': type(result).__name__,
            'preview': str(result)[:50]
        }
    
    def get_orchestrator_stats(self) -> dict[str, Any]:
        """Retourne les statistiques de l'orchestrateur"""
        return {
            'collectors_count': len(self.collectors),
            'execution_stats': self.execution_stats.copy(),
            'collectors': [c.name for c in self.collectors]
        }

async def run_collectors_parallel(collectors: list[Any], timeout: float = None) -> dict[str, Any]:
    """
    Fonction utilitaire pour exécuter des collectors en parallèle.
    
    Args:
        collectors: Liste des collectors
        timeout: Timeout global
        
    Returns:
        Résultats d'exécution
    """
    orchestrator = ParallelOrchestrator(collectors)
    return await orchestrator.run_all_collectors(timeout=timeout)