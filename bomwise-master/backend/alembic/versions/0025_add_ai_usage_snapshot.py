"""add ai_usage_snapshot table

Revision ID: 0025
Revises: 0024
Create Date: 2026-04-24
"""

from alembic import op
import sqlalchemy as sa

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_usage_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("feature", sa.String(50), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("output_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("date", "feature", name="uq_ai_usage_snapshot_date_feature"),
    )
    op.create_index("ix_ai_usage_snapshot_date", "ai_usage_snapshot", ["date"])


def downgrade() -> None:
    op.drop_index("ix_ai_usage_snapshot_date", table_name="ai_usage_snapshot")
    op.drop_table("ai_usage_snapshot")