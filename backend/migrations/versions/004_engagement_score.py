"""v2 ranking: add dim_engagement column to article_scores.

Stores the log10-compressed crowd-signal score (GitHub stars today, neutral
50 for sources without measurable signals). Legacy rows backfilled to 50.

Revision ID: 004
Revises: 003
Create Date: 2026-08-16
"""

from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("article_scores") as batch_op:
        batch_op.add_column(
            sa.Column("dim_engagement", sa.Integer, nullable=False, server_default="50")
        )
        batch_op.create_check_constraint(
            "score_dim_engagement_range",
            "dim_engagement BETWEEN 0 AND 100",
        )


def downgrade() -> None:
    with op.batch_alter_table("article_scores") as batch_op:
        batch_op.drop_constraint("score_dim_engagement_range", type_="check")
        batch_op.drop_column("dim_engagement")
