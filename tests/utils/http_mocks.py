from __future__ import annotations
from typing import Any, List

class DummyResp:
    def __init__(self, payload: Any, raise_error: Exception | None = None):
        self._payload = payload
        self._err = raise_error

    def raise_for_status(self):  # pragma: no cover - trivial
        if self._err:
            raise self._err

    def json(self):  # pragma: no cover - simple
        return self._payload


class DummyAsyncClient:
    def __init__(self, responses: List[Any]):
        self._responses = list(responses)

    async def __aenter__(self):  # pragma: no cover - trivial
        return self

    async def __aexit__(self, exc_type, exc, tb):  # pragma: no cover - trivial
        return False

    async def get(self, url: str, *a, **kw):
        if not self._responses:
            raise RuntimeError("No more responses configured")
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


def make_async_client(sequence: list[Any]):  # pragma: no cover - helper
    return DummyAsyncClient(sequence)
