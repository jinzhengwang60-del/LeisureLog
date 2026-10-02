"""Index bounded incremental processing and source-window anchors."""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

INDEXES = {
    "activity_events": ["source", "device", "stream", "end_time", "start_time"],
    "sessions": ["source", "device", "stream", "end_time", "start_time"],
    "browser_events": ["source", "device", "end_time", "start_time"],
    "idle_events": ["source", "device", "end_time", "start_time"],
}


def upgrade():
    for table, columns in INDEXES.items():
        op.create_index(f"ix_{table}_processing", table, columns)
    op.create_index("ix_resolved_events_window_event_id", "resolved_events", ["window_event_id"])


def downgrade():
    op.drop_index("ix_resolved_events_window_event_id", table_name="resolved_events")
    for table in reversed(INDEXES):
        op.drop_index(f"ix_{table}_processing", table_name=table)
