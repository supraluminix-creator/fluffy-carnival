from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from integrations.x_adapter import _parse_watchlist, get_curated_feed, write_export  # type: ignore


async def main() -> int:
    enabled = os.environ.get("X_ENABLED", "0") in {"1", "true", "yes", "on"}
    if not enabled:
        print("X adapter disabled (set X_ENABLED=1)")
        return 0
    token = os.environ.get("X_BEARER_TOKEN") or os.environ.get("TWITTER_BEARER_TOKEN")
    if not token:
        print("Missing X_BEARER_TOKEN (or TWITTER_BEARER_TOKEN)")
        return 1
    wl = _parse_watchlist(os.environ.get("X_WATCHLIST"))
    if not wl:
        print("Empty X_WATCHLIST — nothing to query")
        return 0
    limit = int(os.environ.get("X_LIMIT", "50"))
    force = os.environ.get("X_FORCE_REFRESH", "0") in {"1", "true", "yes", "on"}

    data = await get_curated_feed(watchlist=wl, limit=limit, force_refresh=force)
    out = write_export(data, out_dir=os.environ.get("X_EXPORT_DIR", "exports/social"), name="latest_x_curated.json")
    print(f"Wrote {out} (items={len(data.get('items') or [])})")

    # Ecrire une empreinte de fraicheur (mode feed/retweeters) pour monitoring simple
    try:
        mode = str((data.get("meta") or {}).get("mode") or "feed")
        stamp = {
            "ts": int(time.time()),
            "mode": mode,
            "items": len(data.get("items") or []),
            "export": out.replace("\\", "/"),
        }
        meta = data.get("meta") or {}
        for k in ("selected_token", "quota_app_next_ts"):
            if k in meta:
                stamp[k] = meta[k]
        dest = Path("run") / "social"
        dest.mkdir(parents=True, exist_ok=True)
        (dest / f"last_success_{mode}.json").write_text(
            json.dumps(stamp, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        # Ne pas faire echouer le rafraichissement pour un souci d'I/O annexe
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
