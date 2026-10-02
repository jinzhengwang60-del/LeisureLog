"""Derived day summaries for bounded date-range analytics. Reprocess after upgrade."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "daily_activity",
        sa.Column("session_id", sa.String(), sa.ForeignKey("sessions.id"), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("app", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("content", sa.String(), nullable=True),
        *[
            sa.Column(name, sa.Float(), nullable=False)
            for name in ["recorded_seconds", "active_seconds", "afk_seconds", "unverified_seconds"]
        ],
    )
    op.create_index("ix_daily_activity_day", "daily_activity", ["day"])


def downgrade():
    op.drop_table("daily_activity")
