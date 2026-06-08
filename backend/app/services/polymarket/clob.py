from typing import Any

import httpx
import structlog

from backend.app.config import Settings

log = structlog.get_logger(__name__)


class ClobClient:
    """Public CLOB read endpoints (no auth required)."""

    def __init__(self, settings: Settings) -> None:
        self._base = settings.clob_api_url.rstrip("/")

    async def get_order_book(self, token_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(f"{self._base}/book", params={"token_id": token_id})
            resp.raise_for_status()
            return resp.json()

    async def get_midpoint(self, token_id: str) -> float | None:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(f"{self._base}/midpoint", params={"token_id": token_id})
            resp.raise_for_status()
            data = resp.json()
        mid = data.get("mid") if isinstance(data, dict) else data
        try:
            return float(mid) if mid is not None else None
        except (TypeError, ValueError):
            return None

    async def get_price(self, token_id: str, side: str = "buy") -> float | None:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{self._base}/price",
                params={"token_id": token_id, "side": side},
            )
            resp.raise_for_status()
            data = resp.json()
        price = data.get("price") if isinstance(data, dict) else data
        try:
            return float(price) if price is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def summarize_book(book: dict[str, Any]) -> dict[str, float | None]:
        bids = book.get("bids") or []
        asks = book.get("asks") or []

        def _best(levels: list, idx: int = 0) -> float | None:
            if not levels:
                return None
            level = levels[idx]
            price = level.get("price") if isinstance(level, dict) else level[0]
            try:
                return float(price)
            except (TypeError, ValueError, IndexError):
                return None

        def _depth(levels: list, n: int = 5) -> float:
            total = 0.0
            for level in levels[:n]:
                if isinstance(level, dict):
                    total += float(level.get("size", 0) or 0)
                elif isinstance(level, (list, tuple)) and len(level) > 1:
                    total += float(level[1])
            return total

        best_bid = _best(bids)
        best_ask = _best(asks)
        mid = None
        spread = None
        if best_bid is not None and best_ask is not None:
            mid = (best_bid + best_ask) / 2
            spread = best_ask - best_bid

        volume_24h = None
        for key in ("volume_24h", "volume24h", "volume", "volume24Hour"):
            raw_val = book.get(key)
            if raw_val is None:
                continue
            try:
                volume_24h = float(raw_val)
                break
            except (TypeError, ValueError):
                continue

        return {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid_price": mid,
            "spread": spread,
            "bid_depth": _depth(bids),
            "ask_depth": _depth(asks),
            "volume_24h": volume_24h,
        }
