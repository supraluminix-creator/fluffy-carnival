"""Lightweight smoke test for the rumour collector."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from pipeline.collectors.rumour_collector import fetch_rumour_trending


async def _run() -> None:
    records = await fetch_rumour_trending(limit=5)
    if not records:
        print("No rumour data available (collector disabled or offline)")
        return
    print(f"Fetched {len(records)} rumour narratives:")
    for rec in records:
        topic = rec.get("topic")
        sentiment = rec.get("sentiment")
        confidence = rec.get("confidence")
        print(f" - {topic} | sentiment={sentiment} | confidence={confidence}")
    snapshot = Path("exports/rumour_latest.json")
    if snapshot.exists():
        print(f"Snapshot saved to {snapshot}")
        try:
            data = json.loads(snapshot.read_text(encoding="utf-8"))
            print(f"Snapshot summary: {list(data.keys())}")
        except Exception:
            print("Snapshot present but could not parse JSON")


if __name__ == "__main__":
    asyncio.run(_run())
