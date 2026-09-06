#!/usr/bin/env python3
"""
Performance benchmark script for new_crypto_prodsafe.

Measures before/after performance improvements:
- HTTP connection overhead
- Cache hit rates
- Latency distributions
- Rate limiting effectiveness
- 429 error rates

Usage:
    python benchmark.py --before  # Baseline measurement
    python benchmark.py --after   # Post-improvement measurement
    python benchmark.py --compare # Compare before/after results
"""

import asyncio
import json
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

import httpx
import structlog

from pipeline.http_client import get_http_client
from pipeline.rate_limiter import acquire_rate_limit, get_rate_limiter_status

logger = structlog.get_logger(__name__)

# Benchmark configuration
BENCHMARK_CONFIG = {
    "apis": [
        {"name": "coingecko", "url": "https://api.coingecko.com/api/v3/ping", "calls": 10},
        {"name": "binance", "url": "https://api.binance.com/api/v3/time", "calls": 20},
        {"name": "bybit", "url": "https://api.bybit.com/v5/market/time", "calls": 15},
    ],
    "iterations": 3,
    "results_dir": Path("benchmark_results"),
}

BENCHMARK_CONFIG["results_dir"].mkdir(exist_ok=True)


async def benchmark_http_performance() -> Dict[str, Any]:
    """Benchmark HTTP connection performance with persistent pooling."""
    results = {
        "persistent_pool": {"latencies": [], "errors": 0},
        "fresh_clients": {"latencies": [], "errors": 0},
    }

    # Test with persistent pool
    logger.info("Testing persistent HTTP pool...")
    for api in BENCHMARK_CONFIG["apis"]:
        for i in range(api["calls"]):
            try:
                start = time.time()
                async with get_http_client() as client:
                    response = await client.get(api["url"], timeout=5.0)
                    response.raise_for_status()
                latency = time.time() - start
                results["persistent_pool"]["latencies"].append(latency)
                await acquire_rate_limit(api["name"])  # Respect rate limits
            except Exception as e:
                results["persistent_pool"]["errors"] += 1
                logger.warning(f"Persistent pool error for {api['name']}: {e}")

    # Test with fresh clients (legacy approach)
    logger.info("Testing fresh HTTP clients...")
    for api in BENCHMARK_CONFIG["apis"]:
        for i in range(api["calls"]):
            try:
                start = time.time()
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(api["url"])
                    response.raise_for_status()
                latency = time.time() - start
                results["fresh_clients"]["latencies"].append(latency)
                await acquire_rate_limit(api["name"])
            except Exception as e:
                results["fresh_clients"]["errors"] += 1
                logger.warning(f"Fresh client error for {api['name']}: {e}")

    return results


async def benchmark_rate_limiting() -> Dict[str, Any]:
    """Benchmark rate limiting effectiveness."""
    results = {"acquisitions": [], "errors": 0}

    logger.info("Testing rate limiting...")
    # Simulate high-frequency requests
    for i in range(100):
        try:
            start = time.time()
            await acquire_rate_limit("coingecko")  # Should throttle
            latency = time.time() - start
            results["acquisitions"].append(latency)
        except Exception as e:
            results["errors"] += 1
            logger.warning(f"Rate limit error: {e}")

    return results


def analyze_results(results: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze benchmark results and compute statistics."""
    analysis = {}

    for test_name, data in results.items():
        if "latencies" in data and data["latencies"]:
            latencies = data["latencies"]
            analysis[test_name] = {
                "count": len(latencies),
                "mean": statistics.mean(latencies),
                "median": statistics.median(latencies),
                "p95": sorted(latencies)[int(len(latencies) * 0.95)],
                "min": min(latencies),
                "max": max(latencies),
                "errors": data.get("errors", 0),
            }
        else:
            analysis[test_name] = {"errors": data.get("errors", 0)}

    # Compute improvements
    if "persistent_pool" in analysis and "fresh_clients" in analysis:
        persistent_mean = analysis["persistent_pool"]["mean"]
        fresh_mean = analysis["fresh_clients"]["mean"]
        improvement = ((fresh_mean - persistent_mean) / fresh_mean) * 100
        analysis["improvement"] = {
            "http_performance": f"{improvement:.1f}%",
            "persistent_vs_fresh": f"{persistent_mean:.3f}s vs {fresh_mean:.3f}s",
        }

    return analysis


async def run_benchmark(label: str) -> None:
    """Run complete benchmark suite."""
    logger.info(f"Starting benchmark: {label}")

    results = {}

    # HTTP performance benchmark
    results["http_performance"] = await benchmark_http_performance()

    # Rate limiting benchmark
    results["rate_limiting"] = await benchmark_rate_limiting()

    # Get rate limiter status
    results["rate_limiter_status"] = get_rate_limiter_status()

    # Analyze results
    analysis = analyze_results(results)

    # Save results
    output = {
        "timestamp": time.time(),
        "label": label,
        "raw_results": results,
        "analysis": analysis,
    }

    output_file = BENCHMARK_CONFIG["results_dir"] / f"benchmark_{label}_{int(time.time())}.json"
    with open(output_file, "w") as f:
        json.dump(output, f, indent=2)

    logger.info(f"Benchmark complete. Results saved to {output_file}")

    # Print summary
    print(f"\n=== BENCHMARK RESULTS: {label} ===")
    for test_name, stats in analysis.items():
        if isinstance(stats, dict) and "mean" in stats:
            print(f"{test_name}: {stats['mean']:.3f}s mean, {stats['errors']} errors")
        elif test_name == "improvement":
            for key, value in stats.items():
                print(f"Improvement {key}: {value}")

    return output


def compare_results(before_file: Path, after_file: Path) -> None:
    """Compare before/after benchmark results."""
    with open(before_file) as f:
        before = json.load(f)
    with open(after_file) as f:
        after = json.load(f)

    print("\n=== COMPARISON: BEFORE vs AFTER ===")

    for test_name in before["analysis"]:
        if test_name in after["analysis"]:
            before_stats = before["analysis"][test_name]
            after_stats = after["analysis"][test_name]

            if "mean" in before_stats and "mean" in after_stats:
                improvement = ((before_stats["mean"] - after_stats["mean"]) / before_stats["mean"]) * 100
                print(f"{test_name}: {before_stats['mean']:.3f}s → {after_stats['mean']:.3f}s ({improvement:+.1f}%)")


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Performance benchmark for new_crypto_prodsafe")
    parser.add_argument("--before", action="store_true", help="Run before-improvement benchmark")
    parser.add_argument("--after", action="store_true", help="Run after-improvement benchmark")
    parser.add_argument("--compare", action="store_true", help="Compare before/after results")

    args = parser.parse_args()

    if args.compare:
        # Find latest before/after files
        results_dir = BENCHMARK_CONFIG["results_dir"]
        files = list(results_dir.glob("benchmark_*.json"))
        before_files = [f for f in files if "before" in f.name]
        after_files = [f for f in files if "after" in f.name]

        if before_files and after_files:
            before_file = max(before_files, key=lambda x: x.stat().st_mtime)
            after_file = max(after_files, key=lambda x: x.stat().st_mtime)
            compare_results(before_file, after_file)
        else:
            print("Need both --before and --after results to compare")
    elif args.before:
        await run_benchmark("before")
    elif args.after:
        await run_benchmark("after")
    else:
        print("Use --before, --after, or --compare")


if __name__ == "__main__":
    asyncio.run(main())