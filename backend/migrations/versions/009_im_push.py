"""settings.im_push: 企业微信推送配置 JSON 列 (specs/006 ticket 01).

存量行落 {} (默认关闭、无 webhook),读取侧对缺失值按默认处理。

Revision ID: 009
Revises: 008
Create Date: 2026-08-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(
            sa.Column("im_push", sa.JSON(), nullable=False, server_default="{}")
        )


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("im_push")
