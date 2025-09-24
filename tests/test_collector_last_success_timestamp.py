import asyncio
import time
from pipeline.collectors.base_collector import BaseCollector
from prometheus_client import REGISTRY


class _DummyCollector(BaseCollector):
    async def fetch_main(self, *args, **kwargs):
        return {"value": 42}

    async def fetch_backup(self, *args, **kwargs):  # pragma: no cover - non utilisé ici
        return {"value": 41}


def _get_metric_value(collector_name: str):
    for metric in REGISTRY.collect():  # brute force acceptable test scope
        if metric.name == 'collector_last_success_timestamp':
            for sample in metric.samples:
                if sample.labels.get('collector') == collector_name:
                    return sample.value
    return None


def test_collector_last_success_timestamp_updates():
    c = _DummyCollector("dummy_last_ts")
    before = time.time()
    asyncio.run(c.fetch())
    val = _get_metric_value("dummy_last_ts")
    assert val is not None
    assert val >= int(before)