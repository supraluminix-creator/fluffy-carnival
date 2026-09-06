"""Market regime detection and volatility clustering analysis."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import structlog
from scipy import stats
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

from analysis.correlation_engine import CorrelationEngine, CorrelationMatrix
from pipeline import redis_cache
from pipeline.metrics.signals import REGIME_DETECTION_DURATION, VOLATILITY_CLUSTER_COUNT

logger = structlog.get_logger(__name__)

# Configuration constants
DEFAULT_REGIME_WINDOW = 200  # Data points for regime analysis
DEFAULT_VOLATILITY_WINDOW = 20  # Rolling volatility window
DEFAULT_CLUSTER_COUNT = 3  # Number of volatility clusters
REGIME_CACHE_TTL = 600  # 10 minutes cache TTL

@dataclass
class MarketRegime:
    """Market regime classification result."""
    regime_type: str  # 'bull', 'bear', 'sideways', 'high_volatility', 'low_volatility'
    confidence: float  # Confidence score (0-1)
    volatility_percentile: float  # Current volatility percentile
    trend_strength: float  # Trend strength indicator
    timestamp: float
    indicators: dict[str, Any]  # Additional regime indicators

@dataclass
class VolatilityCluster:
    """Volatility clustering result."""
    cluster_id: int
    assets: list[str]
    avg_volatility: float
    volatility_range: tuple[float, float]
    cluster_size: int
    characteristics: dict[str, Any]

@dataclass
class RegimeAnalysis:
    """Complete regime analysis result."""
    current_regime: MarketRegime
    volatility_clusters: list[VolatilityCluster]
    correlation_regime: str  # 'correlated', 'uncorrelated', 'mixed'
    market_stress_level: float  # 0-1 scale
    timestamp: float

class RegimeDetector:
    """Market regime detection and volatility clustering engine."""

    def __init__(
        self,
        regime_window: int = DEFAULT_REGIME_WINDOW,
        volatility_window: int = DEFAULT_VOLATILITY_WINDOW,
        cluster_count: int = DEFAULT_CLUSTER_COUNT
    ):
        self.regime_window = regime_window
        self.volatility_window = volatility_window
        self.cluster_count = cluster_count

        # Data storage
        self.price_data: dict[str, list[tuple[float, float]]] = defaultdict(list)
        self.current_regime: MarketRegime | None = None
        self.volatility_clusters: list[VolatilityCluster] = []

        # Cache
        try:
            self._cache = redis_cache.RedisCache(Cache())
        except Exception:
            self._cache = None

        logger.info(
            "regime_detector_initialized",
            regime_window=regime_window,
            volatility_window=volatility_window,
            cluster_count=cluster_count
        )

    async def add_price_data(self, asset: str, timestamp: float, price: float) -> None:
        """Add price data for regime analysis."""
        self.price_data[asset].append((timestamp, price))

        # Maintain window size
        if len(self.price_data[asset]) > self.regime_window:
            self.price_data[asset] = self.price_data[asset][-self.regime_window:]

        # Invalidate cache
        await self._invalidate_cache(asset)

    async def analyze_regime(self, force_refresh: bool = False) -> RegimeAnalysis | None:
        """Perform complete regime analysis."""
        if force_refresh or self.current_regime is None:
            await self._update_regime_analysis()

        if not self.current_regime:
            return None

        return RegimeAnalysis(
            current_regime=self.current_regime,
            volatility_clusters=self.volatility_clusters,
            correlation_regime=await self._analyze_correlation_regime(),
            market_stress_level=self._calculate_market_stress(),
            timestamp=time.time()
        )

    async def get_market_regime(self) -> MarketRegime | None:
        """Get current market regime."""
        analysis = await self.analyze_regime()
        return analysis.current_regime if analysis else None

    async def get_volatility_clusters(self) -> list[VolatilityCluster]:
        """Get current volatility clusters."""
        analysis = await self.analyze_regime()
        return analysis.volatility_clusters if analysis else []

    async def _update_regime_analysis(self) -> None:
        """Update regime analysis from current price data."""
        start_time = time.time()

        # Filter assets with sufficient data
        valid_assets = [
            asset for asset, data in self.price_data.items()
            if len(data) >= self.regime_window
        ]

        if len(valid_assets) < 3:  # Need minimum assets for meaningful analysis
            logger.debug("regime_insufficient_data", valid_assets=len(valid_assets))
            return

        try:
            # Prepare price data
            price_dfs = {}
            for asset in valid_assets:
                timestamps, prices = zip(*self.price_data[asset])
                df = pd.DataFrame({
                    'timestamp': timestamps,
                    'price': prices
                }).set_index('timestamp')
                price_dfs[asset] = df

            # Detect market regime
            self.current_regime = self._detect_market_regime(price_dfs)

            # Perform volatility clustering
            self.volatility_clusters = self._cluster_volatility(price_dfs)

            # Cache results
            await self._cache_regime_analysis()

            # Update metrics
            VOLATILITY_CLUSTER_COUNT.set(len(self.volatility_clusters))
            REGIME_DETECTION_DURATION.observe(time.time() - start_time)

            logger.info(
                "regime_analysis_updated",
                assets=len(valid_assets),
                regime=self.current_regime.regime_type if self.current_regime else None,
                clusters=len(self.volatility_clusters),
                computation_time=time.time() - start_time
            )

        except Exception as exc:
            logger.error(
                "regime_analysis_error",
                error=str(exc),
                exc_info=True
            )

    def _detect_market_regime(self, price_dfs: dict[str, pd.DataFrame]) -> MarketRegime:
        """Detect current market regime from price data."""
        # Calculate returns for all assets
        returns_dfs = {}
        for asset, df in price_dfs.items():
            returns_dfs[asset] = df['price'].pct_change().dropna()

        # Aggregate market returns (equal-weighted)
        market_returns = pd.concat(returns_dfs.values(), axis=1).mean(axis=1)

        # Calculate regime indicators
        trend_strength = self._calculate_trend_strength(market_returns)
        volatility = self._calculate_rolling_volatility(market_returns)
        current_volatility = volatility.iloc[-1] if not volatility.empty else 0.0

        # Historical volatility percentile
        vol_percentile = stats.percentileofscore(volatility.dropna(), current_volatility) / 100.0

        # Classify regime
        regime_type, confidence = self._classify_regime(
            trend_strength, current_volatility, vol_percentile
        )

        indicators = {
            'trend_strength': trend_strength,
            'current_volatility': current_volatility,
            'volatility_percentile': vol_percentile,
            'avg_market_return': market_returns.mean(),
            'market_volatility': market_returns.std(),
            'sharpe_ratio': market_returns.mean() / market_returns.std() if market_returns.std() > 0 else 0.0
        }

        return MarketRegime(
            regime_type=regime_type,
            confidence=confidence,
            volatility_percentile=vol_percentile,
            trend_strength=trend_strength,
            timestamp=time.time(),
            indicators=indicators
        )

    def _calculate_trend_strength(self, returns: pd.Series) -> float:
        """Calculate trend strength using linear regression."""
        if len(returns) < 10:
            return 0.0

        # Cumulative returns
        cum_returns = (1 + returns).cumprod() - 1

        # Linear regression on cumulative returns
        x = np.arange(len(cum_returns))
        slope, _, r_value, _, _ = stats.linregress(x, cum_returns.values)

        # Return R-squared as trend strength
        return abs(r_value ** 2)

    def _calculate_rolling_volatility(self, returns: pd.Series) -> pd.Series:
        """Calculate rolling volatility."""
        return returns.rolling(window=self.volatility_window).std() * np.sqrt(252)  # Annualized

    def _classify_regime(
        self,
        trend_strength: float,
        volatility: float,
        vol_percentile: float
    ) -> tuple[str, float]:
        """Classify market regime based on indicators."""
        # High volatility regimes
        if vol_percentile > 0.8:
            if trend_strength > 0.6:
                return 'high_volatility_bull', 0.8
            elif trend_strength < 0.2:
                return 'high_volatility_bear', 0.8
            else:
                return 'high_volatility', 0.9

        # Low volatility regimes
        elif vol_percentile < 0.2:
            return 'low_volatility', 0.7

        # Normal volatility - classify by trend
        else:
            if trend_strength > 0.7:
                return 'bull', 0.8
            elif trend_strength < 0.3:
                return 'bear', 0.8
            else:
                return 'sideways', 0.6

    def _cluster_volatility(self, price_dfs: dict[str, pd.DataFrame]) -> list[VolatilityCluster]:
        """Perform volatility clustering analysis."""
        if len(price_dfs) < self.cluster_count:
            return []

        # Calculate volatility for each asset
        volatilities = {}
        for asset, df in price_dfs.items():
            returns = df['price'].pct_change().dropna()
            vol = returns.rolling(window=self.volatility_window).std().mean()
            volatilities[asset] = vol

        if len(volatilities) < self.cluster_count:
            return []

        # Prepare data for clustering
        assets = list(volatilities.keys())
        vol_values = np.array(list(volatilities.values())).reshape(-1, 1)

        # Standardize
        scaler = StandardScaler()
        vol_scaled = scaler.fit_transform(vol_values)

        # Perform clustering
        kmeans = KMeans(n_clusters=self.cluster_count, random_state=42, n_init=10)
        clusters = kmeans.fit_predict(vol_scaled)

        # Create cluster objects
        cluster_objects = []
        for cluster_id in range(self.cluster_count):
            cluster_assets = [
                assets[i] for i in range(len(assets))
                if clusters[i] == cluster_id
            ]

            if not cluster_assets:
                continue

            cluster_vols = [volatilities[asset] for asset in cluster_assets]
            avg_vol = np.mean(cluster_vols)
            vol_range = (np.min(cluster_vols), np.max(cluster_vols))

            characteristics = {
                'volatility_cv': np.std(cluster_vols) / np.mean(cluster_vols) if np.mean(cluster_vols) > 0 else 0.0,
                'cluster_centroid': kmeans.cluster_centers_[cluster_id][0],
                'inertia_contribution': sum(
                    np.linalg.norm(vol_scaled[i] - kmeans.cluster_centers_[clusters[i]])
                    for i in range(len(assets)) if clusters[i] == cluster_id
                )
            }

            cluster_objects.append(VolatilityCluster(
                cluster_id=cluster_id,
                assets=cluster_assets,
                avg_volatility=avg_vol,
                volatility_range=vol_range,
                cluster_size=len(cluster_assets),
                characteristics=characteristics
            ))

        # Sort by average volatility
        cluster_objects.sort(key=lambda x: x.avg_volatility)

        return cluster_objects

    async def _analyze_correlation_regime(self) -> str:
        """Analyze correlation regime using correlation engine."""
        try:
            # Get correlation matrix from correlation engine
            correlation_engine = await get_correlation_engine()
            corr_matrix = await correlation_engine.get_correlation_matrix()

            if not corr_matrix:
                return 'unknown'

            # Calculate average absolute correlation
            avg_corr = np.mean(np.abs(corr_matrix.matrix[np.triu_indices_from(corr_matrix.matrix, k=1)]))

            if avg_corr > 0.6:
                return 'correlated'
            elif avg_corr < 0.3:
                return 'uncorrelated'
            else:
                return 'mixed'

        except Exception as exc:
            logger.warning(
                "correlation_regime_analysis_error",
                error=str(exc)
            )
            return 'unknown'

    def _calculate_market_stress(self) -> float:
        """Calculate market stress level (0-1 scale)."""
        if not self.current_regime or not self.volatility_clusters:
            return 0.0

        # Combine multiple stress indicators
        vol_stress = min(1.0, self.current_regime.volatility_percentile * 2)  # 0-1 scale
        cluster_stress = len([c for c in self.volatility_clusters if c.avg_volatility > 0.05]) / len(self.volatility_clusters)

        # Weighted average
        return 0.7 * vol_stress + 0.3 * cluster_stress

    async def _cache_regime_analysis(self) -> None:
        """Cache regime analysis results."""
        if not self._cache or not self.current_regime:
            return

        try:
            cache_key = "regime_analysis:latest"
            cache_data = {
                "current_regime": {
                    "regime_type": self.current_regime.regime_type,
                    "confidence": self.current_regime.confidence,
                    "volatility_percentile": self.current_regime.volatility_percentile,
                    "trend_strength": self.current_regime.trend_strength,
                    "timestamp": self.current_regime.timestamp,
                    "indicators": self.current_regime.indicators
                },
                "volatility_clusters": [
                    {
                        "cluster_id": cluster.cluster_id,
                        "assets": cluster.assets,
                        "avg_volatility": cluster.avg_volatility,
                        "volatility_range": cluster.volatility_range,
                        "cluster_size": cluster.cluster_size,
                        "characteristics": cluster.characteristics
                    }
                    for cluster in self.volatility_clusters
                ],
                "timestamp": time.time()
            }

            await self._cache.set(cache_key, cache_data, ttl=REGIME_CACHE_TTL)

        except Exception as exc:
            logger.warning(
                "regime_cache_error",
                error=str(exc)
            )

    async def _invalidate_cache(self, asset: str) -> None:
        """Invalidate cache when asset data changes."""
        if not self._cache:
            return

        try:
            await self._cache.delete("regime_analysis:latest")
        except Exception as exc:
            logger.debug(
                "regime_cache_invalidation_error",
                asset=asset,
                error=str(exc)
            )

# Global instance
_regime_detector: RegimeDetector | None = None

async def get_regime_detector() -> RegimeDetector:
    """Get the global regime detector instance."""
    global _regime_detector

    if _regime_detector is None:
        _regime_detector = RegimeDetector()

    return _regime_detector

async def analyze_market_regime(price_data: dict[str, list[tuple[float, float]]]) -> RegimeAnalysis | None:
    """Convenience function for one-time regime analysis."""
    detector = RegimeDetector()

    # Add all data
    for asset, data_points in price_data.items():
        for timestamp, price in data_points:
            await detector.add_price_data(asset, timestamp, price)

    # Force update and return
    await detector._update_regime_analysis()
    return await detector.analyze_regime(force_refresh=False)

__all__ = [
    "RegimeDetector",
    "MarketRegime",
    "VolatilityCluster",
    "RegimeAnalysis",
    "get_regime_detector",
    "analyze_market_regime"
]
