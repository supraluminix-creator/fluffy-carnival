import json
import time
import urllib.request

from pipeline.health import start_health_server


def test_health_server_basic():
    # Démarrer sur port éphémère (0) puis récupérer port réel
    server = start_health_server(0)
    assert server is not None
    host_raw, port = server.server_address
    host = host_raw.decode() if isinstance(host_raw, bytes) else host_raw
    if host in ("0.0.0.0", "::"):
        # Pour les requêtes cliente on cible loopback
        host = "127.0.0.1"
    # Attendre petit délai que le thread démarre
    time.sleep(0.05)

    with urllib.request.urlopen(f"http://{host}:{port}/health") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode())
        assert "run_id" in data
        assert "ports" in data

    with urllib.request.urlopen(f"http://{host}:{port}/ready") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode())
        assert "run_id" in data

    # Endpoint inconnu
    from contextlib import suppress

    with suppress(Exception):  # HTTPError attendu
        urllib.request.urlopen(f"http://{host}:{port}/nope")

    server.shutdown()
    server.server_close()
