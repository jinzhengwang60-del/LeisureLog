"""Persistent automatic-sync checkpoint."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sync_checkpoints",
        sa.Column("source", sa.String(), primary_key=True),
        sa.Column("last_success_end", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("sync_checkpoints")
