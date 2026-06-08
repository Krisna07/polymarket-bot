from typing import Any

import httpx
import structlog

from backend.app.config import Settings

log = structlog.get_logger(__name__)


class DataApiClient:
    def __init__(self, settings: Settings) -> None:
        self._base = settings.data_api_url.rstrip("/")
        self._gamma = settings.gamma_api_url.rstrip("/")

    async def get_profile(self, address: str) -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{self._gamma}/public-profile",
                params={"address": address},
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()

    async def get_portfolio_value(self, user_address: str) -> float:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{self._base}/value",
                params={"user": user_address},
            )
            resp.raise_for_status()
            data = resp.json()
        if isinstance(data, list) and data:
            try:
                return float(data[0].get("value", 0) or 0)
            except (TypeError, ValueError):
                return 0.0
        if isinstance(data, dict):
            return float(data.get("value", 0) or 0)
        return 0.0

    async def get_positions(self, user_address: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{self._base}/positions",
                params={"user": user_address},
            )
            resp.raise_for_status()
            data = resp.json()
        return data if isinstance(data, list) else []

    async def get_open_interest(self, condition_id: str) -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{self._base}/oi",
                params={"market": condition_id},
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
