from pipeline.exceptions import (
    CollectorError,
    EmptyDataError,
    NetworkError,
    NotFoundError,
    RateLimitError,
    SchemaError,
    UpstreamError,
)


def test_exception_hierarchy_and_types():
    for cls, et in [
        (NetworkError, "network"),
        (RateLimitError, "rate_limit"),
        (NotFoundError, "not_found"),
        (SchemaError, "schema"),
        (EmptyDataError, "empty_data"),
        (UpstreamError, "upstream"),
    ]:
        e = cls("x")
        assert isinstance(e, CollectorError)
        assert cls.error_type == et
