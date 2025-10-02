import logging
import os

from pipeline import logging_config as lc


def _count_file_handlers():
    return sum(isinstance(h, logging.FileHandler) for h in logging.getLogger().handlers)


def test_setup_logging_simple_mode(tmp_path, monkeypatch):
    lc._reset_logging_for_tests()
    monkeypatch.setenv("ENABLE_FILE_LOGS", "1")  # même si 1, simple=True doit ignorer
    monkeypatch.setenv("LOGS_DIR", str(tmp_path / "logs"))
    logger = lc.setup_logging(simple=True)
    logger.info("test_event", foo=1)
    # Aucun fichier créé
    assert not (tmp_path / "logs").exists()
    # Un seul handler (console)
    assert len(logging.getLogger().handlers) == 1
    # Idempotence sur simple True -> second appel ne change rien
    h_ids = [id(h) for h in logging.getLogger().handlers]
    lc.setup_logging(simple=True)
    assert [id(h) for h in logging.getLogger().handlers] == h_ids


def test_setup_logging_files_created(tmp_path, monkeypatch):
    lc._reset_logging_for_tests()
    monkeypatch.setenv("ENABLE_FILE_LOGS", "1")
    monkeypatch.setenv("LOGS_DIR", str(tmp_path / "logs"))
    logger = lc.setup_logging()
    logger.info("pipeline_started_test", value=42)
    logs_dir = tmp_path / "logs"
    # Répertoire créé
    assert logs_dir.exists()
    # Handlers: console + rotating + run_file = 3
    assert _count_file_handlers() == 2
    assert len(logging.getLogger().handlers) == 3
    # Un fichier run spécifique doit exister
    run_id = os.environ.get("RUN_ID")
    run_files = list(logs_dir.glob(f"run_{run_id}.log"))
    assert run_files, "Fichier de run manquant"
    # Appel idempotent: pas de nouveaux handlers
    handlers_ids = [id(h) for h in logging.getLogger().handlers]
    lc.setup_logging()
    assert [id(h) for h in logging.getLogger().handlers] == handlers_ids


def test_setup_logging_preserve_existing_run_id(tmp_path, monkeypatch):
    lc._reset_logging_for_tests()
    monkeypatch.setenv("ENABLE_FILE_LOGS", "0")  # désactive fichiers pour simplicité
    monkeypatch.setenv("LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("RUN_ID", "fixed1234")
    logger = lc.setup_logging()
    logger.info("something")
    assert os.environ.get("RUN_ID") == "fixed1234"
    # Re-appel ne change pas le RUN_ID
    lc.setup_logging()
    assert os.environ.get("RUN_ID") == "fixed1234"
