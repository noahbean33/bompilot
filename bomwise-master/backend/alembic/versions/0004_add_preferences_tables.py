"""replace project_preferences and add user_preferences tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-06

"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the old project_preferences table (different schema from item 2).
    op.drop_table("project_preferences")

    # Create new project_preferences table per item 6 spec.
    op.create_table(
        "project_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("preferred_currency", sa.String(), nullable=True),
        sa.Column("preferred_distributors", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id"),
    )
    op.create_index(
        op.f("ix_project_preferences_id"), "project_preferences", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_project_preferences_project_id"),
        "project_preferences",
        ["project_id"],
        unique=True,
    )

    # Create user_preferences table.
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "preferred_currency",
            sa.String(),
            nullable=False,
            server_default="USD",
        ),
        sa.Column(
            "preferred_distributors",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index(
        op.f("ix_user_preferences_id"), "user_preferences", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_user_preferences_user_id"), "user_preferences", ["user_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_preferences_user_id"), table_name="user_preferences")
    op.drop_index(op.f("ix_user_preferences_id"), table_name="user_preferences")
    op.drop_table("user_preferences")

    op.drop_index(
        op.f("ix_project_preferences_project_id"), table_name="project_preferences"
    )
    op.drop_index(op.f("ix_project_preferences_id"), table_name="project_preferences")
    op.drop_table("project_preferences")

    # Restore the original project_preferences table.
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
