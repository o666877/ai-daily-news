"""settings: drop style_mode; narrow daily_count enum to (10, 15, 20, 30).

style_mode lost its only consumer when the reading-density UI was removed
(frontend now renders a fixed standard layout); the column is dead weight.
daily_count narrows from 7 values to the 4 the UI exposes. Existing rows
holding a dropped value are normalized first (nearest mapping: 8→10,
40→30, 50→30) so the new check constraint cannot fail on the next UPDATE.

Revision ID: 008
Revises: 007
Create Date: 2026-08-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE settings SET daily_count = CASE "
            "WHEN daily_count <= 10 THEN 10 "
            "ELSE 30 END "
            "WHERE daily_count NOT IN (10, 15, 20, 30)"
        )
    )
    # Conditional drops: the dev database predates the inline named CHECK
    # constraints (see 007), so reflection may find nothing to drop.
    insp = sa.inspect(op.get_bind())
    checks = {c["name"] for c in insp.get_check_constraints("settings")}
    with op.batch_alter_table("settings") as batch_op:
        if "settings_style_mode_enum" in checks:
            batch_op.drop_constraint("settings_style_mode_enum", type_="check")
        batch_op.drop_column("style_mode")
        if "settings_daily_count_enum" in checks:
            batch_op.drop_constraint("settings_daily_count_enum", type_="check")
        batch_op.create_check_constraint(
            "settings_daily_count_enum",
            "daily_count IN (10, 15, 20, 30)",
        )


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_constraint("settings_daily_count_enum", type_="check")
        batch_op.create_check_constraint(
            "settings_daily_count_enum",
            "daily_count IN (8, 10, 15, 20, 30, 40, 50)",
        )
        batch_op.add_column(
            sa.Column("style_mode", sa.String(16), nullable=False, server_default="standard")
        )
        batch_op.create_check_constraint(
            "settings_style_mode_enum",
            "style_mode IN ('concise', 'standard', 'detailed')",
        )
