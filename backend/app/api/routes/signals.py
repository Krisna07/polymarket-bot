from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Position, Signal
from backend.app.db.session import get_db

router = APIRouter(tags=["signals"])


@router.get("/signals")
async def list_signals(
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
) -> list[dict]:
    result = await db.execute(
        select(Signal).order_by(Signal.created_at.desc()).limit(limit)
    )
    signals = result.scalars().all()
    return [
        {
            "id": s.id,
            "market_id": s.market_id,
            "fair_probability": s.fair_probability,
            "market_probability": s.market_probability,
            "edge": s.edge,
            "confidence": s.confidence,
            "position_size": s.position_size,
            "approved": s.approved,
            "rejection_reason": s.rejection_reason,
            "llm_summary": s.llm_summary,
            "created_at": s.created_at.isoformat(),
        }
        for s in signals
    ]


@router.get("/portfolio")
async def portfolio(db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(
        select(Position).where(Position.closed_at.is_(None))
    )
    positions = result.scalars().all()
    total_exposure = sum(p.exposure_usd for p in positions)
    return {
        "positions": [
            {
                "market_id": p.market_id,
                "side": p.side,
                "size": p.size,
                "avg_price": p.avg_price,
                "exposure_usd": p.exposure_usd,
                "mode": p.mode,
            }
            for p in positions
        ],
        "total_exposure_usd": total_exposure,
        "position_count": len(positions),
    }
