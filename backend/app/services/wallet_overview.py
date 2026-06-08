from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import Settings
from backend.app.db.models import Position
from backend.app.services.polymarket.data_api import DataApiClient


async def get_wallet_overview(
    settings: Settings,
    session: AsyncSession,
    wallet_address: str,
) -> dict[str, Any]:
    data = DataApiClient(settings)
    profile = await data.get_profile(wallet_address)
    proxy_wallet = (profile or {}).get("proxyWallet")
    lookup_address = proxy_wallet or wallet_address

    positions_value = await data.get_portfolio_value(lookup_address)
    live_positions = await data.get_positions(lookup_address)

    result = await session.execute(
        select(func.coalesce(func.sum(Position.exposure_usd), 0.0)).where(
            Position.closed_at.is_(None)
        )
    )
    bot_exposure = float(result.scalar() or 0.0)

    bankroll = settings.bankroll_usd
    max_deploy = bankroll * settings.max_total_exposure_pct
    investable = max(0.0, max_deploy - bot_exposure)
    per_trade_cap = bankroll * settings.max_position_pct

    holdings = []
    for pos in live_positions[:20]:
        holdings.append(
            {
                "title": pos.get("title") or pos.get("question") or "Unknown market",
                "outcome": pos.get("outcome"),
                "size": float(pos.get("size", 0) or 0),
                "avg_price": float(pos.get("avgPrice", 0) or pos.get("avg_price", 0) or 0),
                "current_value": float(
                    pos.get("currentValue", 0) or pos.get("current_value", 0) or 0
                ),
                "cash_pnl": float(pos.get("cashPnl", 0) or pos.get("cash_pnl", 0) or 0),
                "condition_id": pos.get("conditionId") or pos.get("condition_id"),
            }
        )

    return {
        "wallet_address": wallet_address.lower(),
        "proxy_wallet": proxy_wallet,
        "display_name": (profile or {}).get("name") or (profile or {}).get("pseudonym"),
        "positions_value_usd": round(positions_value, 2),
        "holdings": holdings,
        "holdings_count": len(live_positions),
        "bot_exposure_usd": round(bot_exposure, 2),
        "bankroll_usd": bankroll,
        "investable_usd": round(investable, 2),
        "per_trade_max_usd": round(per_trade_cap, 2),
        "max_total_exposure_usd": round(max_deploy, 2),
        "trading_mode": settings.trading_mode,
        "has_deposit": positions_value > 0 or len(live_positions) > 0,
    }
