"""Add auto_lock_parts to user_preferences

Revision ID: 0022
Revises: 0021
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa

revision = '0022'
down_revision = '4b57a3ef9d53'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'user_preferences',
        sa.Column('auto_lock_parts', sa.Boolean(), server_default='true', nullable=False, default=True)
    )


def downgrade() -> None:
    op.drop_column('user_preferences', 'auto_lock_parts')