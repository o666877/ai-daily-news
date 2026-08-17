"""Migration 006: articles.is_must_read column + suffix-rule backfill (specs/004 cand 1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

_BACKEND_DIR = Path(__file__).resolve().parents[2]

_ARTICLE_COLS = (
    "id, issue_id, type, src, title, excerpt, lede, summary, body, quote, "
    "points, time, source_url, source_name, reading_minutes, published_at"
)


@pytest.fixture()
def legacy_db(tmp_path, monkeypatch):
    monkeypatch.delenv("AIDAILY_DB_PATH", raising=False)
    db_path = tmp_path / "legacy.db"
    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "005")
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO daily_issues (id, date, edition, status, filters_applied) "
                "VALUES ('20260817', '2026-08-17', 1, 'ready', '{}')"
            )
        )
        for aid in ("20260817-0001", "20260817-0003", "20260817-0004", "20260817-0012", "20260817-SCORE-1"):
            conn.execute(
                text(
                    f"INSERT INTO articles ({_ARTICLE_COLS}) VALUES ("
                    ":id, '20260817', 'tools', 'web', 't', 'e', 'l', 's', 'b', "
                    "NULL, '[\"p\"]', '09:00', 'https://a.com', 'a.com', 1, '2026-08-17')"
                ),
                {"id": aid},
            )
    yield cfg, db_path
    engine.dispose()


def _flags(db_path: Path) -> dict[str, int]:
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT id, is_must_read FROM articles")).all()
            return dict(rows)
    finally:
        engine.dispose()


def test_migration_006_backfills_suffix_rule(legacy_db):
    cfg, db_path = legacy_db
    command.upgrade(cfg, "006")
    flags = _flags(db_path)
    assert flags["20260817-0001"] == 1
    assert flags["20260817-0003"] == 1
    assert flags["20260817-0004"] == 0
    assert flags["20260817-0012"] == 0


def test_migration_006_non_standard_id_not_flagged(legacy_db):
    """Test-style ids like 'SCORE-1' must never be flagged by the backfill."""
    cfg, db_path = legacy_db
    command.upgrade(cfg, "006")
    assert _flags(db_path)["20260817-SCORE-1"] == 0


def test_migration_006_downgrade_drops_column(legacy_db):
    cfg, db_path = legacy_db
    command.upgrade(cfg, "006")
    command.downgrade(cfg, "005")
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            cols = [r[1] for r in conn.execute(text("PRAGMA table_info(articles)"))]
    finally:
        engine.dispose()
    assert "is_must_read" not in cols
