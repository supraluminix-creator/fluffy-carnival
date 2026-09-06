from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from integrations.grok_adapter import get_social_signals


def _assets_from_env() -> list[str]:
    raw = os.environ.get("GROK_ASSETS", "BTC,ETH")
    return [x.strip() for x in raw.split(",") if x.strip()]


async def main() -> int:
    assets = _assets_from_env()
    window = os.environ.get("GROK_WINDOW", "1h")
    limit = int(os.environ.get("GROK_LIMIT", "50"))
    force = os.environ.get("GROK_FORCE", "0") in {"1", "true", "yes"}

    payload = await get_social_signals(assets, window=window, limit=limit, force=force)
    out_dir = Path("exports") / "social"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"latest_grok_{window}.json"
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
