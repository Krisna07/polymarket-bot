import structlog

from backend.app.config import Settings
from backend.app.db.session import AsyncSessionLocal
from backend.app.services.market_sync import MarketSyncService
from backend.app.services.orderbook_sync import OrderbookSyncService
from backend.app.services.trade_pipeline import TradePipelineService
from backend.app.services.wallet_session import mark_bootstrap_complete

log = structlog.get_logger(__name__)


async def run_bootstrap_cycle(settings: Settings, address: str) -> dict[str, int | dict]:
    async with AsyncSessionLocal() as session:
        market_stats = await MarketSyncService(settings).sync(session)
        orderbooks = await OrderbookSyncService(settings).snapshot_all(session, limit=20)
        pipeline = TradePipelineService(settings)
        features = await pipeline.run_feature_pass(session)
        signals = await pipeline.evaluate_trades(session, limit=10)

    await mark_bootstrap_complete(address)
    result = {
        "markets": market_stats,
        "orderbooks": orderbooks,
        "features": features,
        "signals": signals,
    }
    log.info("bootstrap_complete", address=address, **{k: v for k, v in result.items() if k != "markets"})
    return result
