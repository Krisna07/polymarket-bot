import asyncio
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, text

from backend.app.config import Settings, get_settings
from backend.app.db.models import Market, Order, OrderbookSnapshot, Position, Signal, SimulationSession
from backend.app.db.session import AsyncSessionLocal
from backend.app.db.session import get_db
from backend.app.logging_config import configure_logging
from backend.app.services.crypto_feed import BinanceKlineFeed
from backend.app.services.advisor import _gather_opportunities
from backend.app.services.rotation_trader import RotationTraderService

router = APIRouter()

# Global variables to manage bot state
bot_task: asyncio.Task | None = None
bot_running: bool = False
bot_runtime: dict = {"last_cycle": None, "rotation": None, "feed": None, "strategy_mode": "rotation"}


class SimulationStartRequest(BaseModel):
    amount_usd: float = Field(..., gt=0)
    stop_loss_pct: float | None = Field(default=None, gt=0, le=100)
    allocation_mode: Literal["single", "distributed"] = "distributed"
    max_positions: int = Field(default=3, ge=1, le=10)


class BotStartRequest(BaseModel):
    stop_loss_pct: float | None = Field(default=None, gt=0, le=100)
    strategy_mode: Literal["rotation", "fast"] = "rotation"


def _build_strategy_settings(settings: Settings, strategy_mode: str) -> Settings:
    profile = settings.model_copy(deep=True)
    profile.trading_mode = "paper"

    if strategy_mode == "fast":
        profile.rotation_rsi_period = profile.fast_rotation_rsi_period
        profile.rotation_ema_period = profile.fast_rotation_ema_period
        profile.rotation_volume_lookback = profile.fast_rotation_volume_lookback
        profile.rotation_volume_multiplier = profile.fast_rotation_volume_multiplier
        profile.rotation_capital_fraction = profile.fast_rotation_capital_fraction
        profile.rotation_stop_loss_pct = profile.fast_rotation_stop_loss_pct
        profile.rotation_take_profit_pct = profile.fast_rotation_take_profit_pct
        profile.rotation_daily_drawdown_limit_pct = profile.fast_rotation_daily_drawdown_limit_pct
        profile.rotation_max_consecutive_losses = profile.fast_rotation_max_consecutive_losses
        profile.rotation_pause_hours = profile.fast_rotation_pause_hours
        profile.rotation_max_open_trades = profile.fast_rotation_max_open_trades
        profile.rotation_loop_sleep_sec = profile.fast_rotation_loop_sleep_sec

    return profile


async def _latest_simulation_session(db) -> SimulationSession | None:
    result = await db.execute(
        select(SimulationSession).order_by(SimulationSession.created_at.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def _active_simulation_session(db) -> SimulationSession | None:
    result = await db.execute(
        select(SimulationSession)
        .where(SimulationSession.active.is_(True))
        .order_by(SimulationSession.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _ensure_simulation_table(db) -> None:
    await db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS simulation_sessions (
                id SERIAL PRIMARY KEY,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                principal_usd DOUBLE PRECISION NOT NULL,
                max_loss_pct DOUBLE PRECISION NULL,
                started_at TIMESTAMPTZ DEFAULT now(),
                stopped_at TIMESTAMPTZ NULL,
                stop_reason VARCHAR(128) NULL,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now()
            )
            """
        )
    )
    await db.execute(text("ALTER TABLE simulation_sessions ADD COLUMN IF NOT EXISTS max_loss_pct DOUBLE PRECISION NULL"))
    await db.commit()


async def _mode_performance(db, mode: str, principal_usd: float) -> dict[str, float]:
    positions_result = await db.execute(
        select(Position).where(Position.mode == mode, Position.closed_at.is_(None))
    )
    positions = positions_result.scalars().all()

    invested = 0.0
    current_value = 0.0

    for pos in positions:
        ob_result = await db.execute(
            select(OrderbookSnapshot)
            .where(OrderbookSnapshot.market_id == pos.market_id)
            .order_by(OrderbookSnapshot.snapshot_at.desc())
            .limit(1)
        )
        ob = ob_result.scalar_one_or_none()
        mark_price = float(ob.mid_price) if ob and ob.mid_price is not None else float(pos.avg_price)
        direction = 1.0 if pos.side == "buy" else -1.0
        pnl = (mark_price - float(pos.avg_price)) * float(pos.size) * direction
        invested += float(pos.exposure_usd)
        current_value += float(pos.exposure_usd) + pnl

    principal = max(0.0, float(principal_usd))
    total_pnl = current_value - principal
    pnl_pct = (total_pnl / principal * 100.0) if principal > 0 else 0.0
    return {
        "invested_usd": invested,
        "current_value_usd": current_value,
        "total_pnl_usd": total_pnl,
        "total_pnl_pct": pnl_pct,
    }


def _market_icon_url(market: Market | None) -> str | None:
    if not market or not market.raw_metadata:
        return None
    raw = market.raw_metadata
    for key in ("icon", "iconUrl", "image", "imageUrl", "thumbnail"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


async def _prepare_simulation_legs(
    db,
    settings: Settings,
    opportunities: list[dict],
    amount_usd: float,
    allocation_mode: str,
    max_positions: int,
) -> list[dict[str, object]]:
    ranked = [item for item in opportunities if item.get("model_approved")]
    if not ranked:
        ranked = opportunities

    if not ranked:
        return []

    ranked = ranked[:1] if allocation_mode == "single" else ranked[:max_positions]
    market_ids = [int(item["market_id"]) for item in ranked]
    markets_result = await db.execute(select(Market).where(Market.id.in_(market_ids)))
    markets = {market.id: market for market in markets_result.scalars().all()}

    weighted_candidates: list[tuple[dict[str, object], Market, float]] = []
    for item in ranked:
        market = markets.get(int(item["market_id"]))
        if not market or not market.yes_token_id:
            continue
        score = max(0.0001, abs(float(item.get("score") or 0.0)))
        weighted_candidates.append((item, market, score))

    if not weighted_candidates:
        return []

    if allocation_mode == "single" or len(weighted_candidates) == 1:
        weights = [1.0]
    else:
        weights = [candidate[2] for candidate in weighted_candidates]

    total_weight = sum(weights) or float(len(weighted_candidates))
    allocations: list[float] = []
    remaining = float(amount_usd)

    for index, weight in enumerate(weights):
        if index == len(weights) - 1:
            allocation = round(max(0.0, remaining), 2)
        else:
            allocation = round(float(amount_usd) * (weight / total_weight), 2)
            allocation = min(allocation, round(max(0.0, remaining), 2))
        remaining -= allocation
        allocations.append(allocation)

    legs: list[dict[str, object]] = []
    for allocation, (item, market, _) in zip(allocations, weighted_candidates):
        if allocation <= 0:
            continue

        entry_price = float(item.get("market_probability") or 0.5)
        entry_price = min(0.99, max(0.01, entry_price))
        edge = float(item.get("edge") or 0.0)
        side = "buy" if edge >= 0 else "sell"
        shares = allocation / entry_price
        position_size = allocation / max(float(amount_usd), 1.0)

        signal = Signal(
            market_id=market.id,
            fair_probability=float(item.get("fair_probability") or entry_price),
            market_probability=entry_price,
            edge=edge,
            confidence=float(item.get("confidence") or 0.0),
            position_size=position_size,
            ml_score=float(item.get("score") or 0.0),
            llm_summary=("simulation entry: top-ranked market" if allocation_mode == "single" else "simulation entry: distributed basket"),
            approved=True,
            rejection_reason=None,
        )
        db.add(signal)
        await db.flush()

        db.add(
            Order(
                signal_id=signal.id,
                market_id=market.id,
                token_id=market.yes_token_id,
                side=side,
                price=entry_price,
                size=shares,
                status="filled",
                mode="simulation",
            )
        )
        db.add(
            Position(
                market_id=market.id,
                token_id=market.yes_token_id,
                side=side,
                size=shares,
                avg_price=entry_price,
                exposure_usd=allocation,
                mode="simulation",
            )
        )

        legs.append(
            {
                "market_id": market.id,
                "question": market.question,
                "side": side,
                "entry_price": entry_price,
                "shares": shares,
                "exposure_usd": allocation,
                "edge": edge,
                "score": float(item.get("score") or 0.0),
            }
        )

    return legs

async def run_bot_loop(stop_loss_pct: float | None = None, strategy_mode: str = "rotation"):
    """Continuously run the selected strategy loop in paper mode."""
    global bot_running, bot_task
    configure_logging()
    settings = _build_strategy_settings(get_settings(), strategy_mode)
    feed = BinanceKlineFeed(settings) if settings.rotation_use_binance_ws else None
    if feed:
        await feed.start()
    trader = RotationTraderService(settings, feed=feed)

    try:
        while True:
            async with AsyncSessionLocal() as session:
                cycle = await trader.run_cycle(session)
                bot_runtime["last_cycle"] = cycle
                bot_runtime["rotation"] = trader.status()
                bot_runtime["feed"] = feed.status() if feed else None
                bot_runtime["stop_loss_pct"] = stop_loss_pct
                bot_runtime["strategy_mode"] = strategy_mode

                if stop_loss_pct is not None and settings.bankroll_usd > 0:
                    perf = await _mode_performance(session, mode="paper", principal_usd=settings.bankroll_usd)
                    bot_runtime["performance"] = perf
                    if perf["total_pnl_pct"] <= -float(stop_loss_pct):
                        bot_runtime["stop_reason"] = (
                            f"Auto-stopped at {perf['total_pnl_pct']:.2f}% (limit -{stop_loss_pct:.2f}%)."
                        )
                        break

            await asyncio.sleep(settings.rotation_loop_sleep_sec)
    finally:
        if feed:
            await feed.stop()
        bot_running = False
        bot_task = None

@router.post("/bot/start")
async def start_bot(payload: BotStartRequest | None = None):
    global bot_task, bot_running, bot_runtime
    if bot_running:
        raise HTTPException(status_code=400, detail="Bot is already running")
    stop_loss_pct = float(payload.stop_loss_pct) if payload and payload.stop_loss_pct is not None else None
    strategy_mode = payload.strategy_mode if payload else "rotation"
    bot_runtime = {
        "last_cycle": None,
        "rotation": None,
        "feed": None,
        "strategy_mode": strategy_mode,
        "stop_loss_pct": stop_loss_pct,
        "performance": None,
        "stop_reason": None,
    }
    # Start the background task
    bot_task = asyncio.create_task(run_bot_loop(stop_loss_pct=stop_loss_pct, strategy_mode=strategy_mode))
    bot_running = True
    return {"status": "started", "stop_loss_pct": stop_loss_pct, "strategy_mode": strategy_mode}

@router.post("/bot/stop")
async def stop_bot():
    global bot_task, bot_running, bot_runtime
    if not bot_running or bot_task is None:
        raise HTTPException(status_code=400, detail="Bot is not running")
    bot_task.cancel()
    try:
        await bot_task
    except asyncio.CancelledError:
        pass
    bot_running = False
    bot_task = None
    bot_runtime = {"last_cycle": None, "rotation": None, "feed": None, "strategy_mode": "rotation"}
    return {"status": "stopped"}

@router.get("/bot/status")
async def bot_status():
    return {
        "running": bot_running,
        "last_cycle": bot_runtime.get("last_cycle"),
        "rotation": bot_runtime.get("rotation"),
        "feed": bot_runtime.get("feed"),
        "strategy_mode": bot_runtime.get("strategy_mode"),
        "stop_loss_pct": bot_runtime.get("stop_loss_pct"),
        "performance": bot_runtime.get("performance"),
        "stop_reason": bot_runtime.get("stop_reason"),
    }


@router.get("/bot/activity")
async def bot_activity(
    db=Depends(get_db),
    limit: int = 10,
):
    result = await db.execute(
        select(Order, Signal, Market)
        .join(Signal, Signal.id == Order.signal_id, isouter=True)
        .join(Market, Market.id == Order.market_id)
        .where(Order.mode == "paper")
        .order_by(Order.created_at.desc())
        .limit(limit)
    )

    trades = []
    total_expected_profit_usd = 0.0

    for order, signal, market in result.all():
        exposure_usd = float(order.price * order.size)
        edge = float(signal.edge) if signal else 0.0
        expected_profit_usd = abs(edge) * float(order.size)
        total_expected_profit_usd += expected_profit_usd

        trades.append(
            {
                "order_id": order.id,
                "market_id": order.market_id,
                "question": market.question,
                "side": order.side,
                "status": order.status,
                "price": float(order.price),
                "shares": float(order.size),
                "exposure_usd": exposure_usd,
                "fair_probability": float(signal.fair_probability) if signal else None,
                "market_probability": float(signal.market_probability) if signal else float(order.price),
                "edge": edge,
                "confidence": float(signal.confidence) if signal else None,
                "expected_profit_usd": expected_profit_usd,
                "expected_return_pct": (expected_profit_usd / exposure_usd * 100.0)
                if exposure_usd > 0
                else 0.0,
                "created_at": order.created_at.isoformat(),
            }
        )

    return {
        "running": bot_running,
        "trade_count": len(trades),
        "total_expected_profit_usd": total_expected_profit_usd,
        "trades": trades,
    }


@router.post("/bot/simulation/start")
async def start_simulation(
    payload: SimulationStartRequest,
    db=Depends(get_db),
):
    await _ensure_simulation_table(db)
    settings = get_settings()
    opportunities = await _gather_opportunities(db, settings, limit=40)
    if not opportunities:
        raise HTTPException(status_code=400, detail="No opportunities available for simulation yet")

    # Keep one clean active simulation session by clearing prior simulated positions/orders.
    await db.execute(delete(Position).where(Position.mode == "simulation"))
    await db.execute(delete(Order).where(Order.mode == "simulation"))

    legs = await _prepare_simulation_legs(
        db,
        settings,
        opportunities,
        float(payload.amount_usd),
        payload.allocation_mode,
        int(payload.max_positions),
    )
    if not legs:
        raise HTTPException(status_code=400, detail="No tradable markets were found for simulation")

    first_leg = legs[0]

    active_session = await _active_simulation_session(db)
    if active_session:
        active_session.active = False
        active_session.stopped_at = datetime.now(timezone.utc)
        active_session.stop_reason = "restarted"

    session = SimulationSession(
        active=True,
        principal_usd=round(float(payload.amount_usd), 2),
        max_loss_pct=float(payload.stop_loss_pct) if payload.stop_loss_pct is not None else None,
        started_at=datetime.now(timezone.utc),
    )
    db.add(session)
    await db.commit()

    return {
        "ok": True,
        "simulated": True,
        "allocation_mode": payload.allocation_mode,
        "market_id": int(first_leg["market_id"]),
        "question": str(first_leg["question"]),
        "side": str(first_leg["side"]),
        "entry_price": float(first_leg["entry_price"]),
        "shares": float(first_leg["shares"]),
        "principal_usd": session.principal_usd,
        "stop_loss_pct": session.max_loss_pct,
        "legs": legs,
        "tracked_positions": len(legs),
    }


@router.post("/bot/simulation/stop")
async def stop_simulation(db=Depends(get_db)):
    await _ensure_simulation_table(db)
    active_session = await _active_simulation_session(db)
    if active_session:
        active_session.active = False
        active_session.stopped_at = datetime.now(timezone.utc)
        active_session.stop_reason = "manual_stop"

    now = datetime.now(timezone.utc)
    positions_result = await db.execute(
        select(Position).where(Position.mode == "simulation", Position.closed_at.is_(None))
    )
    for pos in positions_result.scalars().all():
        pos.closed_at = now

    await db.execute(delete(Position).where(Position.mode == "simulation"))
    await db.commit()

    return {"ok": True, "simulated": True}


@router.post("/bot/simulation/reset")
async def reset_simulation(db=Depends(get_db)):
    await _ensure_simulation_table(db)
    await stop_simulation(db)
    await db.execute(delete(Order).where(Order.mode == "simulation"))
    await db.commit()
    return {"ok": True, "simulated": True}


@router.get("/bot/simulation/status")
async def simulation_status(db=Depends(get_db)):
    await _ensure_simulation_table(db)
    active_session = await _active_simulation_session(db)
    latest_session = active_session or await _latest_simulation_session(db)

    positions_result = await db.execute(
        select(Position).where(Position.mode == "simulation", Position.closed_at.is_(None))
    )
    positions = positions_result.scalars().all()

    if not positions:
        return {
            "simulated": True,
            "active": False,
            "principal_usd": float(latest_session.principal_usd) if latest_session else 0.0,
            "stop_loss_pct": float(latest_session.max_loss_pct) if latest_session and latest_session.max_loss_pct is not None else None,
            "stop_reason": latest_session.stop_reason if latest_session else None,
            "started_at": latest_session.started_at.isoformat() if latest_session and latest_session.started_at else None,
            "invested_usd": 0.0,
            "current_value_usd": 0.0,
            "total_pnl_usd": 0.0,
            "total_pnl_pct": 0.0,
            "trades": [],
            "note": "No active simulation. Start simulation to run again.",
        }

    invested = 0.0
    current_value = 0.0
    trades = []

    for pos in positions:
        market_result = await db.execute(select(Market).where(Market.id == pos.market_id).limit(1))
        market = market_result.scalar_one_or_none()

        ob_result = await db.execute(
            select(OrderbookSnapshot)
            .where(OrderbookSnapshot.market_id == pos.market_id)
            .order_by(OrderbookSnapshot.snapshot_at.desc())
            .limit(1)
        )
        ob = ob_result.scalar_one_or_none()

        signal_result = await db.execute(
            select(Signal.edge)
            .join(Order, Order.signal_id == Signal.id)
            .where(
                Order.mode == "simulation",
                Order.market_id == pos.market_id,
                Order.signal_id.is_not(None),
            )
            .order_by(Order.created_at.desc())
            .limit(1)
        )
        edge = signal_result.scalar_one_or_none()

        mark_price = float(ob.mid_price) if ob and ob.mid_price is not None else float(pos.avg_price)
        direction = 1.0 if pos.side == "buy" else -1.0
        pnl = (mark_price - float(pos.avg_price)) * float(pos.size) * direction
        invested += float(pos.exposure_usd)
        current_value += float(pos.exposure_usd) + pnl

        edge_abs = abs(float(edge)) if edge is not None else 0.0
        projected_price = float(pos.avg_price) * (1.0 + (direction * edge_abs))
        projected_price = min(0.99, max(0.01, projected_price))

        trades.append(
            {
                "market_id": pos.market_id,
                "question": market.question if market else f"Market #{pos.market_id}",
                "icon_url": _market_icon_url(market),
                "side": pos.side,
                "entry_price": float(pos.avg_price),
                "mark_price": mark_price,
                "projected_price": projected_price,
                "expected_edge_pct": edge_abs * 100.0,
                "shares": float(pos.size),
                "exposure_usd": float(pos.exposure_usd),
                "pnl_usd": pnl,
                "pnl_pct": (pnl / float(pos.exposure_usd) * 100.0) if float(pos.exposure_usd) > 0 else 0.0,
            }
        )

    principal = float(active_session.principal_usd) if active_session else float(invested)
    current_value = max(0.0, current_value)
    total_pnl = current_value - principal
    total_pnl_pct = (total_pnl / principal * 100.0) if principal > 0 else 0.0

    note = "Simulation uses real market prices and simulated execution (no real funds used)."
    stop_on_zero = active_session and current_value <= 0.0
    stop_on_loss_limit = (
        active_session
        and active_session.max_loss_pct is not None
        and total_pnl_pct <= -float(active_session.max_loss_pct)
    )
    if stop_on_zero or stop_on_loss_limit:
        active_session.active = False
        active_session.stopped_at = datetime.now(timezone.utc)
        active_session.stop_reason = "depleted" if stop_on_zero else "loss_limit"
        await db.execute(delete(Position).where(Position.mode == "simulation"))
        await db.commit()
        reason_text = "simulated capital reached 0" if stop_on_zero else f"loss limit {active_session.max_loss_pct:.2f}% reached"
        pnl_pct_out = -100.0 if stop_on_zero else total_pnl_pct
        pnl_out = -principal if stop_on_zero else total_pnl
        value_out = 0.0 if stop_on_zero else max(0.0, current_value)
        return {
            "simulated": True,
            "active": False,
            "principal_usd": principal,
            "stop_loss_pct": float(active_session.max_loss_pct) if active_session.max_loss_pct is not None else None,
            "stop_reason": active_session.stop_reason,
            "started_at": active_session.started_at.isoformat() if active_session.started_at else None,
            "invested_usd": invested,
            "current_value_usd": value_out,
            "total_pnl_usd": pnl_out,
            "total_pnl_pct": pnl_pct_out,
            "trades": [],
            "note": f"Simulation auto-stopped because {reason_text}.",
        }

    return {
        "simulated": True,
        "active": bool(active_session),
        "principal_usd": principal,
        "stop_loss_pct": float(active_session.max_loss_pct) if active_session and active_session.max_loss_pct is not None else None,
        "stop_reason": active_session.stop_reason if active_session else None,
        "started_at": active_session.started_at.isoformat() if active_session and active_session.started_at else None,
        "invested_usd": invested,
        "current_value_usd": current_value,
        "total_pnl_usd": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "trades": trades,
        "note": note,
    }
