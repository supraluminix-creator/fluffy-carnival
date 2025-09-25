import pytest

from pipeline.errors import (
    EmptyDataError,
    NetworkError,
    NotFoundError,
    RateLimitError,
    SchemaError,
    TimeoutError_,
    UpstreamError,
    classify,
)


class DummyTimeout(Exception):
    pass

@pytest.mark.parametrize('exc,expected', [
    (RateLimitError('HTTP 429'), 'rate_limit'),
    (NotFoundError('x'), 'not_found'),
    (UpstreamError('HTTP 502'), 'upstream'),
    (SchemaError('bad'), 'schema'),
    (EmptyDataError('empty'), 'empty_data'),
])
def test_direct_mapping(exc, expected):
    assert classify(exc) == expected

def test_timeout_detection():
    assert classify(TimeoutError_('timeout')) == 'timeout'

def test_network_detection():
    assert classify(NetworkError('boom')) == 'network'

def test_rate_limit_text():
    class Generic(Exception):
        pass
    assert classify(Generic('Too Many Requests')) == 'rate_limit'

def test_unknown():
    class X(Exception):
        pass
    assert classify(X('weird')) == 'unknown'
