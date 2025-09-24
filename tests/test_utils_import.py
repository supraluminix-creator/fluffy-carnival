def test_import_utils():
    import importlib
    import pipeline.utils  # noqa: F401
    # Forcer un reload pour exécuter éventuels top-level (idempotent)
    importlib.reload(pipeline.utils)
    assert True
