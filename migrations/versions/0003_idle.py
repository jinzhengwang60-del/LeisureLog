"""Preserved idle events and auditable Session timing."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "idle_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("raw_event_id", sa.Integer(), sa.ForeignKey("raw_events.id"), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("stream", sa.String(), nullable=False),
        sa.Column("device", sa.String(), nullable=False),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
    )
    op.create_index("ix_idle_events_start_time", "idle_events", ["start_time"])
    for name in ["recorded_seconds", "afk_seconds", "unverified_seconds"]:
        op.add_column("sessions", sa.Column(name, sa.Float(), nullable=False, server_default="0"))
    op.execute(
        "UPDATE sessions SET recorded_seconds=active_seconds, unverified_seconds=active_seconds"
    )


def downgrade():
    op.execute("UPDATE sessions SET active_seconds=recorded_seconds")
    for name in ["recorded_seconds", "afk_seconds", "unverified_seconds"]:
        op.drop_column("sessions", name)
    op.drop_table("idle_events")
