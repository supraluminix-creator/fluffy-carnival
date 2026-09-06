"""
Génère un prompt Markdown à partir d'un fichier JSON de métriques (produit par collect.py).

Exemples:
  python auto_prompter.py data/metrics.json --out exports/analysis/prompt_analysis.md --title "Analyse BTC/ETH"
  python auto_prompter.py data/metrics.json --stdout
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any


def human_ts(ts: int | None) -> str:
    try:
        if ts is None:
            return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        return datetime.fromtimestamp(int(ts), tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def make_prompt(rows: list[dict[str, Any]], title: str | None = None) -> str:
    if not rows:
        return "# Analyse crypto\n\nAucune donnée.\n"
    # Grouper par symbol
    by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        sym = str(r.get("symbol", "")).upper()
        if sym:
            by_sym[sym].append(r)

    # Trouver date max
    ts_vals: list[int | float] = []
    for row in rows:
        ts_val = row.get("timestamp")
    if isinstance(ts_val, int | float):
            ts_vals.append(ts_val)
    last_ts = int(max(ts_vals)) if ts_vals else None
    header = title or f"Analyse – Données du {human_ts(last_ts)}"

    lines: list[str] = [f"# {header}", ""]
    for sym in sorted(by_sym.keys()):
        lines.append(f"## {sym}")
        mrows = by_sym[sym]
        # Regrouper métriques clés
        price = next((r for r in mrows if r.get("metric") == "price_usd"), None)
        chg = next((r for r in mrows if r.get("metric") == "change_24h_pct"), None)
        fr = next((r for r in mrows if r.get("metric") == "funding_rate"), None)
        sent = next((r for r in mrows if r.get("metric") == "sentiment"), None)

        if price is not None:
            lines.append(f"- Prix (USD): {price.get('value')}")
        if chg is not None:
            lines.append(f"- Variation 24h (%): {round(float(chg.get('value', 0)), 3)}")
        if fr is not None:
            lines.append(f"- Funding Rate: {fr.get('value')}")
        if sent is not None:
            lines.append(f"- Sentiment: {sent.get('value')}")
        lines.append("")

    lines.append(
        "> Question: Quelle tendance technique et de flux (OI/funding) se dégage, "
        "et quels scénarios probables à 24-72h ?"
    )
    lines.append("")
    lines.append("(Coller ce prompt dans l'IA de votre choix via le bookmarklet.)")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Générateur de prompt Markdown pour analyses IA")
    p.add_argument("input", type=str, help="fichier JSON (rows)")
    p.add_argument("--out", type=str, default="", help="chemin du fichier Markdown de sortie")
    p.add_argument("--title", type=str, default="", help="titre personnalisé")
    p.add_argument("--stdout", action="store_true", help="écrit le résultat dans la sortie standard")
    args = p.parse_args(argv)

    with open(args.input, encoding="utf-8") as f:
        rows = json.load(f)
    if not isinstance(rows, list):
        raise SystemExit("Format JSON invalide: attendu une liste de lignes")

    prompt = make_prompt(rows, title=(args.title or None))

    if args.stdout or not args.out:
        sys.stdout.write(prompt)
    else:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(prompt)
        print(json.dumps({"status": "ok", "out": args.out}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
