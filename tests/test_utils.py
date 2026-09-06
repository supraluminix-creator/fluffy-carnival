from pipeline.utils import to_float


def test_to_float_success():
    assert to_float("1.25") == 1.25


def test_to_float_default_on_error():
    assert to_float("xyz", default=7.0) == 7.0
    assert to_float(None) == 0.0
