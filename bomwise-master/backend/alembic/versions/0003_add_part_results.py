"""add part_results table and wire selected_result_id FK on bom_lines

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-04

"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "part_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bom_line_id", sa.Integer(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("mpn", sa.String(), nullable=False),
        sa.Column("manufacturer", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("package", sa.String(), nullable=True),
        sa.Column("distributor", sa.String(), nullable=True),
        sa.Column("unit_price", sa.Float(), nullable=True),
        sa.Column("stock", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lifecycle_status", sa.String(), nullable=True),
        sa.Column("tech_specs", sa.JSON(), nullable=True),
        sa.Column("datasheet_url", sa.String(), nullable=True),
        sa.Column("source_provider", sa.String(), nullable=False),
        sa.Column("match_type", sa.String(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["bom_line_id"], ["bom_lines.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_part_results_id"), "part_results", ["id"], unique=False)
    op.create_index(
        op.f("ix_part_results_bom_line_id"), "part_results", ["bom_line_id"], unique=False
    )

    # Add the FK from bom_lines.selected_result_id → part_results.id now that
    # part_results exists.  Use create_foreign_key to add it without recreating
    # the whole table (important for PostgreSQL; Alembic handles this via ALTER).
    op.create_foreign_key(
        "fk_bom_lines_selected_result_id",
        "bom_lines",
        "part_results",
        ["selected_result_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_bom_lines_selected_result_id", "bom_lines", type_="foreignkey"
    )
    op.drop_index(op.f("ix_part_results_bom_line_id"), table_name="part_results")
    op.drop_index(op.f("ix_part_results_id"), table_name="part_results")
    op.drop_table("part_results")
