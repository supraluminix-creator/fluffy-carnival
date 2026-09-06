import structlog

from pipeline.logging_config import _reset_logging_for_tests, mask_secrets_processor, setup_logging


def test_secret_masking(tmp_path, monkeypatch):
    monkeypatch.setenv("ENABLE_FILE_LOGS", "0")
    _reset_logging_for_tests()
    setup_logging(simple=True)
    logger = structlog.get_logger("test")
    # Capture via structlog testing: utiliser un processor mémoire personnalisé
    events = []

    def capture(logger, method_name, event_dict):
        events.append(event_dict)
        return event_dict

    # Reconfigure avec capture + masking
    _reset_logging_for_tests()
    import structlog as sl

    sl.configure(
        processors=[mask_secrets_processor, capture, sl.processors.JSONRenderer()],
        logger_factory=sl.stdlib.LoggerFactory(),
    )
    logger = sl.get_logger("mask")
    logger.info("test", api_key="ABCD1234EFGH", password="supersecret", token="XYZ")
    assert events, "No events captured"
    evt = events[0]
    assert evt["api_key"].startswith("AB") and evt["api_key"].endswith("GH") and "***" in evt["api_key"]
    assert evt["password"].startswith("su") and evt["password"].endswith("et") and "***" in evt["password"]
    assert evt["token"] == "***"  # longueur <=4 => full mask
