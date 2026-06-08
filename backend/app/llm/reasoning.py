import json
from typing import Any

import httpx
import structlog

from backend.app.config import Settings
from backend.app.services.llm_runtime import get_active_model

log = structlog.get_logger(__name__)

PORTFOLIO_ADVISOR_PROMPT = """You are a Polymarket investment advisor.

User wallet summary:
{wallet_summary}

Ranked market opportunities (model + order book data):
{markets_json}

Each market may also include external research:
- google_search: Google Custom Search results when configured
- google_news: Google News RSS results for the market keyword
- newsapi: latest articles if NewsAPI is configured
- related_markets: similar live Polymarket markets matched by keyword

Constraints:
- investable_usd is the max NEW capital to deploy
- per_trade_max_usd is max per single market
- Prefer positive edge (fair_prob > market_prob = buy YES, else buy NO)
- Use the external research when available to challenge or strengthen the model view
- Reason across the candidate set and choose the strongest trade, not just the highest raw score
- Return at most 5 recommendations

Respond ONLY with valid JSON:
{{
  "summary": "<2-3 sentences for the user>",
  "recommendations": [
    {{
      "market_id": <int>,
      "action": "buy_yes|buy_no|watch",
      "suggested_usd": <float>,
      "edge_pct": <float>,
      "confidence_pct": <float>,
      "reasoning": "<one sentence>"
    }}
  ]
}}
"""

TRADE_ANALYSIS_PROMPT = """You are a prediction market analyst. Given market data, estimate fair probability.

Current market probability (YES mid): {market_probability:.2%}
Market question: {question}

Recent features:
{features}

Order book summary:
{orderbook}

Respond ONLY with valid JSON:
{{
  "fair_probability": <float 0-1>,
  "confidence": <float 0-1>,
  "summary": "<one sentence>"
}}
"""


class LLMReasoningService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base = settings.ollama_base_url.rstrip("/")

    async def analyze_market(
        self,
        question: str,
        market_probability: float,
        features: dict[str, Any],
        orderbook: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        model = await get_active_model(self._settings)
        prompt = TRADE_ANALYSIS_PROMPT.format(
            market_probability=market_probability,
            question=question,
            features=json.dumps(features, indent=2),
            orderbook=json.dumps(orderbook or {}, indent=2),
        )
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{self._base}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            text = data.get("response", "")
            return json.loads(text)
        except Exception as e:
            log.warning("llm_analysis_failed", error=str(e))
            return None

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self._base}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    async def advise_portfolio(
        self,
        wallet_summary: dict[str, Any],
        opportunities: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        model = await get_active_model(self._settings)
        prompt = PORTFOLIO_ADVISOR_PROMPT.format(
            wallet_summary=json.dumps(wallet_summary, indent=2),
            markets_json=json.dumps(opportunities[:12], indent=2),
        )
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                resp = await client.post(
                    f"{self._base}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            return json.loads(data.get("response", "{}"))
        except Exception as e:
            log.warning("llm_advisor_failed", error=str(e))
            return None
