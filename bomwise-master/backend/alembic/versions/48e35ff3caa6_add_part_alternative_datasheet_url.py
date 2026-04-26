"""add_part_alternative_datasheet_url

Revision ID: 48e35ff3caa6
Revises: 0021
Create Date: 2026-04-17 14:10:13.988494

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '48e35ff3caa6'
down_revision: Union[str, Sequence[str], None] = '0021'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('part_alternatives', sa.Column('datasheet_url', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('part_alternatives', 'datasheet_url')
