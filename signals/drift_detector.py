# signals/drift_detector.py
"""Drift detection for ML model using KL divergence on feature distributions."""

from __future__ import annotations

import json
import os
from pathlib import Path

import scipy.stats
import structlog
from prometheus_client import Counter, Gauge

from .ml_predictor import SignalFeatures

logger = structlog.get_logger(__name__)

DRIFT_KL_DIVERGENCE = Gauge("drift_kl_divergence", "KL divergence from baseline", ["feature"])
DRIFT_ALERTS_TOTAL = Counter("drift_alerts_total", "Drift detections")

_BASELINE_PATH = Path(os.getenv("DRIFT_BASELINE_PATH", "data/drift_baseline.json"))


def load_baseline() -> dict[str, tuple[float, float]]:
    """Load baseline feature distributions (mean, std) from file."""
    if not _BASELINE_PATH.exists():
        # Initialize with empty if no baseline
        return {}
    try:
        data = json.loads(_BASELINE_PATH.read_text())
        return {k: tuple(v) for k, v in data.items()}
    except Exception as e:
        logger.warning("drift_baseline_load_failed", error=str(e))
        return {}


def save_baseline(baseline: dict[str, tuple[float, float]]) -> None:
    """Save baseline to file."""
    try:
        _BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _BASELINE_PATH.write_text(json.dumps(baseline, indent=2))
    except Exception as e:
        logger.error("drift_baseline_save_failed", error=str(e))


def compute_distribution(features: SignalFeatures) -> dict[str, tuple[float, float]]:
    """Compute mean and std for features (simplified: single sample)."""
    # In prod, accumulate over window
    vector = features.as_vector()
    # Assume features: price, rsi, volume_ratio, fvg, divergence, mtf
    return {
        "price": (vector[0], 0.0),  # mean, std (placeholder)
        "rsi": (vector[1], 0.0),
        "volume_ratio": (vector[2], 0.0),
    }


async def detect_drift(features: SignalFeatures) -> bool:
    """Detect drift using KL divergence."""
    baseline = load_baseline()
    if not baseline:
        # First run: save baseline
        save_baseline(compute_distribution(features))
        return False

    current = compute_distribution(features)
    max_kl = 0.0
    for feat in ["price", "rsi", "volume_ratio"]:
        if feat in baseline and feat in current:
            kl = scipy.stats.entropy(current[feat], baseline[feat])
            DRIFT_KL_DIVERGENCE.labels(feature=feat).set(kl)
            max_kl = max(max_kl, kl)

    if max_kl > 0.1:  # Threshold
        DRIFT_ALERTS_TOTAL.inc()
        logger.warning("drift_detected", kl=max_kl)
        # Trigger retrain (placeholder)
        return True
    return False


__all__ = ["detect_drift"]
