from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.app.config import get_settings
from backend.app.services.bootstrap import run_bootstrap_cycle
from backend.app.services.wallet_session import get_session_status, save_wallet_session

router = APIRouter(prefix="/auth", tags=["auth"])


class WalletConnectRequest(BaseModel):
    address: str = Field(..., min_length=42, max_length=42)
    api_key: str
    secret: str
    passphrase: str
    signature_type: int = 0


@router.get("/status")
async def auth_status(address: str | None = None) -> dict:
    """Always returns 200 — never fails when Redis is down."""
    return await get_session_status(address)


@router.post("/connect")
async def connect_wallet(body: WalletConnectRequest) -> dict:
    if not body.address.startswith("0x"):
        raise HTTPException(status_code=400, detail="Invalid wallet address")

    try:
        await save_wallet_session(
            body.address,
            api_key=body.api_key,
            secret=body.secret,
            passphrase=body.passphrase,
            signature_type=body.signature_type,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    status = await get_session_status(body.address)
    return {"ok": True, **status}


@router.post("/bootstrap")
async def bootstrap_data(address: str = Query(..., min_length=42, max_length=42)) -> dict:
    status = await get_session_status(address)
    if not status.get("redis_ok", True):
        raise HTTPException(
            status_code=503,
            detail=status.get("detail") or "Redis unavailable",
        )
    if not status["connected"] or not status["has_api_keys"]:
        raise HTTPException(status_code=401, detail="Wallet not connected")

    settings = get_settings()
    stats = await run_bootstrap_cycle(settings, address)
    return {"ok": True, "stats": stats}
