"""Run one ingestion + evaluation cycle (no scheduler)."""

import asyncio

from backend.app.config import get_settings
from backend.app.db.session import AsyncSessionLocal
from backend.app.logging_config import configure_logging
from backend.app.services.market_sync import MarketSyncService
from backend.app.services.orderbook_sync import OrderbookSyncService
from backend.app.services.trade_pipeline import TradePipelineService


async def main() -> None:
    configure_logging()
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        print("Syncing markets...")
        stats = await MarketSyncService(settings).sync(session)
        print(stats)

        print("Snapshotting order books...")
        ob = await OrderbookSyncService(settings).snapshot_all(session, limit=20)
        print({"orderbooks": ob})

        pipeline = TradePipelineService(settings)
        print("Computing features...")
        fc = await pipeline.run_feature_pass(session)
        print({"features": fc})

        print("Evaluating trades (paper)...")
        sig = await pipeline.evaluate_trades(session, limit=10)
        print({"signals": sig})


if __name__ == "__main__":
    asyncio.run(main())
