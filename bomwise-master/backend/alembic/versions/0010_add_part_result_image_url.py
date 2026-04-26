"""add image_url column to part_results

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-07

"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "part_results",
        sa.Column("image_url", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("part_results", "image_url")
