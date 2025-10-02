from pipeline import errors


def test_classify_direct_subclasses():
    assert errors.classify(errors.NetworkError()) == "network"
    assert errors.classify(errors.RateLimitError()) == "rate_limit"
    assert errors.classify(errors.SchemaError()) == "schema"
    assert errors.classify(errors.TimeoutError_()) == "timeout"


def test_classify_status_code_mapping():
    class Resp:
        def __init__(self, status_code):
            self.status_code = status_code

    class Exc(Exception):
        def __init__(self, sc):
            self.response = Resp(sc)

    assert errors.classify(Exc(429)) == "rate_limit"
    assert errors.classify(Exc(404)) == "not_found"
    assert errors.classify(Exc(503)).startswith("upstream") or errors.classify(Exc(503)) == "upstream"


def test_classify_heuristics_rate_limit_patterns():
    class RateLimitExceededError(Exception):
        pass

    assert errors.classify(RateLimitExceededError()) == "rate_limit"
    assert errors.classify(Exception("Too Many Requests")) == "rate_limit"
    assert errors.classify(Exception("ratelimitexceeded")) == "rate_limit"


def test_classify_schema_and_network_and_unknown():
    class MyJSONDecodeError(Exception):
        pass

    class MyProxyConnect(Exception):
        pass

    assert errors.classify(MyJSONDecodeError()) == "schema"
    assert errors.classify(MyProxyConnect()) == "network"
    assert errors.classify(Exception("some random")) == "unknown"
