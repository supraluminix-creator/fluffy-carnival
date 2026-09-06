"""
ML Feature Store Implementation using Feast
Provides centralized feature management, serving, and point-in-time correctness
for machine learning models in production.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field
from contextlib import asynccontextmanager

import pandas as pd
import numpy as np
from feast import FeatureStore, Entity, FeatureView, Field
from feast.types import Float32, Int64, String, Bool
from feast.infra.offline_stores.redis import RedisOfflineStore
from feast.infra.online_stores.redis import RedisOnlineStore
from feast.data_source import PushSource
from feast.repo_config import RepoConfig, RegistryConfig
from feast.feature_service import FeatureService
from redis.asyncio import Redis as AsyncRedis
import prometheus_client as prom

from ..core.config import get_settings
from ..core.metrics import get_metrics_collector
from ..core.exceptions import FeatureStoreError, FeatureNotFoundError

logger = logging.getLogger(__name__)
settings = get_settings()
metrics = get_metrics_collector()

# Prometheus metrics
FEATURE_STORE_REQUESTS = prom.Counter(
    'feature_store_requests_total',
    'Total number of feature store requests',
    ['operation', 'status']
)

FEATURE_STORE_LATENCY = prom.Histogram(
    'feature_store_request_duration_seconds',
    'Feature store request latency in seconds',
    ['operation']
)

FEATURE_STORE_CACHE_HITS = prom.Counter(
    'feature_store_cache_hits_total',
    'Total number of feature store cache hits',
    ['feature_view']
)

FEATURE_STORE_CACHE_MISSES = prom.Counter(
    'feature_store_cache_misses_total',
    'Total number of feature store cache misses',
    ['feature_view']
)


@dataclass
class FeatureMetadata:
    """Metadata for a feature in the store."""
    name: str
    dtype: str
    description: str
    tags: List[str] = field(default_factory=list)
    validation_rules: Dict[str, Any] = field(default_factory=dict)
    freshness_requirements: timedelta = field(default_factory=lambda: timedelta(hours=1))


@dataclass
class FeatureBatch:
    """Batch of features for bulk operations."""
    entity_ids: List[str]
    features: Dict[str, List[Any]]
    timestamps: List[datetime]
    metadata: Dict[str, Any] = field(default_factory=dict)


class CryptoFeatureStore:
    """
    Production-ready feature store using Feast for crypto trading ML features.

    Features:
    - Point-in-time correct feature serving
    - Real-time feature updates via push sources
    - Feature validation and quality monitoring
    - High-performance Redis backend
    - Comprehensive monitoring and alerting
    """

    def __init__(self, repo_path: str = "/app/feature_repo"):
        self.repo_path = repo_path
        self.store: Optional[FeatureStore] = None
        self.redis_client: Optional[AsyncRedis] = None
        self.feature_metadata: Dict[str, FeatureMetadata] = {}
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the feature store with Feast configuration."""
        if self._initialized:
            return

        try:
            # Configure Feast with Redis backend
            repo_config = RepoConfig(
                registry=RegistryConfig(
                    registry_type="sql",
                    path=f"sqlite:///{self.repo_path}/registry.db"
                ),
                offline_store=RedisOfflineStore(
                    host=settings.REDIS_HOST,
                    port=settings.REDIS_PORT,
                    db=1  # Separate DB for offline features
                ),
                online_store=RedisOnlineStore(
                    host=settings.REDIS_HOST,
                    port=settings.REDIS_PORT,
                    db=2  # Separate DB for online features
                ),
                feature_server=None,  # We'll handle serving ourselves
                entity_key_serialization_version=2
            )

            # Initialize Redis client for direct operations
            self.redis_client = AsyncRedis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=2,  # Online store DB
                decode_responses=True
            )

            # Create feature store instance
            self.store = FeatureStore(config=repo_config)

            # Register core entities
            await self._register_entities()

            # Register feature views
            await self._register_feature_views()

            # Initialize feature metadata
            await self._load_feature_metadata()

            self._initialized = True
            logger.info("Feature store initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize feature store: {e}")
            raise FeatureStoreError(f"Feature store initialization failed: {e}")

    async def _register_entities(self) -> None:
        """Register core entities for the feature store."""
        # Trading pair entity
        trading_pair = Entity(
            name="trading_pair",
            join_keys=["symbol"],
            description="Cryptocurrency trading pair (e.g., BTCUSDT)"
        )

        # Time window entity for aggregations
        time_window = Entity(
            name="time_window",
            join_keys=["window_start", "window_end"],
            description="Time window for feature aggregations"
        )

        # Model version entity for A/B testing
        model_version = Entity(
            name="model_version",
            join_keys=["model_id", "version"],
            description="Model version for A/B testing and versioning"
        )

        # Register entities
        entities = [trading_pair, time_window, model_version]
        for entity in entities:
            try:
                self.store.apply([entity])
                logger.info(f"Registered entity: {entity.name}")
            except Exception as e:
                logger.warning(f"Entity {entity.name} may already exist: {e}")

    async def _register_feature_views(self) -> None:
        """Register feature views for different feature categories."""
        # Market data features
        market_features = FeatureView(
            name="market_features",
            entities=["trading_pair"],
            schema=[
                Field(name="price", dtype=Float32, description="Current price"),
                Field(name="volume_24h", dtype=Float32, description="24h volume"),
                Field(name="price_change_24h", dtype=Float32, description="24h price change %"),
                Field(name="market_cap", dtype=Float32, description="Market capitalization"),
                Field(name="volatility_24h", dtype=Float32, description="24h volatility"),
            ],
            source=PushSource(name="market_data_push"),
            ttl=timedelta(hours=1)
        )

        # Technical indicator features
        technical_features = FeatureView(
            name="technical_features",
            entities=["trading_pair"],
            schema=[
                Field(name="rsi_14", dtype=Float32, description="14-period RSI"),
                Field(name="macd_signal", dtype=Float32, description="MACD signal line"),
                Field(name="bb_upper", dtype=Float32, description="Bollinger Band upper"),
                Field(name="bb_lower", dtype=Float32, description="Bollinger Band lower"),
                Field(name="stoch_k", dtype=Float32, description="Stochastic %K"),
                Field(name="adx", dtype=Float32, description="Average Directional Index"),
            ],
            source=PushSource(name="technical_indicators_push"),
            ttl=timedelta(hours=1)
        )

        # Correlation features
        correlation_features = FeatureView(
            name="correlation_features",
            entities=["trading_pair"],
            schema=[
                Field(name="btc_correlation", dtype=Float32, description="Correlation with BTC"),
                Field(name="eth_correlation", dtype=Float32, description="Correlation with ETH"),
                Field(name="market_correlation", dtype=Float32, description="Market-wide correlation"),
                Field(name="regime_stability", dtype=Float32, description="Market regime stability"),
            ],
            source=PushSource(name="correlation_push"),
            ttl=timedelta(hours=1)
        )

        # Register feature views
        feature_views = [market_features, technical_features, correlation_features]
        for fv in feature_views:
            try:
                self.store.apply([fv])
                logger.info(f"Registered feature view: {fv.name}")
            except Exception as e:
                logger.warning(f"Feature view {fv.name} may already exist: {e}")

    async def _load_feature_metadata(self) -> None:
        """Load feature metadata for validation and monitoring."""
        self.feature_metadata = {
            "price": FeatureMetadata(
                name="price",
                dtype="float32",
                description="Current market price",
                validation_rules={"min": 0, "max": 1000000},
                freshness_requirements=timedelta(minutes=1)
            ),
            "rsi_14": FeatureMetadata(
                name="rsi_14",
                dtype="float32",
                description="14-period Relative Strength Index",
                validation_rules={"min": 0, "max": 100},
                freshness_requirements=timedelta(minutes=5)
            ),
            "btc_correlation": FeatureMetadata(
                name="btc_correlation",
                dtype="float32",
                description="Correlation coefficient with Bitcoin",
                validation_rules={"min": -1, "max": 1},
                freshness_requirements=timedelta(hours=1)
            ),
            # Add more feature metadata as needed
        }

    @FEATURE_STORE_LATENCY.time()
    async def get_online_features(
        self,
        features: List[str],
        entity_rows: List[Dict[str, Any]],
        feature_service: Optional[str] = None
    ) -> Dict[str, List[Any]]:
        """
        Retrieve online features for real-time inference.

        Args:
            features: List of feature names to retrieve
            entity_rows: List of entity key-value pairs
            feature_service: Optional feature service name

        Returns:
            Dictionary mapping feature names to lists of values
        """
        if not self._initialized:
            await self.initialize()

        try:
            with metrics.timer("feature_store.get_online_features"):
                # Use Feast's online serving
                if feature_service:
                    service = self.store.get_feature_service(feature_service)
                    response = self.store.get_online_features(
                        features=features,
                        entity_rows=entity_rows,
                        feature_service=service
                    )
                else:
                    response = self.store.get_online_features(
                        features=features,
                        entity_rows=entity_rows
                    )

                FEATURE_STORE_REQUESTS.labels(operation="get_online", status="success").inc()

                # Convert to expected format
                result = {}
                for feature in features:
                    if feature in response.to_dict():
                        result[feature] = response.to_dict()[feature]

                return result

        except Exception as e:
            FEATURE_STORE_REQUESTS.labels(operation="get_online", status="error").inc()
            logger.error(f"Failed to get online features: {e}")
            raise FeatureStoreError(f"Online feature retrieval failed: {e}")

    @FEATURE_STORE_LATENCY.time()
    async def push_features(self, feature_batch: FeatureBatch) -> None:
        """
        Push new feature values to the online store.

        Args:
            feature_batch: Batch of features to push
        """
        if not self._initialized:
            await self.initialize()

        try:
            with metrics.timer("feature_store.push_features"):
                # Convert to DataFrame for Feast
                df_data = {
                    "event_timestamp": feature_batch.timestamps,
                    **feature_batch.features
                }

                # Add entity keys
                for i, entity_id in enumerate(feature_batch.entity_ids):
                    df_data["symbol"] = df_data.get("symbol", [None] * len(feature_batch.timestamps))
                    df_data["symbol"][i] = entity_id

                df = pd.DataFrame(df_data)

                # Push to Feast
                self.store.push("market_data_push", df)
                self.store.push("technical_indicators_push", df)
                self.store.push("correlation_push", df)

                FEATURE_STORE_REQUESTS.labels(operation="push", status="success").inc()
                logger.info(f"Pushed {len(feature_batch.entity_ids)} feature batches")

        except Exception as e:
            FEATURE_STORE_REQUESTS.labels(operation="push", status="error").inc()
            logger.error(f"Failed to push features: {e}")
            raise FeatureStoreError(f"Feature push failed: {e}")

    async def validate_features(
        self,
        features: Dict[str, Any],
        strict: bool = True
    ) -> Dict[str, List[str]]:
        """
        Validate feature values against metadata rules.

        Args:
            features: Dictionary of feature names to values
            strict: Whether to raise exceptions on validation failures

        Returns:
            Dictionary mapping feature names to lists of validation errors
        """
        errors = {}

        for feature_name, value in features.items():
            if feature_name not in self.feature_metadata:
                if strict:
                    raise FeatureNotFoundError(f"Unknown feature: {feature_name}")
                continue

            metadata = self.feature_metadata[feature_name]
            feature_errors = []

            # Type validation
            try:
                if metadata.dtype == "float32":
                    float(value)
                elif metadata.dtype == "int64":
                    int(value)
                elif metadata.dtype == "string":
                    str(value)
                elif metadata.dtype == "bool":
                    bool(value)
            except (ValueError, TypeError):
                feature_errors.append(f"Invalid type for {metadata.dtype}")

            # Range validation
            if "min" in metadata.validation_rules and value < metadata.validation_rules["min"]:
                feature_errors.append(f"Value below minimum: {metadata.validation_rules['min']}")
            if "max" in metadata.validation_rules and value > metadata.validation_rules["max"]:
                feature_errors.append(f"Value above maximum: {metadata.validation_rules['max']}")

            if feature_errors:
                errors[feature_name] = feature_errors

        if errors and strict:
            raise FeatureStoreError(f"Feature validation failed: {errors}")

        return errors

    async def get_feature_stats(self, feature_name: str, hours: int = 24) -> Dict[str, Any]:
        """
        Get statistical summary for a feature over time.

        Args:
            feature_name: Name of the feature
            hours: Number of hours to look back

        Returns:
            Dictionary with statistical measures
        """
        if not self._initialized:
            await self.initialize()

        try:
            # Query historical feature values from Redis
            pattern = f"*:online:{feature_name}"
            keys = await self.redis_client.keys(pattern)

            values = []
            for key in keys[:1000]:  # Limit to prevent memory issues
                value = await self.redis_client.get(key)
                if value:
                    try:
                        values.append(float(value))
                    except ValueError:
                        continue

            if not values:
                return {"count": 0, "message": "No data available"}

            return {
                "count": len(values),
                "mean": float(np.mean(values)),
                "std": float(np.std(values)),
                "min": float(np.min(values)),
                "max": float(np.max(values)),
                "p25": float(np.percentile(values, 25)),
                "p50": float(np.median(values)),
                "p75": float(np.percentile(values, 75)),
                "last_updated": datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error(f"Failed to get feature stats for {feature_name}: {e}")
            return {"error": str(e)}

    async def cleanup_stale_features(self, max_age_hours: int = 24) -> int:
        """
        Remove stale features from the online store.

        Args:
            max_age_hours: Maximum age in hours for feature retention

        Returns:
            Number of features cleaned up
        """
        if not self._initialized:
            await self.initialize()

        try:
            # This would typically involve Feast's cleanup mechanisms
            # For now, we'll implement a simple Redis-based cleanup
            cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)

            # Get all feature keys
            pattern = "*:online:*"
            keys = await self.redis_client.keys(pattern)

            cleaned = 0
            for key in keys:
                # Check if key has TTL or is stale
                ttl = await self.redis_client.ttl(key)
                if ttl == -1:  # No TTL set
                    await self.redis_client.expire(key, 3600)  # Set 1 hour TTL
                    cleaned += 1

            logger.info(f"Cleaned up {cleaned} stale features")
            return cleaned

        except Exception as e:
            logger.error(f"Failed to cleanup stale features: {e}")
            return 0

    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on the feature store."""
        if not self._initialized:
            return {"status": "not_initialized"}

        try:
            # Test Redis connectivity
            await self.redis_client.ping()

            # Test Feast store
            self.store.list_feature_views()

            return {
                "status": "healthy",
                "redis_connected": True,
                "feast_operational": True,
                "features_registered": len(self.feature_metadata),
                "timestamp": datetime.utcnow().isoformat()
            }

        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }

    async def close(self) -> None:
        """Clean up resources."""
        if self.redis_client:
            await self.redis_client.close()
        self._initialized = False


# Global feature store instance
_feature_store: Optional[CryptoFeatureStore] = None


async def get_feature_store() -> CryptoFeatureStore:
    """Get or create the global feature store instance."""
    global _feature_store
    if _feature_store is None:
        _feature_store = CryptoFeatureStore()
        await _feature_store.initialize()
    return _feature_store


@asynccontextmanager
async def feature_store_context():
    """Context manager for feature store operations."""
    store = await get_feature_store()
    try:
        yield store
    finally:
        # Don't close here as it's a global instance
        pass