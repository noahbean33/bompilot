"""add dnp column to bom_lines

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bom_lines",
        sa.Column("dnp", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("bom_lines", "dnp")
