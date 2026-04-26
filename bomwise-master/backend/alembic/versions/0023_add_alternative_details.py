"""add package, distributor, stock to part_alternatives

Revision ID: 0023
Revises: 0022
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("part_alternatives", sa.Column("package", sa.String(), nullable=True))
    op.add_column("part_alternatives", sa.Column("distributor", sa.String(), nullable=True))
    op.add_column("part_alternatives", sa.Column("stock", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("part_alternatives", "stock")
    op.drop_column("part_alternatives", "distributor")
    op.drop_column("part_alternatives", "package")