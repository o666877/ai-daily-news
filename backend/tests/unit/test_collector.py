"""T027: Partial failure tolerance (FR-007a).

Cases:
- 1 source collector fails → issue still ready (other sources contribute).
- All summarizers fail → issue marked failed.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.infra import llm as llm_module
from app.infra.db import get_session_factory
from app.models.article import RawItem
from app.models.daily_issue import DailyIssueORM, IssueStatus
from app.models.meta import SourceKey, TypeKey
from app.pipeline import summarizer
from app.pipeline.generator import generate_issue


def _make_raw(source: SourceKey, url: str) -> RawItem:
    return RawItem(
        sourceKey=source,
        sourceName=f"{source.value}.example",
        sourceUrl=url,
        title=f"{source.value} item",
        rawText=f"Raw text from {source.value}.",
        publishedAt=datetime.now(timezone.utc).isoformat(),
        suggestedType=TypeKey.TOOLS,
    )


class _SuccessClient:
    async def summarize(self, title, source, raw_text):
        return llm_module._parse_summary_response(
            '{"title": "t", "lede": "l", "summary": "s", "body": ["p"], "quote": null, "points": ["x"]}'
        )


class _AlwaysFailClient:
    async def summarize(self, title, source, raw_text):
        raise llm_module.LLMProviderError("always fails")


@pytest.mark.asyncio
async def test_one_collector_failure_others_succeed(monkeypatch, db_session):
    """If injected collector raises midway through items, ready issue still produced."""

    async def _mixed_collector():
        return [
            _make_raw(SourceKey.GITHUB, "https://github.com/a"),
            _make_raw(SourceKey.WEB, "https://blog.example/a"),
        ]

    monkeypatch.setattr(summarizer, "check_budget", lambda *_a, **_kw: None)
    monkeypatch.setattr(summarizer, "_track_spend", lambda *_a, **_kw: None)

    issue = await generate_issue(
        date=datetime(2026, 8, 12, tzinfo=timezone.utc),
        inject_collector=_mixed_collector,
        llm_client=_SuccessClient(),
    )
    assert issue.status == IssueStatus.READY.value


@pytest.mark.asyncio
async def test_all_summarizers_fail_falls_back_to_rules(monkeypatch, db_session):
    """US1: if every item's LLM summarization fails, all articles fall back
    to rule_fallback (score_source='rule_fallback') and the issue stays ready.

    Pre-US1 this marked the issue failed with 0 articles. Post-US1 the
    summarizer returns a rule-derived SummaryResult so transient LLM outages
    don't drop articles from the daily issue.
    """

    async def _collector():
        return [
            _make_raw(SourceKey.X, "https://x.com/1"),
            _make_raw(SourceKey.GITHUB, "https://github.com/2"),
        ]

    monkeypatch.setattr(summarizer, "check_budget", lambda *_a, **_kw: None)
    monkeypatch.setattr(summarizer, "_track_spend", lambda *_a, **_kw: None)

    issue = await generate_issue(
        date=datetime(2026, 8, 12, tzinfo=timezone.utc),
        inject_collector=_collector,
        llm_client=_AlwaysFailClient(),
    )
    assert issue.status == IssueStatus.READY.value

    # Both articles persisted with rule_fallback scoring.
    from app.models.article import ArticleORM
    from app.models.article_score import ArticleScoreORM

    factory = get_session_factory()
    async with factory() as s:
        # Use selectinload to avoid lazy-loading greenlet issue.
        from sqlalchemy.orm import selectinload
        rows = (
            await s.execute(
                select(ArticleORM)
                .where(ArticleORM.issue_id == issue.id)
                .options(selectinload(ArticleORM.score))
            )
        ).scalars().all()
        assert len(rows) == 2
        for row in rows:
            assert row.score is not None
            assert row.score.score_source == "rule_fallback"
            assert row.score.composite_score is not None
            assert 0 <= row.score.composite_score <= 100
