from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.analysis.snapshot import AssetSnapshot, gather_snapshots  # noqa: E402
from pipeline.assets import describe_assets  # noqa: E402

EXPORTS_DIR = REPO_ROOT / "exports"


def _format_number(value: float | None, *, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.{digits}f}"


def _format_percent(value: float | None, *, digits: int = 2, scale: float = 1.0) -> str:
    if value is None:
        return "n/a"
    return f"{value * scale:,.{digits}f}%"


def _format_snapshot_lines(asset: str, snapshot: AssetSnapshot | None) -> list[str]:
    if snapshot is None:
        return [f"- {asset}: data unavailable"]
    orderbook = snapshot.orderbook or {}
    lines = [f"- {asset}:"]
    price = _format_number(snapshot.price)
    delta = _format_percent(snapshot.price_change_24h_pct)
    market_cap = _format_number(snapshot.market_cap_usd)
    volume = _format_number(snapshot.volume_24h_usd)
    lines.append(
        f"    price={price} USD (delta_24h={delta}) | "
        f"market_cap={market_cap} USD | volume_24h={volume} USD"
    )
    oi_val = _format_number(snapshot.oi_usd)
    d1_abs = _format_number(snapshot.oi_change_1h_usd)
    d1_pct = _format_percent(snapshot.oi_change_1h_pct)
    d24_abs = _format_number(snapshot.oi_change_24h_usd)
    d24_pct = _format_percent(snapshot.oi_change_24h_pct)
    lines.append(
        f"    OI={oi_val} USD (delta_1h={d1_abs} USD / {d1_pct}, "
        f"delta_24h={d24_abs} USD / {d24_pct})"
    )
    funding = _format_percent(snapshot.funding_rate, scale=100)
    liq = _format_number(snapshot.liquidations_total_usd)
    longs = _format_number(snapshot.liquidations_long_usd)
    shorts = _format_number(snapshot.liquidations_short_usd)
    lines.append(
        f"    funding={funding} | liquidations_24h={liq} USD "
        f"(longs={longs} USD, shorts={shorts} USD)"
    )
    bids = _format_number(orderbook.get("bid_total_quote"))
    asks = _format_number(orderbook.get("ask_total_quote"))
    spread = _format_number(orderbook.get("spread"))
    spread_pct = _format_percent(orderbook.get("spread_pct"))
    lines.append(
        f"    orderbook: bids={bids} USD | asks={asks} USD | spread={spread} USD ({spread_pct})"
    )
    long_ratio = snapshot.long_short_ratio_long_pct
    short_ratio = snapshot.long_short_ratio_short_pct
    if long_ratio is not None or short_ratio is not None:
        long_fmt = _format_number(long_ratio, digits=1) if long_ratio is not None else "n/a"
        short_fmt = _format_number(short_ratio, digits=1) if short_ratio is not None else "n/a"
        lines.append(f"    long/short: longs={long_fmt}% | shorts={short_fmt}%")
    return lines


def _append_enrichment_to_prompt(lines: list[str], enrichment: dict[str, Any]) -> None:
    lines.append("")
    lines.append("Enrichment (secondary REST calls):")
    onchain = enrichment.get("onchain", {})
    if onchain:
        lines.append("- On-chain:")
        for asset, details in onchain.items():
            txcount = details.get("txcount", "n/a")
            hashrate = details.get("hashrate_btc", "n/a")
            sopr = details.get("sopr_btc", "n/a")
            lines.append(
                f"  - {asset}: txcount={txcount}, hashrate_btc={hashrate}, sopr_btc={sopr}"
            )
    sentiment = enrichment.get("sentiment")
    if sentiment:
        val = sentiment.get("value") if isinstance(sentiment, dict) else None
        cls = sentiment.get("value_classification") if isinstance(sentiment, dict) else None
        val_fmt = val if val is not None else "n/a"
        cls_fmt = cls or "n/a"
        lines.append(f"- Sentiment (Fear & Greed): value={val_fmt} ({cls_fmt})")
    cycle = enrichment.get("cycle")
    if cycle:
        top = ", ".join(cycle.get("top", []) or [])
        count = cycle.get("count", "0")
        lines.append(f"- CMC Market Cycle: {count} indicators (top: {top or 'n/a'})")
    defi = enrichment.get("defi", {})
    if defi:
        lines.append("- DeFi TVL:")
        for asset, payload in defi.items():
            tvl = _format_number(payload.get("tvl"))
            prev_day = _format_number(payload.get("tvl_prev_day"))
            prev_week = _format_number(payload.get("tvl_prev_week"))
            prev_month = _format_number(payload.get("tvl_prev_month"))
            lines.append(
                f"  - {asset}: tvl={tvl} USD | prev_day={prev_day} USD | "
                f"prev_week={prev_week} USD | prev_month={prev_month} USD"
            )


def _compose_prompt(
    assets: list[str],
    snapshots: dict[str, AssetSnapshot],
    enrichment: dict[str, Any] | None,
) -> str:
    lines: list[str] = []
    lines.append(
        "You are a crypto market analyst. Provide a structured, concise analysis with numbered sections."
    )
    lines.append(
        "Focus on clarity and actionable insights. Use the provided data; "
        "when a field is missing, point it out explicitly."
    )
    lines.append("")
    lines.append("Assets under review: " + ", ".join(assets))
    lines.append("")
    lines.append("Data snapshot (fresh REST data):")
    for asset in assets:
        lines.extend(_format_snapshot_lines(asset, snapshots.get(asset)))
    lines.extend(
        [
            "",
            "Provide:",
            "1) Market regime and trend per asset (technical + on-chain if inferable)",
            "2) Relative value vs peers and catalysts (fundamental/sentiment/news)",
            "3) Key risks and invalidation levels",
            "4) 24h and weekly scenarios (bull/base/bear) with probability ranges",
            "5) Comparative table with 3 ranks: Momentum, Risk-adjusted Opportunity, Near-term Asymmetry",
        ]
    )
    if enrichment:
        _append_enrichment_to_prompt(lines, enrichment)
    return "\n".join(lines)


def _snapshots_payload(assets: Iterable[str], snapshots: dict[str, AssetSnapshot]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for asset in assets:
        snap = snapshots.get(asset)
        payload[asset] = snap.as_dict() if snap else {}
    return payload


async def _enrich_data_api_async(assets: list[str]) -> dict[str, Any]:
    from pipeline.collectors.coinmarketcap_cycle import fetch_cmc_cycle_indicators
    from pipeline.collectors.defillama import fetch_defillama_tvl
    from pipeline.collectors.onchain import fetch_hashrate, fetch_sopr, fetch_txcount
    from pipeline.collectors.sentiment import fetch_fear_greed

    asset_info = describe_assets(assets)
    normalized_assets = [info.asset for info in asset_info]

    out: dict[str, Any] = {"onchain": {}, "sentiment": {}, "cycle": {}, "defi": {}}
    onchain_targets = [a for a in normalized_assets if a in {"BTC", "ETH"}]

    async def gather_onchain(asset: str) -> tuple[str, dict[str, Any]]:
        data: dict[str, Any] = {}
        try:
            if asset == "BTC":
                tx_btc = await fetch_txcount("BTC")
                if tx_btc:
                    data["txcount"] = tx_btc.get("value")
                hr = await fetch_hashrate("BTC")
                if hr:
                    data["hashrate_btc"] = hr.get("value")
                sp = await fetch_sopr("BTC")
                if sp:
                    data["sopr_btc"] = sp.get("value")
            if asset == "ETH":
                etherscan_key = os.getenv("ETHERSCAN_API_KEY")
                tx_eth = await fetch_txcount("ETH", etherscan_api_key=etherscan_key)
                if tx_eth:
                    data["txcount"] = tx_eth.get("value")
        except Exception:
            pass
        return asset, data

    onchain_results = await asyncio.gather(*(gather_onchain(a) for a in onchain_targets))
    out["onchain"] = {k: v for k, v in onchain_results}

    try:
        fgi = await fetch_fear_greed()
        if fgi:
            out["sentiment"] = fgi
    except Exception:
        pass

    try:
        cycle = fetch_cmc_cycle_indicators()
        out["cycle"] = {
            "count": len(cycle),
            "top": [c.get("name") for c in (cycle[:5] if isinstance(cycle, list) else [])],
        }
    except Exception:
        pass

    chain_to_assets: dict[str, list[str]] = {}
    for info in asset_info:
        if info.defillama_chain:
            chain_to_assets.setdefault(info.defillama_chain, []).append(info.asset)
    if chain_to_assets:
        chain_results = await asyncio.gather(
            *(fetch_defillama_tvl(chain) for chain in chain_to_assets),
            return_exceptions=True,
        )
        defi_payload: dict[str, Any] = {}
        for (_chain, assets_for_chain), res in zip(chain_to_assets.items(), chain_results, strict=False):
            if isinstance(res, Exception) or not isinstance(res, dict):
                continue
            value = res.get("value") if isinstance(res.get("value"), dict) else {}
            if not isinstance(value, dict):
                continue
            summary = {
                "tvl": value.get("tvl"),
                "tvl_prev_day": value.get("tvlPrevDay"),
                "tvl_prev_week": value.get("tvlPrevWeek"),
                "tvl_prev_month": value.get("tvlPrevMonth"),
            }
            for asset in assets_for_chain:
                defi_payload[asset] = summary
        if defi_payload:
            out["defi"] = defi_payload

    return out


def _select_provider(argv_provider: str | None = None):
    prov = (argv_provider or os.getenv("LLM_PROVIDER", "")).strip().lower()
    from pipeline.llm import providers as p

    order: list[tuple[str, Any]] = []
    if prov:
        order.append((prov, prov))
    order.extend(
        [
            ("openrouter", None),
            ("anthropic", None),
            ("openai", None),
            ("gemini", None),
            ("deepseek", None),
            ("ollama", None),
            ("mock", None),
        ]
    )

    for name, _ in order:
        try:
            if name == "openrouter" and os.getenv("OPENROUTER_API_KEY"):
                return name, p.openrouter_generate
            if name == "anthropic" and os.getenv("ANTHROPIC_API_KEY"):
                return name, p.anthropic_generate
            if name == "openai" and os.getenv("OPENAI_API_KEY"):
                return name, p.openai_generate
            if name == "gemini" and (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")):
                return name, p.gemini_generate
            if name == "deepseek" and os.getenv("DEEPSEEK_API_KEY"):
                return name, p.deepseek_generate
            if name == "ollama":
                return name, p.ollama_generate
            if name == "mock":
                return name, p.mock_generate
        except Exception:
            continue
    return "mock", p.mock_generate


def _select_next_provider(tried: set[str], argv_provider: str | None = None):
    from pipeline.llm import providers as p

    pref: list[tuple[str, Any]] = []
    prov = (argv_provider or os.getenv("LLM_PROVIDER", "")).strip().lower()
    if prov:
        pref.append((prov, prov))
    pref.extend(
        [
            ("openrouter", None),
            ("anthropic", None),
            ("openai", None),
            ("gemini", None),
            ("deepseek", None),
            ("ollama", None),
            ("mock", None),
        ]
    )

    for name, _ in pref:
        if name in tried:
            continue
        try:
            if name == "openrouter" and os.getenv("OPENROUTER_API_KEY"):
                return name, p.openrouter_generate
            if name == "anthropic" and os.getenv("ANTHROPIC_API_KEY"):
                return name, p.anthropic_generate
            if name == "openai" and os.getenv("OPENAI_API_KEY"):
                return name, p.openai_generate
            if name == "gemini" and (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")):
                return name, p.gemini_generate
            if name == "deepseek" and os.getenv("DEEPSEEK_API_KEY"):
                return name, p.deepseek_generate
            if name == "ollama":
                return name, p.ollama_generate
            if name == "mock":
                return name, p.mock_generate
        except Exception:
            continue
    return "mock", p.mock_generate


async def _collect_async(
    assets: list[str],
    hours: int,
    enrich: bool,
) -> tuple[dict[str, AssetSnapshot], dict[str, Any] | None]:
    snapshots = await gather_snapshots(assets, hours=hours)
    enrichment: dict[str, Any] | None = None
    if enrich:
        try:
            enrichment = await _enrich_data_api_async(assets)
        except Exception as exc:
            print(f"[warn] enrichment failed: {exc}", file=sys.stderr)
            enrichment = None
    return snapshots, enrichment


def main() -> int:
    try:
        load_dotenv()
        if (REPO_ROOT / ".env.local").exists():
            load_dotenv(REPO_ROOT / ".env.local", override=True)
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Compose et envoie un prompt d'analyse de marche multi-actifs")
    ap.add_argument("--assets", default="BTC,ETH,SOL,LINK,TAO,ATOM,DOT,NEAR,AVAX,SUI")
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--provider", default=None, help="mock|openai|openrouter|anthropic|gemini|deepseek|ollama")
    ap.add_argument("--dry-run", action="store_true", help="Compose le prompt mais n'appelle pas le LLM")
    ap.add_argument(
        "--enrich-api",
        action="store_true",
        help="Collecte REST (on-chain BTC/ETH, sentiment FGI, CMC cycle) et les ajoute au prompt",
    )
    args = ap.parse_args()

    assets = [a.strip().upper() for a in args.assets.split(",") if a.strip()]
    snapshots, enrichment = asyncio.run(_collect_async(assets, args.hours, args.enrich_api))
    prompt = _compose_prompt(assets, snapshots, enrichment)
    snapshot_json = _snapshots_payload(assets, snapshots)

    name, fn = _select_provider(args.provider)
    result: Any | None = None
    if not args.dry_run:
        tried: set[str] = set()
        first_error: str | None = None
        for _ in range(5):
            tried.add(name)
            try:
                result = fn(prompt, {"model": os.getenv("LLM_MODEL", None)})
                break
            except Exception as exc:
                if first_error is None:
                    first_error = f"[LLM ERROR:{name}] {exc}"
                alt_name, alt_fn = _select_next_provider(tried, None)
                if alt_name in tried and alt_name == name:
                    break
                name, fn = alt_name, alt_fn
        if result is None and first_error:
            result = first_error

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_UTC")
    out_dir = EXPORTS_DIR / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"market_analysis_{timestamp}.md"

    md_lines = [
        f"# Market Analysis - {timestamp}",
        "",
        "## Data Snapshot",
        "",
        "```json",
        json.dumps(snapshot_json, indent=2, sort_keys=True),
        "```",
        "",
        "## Prompt",
        "",
        "```",
        prompt,
        "```",
        "",
    ]
    if enrichment:
        md_lines += [
            "## Enrichment",
            "",
            "```json",
            json.dumps(enrichment, indent=2, sort_keys=True),
            "```",
            "",
        ]
    if result is not None:
        md_lines += ["## LLM Output", "", str(result)]
    out_path.write_text("\n".join(md_lines), encoding="utf-8")

    payload: dict[str, Any] = {
        "status": "ok",
        "provider": name,
        "report": str(out_path),
        "snapshots": snapshot_json,
    }
    if enrichment:
        payload["enrichment"] = enrichment
    if result is not None:
        payload["output"] = result
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
