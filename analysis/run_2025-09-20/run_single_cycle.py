import asyncio
import json
import os
import time
from datetime import datetime

from main import run_legacy_collection, setup_logging


async def main():
    start = time.time()
    setup_logging()
    results = await run_legacy_collection()
    duration = time.time() - start
    summary = {
        'timestamp': datetime.utcnow().isoformat(),
        'record_count': len(results),
        'types': sorted(list({r.get('metric_name','unknown') for r in results if isinstance(r, dict)})),
        'duration_seconds': round(duration, 2)
    }
    out_dir = 'analysis/run_2025-09-20/artifacts'
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, 'single_cycle_summary.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)
    print('Single cycle summary saved:', summary)

if __name__ == '__main__':
    asyncio.run(main())
