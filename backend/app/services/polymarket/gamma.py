import json
from typing import Any

import httpx
import structlog

from backend.app.config import Settings

log = structlog.get_logger(__name__)


class GammaClient:
    def __init__(self, settings: Settings) -> None:
        self._base = settings.gamma_api_url.rstrip("/")
        self._excluded = settings.excluded_tag_set
        self._included = settings.included_tag_set

    async def fetch_active_markets(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        params = {
            "active": "true",
            "closed": "false",
            "limit": limit,
            "offset": offset,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{self._base}/markets", params=params)
            resp.raise_for_status()
            data = resp.json()
        if isinstance(data, list):
            return data
        return data.get("data", data.get("markets", []))

    async def fetch_all_active_markets(self, page_size: int = 100, max_pages: int = 20) -> list[dict[str, Any]]:
        all_markets: list[dict[str, Any]] = []
        for page in range(max_pages):
            batch = await self.fetch_active_markets(limit=page_size, offset=page * page_size)
            if not batch:
                break
            all_markets.extend(batch)
            if len(batch) < page_size:
                break
        return all_markets

    def parse_token_ids(self, market: dict[str, Any]) -> tuple[str | None, str | None]:
        raw = market.get("clobTokenIds") or market.get("clob_token_ids")
        if not raw:
            return None, None
        if isinstance(raw, str):
            try:
                ids = json.loads(raw)
            except json.JSONDecodeError:
                ids = [t.strip() for t in raw.split(",") if t.strip()]
        else:
            ids = list(raw)
        if len(ids) >= 2:
            return str(ids[0]), str(ids[1])
        if len(ids) == 1:
            return str(ids[0]), None
        return None, None

    def extract_tags(self, market: dict[str, Any]) -> list[str]:
        tags: list[str] = []
        for key in ("tags", "tagSlugs", "tag_slugs"):
            val = market.get(key)
            if isinstance(val, list):
                for t in val:
                    if isinstance(t, str):
                        tags.append(t.lower())
                    elif isinstance(t, dict):
                        slug = t.get("slug") or t.get("label") or t.get("name")
                        if slug:
                            tags.append(str(slug).lower())
        category = market.get("category")
        if category:
            tags.append(str(category).lower())
        return list(dict.fromkeys(tags))

    def passes_filter(self, market: dict[str, Any], strict: bool = False) -> bool:
        tags = set(self.extract_tags(market))
        if tags & self._excluded:
            return False
        if not strict or not self._included:
            return True
        if tags & self._included:
            return True
        question = (market.get("question") or "").lower()
        return any(t in question for t in self._included)
