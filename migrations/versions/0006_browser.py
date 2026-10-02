"""Browser source records and rebuildable foreground enrichment."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def activity_columns():
    return [
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("stream", sa.String(), nullable=False),
        sa.Column("device", sa.String(), nullable=False),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=False),
        sa.Column("app", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("classification", sa.JSON(), nullable=False),
    ]


def links(target):
    op.create_table(
        "session_events",
        sa.Column("session_id", sa.String(), sa.ForeignKey("sessions.id"), primary_key=True),
        sa.Column("event_id", sa.String(), sa.ForeignKey(target + ".id"), primary_key=True),
    )


def upgrade():
    op.create_table(
        "browser_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("raw_event_id", sa.Integer(), sa.ForeignKey("raw_events.id"), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("stream", sa.String(), nullable=False),
        sa.Column("device", sa.String(), nullable=False),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=False),
        sa.Column("browser_apps", sa.JSON(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("audible", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_browser_events_start_time", "browser_events", ["start_time"])
    op.create_table(
        "resolved_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "window_event_id", sa.String(), sa.ForeignKey("activity_events.id"), nullable=False
        ),
        sa.Column(
            "browser_event_id", sa.String(), sa.ForeignKey("browser_events.id"), nullable=True
        ),
        *activity_columns(),
    )
    op.create_index("ix_resolved_events_start_time", "resolved_events", ["start_time"])
    op.create_table(
        "segment_overrides",
        sa.Column("event_id", sa.String(), primary_key=True),
        sa.Column(
            "window_event_id", sa.String(), sa.ForeignKey("activity_events.id"), nullable=False
        ),
        sa.Column("classification", sa.JSON(), nullable=False),
    )
    op.execute(
        "INSERT INTO resolved_events SELECT id,id,NULL,source,stream,device,"
        "start_time,end_time,app,title,url,classification FROM activity_events"
    )
    op.execute("CREATE TEMP TABLE saved_links AS SELECT * FROM session_events")
    op.drop_table("session_events")
    links("resolved_events")
    op.execute("INSERT INTO session_events SELECT * FROM saved_links")
    op.execute("DROP TABLE saved_links")


def downgrade():
    op.execute(
        "CREATE TEMP TABLE saved_links AS SELECT DISTINCT s.session_id,"
        "r.window_event_id AS event_id FROM session_events s "
        "JOIN resolved_events r ON r.id=s.event_id"
    )
    op.drop_table("session_events")
    links("activity_events")
    op.execute("INSERT INTO session_events SELECT * FROM saved_links")
    op.execute("DROP TABLE saved_links")
    op.drop_table("segment_overrides")
    op.drop_table("resolved_events")
    op.drop_table("browser_events")
