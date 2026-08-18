"""settings.daily_count: add 15 to the enum and move the default from 30 to 15.

Migration 003 created the column with server_default 30 and a check
constraint of (10, 20, 30, 40, 50); the runtime default was later dropped to
8 (accepted only through the ORM-level constraint) and now to 15, which
neither the constraint nor the server default knew about. This migration
aligns the database with DAILY_COUNT_VALUES = (8, 10, 15, 20, 30, 40, 50)
and sets server_default 15. Existing row values are untouched.

Revision ID: 007
Revises: 006
Create Date: 2026-08-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The dev database's settings table was created without inline named
    # CHECK constraints (SQLite never got them from 003's batch ops), so
    # dropping must be conditional or batch mode raises "No such constraint".
    insp = sa.inspect(op.get_bind())
    checks = {c["name"] for c in insp.get_check_constraints("settings")}
    with op.batch_alter_table("settings") as batch_op:
        if "settings_daily_count_enum" in checks:
            batch_op.drop_constraint("settings_daily_count_enum", type_="check")
        batch_op.create_check_constraint(
            "settings_daily_count_enum",
            "daily_count IN (8, 10, 15, 20, 30, 40, 50)",
        )
        batch_op.alter_column(
            "daily_count", existing_type=sa.Integer(), server_default="15"
        )


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.alter_column(
            "daily_count", existing_type=sa.Integer(), server_default="30"
        )
        batch_op.drop_constraint("settings_daily_count_enum", type_="check")
        batch_op.create_check_constraint(
            "settings_daily_count_enum",
            "daily_count IN (10, 20, 30, 40, 50)",
        )
        # downgrade after this point cannot restore the missing inline
        # constraints case; the constraint simply lands where it was.
