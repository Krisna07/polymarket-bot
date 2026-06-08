from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import get_settings
from backend.app.db.session import get_db
from backend.app.services.wallet_overview import get_wallet_overview

router = APIRouter(prefix="/wallet", tags=["wallet"])


@router.get("/overview")
async def wallet_overview(
    address: str = Query(..., min_length=42, max_length=42),
    db: AsyncSession = Depends(get_db),
) -> dict:
    settings = get_settings()
    return await get_wallet_overview(settings, db, address)
