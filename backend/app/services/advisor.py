from typing import Any
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import Settings
from backend.app.db.models import FeatureSnapshot, Market, OrderbookSnapshot
from backend.app.llm.reasoning import LLMReasoningService
from backend.app.ml.inference import MLInferenceService
from backend.app.risk.engine import RiskEngine
from backend.app.services.llm_runtime import get_active_model
from backend.app.services.market_research import MarketResearchService
from backend.app.services.wallet_overview import get_wallet_overview


async def _gather_opportunities(
    session: AsyncSession,
    settings: Settings,
    limit: int = 25,
) -> list[dict[str, Any]]:
    ml = MLInferenceService()
    risk = RiskEngine(settings)

    result = await session.execute(
        select(Market, FeatureSnapshot)
        .join(FeatureSnapshot, FeatureSnapshot.market_id == Market.id)
        .where(Market.active.is_(True), Market.closed.is_(False))
        .order_by(FeatureSnapshot.computed_at.desc())
        .limit(limit * 3)
    )

    seen: set[int] = set()
    opportunities: list[dict[str, Any]] = []

    for market, feat in result.all():
        if market.id in seen:
            continue
        seen.add(market.id)

        mp = feat.market_probability or 0.5
        pred = ml.predict(feat.features, mp)
        trade = risk.evaluate(pred, mp, current_exposure_pct=0.0)
        score = abs(trade.edge) * trade.confidence

        ob_result = await session.execute(
            select(OrderbookSnapshot)
            .where(OrderbookSnapshot.market_id == market.id)
            .order_by(OrderbookSnapshot.snapshot_at.desc())
            .limit(1)
        )
        ob = ob_result.scalar_one_or_none()

        opportunities.append(
            {
                "market_id": market.id,
                "question": market.question[:200],
                "tags": market.tags or [],
                "market_probability": round(mp, 4),
                "fair_probability": round(trade.fair_probability, 4),
                "edge": round(trade.edge, 4),
                "edge_pct": round(trade.edge * 100, 2),
                "confidence": round(trade.confidence, 4),
                "confidence_pct": round(trade.confidence * 100, 1),
                "model_approved": trade.approved,
                "rejection_reason": trade.rejection_reason,
                "suggested_position_pct": round(trade.position_size * 100, 2),
                "score": round(score, 4),
                "spread": ob.spread if ob else None,
                "volume_24h": ob.volume_24h if ob else None,
                "book_imbalance": feat.features.get("book_imbalance"),
            }
        )
        if len(opportunities) >= limit:
            break

    opportunities.sort(key=lambda x: x["score"], reverse=True)
    return opportunities


def _rule_based_advice(
    wallet: dict[str, Any],
    opportunities: list[dict[str, Any]],
) -> dict[str, Any]:
    investable = wallet["investable_usd"]
    per_trade = wallet["per_trade_max_usd"]
    recs = []

    for opp in opportunities[:5]:
        edge = opp["edge"]
        if abs(edge) < 0.005:
            action = "watch"
            suggested = 0.0
        elif edge > 0:
            action = "buy_yes"
            suggested = min(
                per_trade, investable * max(opp["suggested_position_pct"], 1.0) / 100
            )
        else:
            action = "buy_no"
            suggested = min(
                per_trade, investable * max(opp["suggested_position_pct"], 1.0) / 100
            )

        recs.append(
            {
                "market_id": opp["market_id"],
                "question": opp["question"],
                "action": action,
                "suggested_usd": round(suggested, 2),
                "edge_pct": opp["edge_pct"],
                "confidence_pct": opp["confidence_pct"],
                "reasoning": (
                    f"Model edge {opp['edge_pct']:+.1f}% with "
                    f"{opp['confidence_pct']:.0f}% confidence."
                ),
            }
        )

    top = opportunities[0] if opportunities else None
    summary = (
        f"You can deploy up to ${investable:.2f} (max ${per_trade:.2f} per market). "
    )
    if top:
        summary += (
            f"Best scored: #{top['market_id']} at {top['edge_pct']:+.1f}% edge."
        )
    else:
        summary += "No market features yet — run bootstrap or wait for the worker."

    return {"summary": summary, "recommendations": recs, "source": "rules"}


def _simulated_no_funds_plan(
    wallet: dict[str, Any],
    opportunities: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if wallet.get("investable_usd", 0) > 0:
        return None
    if not opportunities:
        return None

    best = opportunities[0]
    paper_stake = max(10.0, min(wallet.get("per_trade_max_usd", 25.0), 25.0))
    edge = abs(float(best.get("edge", 0.0)))
    confidence = float(best.get("confidence", 0.0))
    expected_profit = round(paper_stake * edge, 2)

    return {
        "market_id": best["market_id"],
        "question": best.get("question", ""),
        "simulated_stake_usd": round(paper_stake, 2),
        "expected_profit_usd": expected_profit,
        "chance_pct": round(confidence * 100, 1),
        "note": "No available funds. Showing next best paper-style allocation until next trade window.",
    }


async def get_investment_advice(
    settings: Settings,
    session: AsyncSession,
    wallet_address: str,
    research_keyword: str | None = None,
) -> dict[str, Any]:
    wallet = await get_wallet_overview(settings, session, wallet_address)
    opportunities = await _gather_opportunities(session, settings)
    opportunities = await MarketResearchService(settings).enrich_opportunities(
        opportunities,
        keyword_override=research_keyword,
    )

    llm = LLMReasoningService(settings)
    advice = None
    source = "rules"
    llm_available = await llm.is_available()
    active_model = await get_active_model(settings)

    if settings.enable_llm or llm_available:
        advice = await llm.advise_portfolio(wallet, opportunities)
        if advice:
            advice["source"] = "ollama"
            source = "ollama"

    if not advice:
        advice = _rule_based_advice(wallet, opportunities)

    simulation = _simulated_no_funds_plan(wallet, opportunities)

    for rec in advice.get("recommendations", []):
        mid = rec.get("market_id")
        match = next((o for o in opportunities if o["market_id"] == mid), None)
        if match and not rec.get("question"):
            rec["question"] = match["question"]

    aggregate_counts = {
        "google_search": 0,
        "google_news": 0,
        "newsapi": 0,
        "related_markets": 0,
    }
    for opp in opportunities[: settings.advisor_research_market_limit]:
        research = opp.get("research") or {}
        aggregate_counts["google_search"] += len(research.get("google_search") or [])
        aggregate_counts["google_news"] += len(research.get("google_news") or [])
        aggregate_counts["newsapi"] += len(research.get("newsapi") or [])
        aggregate_counts["related_markets"] += len(research.get("related_markets") or [])

    return {
        "wallet": wallet,
        "opportunities": opportunities[:10],
        "advice": advice,
        "simulation": simulation,
        "research_enabled": True,
        "research_keyword": (research_keyword or "").strip() or None,
        "source": source,
        "ai_enabled": settings.enable_llm,
        "ai_connected": llm_available,
        "ai_model": active_model if llm_available else None,
        "research_sources": {
            "google_search": {
                "configured": True,
                "items": aggregate_counts["google_search"],
            },
            "google_news": {
                "configured": True,
                "items": aggregate_counts["google_news"],
            },
            "newsapi": {
                "configured": True,
                "items": aggregate_counts["newsapi"],
            },
            "related_markets": {
                "configured": True,
                "items": aggregate_counts["related_markets"],
            },
        },
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "analysis_interval_sec": 60,
    }
