def test_is_llm_post_facade_enabled_default(monkeypatch):
    from pipeline.flags import is_llm_post_facade_enabled

    monkeypatch.delenv("FORCE_HTTP_FACADE", raising=False)
    monkeypatch.delenv("LLM_USE_HTTP_FACADE_POST", raising=False)
    monkeypatch.delenv("AI_USE_HTTP_FACADE_POST", raising=False)
    assert is_llm_post_facade_enabled() is False


def test_is_llm_post_facade_enabled_force(monkeypatch):
    from pipeline.flags import is_llm_post_facade_enabled

    monkeypatch.setenv("FORCE_HTTP_FACADE", "1")
    monkeypatch.delenv("LLM_USE_HTTP_FACADE_POST", raising=False)
    monkeypatch.delenv("AI_USE_HTTP_FACADE_POST", raising=False)
    assert is_llm_post_facade_enabled() is True


def test_is_llm_post_facade_enabled_llm_flag(monkeypatch):
    from pipeline.flags import is_llm_post_facade_enabled

    monkeypatch.delenv("FORCE_HTTP_FACADE", raising=False)
    monkeypatch.setenv("LLM_USE_HTTP_FACADE_POST", "1")
    monkeypatch.delenv("AI_USE_HTTP_FACADE_POST", raising=False)
    assert is_llm_post_facade_enabled() is True


def test_is_llm_post_facade_enabled_ai_flag(monkeypatch):
    from pipeline.flags import is_llm_post_facade_enabled

    monkeypatch.delenv("FORCE_HTTP_FACADE", raising=False)
    monkeypatch.delenv("LLM_USE_HTTP_FACADE_POST", raising=False)
    monkeypatch.setenv("AI_USE_HTTP_FACADE_POST", "1")
    assert is_llm_post_facade_enabled() is True
