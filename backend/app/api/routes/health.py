from fastapi import APIRouter

from backend.app.config import get_settings
from backend.app.services.wallet_session import get_session_status

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    settings = get_settings()
    session = await get_session_status()
    return {
        "status": "ok",
        "trading_mode": settings.trading_mode,
        "live_trading_enabled": settings.live_trading_enabled,
        "wallet_connected": session["connected"],
        "wallet_address": session["address"],
        "bootstrap_complete": session["bootstrap_complete"],
        "redis_ok": session.get("redis_ok", True),
    }
