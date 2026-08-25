"""im_push_logs: per-issue per-webhook push records (specs/006 ticket 03).

Revision ID: 010
Revises: 009
Create Date: 2026-08-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "im_push_logs" in inspector.get_table_names():
        return

    op.create_table(
        "im_push_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "issue_id",
            sa.String(length=8),
            sa.ForeignKey("daily_issues.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("webhook_name", sa.String(length=20), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("errcode", sa.Integer(), nullable=True),
        sa.Column("errmsg", sa.String(length=200), nullable=False),
        sa.Column("pushed_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_im_push_logs_issue", "im_push_logs", ["issue_id"])


def downgrade() -> None:
    op.drop_index("ix_im_push_logs_issue", table_name="im_push_logs")
    op.drop_table("im_push_logs")
