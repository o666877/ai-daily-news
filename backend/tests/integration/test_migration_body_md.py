"""Migration 005: articles.body JSON array → markdown TEXT string (specs/002).

Builds a real DB via alembic 001→004, seeds legacy-format rows, upgrades to
005, and asserts the stored conversion. Highest-fidelity seam for the data
conversion: exercises the exact migration chain that production runs.
"""

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


def _cfg(db_path: Path) -> Config:
    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    # Skip alembic.ini's fileConfig() — it resets global logging and breaks
    # caplog capture in tests that run after this one.
    cfg.attributes["configure_logger"] = False
    return cfg


def _insert_article(conn, article_id: str, body: str) -> None:
    conn.execute(
        text(
            f"INSERT INTO articles ({_ARTICLE_COLS}) VALUES ("
            ":id, :issue_id, 'agent', 'github', 't', 'e', 'l', 's', :body, "
            "NULL, '[\"p\"]', '09:00', 'https://a.com', 'a.com', 1, '2026-08-16')"
        ),
        {"id": article_id, "issue_id": "20260816", "body": body},
    )


@pytest.fixture()
def legacy_db(tmp_path, monkeypatch):
    """A 004-schema DB with legacy-format body rows."""
    # conftest sets AIDAILY_DB_PATH=":memory:"; migrations/env.py would pick
    # it up and run against a throwaway DB instead of our tmp file.
    monkeypatch.delenv("AIDAILY_DB_PATH", raising=False)
    db_path = tmp_path / "legacy.db"
    cfg = _cfg(db_path)
    command.upgrade(cfg, "004")
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO daily_issues (id, date, edition, status, filters_applied) "
                "VALUES ('20260816', '2026-08-16', 1, 'ready', '{}')"
            )
        )
        _insert_article(conn, "20260816-0001", json.dumps(["段一", "段二"]))
        _insert_article(conn, "20260816-0002", json.dumps(["段一", "", "段三"]))
        _insert_article(conn, "20260816-0003", json.dumps([]))
        _insert_article(conn, "20260816-0004", "已是纯文本段落")
    yield cfg, db_path
    engine.dispose()


def _fetch_body(db_path: Path, article_id: str) -> object:
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            return conn.execute(
                text("SELECT body FROM articles WHERE id = :i"), {"i": article_id}
            ).scalar()
    finally:
        engine.dispose()


def test_migration_005_joins_array_paragraphs(legacy_db):
    cfg, db_path = legacy_db
    command.upgrade(cfg, "005")
    assert _fetch_body(db_path, "20260816-0001") == "段一\n\n段二"


def test_migration_005_drops_empty_segments(legacy_db):
    cfg, db_path = legacy_db
    command.upgrade(cfg, "005")
    assert _fetch_body(db_path, "20260816-0002") == "段一\n\n段三"


def test_migration_005_empty_array_becomes_empty_string(legacy_db):
    cfg, db_path = legacy_db
    command.upgrade(cfg, "005")
    assert _fetch_body(db_path, "20260816-0003") == ""


def test_migration_005_plain_text_passthrough(legacy_db):
    cfg, db_path = legacy_db
    command.upgrade(cfg, "005")
    assert _fetch_body(db_path, "20260816-0004") == "已是纯文本段落"


def test_migration_005_downgrade_restores_array_form(legacy_db):
    cfg, db_path = legacy_db
    command.upgrade(cfg, "005")
    command.downgrade(cfg, "004")
    assert _fetch_body(db_path, "20260816-0001") == json.dumps(["段一", "段二"], ensure_ascii=False)
