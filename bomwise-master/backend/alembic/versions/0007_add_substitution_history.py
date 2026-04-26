"""add substitution_history table

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-06

"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "substitution_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bom_line_id", sa.Integer(), nullable=False),
        sa.Column("previous_result_id", sa.Integer(), nullable=True),
        sa.Column("new_result_id", sa.Integer(), nullable=False),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["bom_line_id"], ["bom_lines.id"]),
        sa.ForeignKeyConstraint(["previous_result_id"], ["part_results.id"]),
        sa.ForeignKeyConstraint(["new_result_id"], ["part_results.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_substitution_history_id"), "substitution_history", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_substitution_history_bom_line_id"),
        "substitution_history",
        ["bom_line_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_substitution_history_bom_line_id"), table_name="substitution_history"
    )
    op.drop_index(
        op.f("ix_substitution_history_id"), table_name="substitution_history"
    )
    op.drop_table("substitution_history")
