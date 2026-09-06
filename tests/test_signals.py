from __future__ import annotations

import pandas as pd

from pipeline.analysis.signals import detect_signals


def test_detect_signals_handles_rumour_records() -> None:
	df = pd.DataFrame(
		[
			{
				"metric_name": "rumour_sentiment",
				"value": 0.72,
				"topic": "AI tokens",
				"sentiment": "positive",
				"confidence": 0.82,
			},
			{
				"metric_name": "rumour_sentiment",
				"value": 0.7,
				"topic": "AI tokens",
				"sentiment": "positive",
				"confidence": 0.78,
			},
		]
	)

	out = detect_signals(df)

	assert any(sig.get("type") == "narrative_buy_signal" for sig in out)


def test_detect_signals_rumour_sell_trigger() -> None:
	df = pd.DataFrame(
		[
			{
				"metric_name": "rumour_sentiment",
				"value": -0.7,
				"topic": "ETF hype",
				"sentiment": "negative",
				"confidence": 0.75,
			},
			{
				"metric_name": "rumour_sentiment",
				"value": -0.65,
				"topic": "ETF hype",
				"sentiment": "negative",
				"confidence": 0.73,
			},
		]
	)

	out = detect_signals(df)

	assert any(sig.get("type") == "narrative_sell_signal" for sig in out)
