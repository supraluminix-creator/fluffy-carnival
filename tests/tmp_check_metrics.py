from prometheus_client import REGISTRY

from pipeline.instrumentation import instrument_collector


@instrument_collector("demo_inline")
def foo():
    return 7


def _debug_dump() -> None:
    print(sorted({fam.name for fam in REGISTRY.collect() if fam.name.startswith("collector_")}))
    for fam in REGISTRY.collect():
        if fam.name.startswith("collector_"):
            print("FAM", fam.name)
            for s in fam.samples:
                print("  SAMPLE", s.name, s.labels, s.value)


if __name__ == "__main__":  # pragma: no cover
    foo()
    _debug_dump()
