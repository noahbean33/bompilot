"""add locked column to bom_lines

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-07

"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bom_lines",
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("bom_lines", "locked")
