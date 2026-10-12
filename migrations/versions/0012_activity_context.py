"""Independent activity purposes, project metadata and reusable context decisions."""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "activity_projects",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False, server_default=""),
        sa.Column("color", sa.String(), nullable=False, server_default="#6366f1"),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "context_overrides",
        sa.Column("event_id", sa.String(), primary_key=True),
        sa.Column(
            "window_event_id", sa.String(), sa.ForeignKey("activity_events.id"), nullable=False
        ),
        sa.Column("assignments", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_context_overrides_window_event_id", "context_overrides", ["window_event_id"]
    )
    op.create_table(
        "context_rules",
        sa.Column("id", sa.String(), primary_key=True),
        *[
            sa.Column(name, sa.String(), nullable=False)
            for name in ("source", "app", "scope", "value")
        ],
        sa.Column("assignments", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for table in ("resolved_events", "sessions"):
        op.add_column(table, sa.Column("context", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column(
        "daily_activity",
        sa.Column("purpose", sa.String(), nullable=False, server_default="unknown"),
    )
    op.add_column("daily_activity", sa.Column("project_id", sa.String(), nullable=True))
    op.create_index("ix_daily_activity_purpose_day", "daily_activity", ["purpose", "day"])
    op.create_index("ix_daily_activity_project_day", "daily_activity", ["project_id", "day"])


def downgrade():
    op.drop_index("ix_daily_activity_project_day", table_name="daily_activity")
    op.drop_index("ix_daily_activity_purpose_day", table_name="daily_activity")
    op.drop_column("daily_activity", "project_id")
    op.drop_column("daily_activity", "purpose")
    for table in ("sessions", "resolved_events"):
        # SQLite 3.35+ can drop these unconstrained columns without recreating a
        # parent table that is still referenced by session_events/daily_activity.
        op.drop_column(table, "context")
    op.drop_table("context_rules")
    op.drop_index("ix_context_overrides_window_event_id", table_name="context_overrides")
    op.drop_table("context_overrides")
    op.drop_table("activity_projects")
