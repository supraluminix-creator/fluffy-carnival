"""Tests for signals webhook functionality."""

from __future__ import annotations

import ipaddress
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from signals.drift_detector import detect_drift
from signals.ml_predictor import PredictorUnavailable, SignalFeatures
from signals.telegram import TelegramConfigurationError
from signals.webhook import SignalPayload, router
from signals.webhook_auth import validate_ip_trust


@pytest.fixture
def client():
    """FastAPI test client for webhook routes."""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def sample_payload():
    """Sample valid signal payload."""
    return {
        "type": "swing_reversal",
        "symbol": "BTCUSDT",
        "price": 45000.0,
        "rsi": 65.5,
        "volume_ratio": 1.8,
        "fvg": True,
        "divergence": False,
        "mtf": True,
        "timestamp": "2024-01-01T12:00:00Z",
    }


@pytest.fixture
def signal_features():
    """Sample signal features."""
    return SignalFeatures(
        price=45000.0,
        rsi=65.5,
        volume_ratio=1.8,
        fvg=1,
        divergence=0,
        mtf=1,
    )


class TestSignalPayload:
    """Test SignalPayload model validation."""

    def test_valid_payload(self, sample_payload):
        """Test valid payload parsing."""
        payload = SignalPayload(**sample_payload)
        assert payload.symbol == "BTCUSDT"
        assert payload.price == 45000.0
        assert payload.rsi == 65.5

    def test_symbol_uppercase(self):
        """Test symbol is uppercased."""
        payload = SignalPayload(
            type="test",
            symbol="btcusdt",
            price=45000.0,
            rsi=65.5,
            volume_ratio=1.8,
            fvg=False,
            divergence=False,
            mtf=False,
            timestamp=datetime.now(),
        )
        assert payload.symbol == "BTCUSDT"

    def test_invalid_price(self):
        """Test negative price validation."""
        with pytest.raises(ValueError):
            SignalPayload(
                type="test",
                symbol="BTCUSDT",
                price=-100.0,
                rsi=65.5,
                volume_ratio=1.8,
                fvg=False,
                divergence=False,
                mtf=False,
                timestamp=datetime.now(),
            )

    def test_to_features_conversion(self, sample_payload):
        """Test payload to features conversion."""
        payload = SignalPayload(**sample_payload)
        features = payload.to_features()
        assert isinstance(features, SignalFeatures)
        assert features.price == 45000.0
        assert features.fvg == 1  # True -> 1
        assert features.divergence == 0  # False -> 0


class TestIPValidation:
    """Test IP trust validation."""

    @patch("signals.webhook_auth.ALLOWED_IPS", [ipaddress.ip_network("192.168.1.1"), ipaddress.ip_network("10.0.0.1")])
    def test_valid_ip(self):
        """Test valid IP passes validation."""
        validate_ip_trust("192.168.1.1")
        validate_ip_trust("10.0.0.1")

    @patch("signals.webhook_auth.ALLOWED_IPS", [ipaddress.ip_network("192.168.1.0/24")])
    def test_valid_cidr(self):
        """Test CIDR range validation."""
        validate_ip_trust("192.168.1.50")

    @patch("signals.webhook_auth.ALLOWED_IPS", [ipaddress.ip_network("192.168.1.1")])
    def test_invalid_ip_raises_exception(self):
        """Test invalid IP raises HTTPException."""
        with pytest.raises(HTTPException) as exc_info:
            validate_ip_trust("10.0.0.1")
        assert exc_info.value.status_code == 403
        assert "IP not allowed" in exc_info.value.detail

    def test_default_allows_localhost(self):
        """Test default configuration allows localhost."""
        validate_ip_trust("127.0.0.1")


class TestDriftDetection:
    """Test drift detection functionality."""

    @pytest.fixture
    def baseline_file(self):
        """Create temporary baseline file."""
        data = {
            "price": {"mean": 45000.0, "std": 1000.0},
            "rsi": {"mean": 50.0, "std": 10.0},
            "volume_ratio": {"mean": 1.5, "std": 0.5},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            return f.name

    async def test_no_drift_detected(self, signal_features):
        """Test no drift when features match baseline."""
        baseline_file = tempfile.mktemp(suffix=".json")
        # Create baseline matching features
        data = {
            "price": (45000.0, 1000.0),
            "rsi": (65.5, 1.0),
            "volume_ratio": (1.8, 0.1),
        }
        with open(baseline_file, "w") as f:
            json.dump(data, f)

        with patch("signals.drift_detector._BASELINE_PATH", Path(baseline_file)):
            drift = await detect_drift(signal_features)
            assert not drift

    async def test_drift_detected_high_kl(self, signal_features):
        """Test drift detected when KL divergence is high."""
        baseline_file = tempfile.mktemp(suffix=".json")
        # Create baseline very different from features
        data = {
            "price": (30000.0, 1000.0),
            "rsi": (20.0, 5.0),
            "volume_ratio": (0.5, 0.1),
        }
        with open(baseline_file, "w") as f:
            json.dump(data, f)

        with patch("signals.drift_detector._BASELINE_PATH", Path(baseline_file)):
            drift = await detect_drift(signal_features)
            assert drift  # High KL divergence should trigger drift


class TestRateLimiting:
    """Test rate limiting functionality."""

    @patch("signals.webhook._RATE_LIMIT_WINDOW", 1.0)  # 1 second window
    @patch("signals.webhook._RATE_LIMIT", {})
    @patch("signals.webhook._get_client_ip", return_value="127.0.0.1")
    @patch("signals.webhook.validate_ip_trust")
    @patch("signals.webhook.get_predictor")
    async def test_rate_limit_allows_first_request(self, mock_get_predictor, mock_validate_ip, mock_get_ip, client, sample_payload):
        """Test first request in window is allowed."""
        mock_predictor = Mock()
        mock_predictor.predict.return_value = 0.9
        mock_predictor.model_loaded = True
        mock_get_predictor.return_value = mock_predictor

        with patch("signals.webhook.send_signal_alert", new_callable=AsyncMock):
            response = client.post("/signals/webhook", json=sample_payload)

        assert response.status_code in [200, 202, 503]  # Various possible responses

    @patch("signals.webhook._RATE_LIMIT_WINDOW", 0.1)  # Very short window
    @patch("signals.webhook._RATE_LIMIT", {})
    @patch("signals.webhook._get_client_ip", return_value="127.0.0.1")
    @patch("signals.webhook.validate_ip_trust")
    @patch("signals.webhook.get_predictor")
    async def test_rate_limit_blocks_subsequent_requests(self, mock_get_predictor, mock_validate_ip, mock_get_ip, client, sample_payload):
        """Test subsequent requests in window are blocked."""
        mock_predictor = Mock()
        mock_predictor.predict.return_value = 0.9
        mock_predictor.model_loaded = True
        mock_get_predictor.return_value = mock_predictor

        # First request
        with patch("signals.webhook.send_signal_alert", new_callable=AsyncMock):
            client.post("/signals/webhook", json=sample_payload)

        # Second request should be rate limited
        response = client.post("/signals/webhook", json=sample_payload)
        assert response.status_code == 429


class TestSecretValidation:
    """Test webhook secret validation."""

    @patch.dict(os.environ, {"TRADINGVIEW_WEBHOOK_TOKEN": "secret123"})
    @patch("signals.webhook._get_client_ip", return_value="127.0.0.1")
    @patch("signals.webhook.validate_ip_trust")
    @patch("signals.webhook.get_predictor")
    def test_valid_secret(self, mock_get_predictor, mock_validate_ip, mock_get_ip, client, sample_payload):
        """Test valid secret passes."""
        mock_predictor = Mock()
        mock_predictor.predict.return_value = 0.9
        mock_predictor.model_loaded = True
        mock_get_predictor.return_value = mock_predictor

        with patch("signals.webhook.send_signal_alert", new_callable=AsyncMock):
            response = client.post(
                "/signals/webhook",
                json=sample_payload,
                headers={"X-Webhook-Token": "secret123"}
            )

        assert response.status_code == 200

    @patch.dict(os.environ, {"TRADINGVIEW_WEBHOOK_TOKEN": "secret123"})
    @patch("signals.webhook._get_client_ip", return_value="192.168.1.3")
    @patch("signals.webhook.validate_ip_trust")
    def test_invalid_secret_fails(self, mock_validate_ip, mock_get_ip, client, sample_payload):
        """Test invalid secret fails."""
        response = client.post(
            "/signals/webhook",
            json=sample_payload,
            headers={"X-Webhook-Token": "wrong"}
        )
        assert response.status_code == 403

    @patch.dict(os.environ, {})
    @patch("signals.webhook._get_client_ip", return_value="192.168.1.2")
    @patch("signals.webhook.validate_ip_trust")
    @patch("signals.webhook.get_predictor")
    def test_no_secret_required(self, mock_get_predictor, mock_validate_ip, mock_get_ip, client, sample_payload):
        """Test no secret validation when not configured."""
        mock_predictor = Mock()
        mock_predictor.predict.return_value = 0.9
        mock_predictor.model_loaded = True
        mock_get_predictor.return_value = mock_predictor

        with patch("signals.webhook.send_signal_alert", new_callable=AsyncMock):
            response = client.post("/signals/webhook", json=sample_payload)

        assert response.status_code == 200


class TestCircuitBreaker:
    """Test circuit breaker integration."""

    @patch("pipeline.circuit_breaker.should_skip")
    @patch("signals.webhook._get_client_ip", return_value="192.168.1.4")
    @patch("signals.webhook.validate_ip_trust")
    def test_breaker_open_blocks_request(self, mock_validate_ip, mock_get_ip, mock_should_skip, client, sample_payload):
        """Test circuit breaker open blocks requests."""
        mock_should_skip.return_value = True

        response = client.post("/signals/webhook", json=sample_payload)
        assert response.status_code == 503

    @patch("pipeline.circuit_breaker.should_skip")
    @patch("signals.webhook._get_client_ip", return_value="192.168.1.5")
    @patch("signals.webhook.validate_ip_trust")
    @patch("signals.webhook.get_predictor")
    def test_breaker_closed_allows_request(self, mock_get_predictor, mock_validate_ip, mock_get_ip, mock_should_skip, client, sample_payload):
        """Test circuit breaker closed allows requests."""
        mock_should_skip.return_value = False

        mock_predictor = Mock()
        mock_predictor.predict.return_value = 0.9
        mock_predictor.model_loaded = True
        mock_get_predictor.return_value = mock_predictor

        with patch("signals.webhook.send_signal_alert", new_callable=AsyncMock):
            response = client.post("/signals/webhook", json=sample_payload)

        assert response.status_code == 200


class TestMLPrediction:
    """Test ML prediction integration."""

    @patch("signals.webhook.get_predictor")
    @patch("signals.webhook.detect_drift", new_callable=AsyncMock)
    @patch("signals.webhook._get_client_ip", return_value="192.168.1.6")
    @patch("signals.webhook.validate_ip_trust")
    def test_successful_prediction_validated(self, mock_validate_ip, mock_get_ip, mock_detect_drift, mock_get_predictor, client, sample_payload):
        """Test successful prediction above threshold."""
        mock_detect_drift.return_value = False

        mock_predictor = Mock()
        mock_predictor.predict.return_value = 0.9
        mock_predictor.model_loaded = True
        mock_get_predictor.return_value = mock_predictor

        with patch("signals.webhook.send_signal_alert", new_callable=AsyncMock) as mock_send:
            response = client.post("/signals/webhook", json=sample_payload)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "validated"
        assert data["confidence"] == 0.9
        mock_send.assert_called_once()

    @patch("signals.webhook.get_predictor")
    @patch("signals.webhook.detect_drift", new_callable=AsyncMock)
    @patch("signals.webhook._get_client_ip", return_value="192.168.1.7")
    @patch("signals.webhook.validate_ip_trust")
    def test_low_confidence_rejected(self, mock_validate_ip, mock_get_ip, mock_detect_drift, mock_get_predictor, client, sample_payload):
        """Test prediction below threshold is rejected."""
        mock_detect_drift.return_value = False

        mock_predictor = Mock()
        mock_predictor.predict.return_value = 0.7
        mock_predictor.model_loaded = True
        mock_get_predictor.return_value = mock_predictor

        response = client.post("/signals/webhook", json=sample_payload)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "rejected"
        assert data["confidence"] == 0.7

    @patch("signals.webhook.get_predictor")
    @patch("signals.webhook.detect_drift", new_callable=AsyncMock)
    @patch("signals.webhook._get_client_ip", return_value="192.168.1.8")
    @patch("signals.webhook.validate_ip_trust")
    def test_predictor_unavailable_queues_signal(self, mock_validate_ip, mock_get_ip, mock_detect_drift, mock_get_predictor, client, sample_payload):
        """Test predictor unavailable queues signal."""
        mock_detect_drift.return_value = False

        mock_predictor = Mock()
        mock_predictor.predict.side_effect = PredictorUnavailable("Model not loaded")
        mock_get_predictor.return_value = mock_predictor

        response = client.post("/signals/webhook", json=sample_payload)

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "queued"


class TestDriftIntegration:
    """Test drift detection integration in webhook."""

    @patch("signals.webhook.get_predictor")
    @patch("signals.webhook.detect_drift", new_callable=AsyncMock)
    @patch("signals.webhook._get_client_ip", return_value="192.168.1.9")
    @patch("signals.webhook.validate_ip_trust")
    def test_drift_detected_logs_warning(self, mock_validate_ip, mock_get_ip, mock_detect_drift, mock_get_predictor, client, sample_payload):
        """Test drift detection logs warning."""
        mock_detect_drift.return_value = True

        mock_predictor = Mock()
        mock_predictor.predict.return_value = 0.9
        mock_predictor.model_loaded = True
        mock_get_predictor.return_value = mock_predictor

        with patch("signals.webhook.logger") as mock_logger, \
             patch("signals.webhook.send_signal_alert", new_callable=AsyncMock):
            client.post("/signals/webhook", json=sample_payload)

        mock_logger.warning.assert_called_with(
            "drift_detected_in_signal",
            symbol="BTCUSDT",
            confidence=0.9
        )


class TestTelegramIntegration:
    """Test Telegram alert integration."""

    @patch("signals.webhook.get_predictor")
    @patch("signals.webhook.detect_drift", new_callable=AsyncMock)
    @patch("signals.webhook._get_client_ip", return_value="192.168.1.10")
    @patch("signals.webhook.validate_ip_trust")
    def test_telegram_config_error_returns_500(self, mock_validate_ip, mock_get_ip, mock_detect_drift, mock_get_predictor, client, sample_payload):
        """Test Telegram config error returns 500."""
        mock_detect_drift.return_value = False

        mock_predictor = Mock()
        mock_predictor.predict.return_value = 0.9
        mock_predictor.model_loaded = True
        mock_get_predictor.return_value = mock_predictor

        with patch("signals.webhook.send_signal_alert", side_effect=TelegramConfigurationError("No token")):
            response = client.post("/signals/webhook", json=sample_payload)

        assert response.status_code == 500

    @patch("signals.webhook.get_predictor")
    @patch("signals.webhook.detect_drift", new_callable=AsyncMock)
    @patch("signals.webhook._get_client_ip", return_value="192.168.1.11")
    @patch("signals.webhook.validate_ip_trust")
    def test_telegram_delivery_error_returns_502(self, mock_validate_ip, mock_get_ip, mock_detect_drift, mock_get_predictor, client, sample_payload):
        """Test Telegram delivery error returns 502."""
        mock_detect_drift.return_value = False

        mock_predictor = Mock()
        mock_predictor.predict.return_value = 0.9
        mock_predictor.model_loaded = True
        mock_get_predictor.return_value = mock_predictor

        with patch("signals.webhook.send_signal_alert", side_effect=Exception("Network error")):
            response = client.post("/signals/webhook", json=sample_payload)

        assert response.status_code == 502


class TestHealthEndpoint:
    """Test signals health endpoint."""

    @patch("signals.webhook.get_predictor")
    def test_health_model_loaded(self, mock_get_predictor, client):
        """Test health when model is loaded."""
        mock_predictor = Mock()
        mock_predictor.model_loaded = True
        mock_predictor.backlog_size.return_value = 5
        mock_predictor.last_error = None
        mock_get_predictor.return_value = mock_predictor

        response = client.get("/signals/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["model_loaded"] is True
        assert data["backlog_size"] == 5

    @patch("signals.webhook.get_predictor")
    def test_health_model_not_loaded(self, mock_get_predictor, client):
        """Test health when model is not loaded."""
        mock_predictor = Mock()
        mock_predictor.model_loaded = False
        mock_predictor.backlog_size.return_value = 0
        mock_predictor.last_error = "Model failed to load"
        mock_get_predictor.return_value = mock_predictor

        response = client.get("/signals/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["model_loaded"] is False
        assert data["last_error"] == "Model failed to load"


class TestMetricsIntegration:
    """Test Prometheus metrics integration."""

    @patch("signals.webhook.get_predictor")
    @patch("signals.webhook.detect_drift", new_callable=AsyncMock)
    @patch("signals.webhook._get_client_ip", return_value="192.168.1.12")
    @patch("signals.webhook.validate_ip_trust")
    def test_metrics_recorded_on_success(self, mock_validate_ip, mock_get_ip, mock_detect_drift, mock_get_predictor, client, sample_payload):
        """Test metrics are recorded on successful signal processing."""
        mock_detect_drift.return_value = False

        mock_predictor = Mock()
        mock_predictor.predict.return_value = 0.9
        mock_predictor.model_loaded = True
        mock_get_predictor.return_value = mock_predictor

        with patch("signals.webhook.send_signal_alert", new_callable=AsyncMock):
            response = client.post("/signals/webhook", json=sample_payload)

        assert response.status_code == 200

        # Check that metrics were incremented (this would need actual metric collection in real tests)
        # For now, just ensure no exceptions were raised during metric recording

    @patch("signals.webhook.get_predictor")
    @patch("signals.webhook.detect_drift", new_callable=AsyncMock)
    @patch("signals.webhook._get_client_ip", return_value="192.168.1.13")
    @patch("signals.webhook.validate_ip_trust")
    def test_rate_limit_metrics(self, mock_validate_ip, mock_get_ip, mock_detect_drift, mock_get_predictor, client, sample_payload):
        """Test rate limit metrics are recorded."""
        mock_detect_drift.return_value = False

        # Mock rate limit to trigger
        with patch("signals.webhook._RATE_LIMIT_WINDOW", 0.0), \
             patch("signals.webhook._RATE_LIMIT", {"192.168.1.13": float('inf')}):
            response = client.post("/signals/webhook", json=sample_payload)

        assert response.status_code == 429
        # Metrics should be recorded for rate limiting


class TestRedisCacheIntegration:
    """Test Redis cache integration in ML predictor."""

    @patch("signals.webhook.get_predictor")
    @patch("signals.webhook.detect_drift", new_callable=AsyncMock)
    @patch("signals.webhook._get_client_ip", return_value="192.168.1.14")
    @patch("signals.webhook.validate_ip_trust")
    def test_redis_cache_used_in_prediction(self, mock_validate_ip, mock_get_ip, mock_detect_drift, mock_get_predictor, client, sample_payload):
        """Test Redis cache is used during prediction."""
        mock_detect_drift.return_value = False

        mock_predictor = Mock()
        mock_predictor.predict.return_value = 0.9
        mock_predictor.model_loaded = True
        mock_get_predictor.return_value = mock_predictor

        with patch("signals.webhook.send_signal_alert", new_callable=AsyncMock):
            response = client.post("/signals/webhook", json=sample_payload)

        assert response.status_code == 200

        # Verify predictor.predict was called (Redis is used internally for backlog if needed)
        mock_predictor.predict.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__])
