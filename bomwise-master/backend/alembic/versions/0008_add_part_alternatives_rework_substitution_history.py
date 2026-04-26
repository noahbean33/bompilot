"""add part_alternatives and rework substitution_history

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-07

"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ----------------------------------------------------------------
    # Drop old substitution_history (previous_result_id / new_result_id
    # schema) and recreate with mpn-string-based schema.
    # ----------------------------------------------------------------
    op.drop_index(
        op.f("ix_substitution_history_bom_line_id"), table_name="substitution_history"
    )
    op.drop_index(
        op.f("ix_substitution_history_id"), table_name="substitution_history"
    )
    op.drop_table("substitution_history")

    op.create_table(
        "substitution_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bom_line_id", sa.Integer(), nullable=False),
        sa.Column("from_mpn", sa.String(), nullable=True),
        sa.Column("to_mpn", sa.String(), nullable=False),
        sa.Column(
            "swapped_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("swapped_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["bom_line_id"], ["bom_lines.id"]),
        sa.ForeignKeyConstraint(["swapped_by"], ["users.id"]),
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

    # ----------------------------------------------------------------
    # Create part_alternatives table
    # ----------------------------------------------------------------
    op.create_table(
        "part_alternatives",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bom_line_id", sa.Integer(), nullable=False),
        sa.Column("mpn", sa.String(), nullable=False),
        sa.Column("manufacturer", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["bom_line_id"], ["bom_lines.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_part_alternatives_id"), "part_alternatives", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_part_alternatives_bom_line_id"),
        "part_alternatives",
        ["bom_line_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_part_alternatives_bom_line_id"), table_name="part_alternatives")
    op.drop_index(op.f("ix_part_alternatives_id"), table_name="part_alternatives")
    op.drop_table("part_alternatives")

    op.drop_index(
        op.f("ix_substitution_history_bom_line_id"), table_name="substitution_history"
    )
    op.drop_index(
        op.f("ix_substitution_history_id"), table_name="substitution_history"
    )
    op.drop_table("substitution_history")

    # Recreate original substitution_history schema
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
