# signals/model_retrainer.py
"""Automatic model retraining system with blue-green deployment."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import joblib
import numpy as np
import pandas as pd
import structlog
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report

from .drift_detector import detect_drift, load_baseline
from .ml_predictor import SignalFeatures

logger = structlog.get_logger(__name__)


@dataclass
class RetrainingMetrics:
    """Metrics from model retraining."""

    accuracy: float
    precision: float
    recall: float
    f1_score: float
    training_time: float
    dataset_size: int
    improvement_score: float


class ModelRetrainerUnavailable(RuntimeError):
    """Raised when model retrainer cannot perform operations."""


class BlueGreenDeployment:
    """Blue-green deployment manager for ML models."""

    def __init__(self, model_dir: Path, backup_count: int = 3):
        self.model_dir = model_dir
        self.backup_count = backup_count
        self.active_model = "blue"
        self._lock = asyncio.Lock()

    @property
    def active_path(self) -> Path:
        """Path to currently active model."""
        return self.model_dir / f"model_{self.active_model}.pkl"

    @property
    def inactive_path(self) -> Path:
        """Path to inactive model (for staging new deployments)."""
        inactive = "green" if self.active_model == "blue" else "blue"
        return self.model_dir / f"model_{inactive}.pkl"

    async def switch_active_model(self) -> None:
        """Switch active model in blue-green fashion."""
        async with self._lock:
            old_active = self.active_model
            self.active_model = "green" if self.active_model == "blue" else "blue"

            # Backup old model
            await self._backup_model(old_active)

            logger.info(
                "model_switched",
                from_model=old_active,
                to_model=self.active_model,
                active_path=str(self.active_path),
                inactive_path=str(self.inactive_path)
            )

    async def deploy_new_model(self, new_model_path: Path) -> None:
        """Deploy new model to inactive slot."""
        async with self._lock:
            # Copy new model to inactive slot
            shutil.copy2(new_model_path, self.inactive_path)

            # Validate the new model
            await self._validate_model(self.inactive_path)

            logger.info("new_model_deployed", path=str(self.inactive_path))

    async def _backup_model(self, model_color: str) -> None:
        """Backup model before switching."""
        model_path = self.model_dir / f"model_{model_color}.pkl"
        if model_path.exists():
            timestamp = int(time.time())
            backup_path = self.model_dir / f"backup_model_{model_color}_{timestamp}.pkl"
            shutil.copy2(model_path, backup_path)

            # Clean old backups
            await self._cleanup_old_backups(model_color)

    async def _cleanup_old_backups(self, model_color: str) -> None:
        """Keep only the most recent backups."""
        backup_pattern = f"backup_model_{model_color}_*.pkl"
        backups = list(self.model_dir.glob(backup_pattern))
        backups.sort(key=lambda x: x.stat().st_mtime, reverse=True)

        if len(backups) > self.backup_count:
            for old_backup in backups[self.backup_count:]:
                old_backup.unlink()
                logger.debug("old_backup_cleaned", path=str(old_backup))

    async def _validate_model(self, model_path: Path) -> None:
        """Validate that model can be loaded and used."""
        try:
            model = joblib.load(model_path)

            # Test prediction
            test_features = SignalFeatures(
                price=50000.0, rsi=65.0, volume_ratio=1.2,
                fvg=0, divergence=0, mtf=1
            )
            vector = [test_features.as_vector()]
            prediction = model.predict_proba(vector)

            if prediction.shape != (1, 2):
                raise ValueError(f"Invalid prediction shape: {prediction.shape}")

        except Exception as exc:
            raise ModelRetrainerUnavailable(f"Model validation failed: {exc}") from exc


class AutomaticModelRetrainer:
    """Automatic model retraining triggered by drift detection."""

    def __init__(
        self,
        model_dir: Path,
        data_dir: Path,
        drift_threshold: float = 0.1,
        min_retrain_interval: int = 3600,  # 1 hour
        min_dataset_size: int = 1000,
    ):
        self.model_dir = model_dir
        self.data_dir = data_dir
        self.drift_threshold = drift_threshold
        self.min_retrain_interval = min_retrain_interval
        self.min_dataset_size = min_dataset_size

        self.blue_green = BlueGreenDeployment(model_dir)
        self._last_retrain_time = 0
        self._retraining_task: Optional[asyncio.Task] = None
        self._running = False

        # Metrics
        self._retrain_count = 0
        self._last_metrics: Optional[RetrainingMetrics] = None

    @property
    def is_running(self) -> bool:
        """Check if retrainer is running."""
        return self._running and self._retraining_task and not self._retraining_task.done()

    @property
    def last_retraining_metrics(self) -> Optional[RetrainingMetrics]:
        """Get metrics from last retraining."""
        return self._last_metrics

    async def start(self) -> None:
        """Start automatic retraining monitoring."""
        if self.is_running:
            return

        self._running = True
        self._retraining_task = asyncio.create_task(self._monitor_and_retrain())
        logger.info("automatic_retrainer_started")

    async def stop(self) -> None:
        """Stop automatic retraining."""
        self._running = False
        if self._retraining_task:
            self._retraining_task.cancel()
            try:
                await self._retraining_task
            except asyncio.CancelledError:
                pass
        logger.info("automatic_retrainer_stopped")

    async def force_retrain(self) -> RetrainingMetrics:
        """Force immediate retraining."""
        return await self._perform_retraining()

    async def _monitor_and_retrain(self) -> None:
        """Main monitoring loop for drift detection and retraining."""
        while self._running:
            try:
                # Check for drift
                drift_detected = await self._check_for_drift()

                if drift_detected and self._should_retrain():
                    logger.info("drift_detected_triggering_retrain")
                    metrics = await self._perform_retraining()

                    # Switch to new model if significantly better
                    if metrics.improvement_score > 0.05:  # 5% improvement threshold
                        await self.blue_green.switch_active_model()
                        self._retrain_count += 1
                        self._last_metrics = metrics

                        logger.info(
                            "model_retrained_and_deployed",
                            metrics=metrics.__dict__,
                            total_retrains=self._retrain_count
                        )
                    else:
                        logger.info("model_retrained_but_not_deployed", improvement=metrics.improvement_score)

                # Wait before next check
                await asyncio.sleep(300)  # Check every 5 minutes

            except Exception as exc:
                logger.error("retraining_monitor_error", error=str(exc))
                await asyncio.sleep(60)  # Backoff on errors

    async def _check_for_drift(self) -> bool:
        """Check if drift has been detected."""
        try:
            # Use a dummy feature set to trigger drift detection
            dummy_features = SignalFeatures(
                price=50000.0, rsi=50.0, volume_ratio=1.0,
                fvg=0, divergence=0, mtf=0
            )
            return await detect_drift(dummy_features)
        except Exception:
            return False

    def _should_retrain(self) -> bool:
        """Check if retraining conditions are met."""
        now = time.time()

        # Check time since last retrain
        if now - self._last_retrain_time < self.min_retrain_interval:
            return False

        # Check if we have enough data
        dataset_size = self._get_dataset_size()
        if dataset_size < self.min_dataset_size:
            return False

        return True

    async def _perform_retraining(self) -> RetrainingMetrics:
        """Perform model retraining."""
        start_time = time.time()

        try:
            # Load training data
            X, y = await self._load_training_data()

            # Split data
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, random_state=42, stratify=y
            )

            # Train new model
            model = RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                random_state=42,
                n_jobs=-1
            )
            model.fit(X_train, y_train)

            # Evaluate
            y_pred = model.predict(X_test)
            y_pred_proba = model.predict_proba(X_test)

            accuracy = accuracy_score(y_test, y_pred)
            report = classification_report(y_test, y_pred, output_dict=True)

            # Calculate improvement score (vs baseline)
            baseline_accuracy = await self._get_baseline_accuracy()
            improvement_score = accuracy - baseline_accuracy

            # Save new model temporarily
            temp_model_path = self.model_dir / "temp_model.pkl"
            joblib.dump(model, temp_model_path)

            # Deploy to inactive slot
            await self.blue_green.deploy_new_model(temp_model_path)
            temp_model_path.unlink()

            training_time = time.time() - start_time
            self._last_retrain_time = time.time()

            metrics = RetrainingMetrics(
                accuracy=accuracy,
                precision=report['weighted avg']['precision'],
                recall=report['weighted avg']['recall'],
                f1_score=report['weighted avg']['f1-score'],
                training_time=training_time,
                dataset_size=len(X),
                improvement_score=improvement_score
            )

            return metrics

        except Exception as exc:
            logger.error("retraining_failed", error=str(exc))
            raise ModelRetrainerUnavailable(f"Retraining failed: {exc}") from exc

    async def _load_training_data(self) -> tuple[np.ndarray, np.ndarray]:
        """Load training data from recent signals."""
        # This would load from your signal database/cache
        # For now, generate synthetic data
        np.random.seed(42)

        # Generate realistic signal data
        n_samples = 5000
        features = []

        for _ in range(n_samples):
            price = np.random.normal(50000, 5000)
            rsi = np.random.uniform(20, 80)
            volume_ratio = np.random.exponential(1.5)
            fvg = np.random.choice([0, 1])
            divergence = np.random.choice([0, 1])
            mtf = np.random.choice([0, 1])

            features.append([price, rsi, volume_ratio, fvg, divergence, mtf])

        X = np.array(features)

        # Generate labels based on simple rules (for demo)
        # In real implementation, use actual signal outcomes
        y = np.random.choice([0, 1], size=n_samples, p=[0.7, 0.3])  # Bias toward rejection

        return X, y

    async def _get_baseline_accuracy(self) -> float:
        """Get baseline accuracy from current model."""
        try:
            # Test current model on recent data
            X, y = await self._load_training_data()
            _, X_test, _, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

            model = joblib.load(self.blue_green.active_path)
            y_pred = model.predict(X_test)
            return accuracy_score(y_test, y_pred)

        except Exception:
            return 0.5  # Default baseline

    def _get_dataset_size(self) -> int:
        """Get current dataset size."""
        # In real implementation, check database/cache size
        return 5000  # Mock value


# Global retrainer instance
_RETRAINER: Optional[AutomaticModelRetrainer] = None


async def get_model_retrainer() -> AutomaticModelRetrainer:
    """Get global model retrainer instance."""
    global _RETRAINER
    if _RETRAINER is None:
        model_dir = Path(os.getenv("ML_MODEL_DIR", "models"))
        data_dir = Path(os.getenv("SIGNALS_DATA_DIR", "data"))
        _RETRAINER = AutomaticModelRetrainer(model_dir, data_dir)
        await _RETRAINER.start()
    return _RETRAINER


async def reset_model_retrainer() -> None:
    """Reset global model retrainer."""
    global _RETRAINER
    if _RETRAINER is not None:
        await _RETRAINER.stop()
        _RETRAINER = None


__all__ = [
    "RetrainingMetrics",
    "ModelRetrainerUnavailable",
    "BlueGreenDeployment",
    "AutomaticModelRetrainer",
    "get_model_retrainer",
    "reset_model_retrainer",
]