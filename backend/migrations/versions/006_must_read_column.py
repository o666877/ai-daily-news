"""articles.is_must_read: persist the editorial top-N flag (specs/004 cand 1).

The mustRead business rule previously lived as id-suffix string parsing on
three read paths. This migration adds the column and backfills legacy rows
with the same suffix rule (one-time), after which the rule is written once
at generation time from the persistence index.

Revision ID: 006
Revises: 005
Create Date: 2026-08-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("articles") as batch_op:
        batch_op.add_column(
            sa.Column("is_must_read", sa.Boolean(), nullable=False, server_default="0")
        )
    # One-time backfill: ids are f"{issue_id}-{index:04d}" in display order,
    # so suffix 0001-0003 marks the historical editorial top-3. Exact LIKE
    # patterns avoid false positives on non-standard ids (e.g. test rows).
    op.get_bind().execute(
        sa.text(
            "UPDATE articles SET is_must_read = 1 "
            "WHERE id LIKE '%-0001' OR id LIKE '%-0002' OR id LIKE '%-0003'"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("articles") as batch_op:
        batch_op.drop_column("is_must_read")
