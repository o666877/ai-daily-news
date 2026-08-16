"""T076: additive migration for `share_cards` table.

Idempotent guard: schema migration 001 already pre-creates `share_cards` for
the MVP fast-path (avoiding a two-step migration at first install). This file
remains the canonical, additive migration entry so:

- Fresh installs that apply migrations sequentially from scratch still get the
  table through a normal alembic upgrade path.
- Existing deployments (where 001 already ran) skip the redundant create
  via the inspector check below — no destructive ALTER on an existing table.

Revision ID: 002
Revises: 001
Create Date: 2026-08-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create share_cards if absent (additive, no breaking changes)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "share_cards" in inspector.get_table_names():
        return

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
    op.create_index("ix_share_cards_article_id", "share_cards", ["article_id"])


def downgrade() -> None:
    """Drop share_cards only if it exists (defensive)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "share_cards" in inspector.get_table_names():
        op.drop_table("share_cards")
