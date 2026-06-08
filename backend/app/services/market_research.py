from __future__ import annotations

import asyncio
import time
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote_plus

import feedparser
import httpx

from backend.app.config import Settings
from backend.app.services.polymarket.gamma import GammaClient

_STOPWORDS = {
    "a", "an", "and", "are", "be", "by", "for", "from", "if", "in",
    "is", "of", "on", "or", "the", "to", "will", "with", "who", "what",
    "when", "where", "why", "how", "before", "after", "than", "most",
}

_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_CACHE_LOCK = asyncio.Lock()


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._current_href: str | None = None
        self._buffer: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self._current_href = href
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._current_href:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._current_href:
            return
        text = " ".join(part.strip() for part in self._buffer if part.strip()).strip()
        if text:
            self.links.append((self._current_href, text))
        self._current_href = None
        self._buffer = []


class MarketResearchService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._gamma = GammaClient(settings)

    async def enrich_opportunities(
        self,
        opportunities: list[dict[str, Any]],
        keyword_override: str | None = None,
    ) -> list[dict[str, Any]]:
        limit = max(0, self._settings.advisor_research_market_limit)
        if limit <= 0:
            return opportunities

        enriched = list(opportunities)
        tasks = [
            self._research_for_opportunity(opportunity, keyword_override=keyword_override)
            for opportunity in enriched[:limit]
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for opportunity, result in zip(enriched[:limit], results):
            if isinstance(result, dict):
                opportunity["research"] = result
            else:
                opportunity["research"] = None
        return enriched

    async def _research_for_opportunity(
        self,
        opportunity: dict[str, Any],
        keyword_override: str | None = None,
    ) -> dict[str, Any]:
        keyword = (keyword_override or "").strip() or self._extract_keyword(
            opportunity.get("question", ""),
            opportunity.get("tags") or [],
        )
        google_search, google_news, newsapi, related_markets = await asyncio.gather(
            self._cached_source("google_search", keyword, self._google_search),
            self._cached_source("google_news", keyword, self._google_news),
            self._cached_source("newsapi", keyword, self._newsapi),
            self._cached_source("related_markets", keyword, self._related_polymarket),
        )
        return {
            "keyword": keyword,
            "google_search": google_search,
            "google_news": google_news,
            "newsapi": newsapi,
            "related_markets": related_markets,
        }

    async def _cached_source(
        self,
        source_name: str,
        keyword: str,
        fetcher: Any,
    ) -> list[dict[str, Any]]:
        cache_key = f"{source_name}:{keyword.lower().strip()}"
        now = time.monotonic()

        async with _CACHE_LOCK:
            cached = _CACHE.get(cache_key)
            if cached and cached[0] > now:
                return cached[1]

        items = await self._safe_fetch(fetcher, keyword)
        ttl = max(0, self._settings.advisor_research_cache_ttl_sec)
        if ttl > 0:
            async with _CACHE_LOCK:
                _CACHE[cache_key] = (time.monotonic() + ttl, items)
        return items

    async def _safe_fetch(self, fetcher: Any, keyword: str) -> list[dict[str, Any]]:
        timeout = max(1.0, float(self._settings.advisor_research_timeout_sec))
        try:
            result = await asyncio.wait_for(fetcher(keyword), timeout=timeout)
        except Exception:
            return []
        return result if isinstance(result, list) else []

    def _extract_keyword(self, question: str, tags: list[str]) -> str:
        tag_candidates = [tag.strip() for tag in tags if isinstance(tag, str) and tag.strip()]
        if tag_candidates:
            return " ".join(tag_candidates[:2])

        words = []
        for raw in question.replace("?", " ").replace(",", " ").split():
            word = raw.strip().lower()
            if len(word) < 3 or word in _STOPWORDS:
                continue
            words.append(raw.strip())
        if not words:
            return question[:64].strip() or "polymarket"
        return " ".join(words[:4])

    async def _google_news(self, keyword: str) -> list[dict[str, Any]]:
        url = f"https://news.google.com/rss/search?q={quote_plus(keyword)}"
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
        feed = feedparser.parse(response.text)
        items: list[dict[str, Any]] = []
        for entry in feed.entries[: self._settings.advisor_research_items_limit]:
            items.append(
                {
                    "title": entry.get("title"),
                    "link": entry.get("link"),
                    "published": entry.get("published"),
                    "source": getattr(entry.get("source"), "title", None)
                    if entry.get("source")
                    else None,
                }
            )
        return items

    async def _google_search(self, keyword: str) -> list[dict[str, Any]]:
        if not self._settings.google_search_api_key or not self._settings.google_search_cx:
            return await self._duckduckgo_search(keyword)

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                "https://www.googleapis.com/customsearch/v1",
                params={
                    "key": self._settings.google_search_api_key,
                    "cx": self._settings.google_search_cx,
                    "q": keyword,
                    "num": min(10, self._settings.advisor_research_items_limit),
                },
            )
            response.raise_for_status()
            payload = response.json()

        items = payload.get("items", []) if isinstance(payload, dict) else []
        return [
            {
                "title": item.get("title"),
                "link": item.get("link"),
                "snippet": item.get("snippet"),
                "displayLink": item.get("displayLink"),
            }
            for item in items[: self._settings.advisor_research_items_limit]
            if isinstance(item, dict)
        ]

    async def _duckduckgo_search(self, keyword: str) -> list[dict[str, Any]]:
        # Free fallback when custom search credentials are not configured.
        url = f"https://lite.duckduckgo.com/lite/?q={quote_plus(keyword)}"
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()

        parser = _LinkParser()
        parser.feed(response.text)

        items: list[dict[str, Any]] = []
        for link, title in parser.links:
            if not link.startswith("http"):
                continue
            if "duckduckgo.com" in link and ("y.js" in link or "duckduckgo.com/l/" in link):
                continue
            items.append(
                {
                    "title": title,
                    "link": link,
                    "snippet": "",
                    "displayLink": None,
                }
            )
            if len(items) >= self._settings.advisor_research_items_limit:
                break
        return items

    async def _newsapi(self, keyword: str) -> list[dict[str, Any]]:
        if not self._settings.newsapi_key:
            return await self._bing_news(keyword)

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": keyword,
                    "sortBy": "publishedAt",
                    "pageSize": self._settings.advisor_research_items_limit,
                    "language": "en",
                    "apiKey": self._settings.newsapi_key,
                },
            )
            response.raise_for_status()
            payload = response.json()

        articles = payload.get("articles", []) if isinstance(payload, dict) else []
        return [
            {
                "title": article.get("title"),
                "url": article.get("url"),
                "publishedAt": article.get("publishedAt"),
                "source": (article.get("source") or {}).get("name"),
                "description": article.get("description"),
            }
            for article in articles[: self._settings.advisor_research_items_limit]
            if isinstance(article, dict)
        ]

    async def _bing_news(self, keyword: str) -> list[dict[str, Any]]:
        url = f"https://www.bing.com/news/search?q={quote_plus(keyword)}&format=rss"
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
        feed = feedparser.parse(response.text)
        items: list[dict[str, Any]] = []
        for entry in feed.entries[: self._settings.advisor_research_items_limit]:
            items.append(
                {
                    "title": entry.get("title"),
                    "url": entry.get("link"),
                    "publishedAt": entry.get("published"),
                    "source": None,
                    "description": entry.get("summary"),
                }
            )
        return items

    async def _related_polymarket(self, keyword: str) -> list[dict[str, Any]]:
        markets = await self._gamma.fetch_active_markets(limit=100, offset=0)
        keyword_terms = [term.lower() for term in keyword.split() if term.strip()]
        ranked: list[tuple[int, dict[str, Any]]] = []

        for market in markets:
            text = " ".join(
                [
                    str(market.get("question") or market.get("title") or ""),
                    str(market.get("category") or ""),
                    " ".join(self._gamma.extract_tags(market)),
                ]
            ).lower()
            score = sum(1 for term in keyword_terms if term in text)
            if score <= 0:
                continue
            ranked.append((score, market))

        ranked.sort(key=lambda item: item[0], reverse=True)
        related = []
        for score, market in ranked[: self._settings.advisor_research_items_limit]:
            related.append(
                {
                    "question": market.get("question") or market.get("title"),
                    "category": market.get("category"),
                    "score": score,
                    "slug": market.get("slug"),
                    "condition_id": market.get("conditionId") or market.get("condition_id"),
                }
            )
        return related
