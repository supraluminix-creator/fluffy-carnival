from __future__ import annotations

from unittest.mock import patch

from pipeline.collectors.coinmarketcap_cycle import CMCCycleOptions, fetch_cmc_cycle_indicators


def test_cmc_cycle_api_first_then_scrape_fallback(monkeypatch) -> None:
    # Mock API success
    api_payload = {
        "data": {
            "indicators": [
                {
                    "name": "Puell Multiple",
                    "status": "undervalued",
                    "value": 0.47,
                    "thresholds": {"low": 0.5, "high": 1.8},
                }
            ]
        }
    }
    with patch("pipeline.collectors.coinmarketcap_cycle.fetch_json", return_value=api_payload):
        items = fetch_cmc_cycle_indicators(CMCCycleOptions(cache_ttl=1))
        assert items and items[0]["indicator"] == "Puell Multiple"
        assert items[0]["status"] == "undervalued"
        assert items[0]["source"] == "api"


def test_cmc_cycle_scrape_fallback_when_api_fails(monkeypatch) -> None:
    # Mock API None, then scraper returns indicators
    with patch("pipeline.collectors.coinmarketcap_cycle.fetch_json", side_effect=Exception("boom")), patch(
        "httpx.Client.get"
    ) as mock_get:

        class _Resp:
            status_code = 200
            text = '<html><script id="__NEXT_DATA__">{"props":{"pageProps":{"initialState":{"charts":{"cryptoMarketCycleIndicators":{"data":{"indicators":[{"name":"Pi Cycle","status":"neutral","value":1.2,"thresholds":{"low":0.8,"high":2.0}}]}}}}}}}</script></html>'

        mock_get.return_value = _Resp()
        items = fetch_cmc_cycle_indicators(CMCCycleOptions(cache_ttl=1))
        assert items and items[0]["indicator"] == "Pi Cycle"
        assert items[0]["source"] == "scraper"
