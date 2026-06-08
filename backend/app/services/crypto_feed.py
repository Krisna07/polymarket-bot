from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import structlog
import websockets

from backend.app.config import Settings

log = structlog.get_logger(__name__)


@dataclass
class Candle:
    close_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    closed: bool


class BinanceKlineFeed:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._symbols = settings.rotation_stream_symbols
        self._candles: dict[str, deque[Candle]] = {
            s: deque(maxlen=600) for s in self._symbols
        }
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._running = False
        self._last_message_at: datetime | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="binance-kline-feed")

    async def stop(self) -> None:
        self._running = False
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    def status(self) -> dict[str, object]:
        return {
            "enabled": True,
            "running": bool(self._task and not self._task.done()),
            "symbols": self._symbols,
            "last_message_at": self._last_message_at.isoformat()
            if self._last_message_at
            else None,
        }

    async def latest_price(self, symbol: str) -> float | None:
        bars = await self.recent_candles(symbol, limit=1)
        if not bars:
            return None
        return bars[-1].close

    async def recent_candles(self, symbol: str, limit: int = 250) -> list[Candle]:
        s = symbol.lower()
        async with self._lock:
            rows = list(self._candles.get(s, deque()))
        if limit <= 0:
            return rows
        return rows[-limit:]

    async def _run(self) -> None:
        if not self._symbols:
            log.warning("binance_feed_no_symbols")
            return

        streams = "/".join(
            f"{symbol}@kline_{self._settings.rotation_kline_interval}"
            for symbol in self._symbols
        )
        ws_url = f"{self._settings.rotation_ws_url.rstrip('/')}/stream?streams={streams}"

        while self._running:
            try:
                async with websockets.connect(
                    ws_url, ping_interval=20, ping_timeout=20
                ) as ws:
                    log.info("binance_feed_connected", symbols=self._symbols)
                    while self._running:
                        raw = await ws.recv()
                        msg = json.loads(raw)
                        payload = msg.get("data", msg)
                        kline = payload.get("k") if isinstance(payload, dict) else None
                        if not kline:
                            continue
                        await self._upsert_kline(kline)
                        self._last_message_at = datetime.now(timezone.utc)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("binance_feed_disconnected", error=str(e))
                await asyncio.sleep(3)

    async def _upsert_kline(self, kline: dict[str, object]) -> None:
        symbol = str(kline.get("s", "")).lower()
        if symbol not in self._candles:
            return

        candle = Candle(
            close_time_ms=int(kline.get("T") or 0),
            open=float(kline.get("o") or 0.0),
            high=float(kline.get("h") or 0.0),
            low=float(kline.get("l") or 0.0),
            close=float(kline.get("c") or 0.0),
            volume=float(kline.get("v") or 0.0),
            closed=bool(kline.get("x")),
        )

        async with self._lock:
            series = self._candles[symbol]
            if series and series[-1].close_time_ms == candle.close_time_ms:
                series[-1] = candle
            else:
                series.append(candle)

    async def debug_snapshot(self) -> dict[str, object]:
        async with self._lock:
            return {
                "symbols": {
                    symbol: [asdict(c) for c in list(rows)[-3:]]
                    for symbol, rows in self._candles.items()
                }
            }
