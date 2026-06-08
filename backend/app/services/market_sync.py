from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import Settings
from backend.app.db.models import Market
from backend.app.services.polymarket.gamma import GammaClient

log = structlog.get_logger(__name__)


def _parse_end_date(market: dict[str, Any]) -> datetime | None:
    for key in ("endDate", "end_date", "endDateIso"):
        val = market.get(key)
        if not val:
            continue
        if isinstance(val, (int, float)):
            return datetime.fromtimestamp(val / 1000 if val > 1e12 else val, tz=timezone.utc)
        try:
            return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
        except ValueError:
            continue
    return None


class MarketSyncService:
    def __init__(self, settings: Settings) -> None:
        self._gamma = GammaClient(settings)
        self._settings = settings

    async def sync(self, session: AsyncSession) -> dict[str, int]:
        raw_markets = await self._gamma.fetch_all_active_markets()
        filtered = [
            m
            for m in raw_markets
            if self._gamma.passes_filter(m, strict=self._settings.strict_market_filter)
        ]
        log.info("market_sync_fetched", total=len(raw_markets), filtered=len(filtered))

        upserted = 0
        for raw in filtered:
            condition_id = raw.get("conditionId") or raw.get("condition_id")
            if not condition_id:
                continue

            yes_id, no_id = self._gamma.parse_token_ids(raw)
            tags = self._gamma.extract_tags(raw)

            result = await session.execute(
                select(Market).where(Market.condition_id == condition_id)
            )
            existing = result.scalar_one_or_none()

            fields = {
                "slug": raw.get("slug"),
                "question": raw.get("question") or raw.get("title") or "",
                "yes_token_id": yes_id,
                "no_token_id": no_id,
                "tags": tags,
                "category": raw.get("category"),
                "end_date": _parse_end_date(raw),
                "active": bool(raw.get("active", True)),
                "closed": bool(raw.get("closed", False)),
                "raw_metadata": raw,
            }

            if existing:
                for k, v in fields.items():
                    setattr(existing, k, v)
            else:
                session.add(Market(condition_id=condition_id, **fields))
            upserted += 1

        await session.commit()
        return {"fetched": len(raw_markets), "filtered": len(filtered), "upserted": upserted}
