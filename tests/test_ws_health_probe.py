from unittest.mock import patch


def test_health_probe_prefers_health_endpoint(monkeypatch):
    # Activate autostart to enter the function path; it should early-return on healthy probe
    monkeypatch.setenv("BYBIT_WS_AUTOSTART", "1")
    monkeypatch.setenv("BYBIT_WS_PORT", "8000")
    monkeypatch.setenv("BYBIT_WS_HEALTH_PORT", "8100")

    calls = []

    class FakeResp:
        status_code = 200

    def fake_get(url, timeout=0.6):
        calls.append(url)
        # Respond 200 on /health and would fail otherwise, but code falls back only if exception
        return FakeResp()

    with patch("httpx.get", new=fake_get):
        import main as _main

        # call private helper; ensure it does not raise
        _main._ensure_bybit_ws_running()
        # First call should be /health on BYBIT_WS_HEALTH_PORT
        assert any("/health" in c and ":8100" in c for c in calls)
