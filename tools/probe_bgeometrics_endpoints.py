#!/usr/bin/env python3
"""Probe BGeometrics endpoints to find a working MVRV URL.

Usage (PowerShell):
  .\.venv\Scripts\python.exe tools\probe_bgeometrics_endpoints.py

Loads .env.local if present and uses BGEOMETRICS_API_KEY (Bearer) and
BGEOMETRICS_VERIFY_SSL (0/1). Follows redirects, prints status and brief body.
"""
from __future__ import annotations

import asyncio
import json
import os

import httpx
from dotenv import load_dotenv


def _shorten(body: str, n: int = 200) -> str:
    body = body.replace("\n", " ").replace("\r", " ")
    return body[:n]

async def main() -> None:
    load_dotenv(".env.local", override=True)
    api_key = os.getenv("BGEOMETRICS_API_KEY")
    verify_ssl = os.getenv("BGEOMETRICS_VERIFY_SSL", "1") == "1"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    params = {"symbol": os.getenv("MVRV_SYMBOL", "BTC")}

    urls = [
        # v1-style and variants
        "https://api.bgeometrics.com/api/v1/mvrv",
        "https://api.bgeometrics.com/api/mvrv",
        "https://api.bgeometrics.com/v1/mvrv",
        "https://charts.bgeometrics.com/api/v1/mvrv",
        "https://charts.bgeometrics.com/api/mvrv",
        "https://bgeometrics.com/api/v1/mvrv",
        "https://bgeometrics.com/api/mvrv",
        # zscore slugs
        "https://api.bgeometrics.com/api/mvrv-zscore",
        "https://api.bgeometrics.com/v1/mvrv-zscore",
        "https://bgeometrics.com/api/mvrv-zscore",
        "https://charts.bgeometrics.com/api/mvrv-zscore",
        # explicit metrics fallback
        "https://api.bgeometrics.com/api/metrics/mvrv",
        "https://bgeometrics.com/api/metrics/mvrv",
    ]

    print(f"verify_ssl={verify_ssl} api_key={'yes' if api_key else 'no'} symbol={params['symbol']}")
    async with httpx.AsyncClient(follow_redirects=True, verify=verify_ssl, timeout=15) as client:
        for u in urls:
            try:
                r = await client.get(u, headers=headers, params=params)
                try:
                    body = r.json()
                except Exception:
                    body = _shorten(r.text)
                print(json.dumps({
                    "url": u,
                    "status": r.status_code,
                    "ct": r.headers.get("content-type", ""),
                    "body": body,
                }, ensure_ascii=False))
            except Exception as e:
                print(json.dumps({"url": u, "error": str(e)}, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(main())
