from __future__ import annotations

import os
from contextlib import suppress

from fastapi.testclient import TestClient

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover
    load_dotenv = None  # type: ignore


def main() -> int:
    # Load env first, then force deepseek-only before importing the app
    if load_dotenv is not None:
        with suppress(Exception):
            load_dotenv()
            if os.path.exists(".env.local"):
                load_dotenv(".env.local", override=True)

    # Force provider selection if not explicitly set
    os.environ.setdefault("API_LLM_ONLY", "deepseek")

    # Import app after env is ready so the global LLM client is built accordingly
    from pipeline.api import app  # noqa: WPS433 (import after env setup)

    client = TestClient(app)

    # 1) Status
    r = client.get("/api/llm/status")
    if r.status_code != 200:
        print("status_failed", r.status_code, r.text)
        return 1

    # 2) Generate (optional, requires API_WRITE_KEY)
    api_key = os.getenv("API_WRITE_KEY", "")
    if api_key:
        headers = {"X-API-KEY": api_key}
        rg = client.post(
            "/api/llm/generate", json={"prompt": "ping", "max_tokens": 64, "temperature": 0.0}, headers=headers
        )
        if rg.status_code != 200:
            print("generate_failed", rg.status_code, rg.text)
            return 2
        data = rg.json()
        if "output" not in data:
            print("generate_no_output", data)
            return 3

        # 3) Stream SSE
        with client.stream(
            "POST",
            "/api/llm/stream",
            json={"prompt": "hello stream", "max_tokens": 64, "temperature": 0.0},
            headers=headers,
        ) as resp:
            if resp.status_code != 200:
                print("stream_failed", resp.status_code, resp.text)
                return 4
            # read a few lines
            got = False
            for i, ln in enumerate(resp.iter_lines()):
                if ln:
                    got = True
                if i >= 5:
                    break
            if not got:
                print("stream_no_lines")
                return 5

    print("smoke_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
