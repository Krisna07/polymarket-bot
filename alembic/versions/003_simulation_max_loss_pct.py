"""add simulation max loss pct

Revision ID: 003
Revises: 002
Create Date: 2026-06-06

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("simulation_sessions", sa.Column("max_loss_pct", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("simulation_sessions", "max_loss_pct")
