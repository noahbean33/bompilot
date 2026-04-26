"""add notes and datasheet_url to bom_lines

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-06

"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bom_lines", sa.Column("notes", sa.Text(), nullable=True))
    op.add_column("bom_lines", sa.Column("datasheet_url", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("bom_lines", "datasheet_url")
    op.drop_column("bom_lines", "notes")
