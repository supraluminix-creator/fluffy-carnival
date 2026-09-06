from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import suppress
from typing import Any

import httpx

try:  # optional: load local env
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover - optional dep
    load_dotenv = None  # type: ignore


def _stream_sse(url: str, headers: dict[str, str], data: dict) -> tuple[int, Any, Iterator[str]]:
    """Returns (status_code, headers, line iterator). Raises on network errors."""
    # Give enough time for the backend to call the LLM before streaming chunks
    r_ctx = httpx.stream("POST", url, headers=headers, json=data, timeout=30.0)
    r = r_ctx.__enter__()
    try:
        return r.status_code, r.headers, r.iter_lines()
    except Exception:
        r_ctx.__exit__(*sys.exc_info())
        raise


def main() -> int:
    # Load .env and .env.local to get API_WRITE_KEY, provider keys, etc.
    if load_dotenv is not None:
        with suppress(Exception):
            load_dotenv()
            from pathlib import Path

            env_local = Path(".env.local")
            if env_local.exists():
                load_dotenv(env_local, override=True)

    # Bind on a testing port; auto-increment on conflict or slow boot
    base_port = int(os.getenv("SMOKE_API_PORT", "9322"))
    attempts = int(os.getenv("SMOKE_API_PORT_ATTEMPTS", "3"))
    ok = False
    last_proc: subprocess.Popen | None = None
    last_base = ""
    for i in range(attempts):
        port = base_port + i
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
        last_proc = proc
        base = f"http://127.0.0.1:{port}"
        last_base = base
        # Wait up to ~30s for readiness
        for _ in range(120):
            if proc.poll() is not None:
                break  # crashed, try next port
            try:
                r = httpx.get(base + "/api/llm/status", timeout=0.3)
                if r.status_code == 200:
                    ok = True
                    break
            except Exception:
                # Fallback check on /api
                try:
                    r2 = httpx.get(base + "/api", timeout=0.3)
                    if r2.status_code == 200:
                        ok = True
                        break
                except Exception:
                    pass
            time.sleep(0.25)
        if ok:
            break
        # Not ok, terminate and try next port
        with suppress(Exception):
            proc.terminate()
            proc.wait(timeout=3)

    if not ok:
        return 1

    # Optional: exercise POST endpoints if API_WRITE_KEY is provided
    proc = last_proc  # type: ignore[assignment]
    base = last_base
    api_key = os.getenv("API_WRITE_KEY", "")
    if api_key:
        headers = {"Content-Type": "application/json", "X-API-KEY": api_key}
        # Generate
        # Request fewer tokens to speed up generation and allow a longer timeout
        rg = httpx.post(
            base + "/api/llm/generate",
            headers=headers,
            json={"prompt": "ping", "max_tokens": 64, "temperature": 0.0},
            timeout=20.0,
        )
        if rg.status_code != 200:
            return 2
        # Basic header assertions
        for h in ("X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"):
            if h not in rg.headers:
                return 3

        # SSE stream
        scode, sheaders, lines = _stream_sse(
            base + "/api/llm/stream", headers, {"prompt": "hello stream", "max_tokens": 64, "temperature": 0.0}
        )
        if scode != 200:
            return 4
        for h in ("X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"):
            if h not in sheaders:
                return 5
        # Read a few lines to ensure content streams
        got_line = False
        max_lines = 5
        try:
            for i, ln in enumerate(lines):
                if ln:
                    got_line = True
                if i >= max_lines:
                    break
        except Exception as e:  # tolerate normal stream closure
            try:
                from httpx import StreamClosed  # type: ignore

                if not isinstance(e, StreamClosed):
                    raise
            except Exception:
                # If httpx.StreamClosed is not available, ignore generic errors here
                pass
        if not got_line:
            return 6

    rc = 0
    if last_proc is not None:
        with suppress(Exception):
            last_proc.terminate()
            last_proc.wait(timeout=5)
        if last_proc.poll() is None:
            with suppress(Exception):
                last_proc.kill()
                last_proc.wait(timeout=2)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
