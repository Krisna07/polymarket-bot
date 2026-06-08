"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-06-04

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "markets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("condition_id", sa.String(length=128), nullable=False),
        sa.Column("slug", sa.String(length=512), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("yes_token_id", sa.String(length=128), nullable=True),
        sa.Column("no_token_id", sa.String(length=128), nullable=True),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("closed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("resolution_outcome", sa.String(length=32), nullable=True),
        sa.Column("raw_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("condition_id"),
    )
    op.create_index("ix_markets_condition_id", "markets", ["condition_id"])

    op.create_table(
        "orderbook_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("market_id", sa.Integer(), nullable=False),
        sa.Column("token_id", sa.String(length=128), nullable=False),
        sa.Column("best_bid", sa.Float(), nullable=True),
        sa.Column("best_ask", sa.Float(), nullable=True),
        sa.Column("mid_price", sa.Float(), nullable=True),
        sa.Column("spread", sa.Float(), nullable=True),
        sa.Column("bid_depth", sa.Float(), nullable=True),
        sa.Column("ask_depth", sa.Float(), nullable=True),
        sa.Column("volume_24h", sa.Float(), nullable=True),
        sa.Column("raw_book", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ob_market_ts", "orderbook_snapshots", ["market_id", "snapshot_at"])

    op.create_table(
        "news_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("entities", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("market_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "feature_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("market_id", sa.Integer(), nullable=False),
        sa.Column("features", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("market_probability", sa.Float(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feat_market_ts", "feature_snapshots", ["market_id", "computed_at"])

    op.create_table(
        "signals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("market_id", sa.Integer(), nullable=False),
        sa.Column("fair_probability", sa.Float(), nullable=False),
        sa.Column("market_probability", sa.Float(), nullable=False),
        sa.Column("edge", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("position_size", sa.Float(), nullable=False),
        sa.Column("ml_score", sa.Float(), nullable=True),
        sa.Column("llm_summary", sa.Text(), nullable=True),
        sa.Column("approved", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("rejection_reason", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("market_id", sa.Integer(), nullable=False),
        sa.Column("token_id", sa.String(length=128), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("size", sa.Float(), nullable=False),
        sa.Column("avg_price", sa.Float(), nullable=False),
        sa.Column("exposure_usd", sa.Float(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="paper"),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("signal_id", sa.BigInteger(), nullable=True),
        sa.Column("market_id", sa.Integer(), nullable=False),
        sa.Column("token_id", sa.String(length=128), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("size", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="paper"),
        sa.Column("external_order_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"]),
        sa.ForeignKeyConstraint(["signal_id"], ["signals.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("orders")
    op.drop_table("positions")
    op.drop_table("signals")
    op.drop_table("feature_snapshots")
    op.drop_table("news_items")
    op.drop_table("orderbook_snapshots")
    op.drop_table("markets")
