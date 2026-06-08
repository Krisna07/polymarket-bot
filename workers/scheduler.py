import asyncio
import signal
import sys

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.app.config import get_settings
from backend.app.db.session import AsyncSessionLocal
from backend.app.logging_config import configure_logging
from backend.app.services.market_sync import MarketSyncService
from backend.app.services.orderbook_sync import OrderbookSyncService
from backend.app.services.trade_pipeline import TradePipelineService

log = structlog.get_logger(__name__)


async def job_sync_markets() -> None:
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        stats = await MarketSyncService(settings).sync(session)
        log.info("job_sync_markets", **stats)


async def job_snapshot_orderbooks() -> None:
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        count = await OrderbookSyncService(settings).snapshot_all(session)
        log.info("job_snapshot_orderbooks", count=count)


async def job_compute_features() -> None:
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        pipeline = TradePipelineService(settings)
        count = await pipeline.run_feature_pass(session)
        log.info("job_compute_features", count=count)


async def job_evaluate_trades() -> None:
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        pipeline = TradePipelineService(settings)
        count = await pipeline.evaluate_trades(session)
        log.info("job_evaluate_trades", count=count)


async def start_scheduler(scheduler, settings) -> None:
    scheduler.start()
    log.info(
        "worker_started",
        sync_sec=settings.sync_markets_interval_sec,
        features_sec=settings.features_interval_sec,
    )


def main() -> None:
    configure_logging()
    settings = get_settings()
    scheduler = AsyncIOScheduler()

    scheduler.add_job(
        job_sync_markets,
        "interval",
        seconds=settings.sync_markets_interval_sec,
        id="sync_markets",
        max_instances=1,
    )
    scheduler.add_job(
        job_snapshot_orderbooks,
        "interval",
        seconds=settings.snapshot_books_interval_sec,
        id="snapshot_orderbooks",
        max_instances=1,
    )
    scheduler.add_job(
        job_compute_features,
        "interval",
        seconds=settings.features_interval_sec,
        id="compute_features",
        max_instances=1,
    )
    scheduler.add_job(
        job_evaluate_trades,
        "interval",
        seconds=settings.trade_eval_interval_sec,
        id="evaluate_trades",
        max_instances=1,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def shutdown(*_args):
        log.info("worker_shutdown")
        scheduler.shutdown(wait=False)
        loop.stop()

    signal.signal(signal.SIGINT, shutdown)
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, shutdown)

    # Start the scheduler inside a running event loop context
    loop.run_until_complete(start_scheduler(scheduler, settings))

    try:
        loop.run_forever()
    finally:
        loop.close()


if __name__ == "__main__":
    main()
