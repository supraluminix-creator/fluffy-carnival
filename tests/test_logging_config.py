import logging
import os
from pathlib import Path

from pipeline.logging_config import _reset_logging_for_tests, setup_logging


def test_setup_logging_creates_handlers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Ensure fresh environment
    if "RUN_ID" in os.environ:
        del os.environ["RUN_ID"]
    setup_logging()
    # Reset full logging state to force fresh configuration
    _reset_logging_for_tests()
    os.environ.pop("RUN_ID", None)
    setup_logging()
    # RUN_ID assigned
    assert os.getenv("RUN_ID")
    assert os.getenv("RUN_ID"), "RUN_ID should be set by setup_logging on fresh init"
    # A log file handler directory exists
    logs_dir = Path(tmp_path) / "logs"
    assert logs_dir.exists()
    # Emit a log and ensure no exception
    logger = logging.getLogger("test_logger")
    logger.info("hello world")
    # File should have been created (rolling handler)
    files = list(logs_dir.glob("app.log*"))
    assert files, "Expected at least one log file created"
