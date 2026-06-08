from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    database_url: str = (
        "postgresql+asyncpg://polymarket:polymarket@localhost:5432/polymarket_bot"
    )
    database_url_sync: str = (
        "postgresql://polymarket:polymarket@localhost:5432/polymarket_bot"
    )
    redis_url: str = "redis://localhost:6379/0"

    gamma_api_url: str = "https://gamma-api.polymarket.com"
    data_api_url: str = "https://data-api.polymarket.com"
    clob_api_url: str = "https://clob.polymarket.com"
    chain_id: int = 137

    polymarket_private_key: str = ""
    polymarket_funder_address: str = ""
    polymarket_signature_type: int = 0

    bankroll_usd: float = 1000.0
    max_position_pct: float = 0.05
    max_total_exposure_pct: float = 0.30
    kelly_fraction: float = 0.25
    min_edge: float = 0.03
    min_confidence: float = 0.60
    trading_mode: Literal["paper", "live"] = "paper"

    excluded_tags: str = "politics,crypto,geopolitics,elections"
    included_tags: str = "weather,sports,business,science"
    strict_market_filter: bool = False

    newsapi_key: str = ""
    google_search_api_key: str = ""
    google_search_cx: str = ""
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "polymarket-bot/0.1"

    enable_llm: bool = False
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:8b"
    advisor_research_market_limit: int = 3
    advisor_research_items_limit: int = 5
    advisor_research_timeout_sec: float = 6.0
    advisor_research_cache_ttl_sec: int = 180
    advisor_news_max_age_hours: int = 24

    sync_markets_interval_sec: int = 60
    snapshot_books_interval_sec: int = 60
    features_interval_sec: int = 300
    trade_eval_interval_sec: int = 300

    rotation_symbols: str = "btc,eth"
    rotation_quote_asset: str = "usdt"
    rotation_use_binance_ws: bool = True
    rotation_ws_url: str = "wss://stream.binance.com:9443"
    rotation_kline_interval: str = "1m"
    rotation_capital_fraction: float = 0.02
    rotation_rsi_period: int = 14
    rotation_ema_period: int = 200
    rotation_volume_lookback: int = 20
    rotation_volume_multiplier: float = 1.5
    rotation_stop_loss_pct: float = 0.005
    rotation_take_profit_pct: float = 0.01
    rotation_daily_drawdown_limit_pct: float = 0.03
    rotation_max_consecutive_losses: int = 3
    rotation_pause_hours: int = 2
    rotation_max_open_trades: int = 2
    rotation_loop_sleep_sec: int = 20

    fast_rotation_rsi_period: int = 7
    fast_rotation_ema_period: int = 30
    fast_rotation_volume_lookback: int = 8
    fast_rotation_volume_multiplier: float = 1.2
    fast_rotation_capital_fraction: float = 0.01
    fast_rotation_stop_loss_pct: float = 0.003
    fast_rotation_take_profit_pct: float = 0.006
    fast_rotation_daily_drawdown_limit_pct: float = 0.02
    fast_rotation_max_consecutive_losses: int = 2
    fast_rotation_pause_hours: int = 1
    fast_rotation_max_open_trades: int = 4
    fast_rotation_loop_sleep_sec: int = 10

    @property
    def excluded_tag_set(self) -> set[str]:
        return {t.strip().lower() for t in self.excluded_tags.split(",") if t.strip()}

    @property
    def included_tag_set(self) -> set[str]:
        return {t.strip().lower() for t in self.included_tags.split(",") if t.strip()}

    @property
    def live_trading_enabled(self) -> bool:
        return (
            self.trading_mode == "live"
            and bool(self.polymarket_private_key)
            and bool(self.polymarket_funder_address)
        )

    @property
    def rotation_symbol_set(self) -> set[str]:
        return {s.strip().lower() for s in self.rotation_symbols.split(",") if s.strip()}

    @property
    def rotation_stream_symbols(self) -> list[str]:
        quote = self.rotation_quote_asset.strip().lower() or "usdt"
        out: list[str] = []
        for symbol in sorted(self.rotation_symbol_set):
            s = symbol.lower()
            if s.endswith(quote):
                out.append(s)
            else:
                out.append(f"{s}{quote}")
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()
