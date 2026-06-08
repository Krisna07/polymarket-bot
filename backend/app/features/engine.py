from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import FeatureSnapshot, Market, OrderbookSnapshot


class FeatureEngine:
    """Build point-in-time feature rows from latest orderbook snapshots."""

    async def compute_for_active_markets(
        self, session: AsyncSession, limit: int = 50
    ) -> int:
        result = await session.execute(
            select(Market).where(
                Market.active.is_(True),
                Market.closed.is_(False),
            ).limit(limit)
        )
        markets = result.scalars().all()
        count = 0

        for market in markets:
            ob_result = await session.execute(
                select(OrderbookSnapshot)
                .where(OrderbookSnapshot.market_id == market.id)
                .order_by(OrderbookSnapshot.snapshot_at.desc())
                .limit(5)
            )
            snapshots = ob_result.scalars().all()
            if not snapshots:
                continue

            latest = snapshots[0]
            market_prob = latest.mid_price
            features = self._build_features(latest, snapshots, market)

            session.add(
                FeatureSnapshot(
                    market_id=market.id,
                    features=features,
                    market_probability=market_prob,
                    computed_at=datetime.now(timezone.utc),
                )
            )
            count += 1

        await session.commit()
        return count

    def _build_features(
        self,
        latest: OrderbookSnapshot,
        history: list[OrderbookSnapshot],
        market: Market,
    ) -> dict[str, Any]:
        mids = [h.mid_price for h in history if h.mid_price is not None]
        momentum_5m = None
        if len(mids) >= 2 and mids[-1] is not None and mids[0] is not None:
            momentum_5m = mids[-1] - mids[0]

        spread_pct = None
        if latest.mid_price and latest.spread and latest.mid_price > 0:
            spread_pct = latest.spread / latest.mid_price

        imbalance = None
        if latest.bid_depth is not None and latest.ask_depth is not None:
            total = latest.bid_depth + latest.ask_depth
            if total > 0:
                imbalance = (latest.bid_depth - latest.ask_depth) / total

        return {
            "best_bid": latest.best_bid,
            "best_ask": latest.best_ask,
            "mid_price": latest.mid_price,
            "spread": latest.spread,
            "spread_pct": spread_pct,
            "bid_depth": latest.bid_depth,
            "ask_depth": latest.ask_depth,
            "book_imbalance": imbalance,
            "momentum_5snap": momentum_5m,
            "tags": market.tags or [],
            "category": market.category,
        }
