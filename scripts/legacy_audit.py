import argparse
import glob
import json
import os

BASE = "pipeline"

EXCLUDE_BASENAMES = {"__init__", "metrics", "monitoring"}


def collect_files():
    return [f for f in glob.glob(os.path.join(BASE, "**", "*.py"), recursive=True)]


def map_usage(files):
    usage = {f: 0 for f in files}
    sources = {}
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                sources[f] = fh.read()
        except Exception:
            sources[f] = ""
    # Heuristic: look for module basename tokens in other source files
    for f, src in sources.items():
        for other in files:
            if other == f:
                continue
            bn = os.path.splitext(os.path.basename(other))[0]
            if bn in EXCLUDE_BASENAMES:
                continue
            token = bn + "."
            if token in src or f"from {bn} import" in src:
                usage[other] += 1
    return usage


def classify(files, usage):
    candidates = []
    for f in files:
        if f.endswith("__init__.py"):
            continue
        bn = os.path.splitext(os.path.basename(f))[0]
        if bn in EXCLUDE_BASENAMES:
            continue
        if usage.get(f, 0) == 0:
            size = os.path.getsize(f)
            candidates.append({"file": f, "size": size})
    candidates.sort(key=lambda x: x["size"])
    return candidates


def main():
    parser = argparse.ArgumentParser(description="Heuristic legacy module audit")
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    args = parser.parse_args()

    files = collect_files()
    usage = map_usage(files)
    candidates = classify(files, usage)

    if args.json:
        print(json.dumps({"candidate_count": len(candidates), "candidates": candidates}, indent=2))
        return

    print("\n[LEGACY AUDIT] Modules sans références internes (heuristique)")
    for c in candidates:
        print(f" - {c['file']} (size={c['size']})")
    print(f"Total candidats: {len(candidates)}")
    print(
        "\nNOTE: Heuristique basée sur occurrences textuelles des basenames."
        " Vérifier usages dynamiques (importlib, scheduler)."
    )


if __name__ == "__main__":
    main()
