from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

from pipeline.collectors.coinmarketcap_cycle import CMCCycleOptions, fetch_cmc_cycle_indicators

# Racine du repo par défaut (fallback). Peut être surchargée lorsque l'utilisateur
# écrit dans un dossier export différent (ex: tests temporaires).
_DEFAULT_REPO_ROOT = Path(__file__).resolve().parent.parent


def _append_manifest(record: dict[str, Any], *, exports_dir: Path | None = None) -> None:
    """Append une ligne JSON dans <exports_dir>/indicators/cmc_cycle_manifest.jsonl.

    Ne lève pas d'exception (meilleure robustesse CLI). Crée les dossiers au besoin.
    """
    try:
        base_dir = exports_dir or (_DEFAULT_REPO_ROOT / "exports")
        mani_dir = base_dir / "indicators"
        mani_dir.mkdir(parents=True, exist_ok=True)
        mani_path = mani_dir / "cmc_cycle_manifest.jsonl"
        with mani_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        # Best-effort: pas de crash si FS non accessible
        pass


def main() -> int:
    p = argparse.ArgumentParser(description="Dump CoinMarketCap Crypto Market Cycle Indicators")
    p.add_argument("--format", choices=["json", "csv"], default="json")
    p.add_argument("--out", default=None, help="Output file path (default prints to stdout)")
    p.add_argument("--no-cache", action="store_true", help="Disable cache read (CMC_CYCLE_CACHE_DISABLE=1)")
    p.add_argument("--ttl", type=int, default=None, help="Cache TTL seconds (default 3600 or env)")
    args = p.parse_args()

    opts = CMCCycleOptions()
    if args.ttl is not None:
        opts.cache_ttl = int(args.ttl)

    if args.no_cache:
        import os

        os.environ["CMC_CYCLE_CACHE_DISABLE"] = "1"

    items = fetch_cmc_cycle_indicators(opts)
    count = len(items)

    if args.format == "json":
        payload = {"status": "ok", "count": len(items), "items": items}
        text = json.dumps(payload, indent=2)
        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(text, encoding="utf-8")
            # Écrit une ligne de manifeste pour traçabilité
            _append_manifest(
                {
                    "schema_version": 1,
                    "format": "json",
                    "path": out_path.as_posix(),
                    "count": count,
                    "created_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
                },
                exports_dir=out_path.parent,
            )
        else:
            print(text)
        return 0

    # CSV
    headers = ["indicator", "status", "value", "thresholds", "source"]
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=headers)
            w.writeheader()
            for it in items:
                row = {
                    "indicator": it.get("indicator"),
                    "status": it.get("status"),
                    "value": it.get("value"),
                    "thresholds": json.dumps(it.get("thresholds")),
                    "source": it.get("source"),
                }
                w.writerow(row)
        # Manifeste CSV
        _append_manifest(
            {
                "schema_version": 1,
                "format": "csv",
                "path": out_path.as_posix(),
                "count": count,
                "created_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            },
            exports_dir=out_path.parent,
        )
    else:
        writer = csv.DictWriter(sys.stdout, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        for it in items:
            row = {
                "indicator": it.get("indicator"),
                "status": it.get("status"),
                "value": it.get("value"),
                "thresholds": json.dumps(it.get("thresholds")),
                "source": it.get("source"),
            }
            writer.writerow(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
