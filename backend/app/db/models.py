from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Market(Base):
    __tablename__ = "markets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    condition_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    slug: Mapped[str | None] = mapped_column(String(512), nullable=True)
    question: Mapped[str] = mapped_column(Text)
    yes_token_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    no_token_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(JSONB, default=list)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolution_outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    orderbook_snapshots: Mapped[list["OrderbookSnapshot"]] = relationship(
        back_populates="market"
    )
    features: Mapped[list["FeatureSnapshot"]] = relationship(back_populates="market")
    signals: Mapped[list["Signal"]] = relationship(back_populates="market")


class OrderbookSnapshot(Base):
    __tablename__ = "orderbook_snapshots"
    __table_args__ = (Index("ix_ob_market_ts", "market_id", "snapshot_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), index=True)
    token_id: Mapped[str] = mapped_column(String(128))
    best_bid: Mapped[float | None] = mapped_column(Float)
    best_ask: Mapped[float | None] = mapped_column(Float)
    mid_price: Mapped[float | None] = mapped_column(Float)
    spread: Mapped[float | None] = mapped_column(Float)
    bid_depth: Mapped[float | None] = mapped_column(Float)
    ask_depth: Mapped[float | None] = mapped_column(Float)
    volume_24h: Mapped[float | None] = mapped_column(Float)
    raw_book: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    market: Mapped["Market"] = relationship(back_populates="orderbook_snapshots")


class NewsItem(Base):
    __tablename__ = "news_items"
    __table_args__ = (Index("ix_news_published", "published_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    entities: Mapped[list[str] | None] = mapped_column(JSONB)
    market_ids: Mapped[list[int] | None] = mapped_column(JSONB)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FeatureSnapshot(Base):
    __tablename__ = "feature_snapshots"
    __table_args__ = (Index("ix_feat_market_ts", "market_id", "computed_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), index=True)
    features: Mapped[dict[str, Any]] = mapped_column(JSONB)
    market_probability: Mapped[float | None] = mapped_column(Float)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    market: Mapped["Market"] = relationship(back_populates="features")


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), index=True)
    fair_probability: Mapped[float] = mapped_column(Float)
    market_probability: Mapped[float] = mapped_column(Float)
    edge: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    position_size: Mapped[float] = mapped_column(Float)
    ml_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    llm_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    rejection_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    market: Mapped["Market"] = relationship(back_populates="signals")
    orders: Mapped[list["Order"]] = relationship(back_populates="signal")


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), index=True)
    token_id: Mapped[str] = mapped_column(String(128))
    side: Mapped[str] = mapped_column(String(8))
    size: Mapped[float] = mapped_column(Float)
    avg_price: Mapped[float] = mapped_column(Float)
    exposure_usd: Mapped[float] = mapped_column(Float)
    mode: Mapped[str] = mapped_column(String(16), default="paper")
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    signal_id: Mapped[int | None] = mapped_column(
        ForeignKey("signals.id"), nullable=True
    )
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), index=True)
    token_id: Mapped[str] = mapped_column(String(128))
    side: Mapped[str] = mapped_column(String(8))
    price: Mapped[float] = mapped_column(Float)
    size: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    mode: Mapped[str] = mapped_column(String(16), default="paper")
    external_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    signal: Mapped["Signal | None"] = relationship(back_populates="orders")


class SimulationSession(Base):
    __tablename__ = "simulation_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    principal_usd: Mapped[float] = mapped_column(Float)
    max_loss_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
