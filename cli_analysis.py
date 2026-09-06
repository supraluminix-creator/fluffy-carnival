#!/usr/bin/env python3
"""CLI minimal pour lancer une analyse AI et/ou générer des indicateurs.

Usage (PowerShell):
    # Analyse AI classique
    .\\.venv\Scripts\python.exe cli_analysis.py

    # Génération d'indicateurs (CSV)
    .\\.venv\Scripts\python.exe cli_analysis.py indicators `
            --symbol BTCUSDT --interval 1h --limit 300 `
            --source synthetic `
            --indicators rsi,ema,macd,bbands,atr,stoch,adx,cci,roc,obv,adl,kc

    # Génération d'indicateurs (Parquet, binance avec retry/fallback géré côté outil)
    .\\.venv\Scripts\python.exe cli_analysis.py indicators `
            --symbol BTCUSDT --interval 1h --limit 300 `
            --source binance --out-format parquet `
            --binance-timeout 10 --binance-retries 2 `
            --indicators rsi,ema,macd,bbands,atr,stoch,adx,cci,roc,obv,adl,kc

Variables d'environnement utiles:
    ANALYSIS_ONLY_ON_SIGNALS=1   # ne persiste que s'il y a des signaux
    OPENAI_API_KEY / OPENROUTER_API_KEY / OLLAMA_HOST pour providers
"""
from __future__ import annotations

import os

from pipeline.analysis.persist import save_analysis
from pipeline.analysis.runner import run_automatic_analyses
from tools.generate_indicators_csv import generate_indicators_csv


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Analyse AI et utilitaires")
    sub = parser.add_subparsers(dest="cmd")

    p_ind = sub.add_parser("indicators", help="Génère un fichier d'indicateurs techniques (CSV/Parquet)")
    p_ind.add_argument("--symbol", default="BTCUSDT")
    p_ind.add_argument("--interval", default="1h")
    p_ind.add_argument("--limit", type=int, default=300)
    p_ind.add_argument("--source", choices=["binance", "synthetic"], default="synthetic")
    p_ind.add_argument("--indicators", default="rsi,ema,macd,bbands,atr,stoch,adx,cci,roc,obv,adl,kc")
    p_ind.add_argument("--out-dir", default="exports/indicators")
    p_ind.add_argument("--filename", default=None)
    p_ind.add_argument("--out-format", choices=["csv", "parquet"], default="csv")
    p_ind.add_argument("--binance-timeout", type=float, default=10.0)
    p_ind.add_argument("--binance-retries", type=int, default=2)

    args = parser.parse_args()

    if args.cmd == "indicators":
        inds = [s.strip() for s in str(args.indicators).split(",") if s.strip()]
        res = generate_indicators_csv(
            symbol=args.symbol,
            interval=args.interval,
            limit=args.limit,
            source=args.source,
            indicators=inds,
            out_dir=args.out_dir,
            filename=args.filename,
            out_format=args.out_format,
            binance_timeout=args.binance_timeout,
            binance_retries=args.binance_retries,
        )
        # Impression JSON compacte
        import json as _json

        print(_json.dumps(res, indent=2))
        return

    # Mode analyse AI par défaut
    export_path = os.path.join("exports", "latest_export.csv")
    out = run_automatic_analyses(export_path)
    only_on_signals = os.getenv("ANALYSIS_ONLY_ON_SIGNALS", "0") == "1"
    if (not only_on_signals) or out.get("signals"):
        save_analysis(out, "exports")
    print("analysis_status=", out.get("status"))
    if out.get("signals"):
        print("signals=", out["signals"])
    print("insight=", (out.get("insight") or "").strip())


if __name__ == "__main__":
    main()
