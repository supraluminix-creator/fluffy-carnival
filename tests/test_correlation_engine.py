"""Tests for correlation analysis engine."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from analysis.correlation_engine import (
    CorrelationEngine,
    CorrelationMatrix,
    CorrelationResult,
    analyze_correlations,
    get_correlation_engine
)


class TestCorrelationResult:
    """Test CorrelationResult dataclass."""

    def test_creation(self):
        """Test CorrelationResult creation and properties."""
        result = CorrelationResult(
            asset_a="BTCUSDT",
            asset_b="ETHUSDT",
            correlation=0.85,
            significance=0.001,
            strength="strong",
            direction="positive",
            timestamp=1234567890.0
        )

        assert result.asset_a == "BTCUSDT"
        assert result.asset_b == "ETHUSDT"
        assert result.correlation == 0.85
        assert result.significance == 0.001
        assert result.strength == "strong"
        assert result.direction == "positive"
        assert result.timestamp == 1234567890.0


class TestCorrelationMatrix:
    """Test CorrelationMatrix dataclass."""

    def test_creation(self):
        """Test CorrelationMatrix creation."""
        assets = ["BTCUSDT", "ETHUSDT", "ADAUSDT"]
        matrix = np.array([
            [1.0, 0.8, 0.3],
            [0.8, 1.0, 0.2],
            [0.3, 0.2, 1.0]
        ])
        significance = np.array([
            [0.0, 0.001, 0.1],
            [0.001, 0.0, 0.2],
            [0.1, 0.2, 0.0]
        ])

        corr_matrix = CorrelationMatrix(
            assets=assets,
            matrix=matrix,
            significance_matrix=significance,
            timestamp=1234567890.0
        )

        assert corr_matrix.assets == assets
        assert np.array_equal(corr_matrix.matrix, matrix)
        assert np.array_equal(corr_matrix.significance_matrix, significance)
        assert corr_matrix.timestamp == 1234567890.0

    def test_get_correlation(self):
        """Test getting correlation between specific assets."""
        assets = ["BTCUSDT", "ETHUSDT"]
        matrix = np.array([[1.0, 0.8], [0.8, 1.0]])
        significance = np.array([[0.0, 0.001], [0.001, 0.0]])

        corr_matrix = CorrelationMatrix(
            assets=assets,
            matrix=matrix,
            significance_matrix=significance,
            timestamp=1234567890.0
        )

        result = corr_matrix.get_correlation("BTCUSDT", "ETHUSDT")

        assert result is not None
        assert result.asset_a == "BTCUSDT"
        assert result.asset_b == "ETHUSDT"
        assert result.correlation == 0.8
        assert result.significance == 0.001
        assert result.strength == "strong"
        assert result.direction == "positive"

    def test_get_correlation_unknown_asset(self):
        """Test getting correlation for unknown asset."""
        assets = ["BTCUSDT", "ETHUSDT"]
        matrix = np.array([[1.0, 0.8], [0.8, 1.0]])

        corr_matrix = CorrelationMatrix(
            assets=assets,
            matrix=matrix,
            timestamp=1234567890.0
        )

        result = corr_matrix.get_correlation("BTCUSDT", "UNKNOWN")
        assert result is None

    def test_classify_strength(self):
        """Test correlation strength classification."""
        assets = ["BTCUSDT", "ETHUSDT"]
        matrix = np.array([[1.0, 0.8], [0.8, 1.0]])

        corr_matrix = CorrelationMatrix(
            assets=assets,
            matrix=matrix,
            timestamp=1234567890.0
        )

        # Test strong correlation
        result = corr_matrix.get_correlation("BTCUSDT", "ETHUSDT")
        assert result.strength == "strong"

        # Test moderate correlation
        matrix[0, 1] = 0.7
        matrix[1, 0] = 0.7
        result = corr_matrix.get_correlation("BTCUSDT", "ETHUSDT")
        assert result.strength == "moderate"

        # Test weak correlation
        matrix[0, 1] = 0.4
        matrix[1, 0] = 0.4
        result = corr_matrix.get_correlation("BTCUSDT", "ETHUSDT")
        assert result.strength == "weak"

        # Test no correlation
        matrix[0, 1] = 0.1
        matrix[1, 0] = 0.1
        result = corr_matrix.get_correlation("BTCUSDT", "ETHUSDT")
        assert result.strength == "none"

    def test_classify_direction(self):
        """Test correlation direction classification."""
        assets = ["BTCUSDT", "ETHUSDT"]
        matrix = np.array([[1.0, 0.8], [0.8, 1.0]])

        corr_matrix = CorrelationMatrix(
            assets=assets,
            matrix=matrix,
            timestamp=1234567890.0
        )

        # Test positive correlation
        result = corr_matrix.get_correlation("BTCUSDT", "ETHUSDT")
        assert result.direction == "positive"

        # Test negative correlation
        matrix[0, 1] = -0.8
        matrix[1, 0] = -0.8
        result = corr_matrix.get_correlation("BTCUSDT", "ETHUSDT")
        assert result.direction == "negative"

        # Test neutral correlation
        matrix[0, 1] = 0.05
        matrix[1, 0] = 0.05
        result = corr_matrix.get_correlation("BTCUSDT", "ETHUSDT")
        assert result.direction == "neutral"


class TestCorrelationEngine:
    """Test CorrelationEngine class."""

    @pytest.fixture
    async def engine(self):
        """Create a correlation engine instance."""
        engine = CorrelationEngine(window_size=50, update_interval=1)
        yield engine
        await engine.stop()

    @pytest.mark.asyncio
    async def test_initialization(self, engine):
        """Test engine initialization."""
        assert engine.window_size == 50
        assert engine.update_interval == 1
        assert engine.max_assets == 100
        assert not engine.running
        assert engine.correlation_matrix is None

    @pytest.mark.asyncio
    async def test_start_stop(self, engine):
        """Test engine start and stop."""
        await engine.start()
        assert engine.running
        assert engine._update_task is not None

        await engine.stop()
        assert not engine.running

    @pytest.mark.asyncio
    async def test_add_price_data(self, engine):
        """Test adding price data."""
        timestamp = time.time()

        # Add data for BTC
        await engine.add_price_data("BTCUSDT", timestamp, 50000.0)
        await engine.add_price_data("BTCUSDT", timestamp + 1, 50100.0)

        assert len(engine.price_data["BTCUSDT"]) == 2
        assert engine.price_data["BTCUSDT"][0] == (timestamp, 50000.0)
        assert engine.price_data["BTCUSDT"][1] == (timestamp + 1, 50100.0)

    @pytest.mark.asyncio
    async def test_add_price_data_window_limit(self, engine):
        """Test that price data respects window size limit."""
        # Add more data than window size
        for i in range(60):
            await engine.add_price_data("BTCUSDT", time.time() + i, 50000.0 + i)

        # Should only keep last 50 data points
        assert len(engine.price_data["BTCUSDT"]) == 50

    @pytest.mark.asyncio
    async def test_max_assets_limit(self, engine):
        """Test maximum assets limit."""
        # Fill up to max assets
        for i in range(100):
            await engine.add_price_data(f"ASSET{i}", time.time(), 100.0)

        # Try to add one more
        await engine.add_price_data("ASSET100", time.time(), 100.0)

        # Should not be added
        assert "ASSET100" not in engine.price_data
        assert len(engine.price_data) == 100

    @pytest.mark.asyncio
    async def test_get_correlation_matrix_insufficient_data(self, engine):
        """Test correlation matrix with insufficient data."""
        # Add data for only one asset
        await engine.add_price_data("BTCUSDT", time.time(), 50000.0)

        matrix = await engine.get_correlation_matrix()
        assert matrix is None

    @pytest.mark.asyncio
    async def test_get_correlation_matrix_with_data(self, engine):
        """Test correlation matrix calculation with sufficient data."""
        # Add data for two assets
        base_time = time.time()
        for i in range(50):
            await engine.add_price_data("BTCUSDT", base_time + i, 50000.0 + i * 100)
            await engine.add_price_data("ETHUSDT", base_time + i, 3000.0 + i * 10)

        matrix = await engine.get_correlation_matrix(force_refresh=True)

        assert matrix is not None
        assert len(matrix.assets) == 2
        assert "BTCUSDT" in matrix.assets
        assert "ETHUSDT" in matrix.assets
        assert matrix.matrix.shape == (2, 2)
        assert abs(matrix.matrix[0, 0] - 1.0) < 0.001  # Self-correlation should be 1
        assert abs(matrix.matrix[1, 1] - 1.0) < 0.001

    @pytest.mark.asyncio
    async def test_get_asset_correlations(self, engine):
        """Test getting correlations for a specific asset."""
        # Add data for multiple assets
        base_time = time.time()
        for i in range(50):
            await engine.add_price_data("BTCUSDT", base_time + i, 50000.0 + i * 100)
            await engine.add_price_data("ETHUSDT", base_time + i, 3000.0 + i * 10)
            await engine.add_price_data("ADAUSDT", base_time + i, 1.5 + i * 0.01)

        correlations = await engine.get_asset_correlations("BTCUSDT")

        assert len(correlations) == 2  # BTC vs ETH and BTC vs ADA
        assert all(c.asset_a == "BTCUSDT" for c in correlations)
        assert {c.asset_b for c in correlations} == {"ETHUSDT", "ADAUSDT"}

    @pytest.mark.asyncio
    async def test_get_top_correlations(self, engine):
        """Test getting top correlations across all pairs."""
        # Add data for three assets
        base_time = time.time()
        for i in range(50):
            await engine.add_price_data("BTCUSDT", base_time + i, 50000.0 + i * 100)
            await engine.add_price_data("ETHUSDT", base_time + i, 3000.0 + i * 10)
            await engine.add_price_data("ADAUSDT", base_time + i, 1.5 + i * 0.01)

        top_correlations = await engine.get_top_correlations(limit=3)

        assert len(top_correlations) == 3  # All pairs
        # Should be sorted by absolute correlation strength
        assert all(abs(c.correlation) >= abs(top_correlations[i+1].correlation)
                  for i, c in enumerate(top_correlations[:-1]))

    @pytest.mark.asyncio
    async def test_correlation_update_loop(self, engine):
        """Test the background correlation update loop."""
        await engine.start()

        # Add some data
        base_time = time.time()
        for i in range(50):
            await engine.add_price_data("BTCUSDT", base_time + i, 50000.0 + i * 100)
            await engine.add_price_data("ETHUSDT", base_time + i, 3000.0 + i * 10)

        # Wait for update
        await asyncio.sleep(1.5)

        # Should have correlation matrix now
        assert engine.correlation_matrix is not None

        await engine.stop()

    @pytest.mark.asyncio
    async def test_analyze_correlations_function(self):
        """Test the analyze_correlations convenience function."""
        # Create test data
        assets_data = {
            "BTCUSDT": [(time.time() + i, 50000.0 + i * 100) for i in range(50)],
            "ETHUSDT": [(time.time() + i, 3000.0 + i * 10) for i in range(50)]
        }

        matrix = await analyze_correlations(assets_data)

        assert matrix is not None
        assert len(matrix.assets) == 2
        assert matrix.matrix.shape == (2, 2)

    @pytest.mark.asyncio
    async def test_get_correlation_engine_singleton(self):
        """Test the global correlation engine singleton."""
        engine1 = await get_correlation_engine()
        engine2 = await get_correlation_engine()

        assert engine1 is engine2
        assert engine1.running

        # Clean up
        await engine1.stop()


class TestCorrelationEngineIntegration:
    """Integration tests for correlation engine."""

    @pytest.mark.asyncio
    async def test_realistic_correlation_calculation(self):
        """Test correlation calculation with realistic price data."""
        engine = CorrelationEngine(window_size=100)

        # Generate correlated price series
        base_time = time.time()
        np.random.seed(42)

        # BTC and ETH should be highly correlated
        btc_prices = []
        eth_prices = []

        for i in range(100):
            # Base trend
            btc_base = 50000 + i * 50
            eth_base = 3000 + i * 3

            # Add some correlation (80%) and noise
            noise_btc = np.random.normal(0, 100)
            noise_eth = 0.8 * noise_btc + 0.2 * np.random.normal(0, 30)

            btc_prices.append(btc_base + noise_btc)
            eth_prices.append(eth_base + noise_eth)

        # Add data
        for i, (btc_price, eth_price) in enumerate(zip(btc_prices, eth_prices)):
            await engine.add_price_data("BTCUSDT", base_time + i, btc_price)
            await engine.add_price_data("ETHUSDT", base_time + i, eth_price)

        # Calculate correlations
        matrix = await engine.get_correlation_matrix(force_refresh=True)

        assert matrix is not None
        btc_eth_corr = matrix.get_correlation("BTCUSDT", "ETHUSDT")

        assert btc_eth_corr is not None
        assert btc_eth_corr.correlation > 0.7  # Should be highly correlated
        assert btc_eth_corr.strength == "strong"
        assert btc_eth_corr.direction == "positive"

        await engine.stop()

    @pytest.mark.asyncio
    async def test_performance_large_dataset(self):
        """Test performance with larger dataset."""
        engine = CorrelationEngine(window_size=200, max_assets=50)

        base_time = time.time()

        # Add data for 20 assets
        for asset_idx in range(20):
            for i in range(200):
                price = 100.0 + asset_idx * 10 + i * 0.5 + np.random.normal(0, 1)
                await engine.add_price_data(f"ASSET{asset_idx}", base_time + i, price)

        start_time = time.time()
        matrix = await engine.get_correlation_matrix(force_refresh=True)
        computation_time = time.time() - start_time

        assert matrix is not None
        assert len(matrix.assets) == 20
        assert matrix.matrix.shape == (20, 20)

        # Should complete within reasonable time (< 100ms for this test)
        assert computation_time < 0.1, f"Computation took {computation_time:.3f}s"

        await engine.stop()