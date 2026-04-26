"""Add ai_assist_monthly_lines_override to users

Revision ID: 0017
Revises: 0016
Create Date: 2026-04-15
"""

from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("ai_assist_monthly_lines_override", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "ai_assist_monthly_lines_override")
