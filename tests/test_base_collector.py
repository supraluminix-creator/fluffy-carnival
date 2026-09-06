import pytest

from pipeline.base_collector import BaseCollector


class DummyCollector(BaseCollector):
    def collect(self, conn):
        return f"ok:{conn}"


def test_base_collector_not_implemented():
    b = BaseCollector()
    with pytest.raises(NotImplementedError):
        b.collect(None)


def test_dummy_collector():
    d = DummyCollector()
    assert d.collect("X") == "ok:X"
