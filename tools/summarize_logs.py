import argparse
import json
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

# Patterns to detect scheduler and collector events
PATTERN_STD = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[^|]+)\s*\|\s*(?P<level>[A-Z]+)\s*\|\s*(?P<logger>[^|]+)\s*\|\s*(?P<msg>.*)$"
)
PATTERN_SCHED = re.compile(
    r"\[SCHEDULER\]\s*(?P<kind>Running collector|Collector .+ failed|Generating report|Exporting latest data)"
)
PATTERN_COLLECTOR_START = re.compile(r"\[SCHEDULER\]\s*Running collector:\s*(?P<name>\w+)")
PATTERN_COLLECTOR_FAIL = re.compile(r"\[SCHEDULER\]\s*Collector\s+(?P<name>\w+)\s+failed:\s*(?P<err>.*)")

# Optional: parse structlog JSON lines if present


def try_parse_structlog(line: str) -> dict[str, Any] | None:
    try:
        obj = json.loads(line)
        if isinstance(obj, dict) and obj.get("event"):
            return obj
    except Exception:
        return None
    return None


def parse_lines(lines: list[str]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    collector_runs: Counter[str] = Counter()
    collector_failures: Counter[str] = Counter()
    error_messages: Counter[str] = Counter()
    first_ts: datetime | None = None
    last_ts: datetime | None = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        obj = try_parse_structlog(line)
        if obj:
            # Map level
            lvl = obj.get("level", obj.get("log_level", "INFO")).upper()
            if lvl not in LEVELS:
                lvl = "INFO"
            counts[lvl] += 1
            # collector hints
            msg = obj.get("event", "")
            mstart = PATTERN_COLLECTOR_START.search(msg)
            if mstart:
                collector_runs[mstart.group("name")] += 1
            mfail = PATTERN_COLLECTOR_FAIL.search(msg)
            if mfail:
                collector_failures[mfail.group("name")] += 1
                err_text = mfail.group("err").strip()
                if err_text:
                    error_messages[err_text] += 1
            # timestamps
            ts_raw = obj.get("timestamp") or obj.get("time") or obj.get("ts")
            if ts_raw is not None:
                try:
                    dt_parsed: datetime | None = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                except Exception:
                    dt_parsed = None
                if dt_parsed is not None:
                    if first_ts is None:
                        first_ts = dt_parsed
                    last_ts = dt_parsed
            continue

        m = PATTERN_STD.match(line)
        if m:
            ts_raw = m.group("ts").split("|")[0].strip()
            # best-effort ts parse
            dt_line: datetime | None = None
            for fmt in ("%Y-%m-%d %H:%M:%S,%f", "%Y-%m-%d %H:%M:%S"):
                try:
                    dt_line = datetime.strptime(ts_raw, fmt)
                    break
                except Exception:
                    continue
            if dt_line is not None:
                if first_ts is None:
                    first_ts = dt_line
                last_ts = dt_line
            lvl = m.group("level").upper()
            counts[lvl] += 1
            msg = m.group("msg")
            s = PATTERN_COLLECTOR_START.search(msg)
            if s:
                collector_runs[s.group("name")] += 1
            f = PATTERN_COLLECTOR_FAIL.search(msg)
            if f:
                collector_failures[f.group("name")] += 1
                err_text = f.group("err").strip()
                if err_text:
                    error_messages[err_text] += 1

    return {
        "counts": counts,
        "collector_runs": collector_runs,
        "collector_failures": collector_failures,
        "error_messages": error_messages,
        "first_ts": first_ts,
        "last_ts": last_ts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize pipeline logs")
    parser.add_argument("logfile", help="Path to log file")
    parser.add_argument("--since-min", type=int, default=None, help="Only include last N minutes of logs")
    parser.add_argument("--top-errors", type=int, default=5, help="Show top N error messages")
    parser.add_argument("--json", action="store_true", help="Output JSON summary")
    args = parser.parse_args()

    with open(args.logfile, encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    # Optional windowing by time (best-effort): filter by timestamps near file end
    if args.since_min is not None and args.since_min > 0:
        cutoff = datetime.now(UTC) - timedelta(minutes=args.since_min)
        filtered = []
        for line in lines[::-1]:  # scan backwards until before cutoff
            line_stripped = line.strip()
            if not line_stripped:
                continue
            parsed_obj = try_parse_structlog(line_stripped)
            ts = None
            if parsed_obj:
                raw = parsed_obj.get("timestamp") or parsed_obj.get("time") or parsed_obj.get("ts")
                if raw:
                    try:
                        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                    except Exception:
                        ts = None
            if ts is None:
                m = PATTERN_STD.match(line_stripped)
                if m:
                    ts_raw = m.group("ts").split("|")[0].strip()
                    for fmt in ("%Y-%m-%d %H:%M:%S,%f", "%Y-%m-%d %H:%M:%S"):
                        try:
                            ts = datetime.strptime(ts_raw, fmt).replace(tzinfo=UTC)
                            break
                        except Exception:
                            continue
            if ts is None or ts >= cutoff:
                filtered.append(line)
            else:
                # we've reached older than cutoff; keep scanning to collect more non-timestamped lines if needed
                continue
        lines = list(reversed(filtered)) if filtered else lines

    data = parse_lines(lines)

    counts = data["counts"]
    runs = data["collector_runs"]
    fails = data["collector_failures"]
    err_msgs = data["error_messages"]
    first_ts = data["first_ts"]
    last_ts = data["last_ts"]

    duration = None
    if first_ts and last_ts:
        duration = last_ts - first_ts

    summary = {
        "window": {
            "start": first_ts.isoformat() if first_ts else None,
            "end": last_ts.isoformat() if last_ts else None,
            "duration": str(duration) if duration else None,
        },
        "levels": {lvl: counts.get(lvl, 0) for lvl in LEVELS if counts.get(lvl)},
        "collector_runs": dict(runs),
        "collector_failures": dict(fails),
        "top_error_messages": err_msgs.most_common(args.top_errors),
        "per_collector_error_rate": {
            name: {
                "runs": runs[name],
                "failures": fails.get(name, 0),
                "error_rate": (fails.get(name, 0) / runs[name]) if runs[name] else None,
            } for name in set(list(runs.keys()) + list(fails.keys()))
        },
    }

    total_errors = counts.get("ERROR", 0) + counts.get("CRITICAL", 0)
    total_failures = sum(fails.values()) if hasattr(fails, "values") else 0
    if total_errors == 0 and total_failures == 0:
        verdict = "OK"
        note = "no errors detected"
    elif total_errors <= 5 and total_failures <= 3:
        verdict = "MOSTLY_OK"
        note = "a few errors, keep monitoring"
    else:
        verdict = "ISSUES"
        note = "investigate errors"
    summary["verdict"] = {"status": verdict, "note": note}

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    # Human readable output
    print("==== Log Health Summary ====")
    if duration:
        print(f"Window: {first_ts} -> {last_ts} (duration: {duration})")
    print("Levels:")
    for lvl in LEVELS:
        if counts.get(lvl):
            print(f"  {lvl:<8} {counts[lvl]}")
    if fails:
        print("Collector failures:")
        for name, c in fails.most_common():
            print(f"  {name:<16} {c}")
    else:
        print("Collector failures: none detected")

    if runs:
        print("Top collectors by runs:")
        for name, c in runs.most_common():
            rate = None
            if runs[name]:
                rate = (fails.get(name, 0) / runs[name]) if runs[name] else None
            rate_str = f" (error rate: {rate:.1%})" if rate is not None else ""
            print(f"  {name:<16} {c}{rate_str}")

    if err_msgs:
        print(f"Top {min(args.top_errors, len(err_msgs))} error messages:")
        for msg, c in err_msgs.most_common(args.top_errors):
            print(f"  {c:>4}  {msg}")

    print(f"Verdict: {verdict} — {note}")

if __name__ == "__main__":
    main()
