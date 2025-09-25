from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import suppress

import httpx


def _stream_sse(url: str, headers: dict[str, str], data: dict) -> tuple[int, dict, Iterator[str]]:
    """Returns (status_code, headers, line iterator). Raises on network errors."""
    r_ctx = httpx.stream("POST", url, headers=headers, json=data, timeout=5.0)
    r = r_ctx.__enter__()
    try:
        return r.status_code, r.headers, r.iter_lines()
    except Exception:
        r_ctx.__exit__(*sys.exc_info())
        raise


def main() -> int:
    # Bind on ephemeral testing port to avoid conflicts
    port = int(os.getenv("SMOKE_API_PORT", "9322"))
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "pipeline.api:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    proc = subprocess.Popen(cmd)
    try:
        base = f"http://127.0.0.1:{port}"
        ok = False
        for _ in range(60):  # ~15s max
            try:
                r = httpx.get(base + "/api/llm/status", timeout=0.25)
                if r.status_code == 200:
                    ok = True
                    break
            except Exception:
                pass
            time.sleep(0.25)
        if not ok:
            return 1

        # Optional: exercise POST endpoints if API_WRITE_KEY is provided
        api_key = os.getenv("API_WRITE_KEY", "")
        if api_key:
            headers = {"Content-Type": "application/json", "X-API-KEY": api_key}
            # Generate
            rg = httpx.post(base + "/api/llm/generate", headers=headers, json={"prompt": "ping"}, timeout=3.0)
            if rg.status_code != 200:
                return 2
            # Basic header assertions
            for h in ("X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"):
                if h not in rg.headers:
                    return 3

            # SSE stream
            scode, sheaders, lines = _stream_sse(base + "/api/llm/stream", headers, {"prompt": "hello stream"})
            if scode != 200:
                return 4
            for h in ("X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"):
                if h not in sheaders:
                    return 5
            # Read a few lines to ensure content streams
            got_line = False
            max_lines = 5
            for i, ln in enumerate(lines):
                if ln:
                    got_line = True
                if i >= max_lines:
                    break
            if not got_line:
                return 6

        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
            with suppress(Exception):
                proc.wait(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
