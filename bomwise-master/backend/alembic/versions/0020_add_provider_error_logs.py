"""add provider_error_logs table

Revision ID: 0020
Revises: 0019
Create Date: 2026-04-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_error_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_name", sa.String(), nullable=False),
        sa.Column("error_type", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_provider_error_logs_id", "provider_error_logs", ["id"])
    op.create_index(
        "ix_provider_error_logs_provider_name", "provider_error_logs", ["provider_name"]
    )
    op.create_index(
        "ix_provider_error_logs_occurred_at", "provider_error_logs", ["occurred_at"]
    )
    op.create_index(
        "ix_provider_error_logs_name_occurred",
        "provider_error_logs",
        ["provider_name", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_provider_error_logs_name_occurred", table_name="provider_error_logs")
    op.drop_index("ix_provider_error_logs_occurred_at", table_name="provider_error_logs")
    op.drop_index(
        "ix_provider_error_logs_provider_name", table_name="provider_error_logs"
    )
    op.drop_index("ix_provider_error_logs_id", table_name="provider_error_logs")
    op.drop_table("provider_error_logs")
