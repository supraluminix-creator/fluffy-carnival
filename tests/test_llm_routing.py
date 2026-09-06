import pytest

from integrations.ai_provider import LLMConfig, LLMUsageHistory, get_llm_route


@pytest.mark.parametrize(
    "grok_calls, deepseek_calls, expected_first",
    [
        (4, 2, "grok"),
        (5, 1, "deepseek"),
        (6, 0, "deepseek"),
    ],
)
def test_get_llm_route_sentiment_threshold(tmp_path, grok_calls, deepseek_calls, expected_first):
    history = LLMUsageHistory(path=tmp_path / "history.json", window=10)
    config = LLMConfig(primary="grok", backup="deepseek", alternates=["perplexity"], quota_threshold=0.8)
    for _ in range(grok_calls):
        history.record("grok", "sentiment")
    for _ in range(deepseek_calls):
        history.record("deepseek", "sentiment")

    route = get_llm_route("sentiment", config, history)
    assert route[0] == expected_first
    assert "mock" in route
