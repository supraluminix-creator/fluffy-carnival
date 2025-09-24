import pytest

from pipeline.base_collector import BaseCollector


def test_base_collector_not_implemented():
    class C(BaseCollector):
        pass
    with pytest.raises(NotImplementedError):
        C().collect(None)
from pipeline.base_collector import BaseCollector
import pytest

def test_base_collector_not_implemented():
    class Dummy(BaseCollector):
        pass
    with pytest.raises(NotImplementedError):
        Dummy().collect(None)
