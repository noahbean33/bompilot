"""add_user_nl_presets

Revision ID: 4b57a3ef9d53
Revises: 48e35ff3caa6
Create Date: 2026-04-17 19:53:23.222519

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4b57a3ef9d53'
down_revision: Union[str, Sequence[str], None] = '48e35ff3caa6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'user_preferences',
        sa.Column('preferred_nl_presets', sa.JSON(), nullable=False, server_default='[]')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('user_preferences', 'preferred_nl_presets')
