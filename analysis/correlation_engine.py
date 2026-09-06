"""Multi-asset correlation analysis engine for real-time market intelligence."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from contextlib import suppress
from dataclasses import dataclass

import numpy as np
import pandas as pd
import structlog
from diskcache import Cache

from pipeline import redis_cache
from pipeline.metrics.signals import CORRELATION_ANALYSIS_DURATION, CORRELATION_MATRIX_SIZE

logger = structlog.get_logger(__name__)

# Configuration constants
DEFAULT_CORRELATION_WINDOW = 100  # Data points for correlation calculation
DEFAULT_UPDATE_INTERVAL = 60  # Seconds between correlation updates
MAX_ASSETS = 100  # Maximum assets to analyze simultaneously
CORRELATION_CACHE_TTL = 300  # 5 minutes cache TTL

@dataclass
class CorrelationResult:
    """Result of correlation analysis between two assets."""
    asset_a: str
    asset_b: str
    correlation: float
    significance: float  # Statistical significance (p-value)
    strength: str  # 'strong', 'moderate', 'weak', 'none'
    direction: str  # 'positive', 'negative', 'neutral'
    timestamp: float

@dataclass
class CorrelationMatrix:
    """Complete correlation matrix for multiple assets."""
    assets: list[str]
    matrix: np.ndarray
    timestamp: float
    significance_matrix: np.ndarray | None = None

    def get_correlation(self, asset_a: str, asset_b: str) -> CorrelationResult | None:
        """Get correlation result between two specific assets."""
        if asset_a not in self.assets or asset_b not in self.assets:
            return None

        idx_a = self.assets.index(asset_a)
        idx_b = self.assets.index(asset_b)

        correlation = self.matrix[idx_a, idx_b]
        significance = self.significance_matrix[idx_a, idx_b] if self.significance_matrix is not None else 0.0

        strength = self._classify_strength(abs(correlation))
        direction = self._classify_direction(correlation)

        return CorrelationResult(
            asset_a=asset_a,
            asset_b=asset_b,
            correlation=correlation,
            significance=significance,
            strength=strength,
            direction=direction,
            timestamp=self.timestamp
        )

    def _classify_strength(self, abs_corr: float) -> str:
        """Classify correlation strength."""
        if abs_corr >= 0.8:
            return 'strong'
        elif abs_corr >= 0.6:
            return 'moderate'
        elif abs_corr >= 0.3:
            return 'weak'
        else:
            return 'none'

    def _classify_direction(self, corr: float) -> str:
        """Classify correlation direction."""
        if corr > 0.1:
            return 'positive'
        elif corr < -0.1:
            return 'negative'
        else:
            return 'neutral'

class CorrelationEngine:
    """Real-time multi-asset correlation analysis engine."""

    def __init__(
        self,
        window_size: int = DEFAULT_CORRELATION_WINDOW,
        update_interval: int = DEFAULT_UPDATE_INTERVAL,
        max_assets: int = MAX_ASSETS
    ):
        self.window_size = window_size
        self.update_interval = update_interval
        self.max_assets = max_assets

        # Data storage
        self.price_data: dict[str, list[tuple[float, float]]] = defaultdict(list)  # asset -> [(timestamp, price)]
        self.correlation_matrix: CorrelationMatrix | None = None

        # Control flags
        self.running = False
        self._update_task: asyncio.Task | None = None

        # Cache
        try:
            self._cache = redis_cache.RedisCache(Cache())
        except Exception:
            self._cache = None

        logger.info(
            "correlation_engine_initialized",
            window_size=window_size,
            update_interval=update_interval,
            max_assets=max_assets
        )

    async def start(self) -> None:
        """Start the correlation analysis engine."""
        if self.running:
            logger.warning("correlation_engine_already_running")
            return

        self.running = True
        self._update_task = asyncio.create_task(self._correlation_update_loop())

        logger.info("correlation_engine_started")

    async def stop(self) -> None:
        """Stop the correlation analysis engine."""
        if not self.running:
            return

        self.running = False

        if self._update_task:
            self._update_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._update_task

        logger.info("correlation_engine_stopped")

    async def add_price_data(self, asset: str, timestamp: float, price: float) -> None:
        """Add price data for correlation analysis."""
        if len(self.price_data) >= self.max_assets and asset not in self.price_data:
            logger.warning(
                "correlation_max_assets_exceeded",
                asset=asset,
                current_assets=len(self.price_data),
                max_assets=self.max_assets
            )
            return

        # Add new data point
        self.price_data[asset].append((timestamp, price))

        # Maintain window size
        if len(self.price_data[asset]) > self.window_size:
            self.price_data[asset] = self.price_data[asset][-self.window_size:]

        # Invalidate cache
        await self._invalidate_cache(asset)

    async def get_correlation_matrix(self, force_refresh: bool = False) -> CorrelationMatrix | None:
        """Get the current correlation matrix."""
        if force_refresh or self.correlation_matrix is None:
            await self._update_correlations()

        return self.correlation_matrix

    async def get_asset_correlations(self, asset: str, min_strength: str = 'weak') -> list[CorrelationResult]:
        """Get correlations for a specific asset."""
        matrix = await self.get_correlation_matrix()
        if not matrix:
            return []

        results = []
        strength_levels = {'strong': 0.8, 'moderate': 0.6, 'weak': 0.3, 'none': 0.0}
        min_threshold = strength_levels.get(min_strength, 0.3)

        for other_asset in matrix.assets:
            if other_asset == asset:
                continue

            result = matrix.get_correlation(asset, other_asset)
            if result and abs(result.correlation) >= min_threshold:
                results.append(result)

        return sorted(results, key=lambda x: abs(x.correlation), reverse=True)

    async def get_top_correlations(self, limit: int = 10) -> list[CorrelationResult]:
        """Get top correlations across all asset pairs."""
        matrix = await self.get_correlation_matrix()
        if not matrix:
            return []

        results = []
        n = len(matrix.assets)

        for i in range(n):
            for j in range(i + 1, n):  # Upper triangle only
                asset_a = matrix.assets[i]
                asset_b = matrix.assets[j]

                result = matrix.get_correlation(asset_a, asset_b)
                if result:
                    results.append(result)

        # Sort by absolute correlation strength
        results.sort(key=lambda x: abs(x.correlation), reverse=True)
        return results[:limit]

    async def _correlation_update_loop(self) -> None:
        """Background task for periodic correlation updates."""
        while self.running:
            try:
                await self._update_correlations()
                await asyncio.sleep(self.update_interval)
            except Exception as exc:
                logger.error(
                    "correlation_update_error",
                    error=str(exc),
                    exc_info=True
                )
                await asyncio.sleep(10)  # Brief pause before retry

    async def _update_correlations(self) -> None:
        """Update correlation matrix from current price data."""
        start_time = time.time()

        # Filter assets with sufficient data
        valid_assets = [
            asset for asset, data in self.price_data.items()
            if len(data) >= 30  # Minimum data points for meaningful correlation
        ]

        if len(valid_assets) < 2:
            logger.debug("correlation_insufficient_data", valid_assets=len(valid_assets))
            return

        try:
            # Prepare price series
            price_series = {}
            timestamps = None

            for asset in valid_assets:
                data = self.price_data[asset]
                if timestamps is None:
                    timestamps = [t for t, _ in data]
                elif len(data) != len(timestamps):
                    continue  # Skip assets with different data lengths

                price_series[asset] = [p for _, p in data]

            if len(price_series) < 2:
                return

            # Create DataFrame for correlation calculation
            df = pd.DataFrame(price_series)

            # Calculate correlation matrix
            corr_matrix = df.corr().values

            # Calculate statistical significance (simplified p-values)
            n = len(df)
            significance_matrix = self._calculate_significance_matrix(corr_matrix, n)

            # Create correlation matrix object
            self.correlation_matrix = CorrelationMatrix(
                assets=list(price_series.keys()),
                matrix=corr_matrix,
                significance_matrix=significance_matrix,
                timestamp=time.time()
            )

            # Cache the result
            await self._cache_correlation_matrix()

            # Update metrics
            CORRELATION_MATRIX_SIZE.set(len(valid_assets))
            CORRELATION_ANALYSIS_DURATION.observe(time.time() - start_time)

            logger.info(
                "correlation_matrix_updated",
                assets=len(valid_assets),
                computation_time=time.time() - start_time
            )

        except Exception as exc:
            logger.error(
                "correlation_calculation_error",
                error=str(exc),
                exc_info=True
            )

    def _calculate_significance_matrix(self, corr_matrix: np.ndarray, n: int) -> np.ndarray:
        """Calculate statistical significance matrix (simplified)."""
        # Simplified significance calculation
        # In practice, you'd use t-distribution for proper p-values
        significance = np.zeros_like(corr_matrix)

        for i in range(len(corr_matrix)):
            for j in range(len(corr_matrix)):
                if i != j:
                    # Simplified: lower correlation = higher p-value
                    significance[i, j] = max(0.0, 1.0 - abs(corr_matrix[i, j]))

        return significance

    async def _cache_correlation_matrix(self) -> None:
        """Cache the correlation matrix in Redis."""
        if not self.correlation_matrix or not self._cache:
            return

        try:
            cache_key = "correlation_matrix:latest"
            cache_data = {
                "assets": self.correlation_matrix.assets,
                "matrix": self.correlation_matrix.matrix.tolist(),
                "significance_matrix": (
                    self.correlation_matrix.significance_matrix.tolist()
                    if self.correlation_matrix.significance_matrix is not None
                    else None
                ),
                "timestamp": self.correlation_matrix.timestamp
            }

            await self._cache.set(cache_key, cache_data, ttl=CORRELATION_CACHE_TTL)

        except Exception as exc:
            logger.warning(
                "correlation_cache_error",
                error=str(exc)
            )

    async def _invalidate_cache(self, asset: str) -> None:
        """Invalidate cache when asset data changes."""
        if not self._cache:
            return

        try:
            await self._cache.delete("correlation_matrix:latest")
        except Exception as exc:
            logger.debug(
                "correlation_cache_invalidation_error",
                asset=asset,
                error=str(exc)
            )

# Global instance
_correlation_engine: CorrelationEngine | None = None

async def get_correlation_engine() -> CorrelationEngine:
    """Get the global correlation engine instance."""
    global _correlation_engine

    if _correlation_engine is None:
        _correlation_engine = CorrelationEngine()
        await _correlation_engine.start()

    return _correlation_engine

async def analyze_correlations(assets_data: dict[str, list[tuple[float, float]]]) -> CorrelationMatrix | None:
    """Convenience function for one-time correlation analysis."""
    engine = CorrelationEngine()

    # Add all data
    for asset, data_points in assets_data.items():
        for timestamp, price in data_points:
            await engine.add_price_data(asset, timestamp, price)

    # Force update and return
    await engine._update_correlations()
    return engine.correlation_matrix

__all__ = [
    "CorrelationEngine",
    "CorrelationResult",
    "CorrelationMatrix",
    "get_correlation_engine",
    "analyze_correlations"
]
