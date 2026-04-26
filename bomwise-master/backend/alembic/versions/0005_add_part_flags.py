"""add part_flags table

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-06

"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "part_flags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("part_result_id", sa.Integer(), nullable=False),
        sa.Column("flag_type", sa.String(), nullable=False),
        sa.Column("old_value", sa.String(), nullable=True),
        sa.Column("new_value", sa.String(), nullable=True),
        sa.Column(
            "acknowledged",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["part_result_id"], ["part_results.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_part_flags_id"), "part_flags", ["id"], unique=False)
    op.create_index(
        op.f("ix_part_flags_part_result_id"),
        "part_flags",
        ["part_result_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_part_flags_part_result_id"), table_name="part_flags")
    op.drop_index(op.f("ix_part_flags_id"), table_name="part_flags")
    op.drop_table("part_flags")
