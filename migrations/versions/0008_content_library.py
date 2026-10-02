"""Durable content catalog and reversible scoped aliases; derived data stays separate."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "content_items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("notes", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "content_aliases",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("item_id", sa.String(), sa.ForeignKey("content_items.id"), nullable=False),
        sa.Column("app", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.UniqueConstraint("app", "category", "name"),
    )
    op.create_index("ix_content_aliases_item_id", "content_aliases", ["item_id"])
    op.create_index("ix_daily_activity_content", "daily_activity", ["app", "category", "content"])
    # Catalog registration is performed by the normal reprocess use case after upgrading.


def downgrade():
    op.drop_index("ix_daily_activity_content", "daily_activity")
    op.drop_index("ix_content_aliases_item_id", "content_aliases")
    op.drop_table("content_aliases")
    op.drop_table("content_items")
