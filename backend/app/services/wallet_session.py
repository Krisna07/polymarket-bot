from typing import Any

from backend.app.services.redis_store import (
    redis_get,
    redis_get_json,
    redis_ping,
    redis_set,
    redis_set_json,
)

SESSION_PREFIX = "wallet_session:"
ACTIVE_SESSION_KEY = "wallet_session:active"


def _normalize_address(address: str) -> str:
    return address.strip().lower()


def session_key(address: str) -> str:
    return f"{SESSION_PREFIX}{_normalize_address(address)}"


def _disconnected_status(
    address: str | None = None, *, redis_ok: bool = True, detail: str | None = None
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "connected": False,
        "address": _normalize_address(address) if address else None,
        "has_api_keys": False,
        "bootstrap_complete": False,
        "redis_ok": redis_ok,
    }
    if detail:
        out["detail"] = detail
    return out


async def save_wallet_session(
    address: str,
    *,
    api_key: str,
    secret: str,
    passphrase: str,
    signature_type: int = 0,
) -> None:
    if not await redis_ping():
        raise RuntimeError(
            "Redis is not available. Start it with: docker compose up -d redis"
        )

    normalized = _normalize_address(address)
    payload = {
        "address": normalized,
        "api_key": api_key,
        "secret": secret,
        "passphrase": passphrase,
        "signature_type": signature_type,
        "bootstrap_complete": False,
    }
    ok = await redis_set_json(session_key(normalized), payload)
    if not ok:
        raise RuntimeError("Failed to save wallet session to Redis")

    if not await redis_set(ACTIVE_SESSION_KEY, normalized, ttl_sec=604_800):
        raise RuntimeError("Failed to save active wallet session to Redis")


async def mark_bootstrap_complete(address: str) -> None:
    key = session_key(address)
    session = await redis_get_json(key)
    if not session:
        return
    session["bootstrap_complete"] = True
    await redis_set_json(key, session)


async def get_wallet_session(address: str | None = None) -> dict[str, Any] | None:
    if not await redis_ping():
        return None

    if address:
        return await redis_get_json(session_key(address))

    active = await redis_get(ACTIVE_SESSION_KEY)
    if not active:
        return None

    return await redis_get_json(session_key(active))


async def get_session_status(address: str | None = None) -> dict[str, Any]:
    redis_ok = await redis_ping()
    if not redis_ok:
        return _disconnected_status(
            address,
            redis_ok=False,
            detail="Redis unavailable. Run: docker compose up -d redis",
        )

    session = await get_wallet_session(address)
    if not session:
        return _disconnected_status(address, redis_ok=True)

    return {
        "connected": True,
        "address": session.get("address"),
        "has_api_keys": bool(session.get("api_key")),
        "bootstrap_complete": bool(session.get("bootstrap_complete")),
        "redis_ok": True,
    }
