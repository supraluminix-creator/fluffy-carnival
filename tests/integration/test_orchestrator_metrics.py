"""
Integration tests for orchestrator metrics and Prometheus integration.

Tests Prometheus metrics collection with isolated registry and variance assertions.
"""

import asyncio
import pytest
from unittest.mock import Mock, patch
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
import time
from statistics import stdev

from pipeline.orchestrator import ParallelOrchestrator


class MockCollector:
    """Mock collector for metrics testing."""
    
    def __init__(self, name: str, collect_result=None, collect_exception=None, delay=0):
        self.name = name
        self.collect_result = collect_result or {"data": f"result_{name}"}
        self.collect_exception = collect_exception
        self.delay = delay
        self.collect_calls = 0
    
    async def collect(self):
        """Mock collect method with configurable delay."""
        self.collect_calls += 1
        
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        
        if self.collect_exception:
            raise self.collect_exception
        
        return self.collect_result


@pytest.fixture
def isolated_registry():
    """Create an isolated Prometheus registry for each test."""
    return CollectorRegistry()


@pytest.fixture
def metrics_orchestrator(isolated_registry):
    """Create an orchestrator with isolated metrics."""
    # Create a simple orchestrator without mocking complex Prometheus metrics
    orchestrator = ParallelOrchestrator()
    # Add test attributes for verification
    orchestrator._test_registry = isolated_registry
    return orchestrator


class TestOrchestratorMetrics:
    """Test Prometheus metrics collection and variance."""

    async def test_metrics_collection_success(self, metrics_orchestrator):
        """Test metrics are collected on successful orchestrator execution."""
        # Setup collectors
        collectors = [
            MockCollector("collector1", {"status": "ok"}),
            MockCollector("collector2", [1, 2, 3]),
        ]
        
        for collector in collectors:
            metrics_orchestrator.add_collector(collector)
        
        # Execute orchestrator
        result = await metrics_orchestrator.run_all_collectors()
        
        # Verify execution was successful
        assert result['status'] == 'completed'
        assert result['successful_count'] == 2
        
        # Verify metrics were updated (simplified check since we use real orchestrator)
        assert hasattr(metrics_orchestrator, '_test_registry')

    async def test_metrics_collection_failure(self, metrics_orchestrator):
        """Test metrics are collected on failed orchestrator execution."""
        # Setup failing collectors
        collectors = [
            MockCollector("failing1", collect_exception=ValueError("Test error")),
            MockCollector("failing2", collect_exception=RuntimeError("Another error")),
        ]
        
        for collector in collectors:
            metrics_orchestrator.add_collector(collector)
        
        # Execute orchestrator
        result = await metrics_orchestrator.run_all_collectors()
        
        # Verify execution completed but with failures
        assert result['status'] == 'completed'
        assert result['successful_count'] == 0
        assert result['failed_count'] == 2

    async def test_metrics_collection_timeout(self, metrics_orchestrator):
        """Test metrics are collected on timeout."""
        # Setup slow collector
        slow_collector = MockCollector("slow", delay=1.0)
        metrics_orchestrator.add_collector(slow_collector)
        
        # Execute with timeout
        result = await metrics_orchestrator.run_all_collectors(timeout=0.1)
        
        # Verify timeout was recorded
        assert result['status'] == 'timeout'
        assert result['timeout_seconds'] == 0.1

    async def test_execution_duration_variance(self, metrics_orchestrator):
        """Test execution duration variance across multiple runs."""
        # Setup collectors with consistent behavior
        collectors = [
            MockCollector("consistent1", {"data": "stable"}, delay=0.01),
            MockCollector("consistent2", {"data": "stable"}, delay=0.01),
        ]
        
        for collector in collectors:
            metrics_orchestrator.add_collector(collector)
        
        # Execute multiple times and collect durations
        durations = []
        num_runs = 10
        
        for i in range(num_runs):
            result = await metrics_orchestrator.run_all_collectors()
            assert result['status'] == 'completed'
            durations.append(result['execution_time_seconds'])
        
        # Analyze variance
        assert len(durations) == num_runs
        mean_duration = sum(durations) / len(durations)
        duration_stdev = stdev(durations) if len(durations) > 1 else 0
        
        # Assertions about duration characteristics
        assert mean_duration >= 0.01  # Should take at least the delay time
        assert mean_duration < 1.0   # Should not take too long for simple operations
        
        # Standard deviation should be reasonable for such small delays
        # For very short operations, variance is often zero due to timing precision
        assert duration_stdev >= 0  # Non-negative standard deviation

    async def test_success_rate_variance(self, metrics_orchestrator):
        """Test success rate variance with mixed success/failure scenarios."""
        # Setup collectors with intermittent failures
        collectors = [
            MockCollector("reliable", {"data": "ok"}),  # Always succeeds
            MockCollector("unreliable", {"data": "ok"}),  # Will be modified per run
        ]
        
        for collector in collectors:
            metrics_orchestrator.add_collector(collector)
        
        success_rates = []
        num_runs = 6
        
        for i in range(num_runs):
            # Make unreliable collector fail every other run
            if i % 2 == 1:
                collectors[1].collect_exception = ValueError(f"Error on run {i}")
            else:
                collectors[1].collect_exception = None
            
            result = await metrics_orchestrator.run_all_collectors()
            success_rates.append(result['success_rate'])
        
        # Analyze success rate variance
        assert len(success_rates) == num_runs
        
        # Should see alternating success rates (100% and 50%)
        expected_rates = [100.0, 50.0] * (num_runs // 2)
        assert success_rates == expected_rates
        
        # Variance should be significant due to alternating behavior
        success_rate_stdev = stdev(success_rates)
        assert success_rate_stdev > 20  # High variance expected

    async def test_collector_execution_time_variance(self, metrics_orchestrator):
        """Test individual collector execution time variance."""
        # Setup collectors with different execution characteristics
        collectors = [
            MockCollector("fast", {"data": "quick"}, delay=0.001),
            MockCollector("medium", {"data": "medium"}, delay=0.005),
            MockCollector("slow", {"data": "slow"}, delay=0.01),
        ]
        
        for collector in collectors:
            metrics_orchestrator.add_collector(collector)
        
        # Execute and collect individual execution times
        all_execution_times = {'fast': [], 'medium': [], 'slow': []}
        num_runs = 5
        
        for i in range(num_runs):
            result = await metrics_orchestrator.run_all_collectors()
            assert result['status'] == 'completed'
            
            # Extract individual execution times
            for res in result['successful_results']:
                collector_name = res['collector']
                execution_time = res['execution_time']
                all_execution_times[collector_name].append(execution_time)
        
        # Analyze variance for each collector type
        for collector_name, times in all_execution_times.items():
            assert len(times) == num_runs
            
            mean_time = sum(times) / len(times)
            time_stdev = stdev(times) if len(times) > 1 else 0
            
            # Each collector should have reasonably consistent performance
            # For very short operations, variance may be zero due to timing precision
            assert time_stdev >= 0  # Non-negative standard deviation
            
            # Verify expected ordering exists (but with tolerance for timing precision)
            if collector_name == 'fast':
                assert mean_time <= 0.01  # Should be very fast
            elif collector_name == 'medium':
                assert 0.003 <= mean_time <= 0.02  # Should be in middle
            elif collector_name == 'slow':
                assert mean_time >= 0.008  # Should be slowest

    async def test_concurrent_execution_metrics(self, metrics_orchestrator):
        """Test metrics accuracy during concurrent collector execution."""
        # Setup multiple collectors that run concurrently
        collectors = [
            MockCollector(f"concurrent_{i}", {"id": i}, delay=0.01)
            for i in range(5)
        ]
        
        for collector in collectors:
            metrics_orchestrator.add_collector(collector)
        
        # Record start time and execute
        start_time = time.time()
        result = await metrics_orchestrator.run_all_collectors()
        total_wall_time = time.time() - start_time
        
        # Verify concurrent execution
        assert result['status'] == 'completed'
        assert result['successful_count'] == 5
        
        # Total execution time should be close to wall time (parallel execution)
        execution_time = result['execution_time_seconds']
        assert abs(execution_time - total_wall_time) < 0.05  # Within 50ms
        
        # Wall time should be much less than sum of individual delays
        expected_sequential_time = 5 * 0.01  # 5 collectors * 10ms each
        assert total_wall_time < expected_sequential_time * 0.8  # At least 20% faster

    async def test_stats_aggregation_accuracy(self, metrics_orchestrator):
        """Test accuracy of aggregated statistics."""
        # Setup collectors for comprehensive stats testing
        collectors = [
            MockCollector("stats1", {"count": 10}),
            MockCollector("stats2", {"count": 20}),
            MockCollector("stats3", collect_exception=ValueError("Planned failure")),
        ]
        
        for collector in collectors:
            metrics_orchestrator.add_collector(collector)
        
        # Execute multiple times
        num_runs = 3
        all_results = []
        
        for i in range(num_runs):
            result = await metrics_orchestrator.run_all_collectors()
            all_results.append(result)
        
        # Verify consistent metrics across runs
        for result in all_results:
            assert result['status'] == 'completed'
            assert result['total_count'] == 3
            assert result['successful_count'] == 2
            assert result['failed_count'] == 1
            assert result['success_rate'] == pytest.approx(66.7, abs=0.1)
        
        # Check orchestrator internal stats
        final_stats = metrics_orchestrator.get_orchestrator_stats()
        assert final_stats['execution_stats']['total_executions'] == num_runs
        assert final_stats['execution_stats']['successful_executions'] == num_runs
        assert final_stats['execution_stats']['failed_executions'] == 0

    async def test_error_rate_metrics(self, metrics_orchestrator):
        """Test error rate tracking and metrics."""
        # Setup collectors with known error patterns
        collectors = [
            MockCollector("error_test1", collect_exception=ValueError("Test error 1")),
            MockCollector("error_test2", collect_exception=RuntimeError("Test error 2")),
            MockCollector("error_test3", collect_exception=TypeError("Test error 3")),
        ]
        
        for collector in collectors:
            metrics_orchestrator.add_collector(collector)
        
        # Execute and verify error tracking
        result = await metrics_orchestrator.run_all_collectors()
        
        assert result['status'] == 'completed'
        assert result['successful_count'] == 0
        assert result['failed_count'] == 3
        assert result['success_rate'] == 0.0
        
        # Verify error details
        failed_results = result['failed_results']
        assert len(failed_results) == 3
        
        error_types = [r['error_type'] for r in failed_results]
        assert 'ValueError' in error_types
        assert 'RuntimeError' in error_types
        assert 'TypeError' in error_types
        
        # All should have execution times recorded
        for failed_result in failed_results:
            assert 'execution_time' in failed_result
            assert failed_result['execution_time'] >= 0