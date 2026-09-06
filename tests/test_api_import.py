import importlib


def test_pipeline_api_imports():
    mod = importlib.import_module("pipeline.api")
    assert hasattr(mod, "app")
