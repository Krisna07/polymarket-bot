import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import Settings
from backend.app.db.models import FeatureSnapshot, Market, Order, Position, Signal
from backend.app.features.engine import FeatureEngine
from backend.app.llm.reasoning import LLMReasoningService
from backend.app.ml.inference import MLInferenceService
from backend.app.risk.engine import RiskEngine

log = structlog.get_logger(__name__)


class TradePipelineService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._features = FeatureEngine()
        self._ml = MLInferenceService()
        self._risk = RiskEngine(settings)
        self._llm = LLMReasoningService(settings)

    async def run_feature_pass(self, session: AsyncSession) -> int:
        return await self._features.compute_for_active_markets(session)

    async def evaluate_trades(self, session: AsyncSession, limit: int = 30) -> int:
        exposure = await self._current_exposure_pct(session)
        result = await session.execute(
            select(Market, FeatureSnapshot)
            .join(FeatureSnapshot, FeatureSnapshot.market_id == Market.id)
            .where(Market.active.is_(True))
            .order_by(FeatureSnapshot.computed_at.desc())
            .limit(limit)
        )
        rows = result.all()
        signals_created = 0

        for market, feat in rows:
            mp = feat.market_probability or 0.5
            prediction = self._ml.predict(feat.features, mp)
            trade_signal = self._risk.evaluate(prediction, mp, exposure)

            llm_summary = None
            if self._settings.enable_llm:
                llm_result = await self._llm.analyze_market(
                    market.question, mp, feat.features
                )
                if llm_result:
                    llm_summary = llm_result.get("summary")

            signal = Signal(
                market_id=market.id,
                fair_probability=trade_signal.fair_probability,
                market_probability=trade_signal.market_probability,
                edge=trade_signal.edge,
                confidence=trade_signal.confidence,
                position_size=trade_signal.position_size,
                ml_score=trade_signal.ml_score,
                llm_summary=llm_summary,
                approved=trade_signal.approved,
                rejection_reason=trade_signal.rejection_reason,
            )
            session.add(signal)
            await session.flush()
            signals_created += 1

            if trade_signal.approved and market.yes_token_id:
                await self._execute_paper(
                    session, market, signal, trade_signal.position_size, mp
                )
                exposure += trade_signal.position_size

        await session.commit()
        log.info("trade_evaluation_done", signals=signals_created)
        return signals_created

    async def _current_exposure_pct(self, session: AsyncSession) -> float:
        result = await session.execute(
            select(func.coalesce(func.sum(Position.exposure_usd), 0.0)).where(
                Position.closed_at.is_(None)
            )
        )
        total_exposure = float(result.scalar() or 0)
        if self._settings.bankroll_usd <= 0:
            return 0.0
        return total_exposure / self._settings.bankroll_usd

    async def _execute_paper(
        self,
        session: AsyncSession,
        market: Market,
        signal: Signal,
        position_pct: float,
        price: float,
    ) -> None:
        size_usd = self._settings.bankroll_usd * position_pct
        shares = size_usd / max(price, 0.01)

        order = Order(
            signal_id=signal.id,
            market_id=market.id,
            token_id=market.yes_token_id or "",
            side="buy" if signal.edge > 0 else "sell",
            price=price,
            size=shares,
            status="filled",
            mode="paper",
        )
        session.add(order)

        session.add(
            Position(
                market_id=market.id,
                token_id=market.yes_token_id or "",
                side=order.side,
                size=shares,
                avg_price=price,
                exposure_usd=size_usd,
                mode="paper",
            )
        )
