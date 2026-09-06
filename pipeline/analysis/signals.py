"""Détection de signaux simples et robustes (MVP).

Renvoie une liste de signaux (dict) prêts pour consommation par un moteur d'analyse/LLM.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

Signal = dict[str, Any]


def detect_signals(df: pd.DataFrame) -> list[Signal]:
    signals: list[Signal] = []
    cols = set(df.columns)
    if not {"metric_name", "value"}.issubset(cols):
        return signals

    # Heuristique Long/Short Ratio (Bybit)
    lsr = df[df["metric_name"].str.contains("lsr|long_short_ratio", case=False, na=False)]
    if not lsr.empty:
        latest = lsr.iloc[-1]
        val = float(latest.get("value", 0.0) or 0.0)
        if val > 0.6:
            signals.append(
                {
                    "type": "derivatives_lsr_bullish",
                    "severity": "info" if val < 0.7 else "warn",
                    "value": val,
                    "msg": f"Long/Short ratio élevé ({val:.2f})",
                }
            )
        elif val < 0.4:
            signals.append(
                {
                    "type": "derivatives_lsr_bearish",
                    "severity": "info" if val > 0.3 else "warn",
                    "value": val,
                    "msg": f"Long/Short ratio faible ({val:.2f})",
                }
            )

    # Heuristique Fear & Greed
    fg = df[df["metric_name"].str.contains("fear|greed", case=False, na=False)]
    if not fg.empty:
        latest = fg.iloc[-1]
        val = float(latest.get("value", 0.0) or 0.0)
        if val <= 20:
            signals.append({"type": "sentiment_extreme_fear", "severity": "warn", "value": val})
        elif val >= 80:
            signals.append({"type": "sentiment_extreme_greed", "severity": "warn", "value": val})

    # Heuristique Open Interest (delta simple)
    oi = df[df["metric_name"].str.contains("open_interest|oi", case=False, na=False)]
    if len(oi) >= 2:
        last2 = oi.tail(2)["value"].astype(float).tolist()
        delta = last2[-1] - last2[-2]
        if abs(delta) / max(1.0, last2[-2]) > 0.05:  # >5%
            signals.append(
                {
                    "type": "derivatives_oi_jump",
                    "severity": "info",
                    "delta": delta,
                    "msg": f"Variation OI ~ {delta:+.1f}",
                }
            )

    # Heuristique TVL Defi (delta simple)
    tvl = df[df["metric_name"].str.contains("tvl", case=False, na=False)]
    if len(tvl) >= 2:
        last2 = tvl.tail(2)["value"].astype(float).tolist()
        delta = last2[-1] - last2[-2]
        if abs(delta) / max(1.0, last2[-2]) > 0.03:  # >3%
            signals.append(
                {"type": "defi_tvl_change", "severity": "info", "delta": delta, "msg": f"Variation TVL ~ {delta:+.1f}"}
            )

    if {"topic", "sentiment", "confidence"}.issubset(cols):
        rumour = df[df["metric_name"].str.contains("rumour", case=False, na=False)]
        if not rumour.empty:
            try:
                rumour = rumour.copy()
                rumour["value_float"] = rumour["value"].astype(float)
                rumour["confidence_float"] = rumour["confidence"].astype(float)
            except Exception:
                rumour["value_float"] = 0.0
                rumour["confidence_float"] = 0.0
            grouped = rumour.groupby(rumour["topic"].fillna("narrative"))
            for topic, grp in grouped:
                avg_conf = float(grp["confidence_float"].mean()) if not grp.empty else 0.0
                avg_intensity = float(grp["value_float"].mean()) if not grp.empty else 0.0
                if avg_conf <= 0:
                    continue
                sentiment_modes = grp["sentiment"].dropna().astype(str)
                sentiment_label = sentiment_modes.iloc[-1] if not sentiment_modes.empty else "neutral"
                note = "NFA: Based on unverified narratives."
                payload = {
                    "topic": topic,
                    "confidence": round(avg_conf, 3),
                    "intensity": round(avg_intensity, 4),
                    "sentiment": sentiment_label,
                    "note": note,
                }
                if avg_intensity >= 0.6:
                    severity = "warn" if avg_intensity >= 0.8 else "info"
                    signals.append(
                        {
                            "type": "narrative_buy_signal",
                            "severity": severity,
                            "msg": f"Narrative momentum up on {topic}",
                            **payload,
                        }
                    )
                elif avg_intensity <= -0.6:
                    severity = "warn" if avg_intensity <= -0.8 else "info"
                    signals.append(
                        {
                            "type": "narrative_sell_signal",
                            "severity": severity,
                            "msg": f"Narrative momentum down on {topic}",
                            **payload,
                        }
                    )

    return signals
