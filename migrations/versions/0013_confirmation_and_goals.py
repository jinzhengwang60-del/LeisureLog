"""Reversible context decisions and optional lifetime project time targets."""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("activity_projects", sa.Column("goal_seconds", sa.Float(), nullable=True))
    op.create_table(
        "context_changes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("before", sa.JSON(), nullable=False),
        sa.Column("after", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("undone_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_context_changes_created_at", "context_changes", ["created_at"])


def downgrade():
    op.drop_index("ix_context_changes_created_at", table_name="context_changes")
    op.drop_table("context_changes")
    op.drop_column("activity_projects", "goal_seconds")
