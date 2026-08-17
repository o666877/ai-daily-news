"""Shared pytest fixtures.

- `client`: httpx.AsyncClient with ASGITransport against the real FastAPI app.
- `db_session`: real in-memory SQLite session (no DB mocking per constitution II).
- Override `get_session` dependency to use the test engine.
- Override LLM client via `monkeypatch` to avoid real Anthropic calls.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import models  # noqa: F401 register ORM
from app.config import get_settings, reset_settings_cache
from app.infra import db as db_module
from app.infra.db import Base, init_db
from app.infra.db import get_session as real_get_session


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch, tmp_path):
    """Force settings: in-memory SQLite, deterministic TZ, dummy creds."""
    monkeypatch.setenv("AIDAILY_DB_PATH", ":memory:")
    monkeypatch.setenv("AIDAILY_LLM_API_KEY", "test-key")
    monkeypatch.setenv("AIDAILY_LLM_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("AIDAILY_LLM_MODEL", "claude-test-model")
    monkeypatch.setenv("AIDAILY_BEARER_TOKEN", "test-bearer-token")
    monkeypatch.setenv("AIDAILY_TZ", "UTC")
    monkeypatch.setenv("AIDAILY_DAILY_PUSH_TIME", "08:00")
    # X collector: zero retry backoff so failure-path tests stay fast.
    monkeypatch.setenv("AIDAILY_X_RETRY_BACKOFF_S", "0")
    reset_settings_cache()
    # Reset DB engine cache so new settings apply.
    db_module._engine = None
    db_module._session_factory = None
    yield
    reset_settings_cache()
    db_module._engine = None
    db_module._session_factory = None


@pytest_asyncio.fixture
async def test_engine():
    """Provide a fresh in-memory engine + tables per test."""
    engine = db_module.make_engine(":memory:")
    await init_db(engine)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncIterator[AsyncSession]:
    """Yield a session bound to the test engine."""
    factory = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        # Patch the global factory to use this one (for code paths that call get_session_factory).
        db_module._session_factory = factory
        db_module._engine = test_engine
        yield session


@pytest_asyncio.fixture
async def client(db_session) -> AsyncIterator[AsyncClient]:
    """HTTP client bound to FastAPI via ASGITransport; uses the test DB."""
    from app.main import create_app

    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        # Yield from the same factory bound to the in-memory engine.
        factory = db_module.get_session_factory()
        async with factory() as session:
            yield session

    app.dependency_overrides[real_get_session] = _override_session

    # Avoid scheduler + first-install firing during tests.
    async def _noop():  # noqa: RUF029
        return None

    app.router.lifespan_context = lambda _app: _noop_lifespan()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class _noop_lifespan:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *args):
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def ready_issue_with_articles(db_session):
    """Seed: a ready DailyIssue + 2 articles (one reddit/agent, one x/tools).

    Uses today's date (UTC) so /daily/today resolves correctly regardless of
    when the test suite runs.
    """
    from app.models.article import ArticleORM
    from app.models.daily_issue import DailyIssueORM

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_gen = datetime.now(timezone.utc).replace(hour=8, minute=0, second=0, microsecond=0)

    issue = DailyIssueORM(
        id=today,
        date=today_iso,
        edition=1,
        status="ready",
        generated_at=today_gen,
        filters_applied={
            "sources": ["x", "github", "reddit", "web"],
            "types": ["agent", "self_improve", "open_source", "tools"],
        },
    )
    db_session.add(issue)
    await db_session.commit()  # commit issue first so FK resolves

    art1 = ArticleORM(
        id=f"{today}-0001",
        issue_id=today,
        type="agent",
        src="reddit",
        title="Reddit Agent Post",
        excerpt="Reddit agent excerpt",
        lede="Reddit lede paragraph",
        summary="Reddit one-liner",
        body="Body para 1\n\nBody para 2",
        quote=None,
        points=["Point 1", "Point 2"],
        time="09:00",
        source_url="https://reddit.com/r/example/1",
        source_name="reddit.com/r/MachineLearning",
        reading_minutes=4,
        published_at="2026-08-12T09:00:00+00:00",
    )
    art2 = ArticleORM(
        id=f"{today}-0002",
        issue_id=today,
        type="tools",
        src="x",
        title="X Tools Post",
        excerpt="X tools excerpt",
        lede="X lede",
        summary="X summary",
        body="X body",
        quote="quote text",
        points=["X point"],
        time="10:00",
        source_url="https://x.com/example/status/2",
        source_name="x.com/@swyx",
        reading_minutes=2,
        published_at="2026-08-12T10:00:00+00:00",
    )
    db_session.add(art1)
    db_session.add(art2)
    await db_session.commit()
    return issue, [art1, art2]


def mock_summary_response(
    title: str = "测试用中文标题",
    lede: str = "导语段落",
    summary: str = "一句话总结。",
    body: str | None = None,
    quote: str | None = None,
    points: list[str] | None = None,
) -> str:
    """Return JSON text as if from the LLM."""
    return json.dumps(
        {
            "title": title,
            "lede": lede,
            "summary": summary,
            "body": body or "段一\n\n段二",
            "quote": quote,
            "points": points or ["要点 1", "要点 2"],
        },
        ensure_ascii=False,
    )


@pytest.fixture
def patch_llm_success(monkeypatch):
    """Monkeypatch the LLM client to return a successful summary without network."""
    from app.infra import llm as llm_module
    from app.pipeline import summarizer as summarizer_module

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def summarize(self, title, source, raw_text):
            return llm_module._parse_summary_response(mock_summary_response())

        async def complete_json(self, prompt, system=None):
            return mock_summary_response()

    monkeypatch.setattr(llm_module, "LLMClient", _FakeClient)
    return _FakeClient


__all__ = ["client", "db_session", "mock_summary_response", "patch_llm_success", "ready_issue_with_articles"]
