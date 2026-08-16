"""T008: 002 personalization — article_scores table + settings extensions.

Adds:
- New table `article_scores` (1:1 with articles) storing composite score,
  4 dimension sub-scores, authority tier, dedup signals (topic_id /
  opinion_fingerprint), score_source (llm/rule_fallback), computed_at.
- Two new columns on `settings`: `daily_count` (INT default 30) and
  `style_mode` (VARCHAR(16) default 'standard').

Revision ID: 003
Revises: 002
Create Date: 2026-08-13
"""

from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "article_scores",
        sa.Column(
            "article_id",
            sa.String(64),
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("composite_score", sa.Integer, nullable=False),
        sa.Column("dim_authority", sa.Integer, nullable=False),
        sa.Column("dim_depth", sa.Integer, nullable=False),
        sa.Column("dim_timeliness", sa.Integer, nullable=False),
        sa.Column("dim_expression", sa.Integer, nullable=False),
        sa.Column("authority_tier", sa.String(32), nullable=False),
        sa.Column("topic_id", sa.String(128), nullable=True),
        sa.Column("opinion_fingerprint", sa.String(128), nullable=True),
        sa.Column("score_source", sa.String(16), nullable=False, server_default="llm"),
        sa.Column("computed_at", sa.DateTime, nullable=False),
        sa.CheckConstraint(
            "composite_score BETWEEN 0 AND 100", name="score_composite_range"
        ),
        sa.CheckConstraint(
            "dim_authority BETWEEN 0 AND 100", name="score_dim_authority_range"
        ),
        sa.CheckConstraint("dim_depth BETWEEN 0 AND 100", name="score_dim_depth_range"),
        sa.CheckConstraint(
            "dim_timeliness BETWEEN 0 AND 100", name="score_dim_timeliness_range"
        ),
        sa.CheckConstraint(
            "dim_expression BETWEEN 0 AND 100", name="score_dim_expression_range"
        ),
        sa.CheckConstraint(
            "authority_tier IN ('official_blog', 'authoritative_media', 'community')",
            name="score_authority_tier_enum",
        ),
        sa.CheckConstraint(
            "score_source IN ('llm', 'rule_fallback')", name="score_source_enum"
        ),
    )
    op.create_index(
        "ix_article_scores_composite_score",
        "article_scores",
        ["composite_score"],
    )
    op.create_index(
        "ix_article_scores_topic_id", "article_scores", ["topic_id"]
    )
    op.create_index(
        "ix_article_scores_opinion_fingerprint",
        "article_scores",
        ["opinion_fingerprint"],
    )

    op.add_column(
        "settings",
        sa.Column(
            "daily_count",
            sa.Integer,
            nullable=False,
            server_default="30",
        ),
    )
    op.add_column(
        "settings",
        sa.Column(
            "style_mode",
            sa.String(16),
            nullable=False,
            server_default="standard",
        ),
    )
    with op.batch_alter_table("settings") as batch_op:
        batch_op.create_check_constraint(
            "settings_daily_count_enum",
            "daily_count IN (10, 20, 30, 40, 50)",
        )
        batch_op.create_check_constraint(
            "settings_style_mode_enum",
            "style_mode IN ('concise', 'standard', 'detailed')",
        )


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_constraint("settings_style_mode_enum", type_="check")
        batch_op.drop_constraint("settings_daily_count_enum", type_="check")
    op.drop_column("settings", "style_mode")
    op.drop_column("settings", "daily_count")

    op.drop_index(
        "ix_article_scores_opinion_fingerprint", table_name="article_scores"
    )
    op.drop_index("ix_article_scores_topic_id", table_name="article_scores")
    op.drop_index(
        "ix_article_scores_composite_score", table_name="article_scores"
    )
    op.drop_table("article_scores")
