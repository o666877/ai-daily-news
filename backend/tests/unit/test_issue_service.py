"""Unit tests for app/services/issue_service.py.

Covers:
- _to_daily_issue: maps ORM → Pydantic with all fields
- _compute_summary: counts byType and bySource correctly
- get_issue_by_id: returns ORM or None
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import ArticleORM
from app.models.daily_issue import DailyIssueORM, IssueStatus
from app.models.meta import SOURCE_KEYS, TYPE_KEYS, SourceKey, TypeKey
from app.services.issue_service import (
    _compute_summary,
    _to_daily_issue,
    get_issue_by_id,
    get_today,
)


def _make_issue_orm(**overrides):
    defaults = {
        "id": "20260812",
        "date": "2026-08-12",
        "edition": 3,
        "status": IssueStatus.READY.value,
        "generated_at": datetime(2026, 8, 12, 8, 0, tzinfo=timezone.utc),
        "filters_applied": {
            "sources": ["x", "github", "reddit", "web"],
            "types": ["agent", "self_improve", "open_source", "tools"],
        },
    }
    defaults.update(overrides)
    return DailyIssueORM(**defaults)


# ---------- _to_daily_issue ----------

@pytest.mark.asyncio
async def test_to_daily_issue_happy_path():
    orm = _make_issue_orm()
    issue = await _to_daily_issue(orm, article_count=5)
    assert issue.id == "20260812"
    assert issue.date == "2026-08-12"
    assert issue.edition == 3
    assert issue.status == IssueStatus.READY
    assert issue.generatedAt is not None
    assert issue.articleCount == 5
    # filters
    assert set(issue.filtersApplied.sources) == {
        SourceKey.X, SourceKey.GITHUB, SourceKey.REDDIT, SourceKey.WEB
    }
    assert set(issue.filtersApplied.types) == {
        TypeKey.AGENT, TypeKey.SELF_IMPROVE, TypeKey.OPEN_SOURCE, TypeKey.TOOLS
    }


@pytest.mark.asyncio
async def test_to_daily_issue_no_filters_defaults_empty():
    orm = _make_issue_orm(filters_applied={"sources": [], "types": []})
    issue = await _to_daily_issue(orm, article_count=0)
    assert issue.filtersApplied.sources == []
    assert issue.filtersApplied.types == []


@pytest.mark.asyncio
async def test_to_daily_issue_null_filters():
    """Null filters_applied → empty lists, no crash."""
    orm = _make_issue_orm(filters_applied=None)
    issue = await _to_daily_issue(orm, article_count=0)
    assert issue.filtersApplied.sources == []
    assert issue.filtersApplied.types == []


@pytest.mark.asyncio
async def test_to_daily_issue_generating_status():
    orm = _make_issue_orm(status=IssueStatus.GENERATING.value, generated_at=None)
    issue = await _to_daily_issue(orm, article_count=0)
    assert issue.status == IssueStatus.GENERATING
    assert issue.generatedAt is None


# ---------- _compute_summary ----------

@pytest.mark.asyncio
async def test_compute_summary_empty(db_session):
    """No articles → all keys present, all zero."""
    summary = await _compute_summary(db_session, "20260812")
    assert summary.byType == {k: 0 for k in TYPE_KEYS}
    assert summary.bySource == {k: 0 for k in SOURCE_KEYS}


@pytest.mark.asyncio
async def test_compute_summary_counts(db_session, ready_issue_with_articles):
    """Counts match article rows. Fixture: 1 reddit/agent, 1 x/tools."""
    issue_id, _ = ready_issue_with_articles
    summary = await _compute_summary(db_session, issue_id.id)
    assert summary.byType[TypeKey.AGENT] == 1
    assert summary.byType[TypeKey.TOOLS] == 1
    assert summary.byType[TypeKey.SELF_IMPROVE] == 0
    assert summary.byType[TypeKey.OPEN_SOURCE] == 0
    assert summary.bySource[SourceKey.REDDIT] == 1
    assert summary.bySource[SourceKey.X] == 1


# ---------- get_issue_by_id ----------

@pytest.mark.asyncio
async def test_get_issue_by_id_found(db_session, ready_issue_with_articles):
    issue, _ = ready_issue_with_articles
    found = await get_issue_by_id(db_session, issue.id)
    assert found is not None
    assert found.id == issue.id


@pytest.mark.asyncio
async def test_get_issue_by_id_missing(db_session):
    found = await get_issue_by_id(db_session, "99999999")
    assert found is None


# ---------- get_today (additional cases beyond integration tests) ----------

@pytest.mark.asyncio
async def test_get_today_no_issue_raises_2002(db_session):
    from app.infra.errors import IssueNotGeneratedError

    with pytest.raises(IssueNotGeneratedError) as exc_info:
        await get_today(db_session)
    assert exc_info.value.code == 2002


@pytest.mark.asyncio
async def test_get_today_failed_issue_raises_2002(db_session):
    """Failed status is treated as not-generated (2002)."""
    from app.infra.errors import IssueNotGeneratedError

    now = datetime.now(timezone.utc)
    issue = DailyIssueORM(
        id=now.strftime("%Y%m%d"),
        date=now.strftime("%Y-%m-%d"),
        status=IssueStatus.FAILED.value,
        filters_applied={"sources": [], "types": []},
    )
    db_session.add(issue)
    await db_session.commit()

    with pytest.raises(IssueNotGeneratedError):
        await get_today(db_session)


@pytest.mark.asyncio
async def test_get_today_generating_raises_2003(db_session):
    from app.infra.errors import IssueGeneratingError

    now = datetime.now(timezone.utc)
    issue = DailyIssueORM(
        id=now.strftime("%Y%m%d"),
        date=now.strftime("%Y-%m-%d"),
        status=IssueStatus.GENERATING.value,
        filters_applied={"sources": [], "types": []},
    )
    db_session.add(issue)
    await db_session.commit()

    with pytest.raises(IssueGeneratingError) as exc_info:
        await get_today(db_session)
    assert exc_info.value.code == 2003


__all__ = []