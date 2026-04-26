"""Add paddle_events table

Revision ID: 0019
Revises: 0018
Create Date: 2026-04-15
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paddle_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_paddle_events_event_id"),
    )
    op.create_index("ix_paddle_events_event_id", "paddle_events", ["event_id"])
    op.create_index("ix_paddle_events_event_type", "paddle_events", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_paddle_events_event_type", table_name="paddle_events")
    op.drop_index("ix_paddle_events_event_id", table_name="paddle_events")
    op.drop_table("paddle_events")
