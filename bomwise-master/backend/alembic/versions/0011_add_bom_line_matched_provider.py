"""add matched_provider column to bom_lines

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-07

"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bom_lines",
        sa.Column("matched_provider", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bom_lines", "matched_provider")
