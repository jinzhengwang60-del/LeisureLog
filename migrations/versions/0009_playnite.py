"""Separate source catalog snapshots and normalized game matching metadata."""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "game_snapshots", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("digest", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("imported_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "game_catalog", sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("installed", sa.Boolean(), nullable=False),
        sa.Column("directory", sa.String(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("matches", sa.JSON(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("game_snapshots.id"), nullable=False),
    )


def downgrade():
    op.drop_table("game_catalog")
    op.drop_table("game_snapshots")
