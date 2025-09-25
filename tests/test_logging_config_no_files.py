import logging

from pipeline import logging_config as lc


def test_logging_config_no_file_handlers(monkeypatch):
    lc._reset_logging_for_tests()
    monkeypatch.setenv("ENABLE_FILE_LOGS", "0")  # désactive fichiers
    # simple=False mais ENABLE_FILE_LOGS=0 => pas de file handlers et run_log_path None
    logger = lc.setup_logging(simple=False)
    logger.info("evt")
    assert len(logging.getLogger().handlers) == 1
    # vérifier qu'aucun handler fichier
    assert not any(hasattr(h, 'baseFilename') for h in logging.getLogger().handlers)
