import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import Settings
from backend.app.db.models import Market, OrderbookSnapshot
from backend.app.services.polymarket.clob import ClobClient

log = structlog.get_logger(__name__)


class OrderbookSyncService:
    def __init__(self, settings: Settings) -> None:
        self._clob = ClobClient(settings)

    async def snapshot_all(self, session: AsyncSession, limit: int = 50) -> int:
        result = await session.execute(
            select(Market).where(
                Market.active.is_(True),
                Market.closed.is_(False),
                Market.yes_token_id.isnot(None),
            ).limit(limit)
        )
        markets = result.scalars().all()
        count = 0

        for market in markets:
            token_id = market.yes_token_id
            if not token_id:
                continue
            try:
                book = await self._clob.get_order_book(token_id)
                summary = self._clob.summarize_book(book)
                session.add(
                    OrderbookSnapshot(
                        market_id=market.id,
                        token_id=token_id,
                        best_bid=summary["best_bid"],
                        best_ask=summary["best_ask"],
                        mid_price=summary["mid_price"],
                        spread=summary["spread"],
                        bid_depth=summary["bid_depth"],
                        ask_depth=summary["ask_depth"],
                        volume_24h=summary.get("volume_24h"),
                        raw_book=book,
                    )
                )
                count += 1
            except Exception as e:
                log.warning("orderbook_snapshot_failed", market_id=market.id, error=str(e))

        await session.commit()
        log.info("orderbook_snapshots_saved", count=count)
        return count
