from pipeline import monitoring


def test_monitoring_metrics_basic():
    # Incrément simple pour vérifier absence d'exception
    c = monitoring.REQUEST_SUCCESS.labels(collector="x")
    c.inc()
    monitoring.REQUEST_ERRORS.labels(collector="x").inc()
    monitoring.REQUEST_LATENCY.labels(collector="x").observe(0.01)
