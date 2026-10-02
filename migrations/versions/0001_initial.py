"""Initial schema; frozen independently of runtime ORM models."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def common_columns():
    return [
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("stream", sa.String(), nullable=False),
        sa.Column("device", sa.String(), nullable=False),
        sa.Column("app", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=False),
        sa.Column("classification", sa.JSON(), nullable=False),
    ]


def upgrade():
    op.create_table(
        "raw_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("stream", sa.String(), nullable=False),
        sa.Column("source_event_id", sa.String(), nullable=False),
        sa.Column("payload_hash", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("event_id", "payload_hash"),
    )
    op.create_index("ix_raw_events_event_id", "raw_events", ["event_id"])
    op.create_table(
        "activity_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("raw_event_id", sa.Integer(), sa.ForeignKey("raw_events.id"), nullable=False),
        *common_columns(),
    )
    op.create_index("ix_activity_events_start_time", "activity_events", ["start_time"])
    op.create_table(
        "manual_overrides",
        sa.Column("event_id", sa.String(), sa.ForeignKey("activity_events.id"), primary_key=True),
        sa.Column("classification", sa.JSON(), nullable=False),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(), primary_key=True),
        *common_columns(),
        sa.Column("active_seconds", sa.Float(), nullable=False),
    )
    op.create_index("ix_sessions_start_time", "sessions", ["start_time"])
    op.create_table(
        "session_events",
        sa.Column("session_id", sa.String(), sa.ForeignKey("sessions.id"), primary_key=True),
        sa.Column("event_id", sa.String(), sa.ForeignKey("activity_events.id"), primary_key=True),
    )


def downgrade():
    for name in ["session_events", "sessions", "manual_overrides", "activity_events", "raw_events"]:
        op.drop_table(name)
