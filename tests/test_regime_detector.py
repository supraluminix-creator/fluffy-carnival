"""Tests for market regime detection and volatility clustering."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from analysis.regime_detector import (
    RegimeDetector,
    MarketRegime,
    VolatilityCluster,
    RegimeAnalysis,
    analyze_market_regime,
    get_regime_detector
)


class TestMarketRegime:
    """Test MarketRegime dataclass."""

    def test_creation(self):
        """Test MarketRegime creation and properties."""
        indicators = {'trend_strength': 0.8, 'volatility': 0.05}

        regime = MarketRegime(
            regime_type="bull",
            confidence=0.85,
            volatility_percentile=0.7,
            trend_strength=0.8,
            timestamp=1234567890.0,
            indicators=indicators
        )

        assert regime.regime_type == "bull"
        assert regime.confidence == 0.85
        assert regime.volatility_percentile == 0.7
        assert regime.trend_strength == 0.8
        assert regime.timestamp == 1234567890.0
        assert regime.indicators == indicators


class TestVolatilityCluster:
    """Test VolatilityCluster dataclass."""

    def test_creation(self):
        """Test VolatilityCluster creation."""
        characteristics = {'volatility_cv': 0.3}

        cluster = VolatilityCluster(
            cluster_id=1,
            assets=["BTCUSDT", "ETHUSDT"],
            avg_volatility=0.05,
            volatility_range=(0.03, 0.08),
            cluster_size=2,
            characteristics=characteristics
        )

        assert cluster.cluster_id == 1
        assert cluster.assets == ["BTCUSDT", "ETHUSDT"]
        assert cluster.avg_volatility == 0.05
        assert cluster.volatility_range == (0.03, 0.08)
        assert cluster.cluster_size == 2
        assert cluster.characteristics == characteristics


class TestRegimeDetector:
    """Test RegimeDetector class."""

    @pytest.fixture
    async def detector(self):
        """Create a regime detector instance."""
        detector = RegimeDetector(regime_window=100, volatility_window=10, cluster_count=2)
        yield detector

    @pytest.mark.asyncio
    async def test_initialization(self, detector):
        """Test detector initialization."""
        assert detector.regime_window == 100
        assert detector.volatility_window == 10
        assert detector.cluster_count == 2
        assert detector.current_regime is None
        assert detector.volatility_clusters == []

    @pytest.mark.asyncio
    async def test_add_price_data(self, detector):
        """Test adding price data."""
        timestamp = time.time()

        # Add data for BTC
        await detector.add_price_data("BTCUSDT", timestamp, 50000.0)
        await detector.add_price_data("BTCUSDT", timestamp + 1, 50100.0)

        assert len(detector.price_data["BTCUSDT"]) == 2

    @pytest.mark.asyncio
    async def test_add_price_data_window_limit(self, detector):
        """Test that price data respects window size limit."""
        # Add more data than window size
        for i in range(120):
            await detector.add_price_data("BTCUSDT", time.time() + i, 50000.0 + i)

        # Should only keep last 100 data points
        assert len(detector.price_data["BTCUSDT"]) == 100

    @pytest.mark.asyncio
    async def test_analyze_regime_insufficient_data(self, detector):
        """Test regime analysis with insufficient data."""
        # Add data for only one asset
        await detector.add_price_data("BTCUSDT", time.time(), 50000.0)

        analysis = await detector.analyze_regime()
        assert analysis is None

    @pytest.mark.asyncio
    async def test_analyze_regime_with_data(self, detector):
        """Test regime analysis with sufficient data."""
        # Add data for multiple assets with trend
        base_time = time.time()
        for i in range(120):
            # Bull market trend
            btc_price = 50000.0 + i * 100  # Strong upward trend
            eth_price = 3000.0 + i * 15    # Correlated upward trend
            ada_price = 1.5 + i * 0.02     # Weaker trend

            await detector.add_price_data("BTCUSDT", base_time + i, btc_price)
            await detector.add_price_data("ETHUSDT", base_time + i, eth_price)
            await detector.add_price_data("ADAUSDT", base_time + i, ada_price)

        analysis = await detector.analyze_regime(force_refresh=True)

        assert analysis is not None
        assert analysis.current_regime is not None
        assert isinstance(analysis.current_regime.regime_type, str)
        assert 0.0 <= analysis.current_regime.confidence <= 1.0
        assert len(analysis.volatility_clusters) > 0
        assert isinstance(analysis.correlation_regime, str)
        assert 0.0 <= analysis.market_stress_level <= 1.0

    @pytest.mark.asyncio
    async def test_get_market_regime(self, detector):
        """Test getting market regime."""
        # Setup with sufficient data (need at least 3 assets)
        base_time = time.time()
        for i in range(120):
            await detector.add_price_data("BTCUSDT", base_time + i, 50000.0 + i * 50)
            await detector.add_price_data("ETHUSDT", base_time + i, 3000.0 + i * 5)
            await detector.add_price_data("ADAUSDT", base_time + i, 1.5 + i * 0.01)

        regime = await detector.get_market_regime()
        assert regime is not None
        assert hasattr(regime, 'regime_type')

    @pytest.mark.asyncio
    async def test_get_volatility_clusters(self, detector):
        """Test getting volatility clusters."""
        # Setup with sufficient data
        base_time = time.time()
        for i in range(120):
            await detector.add_price_data("BTCUSDT", base_time + i, 50000.0 + i * 50)
            await detector.add_price_data("ETHUSDT", base_time + i, 3000.0 + i * 5)
            await detector.add_price_data("ADAUSDT", base_time + i, 1.5 + i * 0.01)

        clusters = await detector.get_volatility_clusters()
        assert isinstance(clusters, list)

    def test_calculate_trend_strength(self, detector):
        """Test trend strength calculation."""
        # Create test returns series
        dates = pd.date_range('2023-01-01', periods=50, freq='D')
        # Strong upward trend
        returns = pd.Series(np.linspace(0.001, 0.01, 50), index=dates)

        strength = detector._calculate_trend_strength(returns)
        assert 0.0 <= strength <= 1.0
        assert strength > 0.8  # Should be strong trend

    def test_calculate_rolling_volatility(self, detector):
        """Test rolling volatility calculation."""
        # Create test returns series
        dates = pd.date_range('2023-01-01', periods=50, freq='D')
        returns = pd.Series(np.random.normal(0, 0.02, 50), index=dates)

        volatility = detector._calculate_rolling_volatility(returns)
        assert len(volatility) == len(returns)
        assert all(v >= 0 for v in volatility.dropna())

    def test_classify_regime_bull(self, detector):
        """Test bull regime classification."""
        regime_type, confidence = detector._classify_regime(
            trend_strength=0.8,  # Strong trend
            volatility=0.02,     # Normal volatility
            vol_percentile=0.5   # Normal percentile
        )

        assert regime_type == "bull"
        assert confidence > 0.7

    def test_classify_regime_high_volatility(self, detector):
        """Test high volatility regime classification."""
        regime_type, confidence = detector._classify_regime(
            trend_strength=0.5,  # Moderate trend
            volatility=0.05,     # High volatility
            vol_percentile=0.9   # High percentile
        )

        assert "high_volatility" in regime_type
        assert confidence > 0.8

    def test_classify_regime_low_volatility(self, detector):
        """Test low volatility regime classification."""
        regime_type, confidence = detector._classify_regime(
            trend_strength=0.3,  # Weak trend
            volatility=0.005,    # Low volatility
            vol_percentile=0.1   # Low percentile
        )

        assert regime_type == "low_volatility"
        assert confidence > 0.6

    @pytest.mark.asyncio
    async def test_cluster_volatility(self, detector):
        """Test volatility clustering."""
        # Create test price data with different volatilities
        base_time = time.time()
        np.random.seed(42)

        # High volatility asset
        for i in range(120):
            price = 50000 + np.random.normal(0, 500)
            await detector.add_price_data("HIGHVOL", base_time + i, price)

        # Medium volatility asset
        for i in range(120):
            price = 30000 + np.random.normal(0, 200)
            await detector.add_price_data("MEDVOL", base_time + i, price)

        # Low volatility asset
        for i in range(120):
            price = 10000 + np.random.normal(0, 50)
            await detector.add_price_data("LOWVOL", base_time + i, price)

        # Force update
        await detector._update_regime_analysis()

        clusters = detector.volatility_clusters
        assert len(clusters) > 0

        # Check cluster properties
        for cluster in clusters:
            assert cluster.cluster_id >= 0
            assert len(cluster.assets) > 0
            assert cluster.avg_volatility >= 0
            assert cluster.volatility_range[0] <= cluster.volatility_range[1]
            assert cluster.cluster_size == len(cluster.assets)

    @pytest.mark.asyncio
    async def test_analyze_market_regime_function(self):
        """Test the analyze_market_regime convenience function."""
        # Create test data with sufficient length for default regime_window (200)
        base_time = time.time()
        assets_data = {
            "BTCUSDT": [(base_time + i, 50000.0 + i * 50) for i in range(250)],
            "ETHUSDT": [(base_time + i, 3000.0 + i * 5) for i in range(250)],
            "ADAUSDT": [(base_time + i, 1.5 + i * 0.01) for i in range(250)]
        }

        analysis = await analyze_market_regime(assets_data)

        assert analysis is not None
        assert analysis.current_regime is not None
        assert len(analysis.volatility_clusters) > 0

    @pytest.mark.asyncio
    async def test_get_regime_detector_singleton(self):
        """Test the global regime detector singleton."""
        detector1 = await get_regime_detector()
        detector2 = await get_regime_detector()

        assert detector1 is detector2


class TestRegimeDetectorIntegration:
    """Integration tests for regime detector."""

    @pytest.mark.asyncio
    async def test_realistic_regime_detection(self):
        """Test regime detection with realistic market data."""
        detector = RegimeDetector(regime_window=100, volatility_window=10)

        # Generate realistic price series
        base_time = time.time()
        np.random.seed(42)

        # Simulate bull market with increasing prices and moderate volatility
        for i in range(120):
            # Base trend + noise
            btc_trend = 50000 + i * 200  # Strong upward trend
            btc_noise = np.random.normal(0, btc_trend * 0.02)  # 2% volatility
            btc_price = btc_trend + btc_noise

            eth_trend = 3000 + i * 20
            eth_noise = np.random.normal(0, eth_trend * 0.025)  # 2.5% volatility
            eth_price = eth_trend + eth_noise

            await detector.add_price_data("BTCUSDT", base_time + i, btc_price)
            await detector.add_price_data("ETHUSDT", base_time + i, eth_price)

        analysis = await detector.analyze_regime(force_refresh=True)

        assert analysis is not None
        regime = analysis.current_regime

        # Should detect bull market
        assert regime.regime_type in ['bull', 'high_volatility_bull']
        assert regime.trend_strength > 0.5  # Strong trend
        assert regime.confidence > 0.6

        # Should have volatility clusters
        assert len(analysis.volatility_clusters) > 0

    @pytest.mark.asyncio
    async def test_high_volatility_regime(self):
        """Test detection of high volatility regime."""
        detector = RegimeDetector(regime_window=100, volatility_window=10)

        base_time = time.time()
        np.random.seed(123)

        # Simulate high volatility sideways market
        for i in range(120):
            # Sideways trend with high volatility
            btc_base = 50000
            btc_volatility = np.random.normal(0, btc_base * 0.08)  # 8% volatility
            btc_price = btc_base + btc_volatility

            eth_base = 3000
            eth_volatility = np.random.normal(0, eth_base * 0.10)  # 10% volatility
            eth_price = eth_base + eth_volatility

            await detector.add_price_data("BTCUSDT", base_time + i, btc_price)
            await detector.add_price_data("ETHUSDT", base_time + i, eth_price)

        analysis = await detector.analyze_regime(force_refresh=True)

        assert analysis is not None
        regime = analysis.current_regime

        # Should detect high volatility
        assert 'high_volatility' in regime.regime_type
        assert regime.volatility_percentile > 0.7  # High percentile

    @pytest.mark.asyncio
    async def test_performance_large_dataset(self):
        """Test performance with larger dataset."""
        detector = RegimeDetector(regime_window=200, volatility_window=20)

        base_time = time.time()

        # Add data for 10 assets
        for asset_idx in range(10):
            for i in range(200):
                price = 100.0 + asset_idx * 10 + i * 0.5 + np.random.normal(0, 1)
                await detector.add_price_data(f"ASSET{asset_idx}", base_time + i, price)

        start_time = time.time()
        analysis = await detector.analyze_regime(force_refresh=True)
        computation_time = time.time() - start_time

        assert analysis is not None
        assert analysis.current_regime is not None
        assert len(analysis.volatility_clusters) > 0

        # Should complete within reasonable time (< 200ms for this test)
        assert computation_time < 0.2, f"Computation took {computation_time:.3f}s"
