import pytest

from pipeline.config import get_config, get_env_bool, get_env_int, get_env_list, get_env_str, refresh_config_cache


def test_get_env_bool(monkeypatch):
    monkeypatch.setenv("FLAG_X", "TrUe")
    assert get_env_bool("FLAG_X") is True
    monkeypatch.setenv("FLAG_X", "off")
    assert get_env_bool("FLAG_X") is False


def test_get_env_int_bounds(monkeypatch):
    monkeypatch.setenv("LIMIT", "5")
    assert get_env_int("LIMIT", 1, min_value=1, max_value=10) == 5
    monkeypatch.setenv("LIMIT", "0")
    with pytest.raises(ValueError):
        get_env_int("LIMIT", 1, min_value=1)


def test_get_env_list(monkeypatch):
    monkeypatch.setenv("LIST_VAL", "a, b , ,c")
    assert get_env_list("LIST_VAL") == ["a", "b", "c"]


def test_get_env_str_required(monkeypatch):
    with pytest.raises(ValueError):
        get_env_str("MISSING_X", required=True)


def test_get_config_cached(monkeypatch):
    refresh_config_cache()
    monkeypatch.setenv("CRYPTO_MONITOR_MODE", "worker")
    cfg1 = get_config()
    monkeypatch.setenv("CRYPTO_MONITOR_MODE", "ignored_change")
    cfg2 = get_config()
    assert cfg1 is cfg2  # cache effect
    refresh_config_cache()
    cfg3 = get_config()
    assert cfg3 is not cfg1
