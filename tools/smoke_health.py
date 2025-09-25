from __future__ import annotations

import subprocess
import sys
import time
from contextlib import suppress

import httpx


def main() -> int:
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "api.health:app",
        "--host",
        "127.0.0.1",
        "--port",
        "9310",
        "--log-level",
        "warning",
    ]
    proc = subprocess.Popen(cmd)
    try:
        url = "http://127.0.0.1:9310/health"
        ok = False
        for _ in range(40):  # ~10s max
            try:
                r = httpx.get(url, timeout=0.25)
                if r.status_code == 200:
                    ok = True
                    break
            except Exception:
                pass
            time.sleep(0.25)
        return 0 if ok else 1
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
