"""specs/005 part 1: cross-issue dedup.

recent_published_keys: URLs + topic_ids from the N most recent issues before
the generating issue. exclude_published wiring: candidates already published
in that window never reach the new issue (hard drop, no score exemption).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra import db as db_module
from app.infra.llm import SummaryResult
from app.models.article import ArticleORM, RawItem, SourceKey, TypeKey
from app.models.daily_issue import IssueStatus
from app.pipeline import generator as gen_mod
from app.pipeline import summarizer
from app.pipeline.issue_repository import recent_published_keys


# ---------- recent_published_keys ----------


def _raw(url: str) -> RawItem:
    return RawItem(
        sourceKey=SourceKey.WEB,
        sourceName="stub",
        sourceUrl=url,
        title=f"title {url}",
        rawText="x" * 200,
        publishedAt=datetime.now(timezone.utc).isoformat(),
        suggestedType=TypeKey.AGENT,
    )


def _summary_for(url: str, topic_map: dict[str, str]) -> SummaryResult:
    return SummaryResult(
        title=f"title {url}",
        lede="",
        summary="",
        body=[],
        quote=None,
        points=[],
        dimension_scores={
            "authority": 50, "depth": 50, "timeliness": 50, "expression": 50,
        },
        authority_tier="community",
        topic_id=topic_map.get(url),
        opinion_fingerprint=None,
        composite_score=80,
        score_source="llm",
    )


async def _generate_with(
    date: datetime, items: list[RawItem], topic_map: dict[str, str]
):
    async def _collector() -> list[RawItem]:
        return items

    async def _summarize(item: RawItem, **_kwargs: Any) -> SummaryResult:
        return _summary_for(item.sourceUrl, topic_map)

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(gen_mod, "collect_all", _collector)
        monkey.setattr(summarizer, "summarize_item", _summarize)
        monkey.setattr(summarizer, "check_budget", lambda *_a, **_kw: None)
        monkey.setattr(summarizer, "_track_spend", lambda *_a, **_kw: None)
        factory = db_module.get_session_factory()
        db_module._session_factory = factory
        return await gen_mod.generate_issue(date=date)
    finally:
        monkey.undo()


async def _article_urls(session: AsyncSession, issue_id: str) -> set[str]:
    from sqlalchemy import select

    from app.models.article import ArticleORM

    rows = (
        await session.execute(
            select(ArticleORM.source_url).where(ArticleORM.issue_id == issue_id)
        )
    ).all()
    return {r[0] for r in rows}


@pytest.mark.asyncio
async def test_recent_published_keys_window_and_join(db_session: AsyncSession):
    """Keys come from the 3 issues immediately before the generating issue —
    the 4th-oldest issue is out of the window; topic_id joins via scores."""
    topic_map = {"https://example.com/d1": "topic-d1"}
    await _generate_with(
        datetime(2026, 8, 14, tzinfo=timezone.utc),
        [_raw("https://example.com/d1")],
        topic_map,
    )
    await _generate_with(
        datetime(2026, 8, 15, tzinfo=timezone.utc),
        [_raw("https://example.com/d2")],
        {},
    )
    await _generate_with(
        datetime(2026, 8, 16, tzinfo=timezone.utc),
        [_raw("https://example.com/d3")],
        {},
    )
    # 4 issues back: outside the 3-issue lookback.
    await _generate_with(
        datetime(2026, 8, 12, tzinfo=timezone.utc),
        [_raw("https://example.com/d0-old")],
        {},
    )

    urls, topics = await recent_published_keys(
        db_session, before_issue_id="20260817", issues=3
    )
    assert urls == {
        "https://example.com/d1",
        "https://example.com/d2",
        "https://example.com/d3",
    }
    assert topics == {"topic-d1"}


@pytest.mark.asyncio
async def test_recent_published_keys_empty_when_no_history(db_session: AsyncSession):
    urls, topics = await recent_published_keys(
        db_session, before_issue_id="20260818", issues=3
    )
    assert urls == set()
    assert topics == set()


@pytest.mark.asyncio
async def test_second_issue_excludes_published_url_and_topic(
    db_session: AsyncSession,
):
    """Day 1 publishes URL A (topic T). Day 2 candidates: URL A again, a
    different URL carrying the same topic T, and a fresh story → only the
    fresh story survives into day 2."""
    day1_items = [_raw("https://example.com/story-a")]
    await _generate_with(
        datetime(2026, 8, 17, tzinfo=timezone.utc),
        day1_items,
        {"https://example.com/story-a": "story-a-topic"},
    )

    day2_items = [
        _raw("https://example.com/story-a"),                       # same URL
        _raw("https://other.example.com/story-a-coverage"),        # same topic, new URL
        _raw("https://example.com/story-b"),                       # fresh
    ]
    issue2 = await _generate_with(
        datetime(2026, 8, 18, tzinfo=timezone.utc),
        day2_items,
        {
            "https://example.com/story-a": "story-a-topic",
            "https://other.example.com/story-a-coverage": "story-a-topic",
            "https://example.com/story-b": "story-b-topic",
        },
    )
    assert issue2.status == IssueStatus.READY.value

    urls = await _article_urls(db_session, issue2.id)
    assert urls == {"https://example.com/story-b"}


@pytest.mark.asyncio
async def test_regeneration_same_issue_not_self_blocked(db_session: AsyncSession):
    """Regeneration deletes the issue first, so its own rows are gone from
    the lookback — the same URL re-enters the rebuilt issue."""
    from sqlalchemy import delete as sa_delete

    from app.models.article_score import ArticleScoreORM
    from app.models.daily_issue import DailyIssueORM

    day1 = [_raw("https://example.com/regen")]
    issue = await _generate_with(
        datetime(2026, 8, 17, tzinfo=timezone.utc),
        day1,
        {"https://example.com/regen": "regen-topic"},
    )
    assert issue.status == IssueStatus.READY.value

    # Regeneration path: delete the issue (cascading its rows), then rebuild.
    await db_session.execute(
        sa_delete(ArticleScoreORM).where(
            ArticleScoreORM.article_id.like(f"{issue.id}-%")
        )
    )
    await db_session.execute(
        sa_delete(ArticleORM).where(ArticleORM.issue_id == issue.id)
    )
    await db_session.execute(
        sa_delete(DailyIssueORM).where(DailyIssueORM.id == issue.id)
    )
    await db_session.commit()

    # Contract: regeneration removes issue + articles + scores. If articles
    # survived as orphans the lookback would still see this issue's keys and
    # the rebuild would be self-blocked.
    urls_after, topics_after = await recent_published_keys(
        db_session, before_issue_id=issue.id, issues=3
    )
    assert "https://example.com/regen" not in urls_after
    assert "regen-topic" not in topics_after

    issue_again = await _generate_with(
        datetime(2026, 8, 17, tzinfo=timezone.utc),
        day1,
        {"https://example.com/regen": "regen-topic"},
    )
    assert issue_again.status == IssueStatus.READY.value
    urls = await _article_urls(db_session, issue_again.id)
    assert urls == {"https://example.com/regen"}


__all__ = []
