"""initial schema: daily_issues, articles, settings, share_cards

Revision ID: 001
Revises:
Create Date: 2026-08-12

Tables per data-model.md storage mapping (T031).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # daily_issues
    op.create_table(
        "daily_issues",
        sa.Column("id", sa.String(length=8), primary_key=True),
        sa.Column("date", sa.String(length=10), nullable=False),
        sa.Column("edition", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "status",
            sa.Enum("generating", "ready", "failed", name="issue_status"),
            nullable=False,
            server_default="generating",
        ),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
        sa.Column("filters_applied", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_daily_issues_status", "daily_issues", ["status"])

    # articles
    op.create_table(
        "articles",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column(
            "issue_id",
            sa.String(length=8),
            sa.ForeignKey("daily_issues.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("src", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("excerpt", sa.String(length=200), nullable=False),
        sa.Column("lede", sa.Text(), nullable=False),
        sa.Column("summary", sa.String(length=150), nullable=False),
        sa.Column("body", sa.JSON(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("points", sa.JSON(), nullable=False),
        sa.Column("time", sa.String(length=5), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_name", sa.String(length=200), nullable=False),
        sa.Column("reading_minutes", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_articles_issue_id", "articles", ["issue_id"])
    op.create_index("ix_articles_type", "articles", ["type"])
    op.create_index("ix_articles_src", "articles", ["src"])

    # settings (singleton id=1)
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), primary_key=True, server_default="1"),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("types", sa.JSON(), nullable=False),
        sa.Column("daily_push", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("id = 1", name="settings_singleton"),
    )

    # share_cards
    op.create_table(
        "share_cards",
        sa.Column("share_id", sa.String(length=20), primary_key=True),
        sa.Column(
            "article_id",
            sa.String(length=32),
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("article_title", sa.String(length=200), nullable=False),
        sa.Column("card_url", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("share_cards")
    op.drop_table("settings")
    op.drop_table("articles")
    op.drop_table("daily_issues")
