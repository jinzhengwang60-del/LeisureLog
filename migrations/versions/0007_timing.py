"""Timing policies and derived detected/retained AFK accounting."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "timing_overrides",
        sa.Column("event_id", sa.String(), primary_key=True),
        sa.Column(
            "window_event_id", sa.String(), sa.ForeignKey("activity_events.id"), nullable=False
        ),
        sa.Column("policy", sa.String(), nullable=False),
    )
    for table in ["sessions", "daily_activity"]:
        for name in ["detected_afk_seconds", "retained_afk_seconds"]:
            op.add_column(table, sa.Column(name, sa.Float(), nullable=False, server_default="0"))
        op.execute(f"UPDATE {table} SET detected_afk_seconds=afk_seconds")
    for table in ["sessions", "resolved_events"]:
        op.add_column(
            table, sa.Column("timing_policy", sa.String(), nullable=False, server_default="afk")
        )
        op.add_column(
            table, sa.Column("timing_origin", sa.String(), nullable=False, server_default="default")
        )
    op.add_column(
        "resolved_events", sa.Column("audible", sa.Boolean(), nullable=False, server_default="0")
    )


def downgrade():
    for table in ["sessions", "daily_activity"]:
        op.execute(
            f"UPDATE {table} SET afk_seconds=detected_afk_seconds, "
            "active_seconds=recorded_seconds-detected_afk_seconds"
        )
    op.drop_table("timing_overrides")
    op.drop_column("resolved_events", "audible")
    for table in ["sessions", "resolved_events"]:
        op.drop_column(table, "timing_policy")
        op.drop_column(table, "timing_origin")
    for table in ["sessions", "daily_activity"]:
        op.drop_column(table, "detected_afk_seconds")
        op.drop_column(table, "retained_afk_seconds")
