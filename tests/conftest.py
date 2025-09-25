from collections.abc import Iterator

import pytest
from diskcache import Cache


@pytest.fixture(autouse=True)
def clear_global_caches() -> Iterator[None]:
    """
    Ensure disk-based caches used by collectors do not leak state across tests.
    This avoids false positives/negatives when tests rely on specific HTTP behavior.
    """
    for path in [".cache", ".cache_txcount"]:
        try:
            cache: Cache = Cache(path)
            cache.clear()
            cache.close()
        except Exception:
            # Ignore cache errors; tests should still proceed
            pass
    yield
    # Optionally clear again after test
    for path in [".cache", ".cache_txcount"]:
        try:
            cache = Cache(path)
            cache.clear()
            cache.close()
        except Exception:
            pass
