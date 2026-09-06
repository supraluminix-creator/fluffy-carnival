import socket

from pipeline import monitoring


def test_start_metrics_server(monkeypatch):
    # Find free port
    sock = socket.socket()
    sock.bind(("localhost", 0))
    port = sock.getsockname()[1]
    sock.close()
    # Start server (non-blocking)
    monitoring.start_metrics_server(port=port)
    # We don't assert scrape; just ensure no exception and port chosen
    assert port > 0


def test_start_metrics_server_unused_port():
    # Trouve un port libre
    s = socket.socket()
    try:
        # Binder sur l'interface loopback pour éviter 0.0.0.0
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    finally:
        s.close()
    monitoring.start_metrics_server(port=port)
    # Juste vérifier que la fonction ne lève pas et que les métriques globales existent
    assert hasattr(monitoring, "REQUEST_LATENCY")
    assert hasattr(monitoring, "REQUEST_ERRORS")
