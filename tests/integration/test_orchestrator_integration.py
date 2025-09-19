"""
Integration tests for the ParallelOrchestrator.

Tests the orchestrator with various scenarios including success, failure, and timeout conditions.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, Mock

from pipeline.orchestrator import ParallelOrchestrator


class MockCollector:
    """Mock collector for testing orchestrator behavior."""
    
    def __init__(self, name: str, collect_result=None, collect_exception=None, delay=0):
        self.name = name
        self.collect_result = collect_result
        self.collect_exception = collect_exception
        self.delay = delay
        self.collect_calls = 0
    
    async def collect(self):
        """Mock collect method with configurable behavior."""
        self.collect_calls += 1
        
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        
        if self.collect_exception:
            raise self.collect_exception
        
        return self.collect_result


@pytest.fixture
def orchestrator():
    """Create a fresh orchestrator instance for each test."""
    return ParallelOrchestrator()


class TestOrchestratorIntegration:
    """Integration tests for ParallelOrchestrator."""

    async def test_orchestrator_success_scenario(self, orchestrator):
        """Test successful execution of multiple collectors."""
        # Setup collectors with different data types
        collectors = [
            MockCollector("test_dict", {"data": "test1", "count": 10}),
            MockCollector("test_list", [1, 2, 3, 4, 5]),
            MockCollector("test_string", "success_data"),
            MockCollector("test_none", None),
        ]
        
        for collector in collectors:
            orchestrator.add_collector(collector)
        
        # Execute orchestrator
        result = await orchestrator.run_all_collectors()
        
        # Verify overall execution
        assert result['status'] == 'completed'
        assert result['total_count'] == 4
        assert result['successful_count'] == 4
        assert result['failed_count'] == 0
        assert result['success_rate'] == 100.0
        assert 'execution_time_seconds' in result
        assert result['execution_time_seconds'] >= 0
        
        # Verify all collectors were called
        for collector in collectors:
            assert collector.collect_calls == 1
        
        # Verify individual results
        successful_results = result['successful_results']
        assert len(successful_results) == 4
        
        collector_names = [r['collector'] for r in successful_results]
        assert 'test_dict' in collector_names
        assert 'test_list' in collector_names
        assert 'test_string' in collector_names
        assert 'test_none' in collector_names

    async def test_orchestrator_mixed_success_failure(self, orchestrator):
        """Test orchestrator with both successful and failing collectors."""
        # Setup mixed collectors
        collectors = [
            MockCollector("success1", {"data": "ok"}),
            MockCollector("failure1", collect_exception=ValueError("Test error")),
            MockCollector("success2", [1, 2, 3]),
            MockCollector("failure2", collect_exception=RuntimeError("Another error")),
        ]
        
        for collector in collectors:
            orchestrator.add_collector(collector)
        
        # Execute orchestrator
        result = await orchestrator.run_all_collectors()
        
        # Verify mixed results
        assert result['status'] == 'completed'
        assert result['total_count'] == 4
        assert result['successful_count'] == 2
        assert result['failed_count'] == 2
        assert result['success_rate'] == 50.0
        
        # Check successful results
        successful_results = result['successful_results']
        assert len(successful_results) == 2
        success_names = [r['collector'] for r in successful_results]
        assert 'success1' in success_names
        assert 'success2' in success_names
        
        # Check failed results
        failed_results = result['failed_results']
        assert len(failed_results) == 2
        failure_names = [r['collector'] for r in failed_results]
        assert 'failure1' in failure_names
        assert 'failure2' in failure_names
        
        # Check error details
        for failed_result in failed_results:
            assert failed_result['status'] == 'error'
            assert 'error' in failed_result
            assert 'execution_time' in failed_result

    async def test_orchestrator_timeout_scenario(self, orchestrator):
        """Test orchestrator timeout handling."""
        # Setup collectors with one slow collector
        collectors = [
            MockCollector("fast1", {"data": "quick"}, delay=0.1),
            MockCollector("slow", {"data": "delayed"}, delay=2.0),  # Will timeout
            MockCollector("fast2", [1, 2, 3], delay=0.1),
        ]
        
        for collector in collectors:
            orchestrator.add_collector(collector)
        
        # Execute with short timeout
        result = await orchestrator.run_all_collectors(timeout=0.5)
        
        # Verify timeout handling
        assert result['status'] == 'timeout'
        assert result['timeout_seconds'] == 0.5
        assert 'partial_execution_time' in result
        assert result['partial_execution_time'] > 0.4  # Should be close to timeout

    async def test_orchestrator_empty_collectors(self, orchestrator):
        """Test orchestrator behavior with no collectors."""
        result = await orchestrator.run_all_collectors()
        
        assert result['status'] == 'skipped'
        assert result['reason'] == 'no_collectors'
        assert result['results'] == {}

    async def test_orchestrator_exception_handling(self, orchestrator):
        """Test orchestrator handling of various exception types."""
        exceptions_to_test = [
            ValueError("Value error test"),
            RuntimeError("Runtime error test"),
            TypeError("Type error test"),
            ConnectionError("Connection error test"),
        ]
        
        collectors = [
            MockCollector(f"error_{i}", collect_exception=exc)
            for i, exc in enumerate(exceptions_to_test)
        ]
        
        for collector in collectors:
            orchestrator.add_collector(collector)
        
        # Execute orchestrator
        result = await orchestrator.run_all_collectors()
        
        # Verify all exceptions were caught
        assert result['status'] == 'completed'
        assert result['successful_count'] == 0
        assert result['failed_count'] == len(exceptions_to_test)
        
        # Check error details
        failed_results = result['failed_results']
        error_types = [r['error_type'] for r in failed_results]
        assert 'ValueError' in error_types
        assert 'RuntimeError' in error_types
        assert 'TypeError' in error_types
        assert 'ConnectionError' in error_types

    async def test_orchestrator_stats_tracking(self, orchestrator):
        """Test orchestrator statistics tracking."""
        # Check initial stats
        initial_stats = orchestrator.get_orchestrator_stats()
        assert initial_stats['collectors_count'] == 0
        assert initial_stats['execution_stats']['total_executions'] == 0
        
        # Add collectors and run
        collectors = [
            MockCollector("test1", {"data": "ok"}),
            MockCollector("test2", [1, 2, 3]),
        ]
        
        for collector in collectors:
            orchestrator.add_collector(collector)
        
        # Execute multiple times
        for i in range(3):
            await orchestrator.run_all_collectors()
        
        # Check final stats
        final_stats = orchestrator.get_orchestrator_stats()
        assert final_stats['collectors_count'] == 2
        assert final_stats['execution_stats']['total_executions'] == 3
        assert final_stats['execution_stats']['successful_executions'] == 3
        assert final_stats['execution_stats']['failed_executions'] == 0
        assert final_stats['execution_stats']['last_execution_time'] is not None
        assert final_stats['execution_stats']['last_execution_duration'] is not None

    async def test_collector_management(self, orchestrator):
        """Test adding and removing collectors."""
        # Add collectors
        collector1 = MockCollector("test1", {"data": "ok"})
        collector2 = MockCollector("test2", [1, 2, 3])
        
        orchestrator.add_collector(collector1)
        orchestrator.add_collector(collector2)
        
        stats = orchestrator.get_orchestrator_stats()
        assert stats['collectors_count'] == 2
        assert 'test1' in stats['collectors']
        assert 'test2' in stats['collectors']
        
        # Remove collector
        removed = orchestrator.remove_collector("test1")
        assert removed is True
        
        stats = orchestrator.get_orchestrator_stats()
        assert stats['collectors_count'] == 1
        assert 'test1' not in stats['collectors']
        assert 'test2' in stats['collectors']
        
        # Try to remove non-existent collector
        removed = orchestrator.remove_collector("nonexistent")
        assert removed is False
        
        stats = orchestrator.get_orchestrator_stats()
        assert stats['collectors_count'] == 1

    async def test_result_summarization(self, orchestrator):
        """Test result summarization for different data types."""
        collectors = [
            MockCollector("dict_collector", {"key1": "value1", "key2": "value2", "key3": "value3"}),
            MockCollector("list_collector", list(range(10))),
            MockCollector("string_collector", "a" * 100),  # Long string
            MockCollector("none_collector", None),
        ]
        
        for collector in collectors:
            orchestrator.add_collector(collector)
        
        result = await orchestrator.run_all_collectors()
        
        # Check result summaries
        successful_results = result['successful_results']
        
        for res in successful_results:
            summary = res['result_summary']
            collector_name = res['collector']
            
            if collector_name == "dict_collector":
                assert summary['type'] == 'dict'
                assert summary['keys_count'] == 3
                assert len(summary['sample_keys']) <= 3
            elif collector_name == "list_collector":
                assert summary['type'] == 'list'
                assert summary['length'] == 10
            elif collector_name == "string_collector":
                assert summary['type'] == 'string'
                assert summary['length'] == 100
                assert len(summary['preview']) <= 53  # 50 chars + "..."
            elif collector_name == "none_collector":
                assert summary['type'] == 'none'