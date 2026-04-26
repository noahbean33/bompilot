"""add ai_advisor_monthly_queries_override to users

Revision ID: 0024
Revises: 0023
Create Date: 2026-04-23
"""

from alembic import op
import sqlalchemy as sa

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("ai_advisor_monthly_queries_override", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "ai_advisor_monthly_queries_override")