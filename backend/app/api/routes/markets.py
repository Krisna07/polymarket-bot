from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Market, OrderbookSnapshot
from backend.app.db.session import get_db

router = APIRouter(prefix="/markets", tags=["markets"])


@router.get("")
async def list_markets(
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    active_only: bool = True,
) -> list[dict]:
    q = select(Market).order_by(Market.updated_at.desc()).limit(limit)
    if active_only:
        q = q.where(Market.active.is_(True), Market.closed.is_(False))
    result = await db.execute(q)
    markets = result.scalars().all()
    return [
        {
            "id": m.id,
            "condition_id": m.condition_id,
            "question": m.question,
            "tags": m.tags,
            "yes_token_id": m.yes_token_id,
            "category": m.category,
        }
        for m in markets
    ]


@router.get("/{market_id}/orderbook/latest")
async def latest_orderbook(
    market_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict | None:
    result = await db.execute(
        select(OrderbookSnapshot)
        .where(OrderbookSnapshot.market_id == market_id)
        .order_by(OrderbookSnapshot.snapshot_at.desc())
        .limit(1)
    )
    snap = result.scalar_one_or_none()
    if not snap:
        return None
    return {
        "best_bid": snap.best_bid,
        "best_ask": snap.best_ask,
        "mid_price": snap.mid_price,
        "spread": snap.spread,
        "snapshot_at": snap.snapshot_at.isoformat(),
    }


@router.get("/{market_id}/history")
async def market_history(
    market_id: int,
    db: AsyncSession = Depends(get_db),
    limit: int = 60,
) -> dict:
    result = await db.execute(
        select(OrderbookSnapshot)
        .where(OrderbookSnapshot.market_id == market_id)
        .order_by(OrderbookSnapshot.snapshot_at.desc())
        .limit(limit)
    )
    snapshots = list(reversed(result.scalars().all()))
    return {
        "market_id": market_id,
        "points": [
            {
                "snapshot_at": snap.snapshot_at.isoformat(),
                "mid_price": snap.mid_price,
                "best_bid": snap.best_bid,
                "best_ask": snap.best_ask,
                "spread": snap.spread,
                "bid_depth": snap.bid_depth,
                "ask_depth": snap.ask_depth,
                "volume_24h": snap.volume_24h,
            }
            for snap in snapshots
        ],
    }
