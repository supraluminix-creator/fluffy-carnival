import asyncio

from pipeline.collectors.bybit_ws import BybitWSService


async def main():
    svc = BybitWSService(["BTCUSDT"], flush_size=1, flush_interval=2)
    task = asyncio.create_task(svc.run())
    await asyncio.sleep(6)
    await svc.stop()
    await task


if __name__ == "__main__":
    asyncio.run(main())
