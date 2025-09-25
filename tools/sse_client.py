from __future__ import annotations

import argparse
import os
from collections.abc import Iterator

import httpx


def stream_sse(url: str, headers: dict[str, str], data: dict) -> Iterator[str]:
    with httpx.stream("POST", url, headers=headers, json=data, timeout=10.0) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            yield line


def main() -> int:
    ap = argparse.ArgumentParser(description="Tiny SSE client for /api/llm/stream")
    ap.add_argument("--host", default="127.0.0.1", help="Host (default 127.0.0.1)")
    ap.add_argument("--port", type=int, default=8000, help="Port (default 8000)")
    ap.add_argument("--key", default=os.getenv("API_WRITE_KEY", ""), help="X-API-KEY value (or env API_WRITE_KEY)")
    ap.add_argument("--prompt", default="hello stream from python", help="Prompt to send")
    args = ap.parse_args()

    base = f"http://{args.host}:{args.port}"
    url = base + "/api/llm/stream"
    headers = {"Content-Type": "application/json"}
    if args.key:
        headers["X-API-KEY"] = args.key

    try:
        for ln in stream_sse(url, headers, {"prompt": args.prompt}):
            print(ln)
        return 0
    except httpx.HTTPStatusError as e:
        print(f"HTTP {e.response.status_code}: {e.response.text}")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
