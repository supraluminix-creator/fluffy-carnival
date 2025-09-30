import csv, json, os, re, sqlite3
from datetime import datetime, timezone
from glob import glob
from urllib.request import urlopen, Request

ROOT = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(ROOT)  # repo root


def _read_latest_manifest():
    path = os.path.join(ROOT, "exports", "export_manifest.jsonl")
    if not os.path.exists(path):
        return None
    last = None
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    last = json.loads(line)
                except Exception:
                    pass
    return last


def _read_csv_rows(csv_path, max_rows=5):
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return rows, rows[:max_rows]


def _fetch(url, timeout=3.0, headers=None):
    req = Request(url, headers=headers or {"User-Agent": "verify/1.0"})
    with urlopen(req, timeout=timeout) as r:
        return r.getcode(), r.read().decode("utf-8", errors="replace")


def _parse_prom_value(lines, metric):
    # returns [(labels_dict, value_float), ...]
    res = []
    for line in lines.splitlines():
        if not line or line.startswith("#"):
            continue
        if not line.startswith(metric):
            continue
        # ex: metric{label="x"} 123.0
        m = re.match(rf'^{re.escape(metric)}(\{{.*\}})?\s+([\-0-9\.|eE]+)$', line)
        if not m:
            continue
        labels_raw, val_s = m.group(1), m.group(2)
        labels = {}
        if labels_raw:
            for kv in labels_raw.strip("{}").split(","):
                if not kv:
                    continue
                if "=" not in kv:
                    continue
                k, v = kv.split("=", 1)
                labels[k.strip()] = v.strip().strip('"')
        try:
            val = float(val_s)
        except Exception:
            continue
        res.append((labels, val))
    return res


def _most_recent(path_glob):
    files = glob(path_glob)
    if not files:
        return None
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return files[0]


def _find_liq_db():
    # 1) env
    env_db = os.getenv("BYBIT_WS_DB")
    if env_db and os.path.exists(env_db):
        return env_db
    # 2) heuristic in data/
    candidates = []
    for pat in [
        os.path.join(ROOT, "data", "*.db"),
        os.path.join(ROOT, "data", "**", "*.db"),
    ]:
        candidates += glob(pat, recursive=True)
    candidates = [p for p in candidates if re.search(r"(liq|bybit)", os.path.basename(p), re.I)]
    if not candidates:
        any_db = glob(os.path.join(ROOT, "data", "**", "*.db"), recursive=True)
        if not any_db:
            return None
        any_db.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return any_db[0]
    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return candidates[0]


def _inspect_liq_db(db_path, limit=5):
    info = {"db_path": db_path, "tables": [], "counts": {}, "samples": {}}
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    info["tables"] = tables
    target = None
    for t in tables:
        if re.search(r"(liq|liquidat)", t, re.I):
            target = t
            break
    if not target and tables:
        target = tables[0]
    if not target:
        con.close()
        return info
    try:
        cur.execute(f"SELECT COUNT(*) FROM {target}")
        info["counts"][target] = cur.fetchone()[0]
    except Exception:
        pass
    try:
        cur.execute(f"PRAGMA table_info({target})")
        cols = [r[1] for r in cur.fetchall()]
    except Exception:
        cols = []
    order_col = "ts" if "ts" in cols else ("timestamp" if "timestamp" in cols else None)
    try:
        if order_col:
            cur.execute(f"SELECT * FROM {target} ORDER BY {order_col} DESC LIMIT {limit}")
        else:
            cur.execute(f"SELECT * FROM {target} LIMIT {limit}")
        rows = cur.fetchall()
    except Exception:
        rows = []
    info["samples"][target] = {"columns": cols, "rows": rows}
    con.close()
    return info


def _probe_ws_health():
    port = os.getenv("BYBIT_WS_HEALTH_PORT") or os.getenv("BYBIT_WS_PORT") or "8000"
    base = f"http://127.0.0.1:{port}"
    for path in ("/health", "/"):
        try:
            code, body = _fetch(base + path, timeout=1.5)
            return {"url": base + path, "status": code, "body": body[:300]}
        except Exception as e:
            last_err = str(e)
    return {"error": last_err}


def main():
    print("== Check exports ==")
    mani = _read_latest_manifest()
    if not mani:
        print("manifest: introuvable")
    else:
        print(
            f"manifest last row_count={mani.get('row_count')}, latest={mani.get('latest_path')}, ts_path={mani.get('timestamped_path')}"
        )
        latest = mani.get("latest_path")
        if latest and os.path.exists(latest):
            rows, sample = _read_csv_rows(latest)
            headers = list(sample[0].keys()) if sample else []
            print(f"CSV latest rows={len(rows)} headers={headers}")
            for r in sample:
                keys = list(r.keys())[:6]
                print(" sample:", {k: r[k] for k in keys})
        else:
            latest_path = os.path.join(ROOT, "exports", "latest_export.csv")
            if os.path.exists(latest_path):
                rows, sample = _read_csv_rows(latest_path)
                headers = list(sample[0].keys()) if sample else []
                print(f"CSV latest rows={len(rows)} headers={headers}")
                for r in sample:
                    keys = list(r.keys())[:6]
                    print(" sample:", {k: r[k] for k in keys})
            else:
                print("latest_export.csv introuvable")

    print("\n== Check Prometheus metrics ==")
    metrics_port = os.getenv("METRICS_PORT") or "9300"
    metrics_url_primary = f"http://127.0.0.1:{metrics_port}/metrics"
    metrics_url_fallback = "http://127.0.0.1:9310/metrics"  # si API health FastAPI est utilisée
    body = None
    try:
        code, body = _fetch(metrics_url_primary, timeout=2.5)
        print("metrics GET (primary):", metrics_url_primary, code)
    except Exception as e:
        print("metrics primary error:", e)
        try:
            code, body = _fetch(metrics_url_fallback, timeout=2.5)
            print("metrics GET (fallback):", metrics_url_fallback, code)
        except Exception as e2:
            print("metrics fallback error:", e2)
    if body:
        for m in [
            "pipeline_exports_total",
            "pipeline_export_rows_total",
            "flush_liq_rows_written",
            "writer_last_seen_event_timestamp",
            "writer_last_flush_timestamp",
        ]:
            vals = _parse_prom_value(body, m)
            print(f" {m}:", vals[:5] if vals else "absent")

    print("\n== Check app health ==")
    health_port = os.getenv("HEALTH_PORT") or "9310"
    try:
        code, body = _fetch(f"http://127.0.0.1:{health_port}/health", timeout=2.5)
        print("health GET:", f"http://127.0.0.1:{health_port}/health", code)
    except Exception as e:
        print("health error:", e)

    print("\n== Check WS sidecar health ==")
    print(_probe_ws_health())

    print("\n== Check liquidations DB ==")
    db = _find_liq_db()
    if not db:
        print("Aucune base .db trouvée dans data/")
    else:
        info = _inspect_liq_db(db)
        print("DB:", info.get("db_path"))
        print(" tables:", info.get("tables"))
        for t, c in (info.get("counts") or {}).items():
            print(f" {t}: count={c}")
        for t, s in (info.get("samples") or {}).items():
            if not s:
                continue
            print(f" {t} columns:", s.get("columns"))
            for row in (s.get("rows") or [])[:5]:
                print("  row:", row)

    print("\n== Scan logs for MVRV ==")
    last_log = _most_recent(os.path.join(ROOT, "logs", "run_*.log"))
    if last_log and os.path.exists(last_log):
        try:
            with open(last_log, "r", encoding="utf-8", errors="ignore") as f:
                lines = [ln for ln in f if "mvrv" in ln.lower()]
            print(f"log: {os.path.basename(last_log)}, mvrv-lines={len(lines)}")
            for ln in lines[-5:]:
                print(" ", ln.strip())
        except Exception as e:
            print("log read error:", e)
    else:
        print("Aucun log run_*.log trouvé")


if __name__ == "__main__":
    main()
