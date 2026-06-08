"""add simulation sessions

Revision ID: 002
Revises: 001
Create Date: 2026-06-06

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "simulation_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("principal_usd", sa.Float(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stop_reason", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("simulation_sessions")
