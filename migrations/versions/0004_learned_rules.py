"""Reusable user classification rules, separate from event overrides."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "learned_rules",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("app", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("classification", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("learned_rules")
