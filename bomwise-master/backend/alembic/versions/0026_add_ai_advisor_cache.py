"""add ai_advisor_cache table

Revision ID: 0026
Revises: 0025
Create Date: 2026-04-24 11:26:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_advisor_cache",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("mpn_hash", sa.VARCHAR(32), unique=True, nullable=False, index=True),
        sa.Column("mpns", sa.JSON(), nullable=False),
        sa.Column("bom_context", sa.JSON(), nullable=True),
        sa.Column("explanation", sa.TEXT(), nullable=True),
        sa.Column("recommendation", sa.VARCHAR(255), nullable=True),
        sa.Column("reasoning", sa.TEXT(), nullable=True),
        sa.Column("input_tokens", sa.INTEGER(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.INTEGER(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_accessed",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("access_count", sa.INTEGER(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ai_advisor_cache")