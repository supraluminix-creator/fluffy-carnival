from pipeline.monitoring import REQUEST_ERRORS, REQUEST_LATENCY, REQUEST_SUCCESS


def test_metrics_labels():
    REQUEST_LATENCY.labels(collector="test").observe(0.1)
    REQUEST_ERRORS.labels(collector="test").inc()
    REQUEST_SUCCESS.labels(collector="test").inc()
    # No assertion needed, just ensure no exception

# feat: Phase 2 - monitoring Prometheus + logs JSON structlog sur tous les collectors