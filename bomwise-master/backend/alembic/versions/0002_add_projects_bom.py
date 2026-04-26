"""add projects, project_preferences, bom_lines tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-04

"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("variant_tag", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_projects_id"), "projects", ["id"], unique=False)
    op.create_index(op.f("ix_projects_user_id"), "projects", ["user_id"], unique=False)

    op.create_table(
        "project_preferences",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("distributor_restriction", sa.JSON(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("grade", sa.String(), nullable=True),
        sa.Column("lifecycle_policy", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("project_id"),
    )

    op.create_table(
        "bom_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("reference", sa.String(), nullable=True),
        sa.Column("value", sa.String(), nullable=True),
        sa.Column("footprint", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("mpn_raw", sa.String(), nullable=True),
        sa.Column("raw_fields", sa.JSON(), nullable=False),
        sa.Column("match_type", sa.String(), nullable=True),
        # selected_result_id — FK to part_results added in a later migration
        sa.Column("selected_result_id", sa.Integer(), nullable=True),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_bom_lines_id"), "bom_lines", ["id"], unique=False)
    op.create_index(
        op.f("ix_bom_lines_project_id"), "bom_lines", ["project_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_bom_lines_project_id"), table_name="bom_lines")
    op.drop_index(op.f("ix_bom_lines_id"), table_name="bom_lines")
    op.drop_table("bom_lines")
    op.drop_table("project_preferences")
    op.drop_index(op.f("ix_projects_user_id"), table_name="projects")
    op.drop_index(op.f("ix_projects_id"), table_name="projects")
    op.drop_table("projects")
