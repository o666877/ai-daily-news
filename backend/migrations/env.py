"""Alembic environment. Uses synchronous engine for migrations.

Per T009, autogenerate is configured against app.models metadata.
"""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure backend/ is on sys.path so `app.*` imports resolve.
THIS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = THIS_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.infra.db import Base  # noqa: E402
from app import models  # noqa: F401, E402  (register ORM on Base.metadata)

config = context.config

# Honor configure_logger=False (set by tests) so fileConfig() doesn't reset
# global logging — disable_existing_loggers would break later caplog capture.
if config.config_file_name is not None and config.attributes.get(
    "configure_logger", True
):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Override sqlalchemy.url from env if set.
db_path = os.environ.get("AIDAILY_DB_PATH")
if db_path:
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True,  # SQLite-friendly ALTER
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
