from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from statistics import mean

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import Settings
from backend.app.db.models import Market, Order, OrderbookSnapshot, Position, Signal
from backend.app.services.crypto_feed import BinanceKlineFeed
from backend.app.services.orderbook_sync import OrderbookSyncService
from backend.app.services.redis_store import redis_get_json, redis_set_json

log = structlog.get_logger(__name__)


@dataclass
class GuardrailState:
    current_day: date
    day_start_equity: float
    realized_pnl_today: float = 0.0
    consecutive_losses: int = 0
    paused_until: datetime | None = None
    trading_halted_today: bool = False


@dataclass
class IndicatorState:
    price: float
    ema: float
    prev_rsi: float
    current_rsi: float
    current_volume: float
    avg_volume: float


class RotationTraderService:
    """Momentum re-entry strategy with strict stop/take-profit guardrails."""

    def __init__(
        self,
        settings: Settings,
        feed: BinanceKlineFeed | None = None,
    ) -> None:
        self._settings = settings
        self._sync = OrderbookSyncService(settings)
        self._feed = feed
        self._state_loaded = False
        self._guardrails = GuardrailState(
            current_day=datetime.now(timezone.utc).date(),
            day_start_equity=settings.bankroll_usd,
        )

    async def run_cycle(self, session: AsyncSession) -> dict[str, float | int | bool | str | None]:
        await self._load_state_once()
        self._roll_day_if_needed()
        await self._ensure_synthetic_markets(session)

        # Step 1: fetch latest market data into snapshots.
        synced = 0
        if not self._feed:
            synced = await self._sync.snapshot_all(session)

        # Step 2: evaluate open positions against OCO exits.
        closed = await self._process_open_positions(session)

        # Step 3: enforce daily drawdown lockout before new entries.
        await self._enforce_drawdown_guardrail(session)

        opened = 0
        reason: str | None = None
        if not self._can_trade_now():
            reason = self._pause_reason()
        else:
            opened = await self._try_open_positions(session)

        await session.commit()
        await self._save_state()
        return {
            "synced": synced,
            "opened": opened,
            "closed": closed,
            "trading_halted_today": self._guardrails.trading_halted_today,
            "consecutive_losses": self._guardrails.consecutive_losses,
            "realized_pnl_today": self._guardrails.realized_pnl_today,
            "pause_reason": reason,
        }

    def status(self) -> dict[str, object]:
        return {
            "current_day": self._guardrails.current_day.isoformat(),
            "day_start_equity": self._guardrails.day_start_equity,
            "realized_pnl_today": self._guardrails.realized_pnl_today,
            "consecutive_losses": self._guardrails.consecutive_losses,
            "paused_until": self._guardrails.paused_until.isoformat()
            if self._guardrails.paused_until
            else None,
            "trading_halted_today": self._guardrails.trading_halted_today,
        }

    async def _try_open_positions(self, session: AsyncSession) -> int:
        open_positions = await self._open_positions(session)
        max_open = self._settings.rotation_max_open_trades
        if len(open_positions) >= max_open:
            return 0

        exposure_usd = await self._open_exposure_usd(session)
        equity = max(0.0, self._settings.bankroll_usd + self._guardrails.realized_pnl_today)
        available = max(0.0, equity - exposure_usd)
        if available <= 0:
            return 0

        result = await session.execute(
            select(Market)
            .where(
                Market.active.is_(True),
                Market.closed.is_(False),
                Market.condition_id.like("crypto:%"),
            )
            .order_by(Market.updated_at.desc())
            .limit(80)
        )
        markets = result.scalars().all()

        opened = 0
        open_market_ids = {p.market_id for p in open_positions}
        for market in markets:
            if len(open_market_ids) >= max_open:
                break
            if market.id in open_market_ids:
                continue

            indicators = await self._indicator_state(session, market)
            if not indicators:
                continue

            trend_ok = indicators.price > indicators.ema
            momentum_ok = indicators.prev_rsi <= 30.0 < indicators.current_rsi
            volume_ok = (
                indicators.avg_volume > 0
                and indicators.current_volume
                >= indicators.avg_volume * self._settings.rotation_volume_multiplier
            )

            if not (trend_ok and momentum_ok and volume_ok):
                continue

            stake_usd = min(
                available,
                equity * self._settings.rotation_capital_fraction,
            )
            if stake_usd <= 0:
                break

            await self._open_long_with_oco(session, market, indicators, stake_usd)
            available -= stake_usd
            open_market_ids.add(market.id)
            opened += 1

        return opened

    async def _open_long_with_oco(
        self,
        session: AsyncSession,
        market: Market,
        indicators: IndicatorState,
        stake_usd: float,
    ) -> None:
        entry_price = indicators.price
        shares = stake_usd / max(entry_price, 0.000001)

        signal = Signal(
            market_id=market.id,
            fair_probability=indicators.ema,
            market_probability=entry_price,
            edge=(entry_price - indicators.ema),
            confidence=min(1.0, max(0.0, indicators.current_rsi / 100.0)),
            position_size=stake_usd / max(self._settings.bankroll_usd, 1.0),
            ml_score=indicators.current_rsi,
            llm_summary=(
                "rotation entry: price>EMA200, RSI cross above 30, volume surge"
            ),
            approved=True,
            rejection_reason=None,
        )
        session.add(signal)
        await session.flush()

        buy = Order(
            signal_id=signal.id,
            market_id=market.id,
            token_id=market.yes_token_id or "",
            side="buy",
            price=entry_price,
            size=shares,
            status="filled",
            mode="paper",
        )
        session.add(buy)

        position = Position(
            market_id=market.id,
            token_id=market.yes_token_id or "",
            side="buy",
            size=shares,
            avg_price=entry_price,
            exposure_usd=stake_usd,
            mode="paper",
        )
        session.add(position)
        await session.flush()

        stop_price = entry_price * (1.0 - self._settings.rotation_stop_loss_pct)
        take_price = entry_price * (1.0 + self._settings.rotation_take_profit_pct)
        group = f"oco:{position.id}"

        session.add(
            Order(
                signal_id=signal.id,
                market_id=market.id,
                token_id=position.token_id,
                side="sell",
                price=stop_price,
                size=shares,
                status="oco_open",
                mode="paper",
                external_order_id=f"{group}:sl",
            )
        )
        session.add(
            Order(
                signal_id=signal.id,
                market_id=market.id,
                token_id=position.token_id,
                side="sell",
                price=take_price,
                size=shares,
                status="oco_open",
                mode="paper",
                external_order_id=f"{group}:tp",
            )
        )

        log.info(
            "rotation_opened",
            market_id=market.id,
            entry_price=entry_price,
            stop_price=stop_price,
            take_price=take_price,
            stake_usd=stake_usd,
        )

    async def _process_open_positions(self, session: AsyncSession) -> int:
        positions = await self._open_positions(session)
        closed = 0

        market_map = await self._market_map(session, [p.market_id for p in positions])

        for position in positions:
            market = market_map.get(position.market_id)
            if not market:
                continue

            market_price = await self._latest_price(session, market)
            if market_price is None:
                continue

            result = await session.execute(
                select(Order).where(
                    Order.mode == "paper",
                    Order.status == "oco_open",
                    Order.external_order_id.like(f"oco:{position.id}:%"),
                )
            )
            oco_orders = result.scalars().all()
            if len(oco_orders) < 2:
                continue

            stop_order = next(
                (o for o in oco_orders if (o.external_order_id or "").endswith(":sl")),
                None,
            )
            take_order = next(
                (o for o in oco_orders if (o.external_order_id or "").endswith(":tp")),
                None,
            )
            if not stop_order or not take_order:
                continue

            filled: Order | None = None
            canceled: Order | None = None
            if market_price <= stop_order.price:
                filled = stop_order
                canceled = take_order
            elif market_price >= take_order.price:
                filled = take_order
                canceled = stop_order

            if not filled or not canceled:
                continue

            filled.status = "filled"
            canceled.status = "canceled"
            position.closed_at = datetime.now(timezone.utc)

            pnl = (filled.price - position.avg_price) * position.size
            self._record_closed_trade(pnl)
            closed += 1

            log.info(
                "rotation_closed",
                position_id=position.id,
                market_id=position.market_id,
                exit_price=filled.price,
                pnl=pnl,
            )

        return closed

    async def _indicator_state(
        self,
        session: AsyncSession,
        market: Market,
    ) -> IndicatorState | None:
        prices: list[float]
        volumes: list[float]

        if self._feed and market.condition_id.startswith("crypto:"):
            symbol = market.condition_id.split(":", 1)[1].lower()
            needed = max(
                self._settings.rotation_ema_period + 2,
                self._settings.rotation_rsi_period + 3,
                self._settings.rotation_volume_lookback + 2,
            )
            bars = await self._feed.recent_candles(symbol, limit=needed)
            prices = [c.close for c in bars]
            volumes = [c.volume for c in bars]
        else:
            needed = max(
                self._settings.rotation_ema_period + 2,
                self._settings.rotation_rsi_period + 3,
                self._settings.rotation_volume_lookback + 2,
            )
            result = await session.execute(
                select(OrderbookSnapshot)
                .where(OrderbookSnapshot.market_id == market.id)
                .order_by(OrderbookSnapshot.snapshot_at.desc())
                .limit(needed)
            )
            snapshots = list(reversed(result.scalars().all()))
            prices = [s.mid_price for s in snapshots if s.mid_price is not None]
            volumes = [self._snapshot_volume(s) for s in snapshots]

        if len(prices) < needed or len(volumes) < needed:
            return None

        ema = self._ema(prices, self._settings.rotation_ema_period)
        if ema is None:
            return None

        rsi_values = self._rsi_series(prices, self._settings.rotation_rsi_period)
        valid_rsi = [v for v in rsi_values if v is not None]
        if len(valid_rsi) < 2:
            return None

        lookback = self._settings.rotation_volume_lookback
        current_volume = volumes[-1]
        avg_volume = mean(volumes[-(lookback + 1) : -1])

        return IndicatorState(
            price=prices[-1],
            ema=ema,
            prev_rsi=valid_rsi[-2],
            current_rsi=valid_rsi[-1],
            current_volume=current_volume,
            avg_volume=avg_volume,
        )

    async def _latest_price(self, session: AsyncSession, market: Market) -> float | None:
        if self._feed and market.condition_id.startswith("crypto:"):
            symbol = market.condition_id.split(":", 1)[1].lower()
            return await self._feed.latest_price(symbol)

        result = await session.execute(
            select(OrderbookSnapshot.mid_price)
            .where(OrderbookSnapshot.market_id == market.id)
            .order_by(OrderbookSnapshot.snapshot_at.desc())
            .limit(1)
        )
        price = result.scalar_one_or_none()
        return float(price) if price is not None else None

    async def _open_positions(self, session: AsyncSession) -> list[Position]:
        result = await session.execute(
            select(Position).where(
                Position.mode == "paper",
                Position.closed_at.is_(None),
            )
        )
        return result.scalars().all()

    async def _open_exposure_usd(self, session: AsyncSession) -> float:
        result = await session.execute(
            select(func.coalesce(func.sum(Position.exposure_usd), 0.0)).where(
                Position.mode == "paper",
                Position.closed_at.is_(None),
            )
        )
        return float(result.scalar() or 0.0)

    async def _enforce_drawdown_guardrail(self, session: AsyncSession) -> None:
        if self._guardrails.trading_halted_today:
            return

        equity = self._settings.bankroll_usd + self._guardrails.realized_pnl_today
        if self._guardrails.day_start_equity <= 0:
            return

        drawdown = (
            self._guardrails.day_start_equity - equity
        ) / self._guardrails.day_start_equity
        if drawdown < self._settings.rotation_daily_drawdown_limit_pct:
            return

        self._guardrails.trading_halted_today = True
        await self._cancel_open_orders(session)
        log.error(
            "daily_drawdown_halt",
            drawdown=drawdown,
            threshold=self._settings.rotation_daily_drawdown_limit_pct,
        )

    async def _cancel_open_orders(self, session: AsyncSession) -> None:
        result = await session.execute(
            select(Order).where(
                Order.mode == "paper",
                Order.status.in_(["pending", "oco_open"]),
            )
        )
        for order in result.scalars().all():
            order.status = "canceled"

    async def _ensure_synthetic_markets(self, session: AsyncSession) -> None:
        for symbol in self._settings.rotation_stream_symbols:
            condition_id = f"crypto:{symbol}"
            result = await session.execute(
                select(Market).where(Market.condition_id == condition_id)
            )
            existing = result.scalar_one_or_none()
            if existing:
                existing.active = True
                existing.closed = False
                continue

            session.add(
                Market(
                    condition_id=condition_id,
                    slug=condition_id,
                    question=f"{symbol.upper()} spot rotation",
                    yes_token_id=symbol,
                    no_token_id=None,
                    tags=["crypto", "rotation"],
                    category="crypto",
                    active=True,
                    closed=False,
                    resolved=False,
                    resolution_outcome=None,
                    raw_metadata={"source": "binance_ws", "symbol": symbol},
                )
            )

    async def _market_map(
        self,
        session: AsyncSession,
        market_ids: list[int],
    ) -> dict[int, Market]:
        if not market_ids:
            return {}
        result = await session.execute(select(Market).where(Market.id.in_(market_ids)))
        return {m.id: m for m in result.scalars().all()}

    async def _load_state_once(self) -> None:
        if self._state_loaded:
            return
        payload = await redis_get_json("rotation:guardrails")
        if payload:
            self._guardrails.current_day = date.fromisoformat(
                payload.get("current_day", self._guardrails.current_day.isoformat())
            )
            self._guardrails.day_start_equity = float(
                payload.get("day_start_equity", self._settings.bankroll_usd)
            )
            self._guardrails.realized_pnl_today = float(
                payload.get("realized_pnl_today", 0.0)
            )
            self._guardrails.consecutive_losses = int(
                payload.get("consecutive_losses", 0)
            )
            paused_until = payload.get("paused_until")
            if paused_until:
                self._guardrails.paused_until = datetime.fromisoformat(paused_until)
            self._guardrails.trading_halted_today = bool(
                payload.get("trading_halted_today", False)
            )
        self._state_loaded = True

    async def _save_state(self) -> None:
        payload = {
            "current_day": self._guardrails.current_day.isoformat(),
            "day_start_equity": self._guardrails.day_start_equity,
            "realized_pnl_today": self._guardrails.realized_pnl_today,
            "consecutive_losses": self._guardrails.consecutive_losses,
            "paused_until": self._guardrails.paused_until.isoformat()
            if self._guardrails.paused_until
            else None,
            "trading_halted_today": self._guardrails.trading_halted_today,
        }
        await redis_set_json("rotation:guardrails", payload)

    def _record_closed_trade(self, pnl: float) -> None:
        self._guardrails.realized_pnl_today += pnl
        if pnl < 0:
            self._guardrails.consecutive_losses += 1
        else:
            self._guardrails.consecutive_losses = 0

        if (
            self._guardrails.consecutive_losses
            >= self._settings.rotation_max_consecutive_losses
        ):
            self._guardrails.paused_until = datetime.now(timezone.utc) + timedelta(
                hours=self._settings.rotation_pause_hours
            )
            log.warning(
                "consecutive_loss_pause",
                losses=self._guardrails.consecutive_losses,
                paused_until=self._guardrails.paused_until.isoformat(),
            )

    def _can_trade_now(self) -> bool:
        if self._guardrails.trading_halted_today:
            return False
        now = datetime.now(timezone.utc)
        if self._guardrails.paused_until and now < self._guardrails.paused_until:
            return False
        return True

    def _pause_reason(self) -> str:
        if self._guardrails.trading_halted_today:
            return "daily_drawdown_halt"
        if self._guardrails.paused_until:
            return f"paused_until_{self._guardrails.paused_until.isoformat()}"
        return "paused"

    def _roll_day_if_needed(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today == self._guardrails.current_day:
            return

        self._guardrails.current_day = today
        self._guardrails.day_start_equity = (
            self._settings.bankroll_usd + self._guardrails.realized_pnl_today
        )
        self._guardrails.realized_pnl_today = 0.0
        self._guardrails.trading_halted_today = False
        self._guardrails.consecutive_losses = 0
        self._guardrails.paused_until = None

    @staticmethod
    def _snapshot_volume(snapshot: OrderbookSnapshot) -> float:
        if snapshot.volume_24h is not None:
            return float(snapshot.volume_24h)
        return float((snapshot.bid_depth or 0.0) + (snapshot.ask_depth or 0.0))

    @staticmethod
    def _ema(prices: list[float], period: int) -> float | None:
        if len(prices) < period:
            return None
        k = 2.0 / (period + 1.0)
        ema = mean(prices[:period])
        for price in prices[period:]:
            ema = (price * k) + (ema * (1.0 - k))
        return ema

    @staticmethod
    def _rsi_series(prices: list[float], period: int) -> list[float | None]:
        if len(prices) < period + 1:
            return [None] * len(prices)

        deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        gains = [max(delta, 0.0) for delta in deltas]
        losses = [max(-delta, 0.0) for delta in deltas]

        avg_gain = mean(gains[:period])
        avg_loss = mean(losses[:period])

        rsi: list[float | None] = [None] * len(prices)

        def _to_rsi(g: float, l: float) -> float:
            if l == 0:
                return 100.0
            rs = g / l
            return 100.0 - (100.0 / (1.0 + rs))

        rsi[period] = _to_rsi(avg_gain, avg_loss)

        for i in range(period + 1, len(prices)):
            gain = gains[i - 1]
            loss = losses[i - 1]
            avg_gain = ((avg_gain * (period - 1)) + gain) / period
            avg_loss = ((avg_loss * (period - 1)) + loss) / period
            rsi[i] = _to_rsi(avg_gain, avg_loss)

        return rsi
