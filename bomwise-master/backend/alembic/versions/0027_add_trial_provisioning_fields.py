"""add trial provisioning fields

Revision ID: 0027
Revises: 0026
Create Date: 2026-04-24 12:50:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_trial_provisioned", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "users",
        sa.Column("trial_source", sa.VARCHAR(255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("trial_expiry_email_sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "trial_expiry_email_sent_at")
    op.drop_column("users", "trial_source")
    op.drop_column("users", "is_trial_provisioned")