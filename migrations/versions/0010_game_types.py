"""Preserve user game types independently of imported source metadata."""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "game_type_overrides",
        sa.Column("game_key", sa.String(), primary_key=True),
        sa.Column("primary_type", sa.String(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("game_type_overrides")
