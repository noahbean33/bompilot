"""add plan and limit override columns to users

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-10

"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("plan", sa.String(), nullable=False, server_default="free"),
    )
    op.add_column(
        "users",
        sa.Column("max_projects_override", sa.Integer(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("max_parts_per_project_override", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "max_parts_per_project_override")
    op.drop_column("users", "max_projects_override")
    op.drop_column("users", "plan")
