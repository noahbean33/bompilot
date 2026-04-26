"""Add Paddle subscription fields to users

Revision ID: 0018
Revises: 0017
Create Date: 2026-04-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("paddle_customer_id", sa.String(), nullable=True))
    op.add_column("users", sa.Column("paddle_subscription_id", sa.String(), nullable=True))
    op.add_column("users", sa.Column("subscription_status", sa.String(), nullable=True))
    op.add_column("users", sa.Column("subscription_plan", sa.String(), nullable=True))
    op.add_column(
        "users",
        sa.Column("subscription_current_period_end", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "trial_ends_at")
    op.drop_column("users", "subscription_current_period_end")
    op.drop_column("users", "subscription_plan")
    op.drop_column("users", "subscription_status")
    op.drop_column("users", "paddle_subscription_id")
    op.drop_column("users", "paddle_customer_id")
