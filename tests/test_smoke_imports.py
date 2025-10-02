import importlib

import pytest

MODULES = [
    "main",
    "pipeline.collectors.market",
    "pipeline.collectors.derivatives",
    "pipeline.collectors.defillama",
    "pipeline.collectors.bybit_liquidations",
    "pipeline.collectors.bybit_ws",
    "pipeline.exporter",
    "pipeline.reporter",
]

@pytest.mark.parametrize("mod", MODULES)
def test_smoke_import(mod):
    m = importlib.import_module(mod)
    assert m is not None
