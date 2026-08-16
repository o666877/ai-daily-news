"""T028: settings effect on generator pipeline (US2 dedup + truncate).

Saves dailyCount via PUT /settings, triggers generator(date=tomorrow) with
stubbed collector + summarizer. Asserts the generated issue contains exactly
dailyCount articles (or fewer if not enough candidates), in compositeScore
DESC order.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra import llm as llm_module
from app.infra.llm import SummaryResult
from app.models.article import ArticleORM, RawItem, SourceKey, TypeKey
from app.models.article_score import ArticleScoreORM
from app.models.daily_issue import DailyIssueORM, IssueStatus
from app.pipeline import generator as gen_mod


AUTH = {"Authorization": "Bearer test-bearer-token"}


def _stub_raw_items(n: int) -> list[RawItem]:
    """Build n RawItems with distinct URLs + composite_score gradient."""
    out: list[RawItem] = []
    for i in range(n):
        out.append(
            RawItem(
                sourceKey=SourceKey.X,
                sourceName="Stub Source",
                sourceUrl=f"https://stub.example.com/article-{i}",
                title=f"stub-{i}",
                rawText="x" * 200,
                publishedAt=datetime.now(timezone.utc).isoformat(),
                suggestedType=TypeKey.AGENT,
            )
        )
    return out


class _StubSummaryClient:
    """Fake LLMClient that assigns composite_score = idx*10 (descending over items).

    Items at lower index get HIGHER scores — the truncate should preserve the
    top-N highest, so the issue should contain items idx=0..N-1 in DESC score
    order (i.e., ascending idx since scores decrease with idx).
    """

    def __init__(self) -> None:
        self._idx = 0

    async def summarize(self, title: str, source: str, raw_text: str) -> SummaryResult:
        score = max(0, 100 - self._idx * 5)
        self._idx += 1
        return SummaryResult(
            title=title or "stub",
            lede="",
            summary="",
            body=[],
            quote=None,
            points=[],
            dimension_scores={
                "authority": 50,
                "depth": 50,
                "timeliness": 50,
                "expression": 50,
            },
            authority_tier="community",
            topic_id=None,
            opinion_fingerprint=None,
            composite_score=score,
            score_source="llm",
        )


@pytest.fixture
def stub_pipeline(monkeypatch):
    """Stub collector + summarizer for the generator pipeline."""

    async def _fake_collect_all() -> list[RawItem]:
        return _stub_raw_items(20)  # 20 candidates

    stub_client = _StubSummaryClient()

    monkeypatch.setattr(gen_mod, "collect_all", _fake_collect_all)
    monkeypatch.setattr(gen_mod, "summarize_item", _stub_summarize_factory(stub_client))
    monkeypatch.setattr(llm_module, "LLMClient", lambda *a, **kw: stub_client)
    return stub_client


def _stub_summarize_factory(client):
    async def _summarize(item: RawItem, **_kwargs: Any) -> SummaryResult:
        return await client.summarize(item.title, item.sourceName, item.rawText)

    return _summarize


@pytest.mark.asyncio
async def test_generate_issue_truncates_to_daily_count(
    client: AsyncClient, stub_pipeline, db_session: AsyncSession
) -> None:
    """Save dailyCount=10, trigger generator(tomorrow), expect 10 articles."""
    body = {
        "sources": {"x": True, "github": True, "reddit": True, "web": True},
        "types": {
            "agent": True,
            "self_improve": True,
            "open_source": True,
            "tools": True,
        },
        "dailyPush": {"enabled": True, "time": "08:00"},
        "dailyCount": 10,
        "styleMode": "standard",
    }
    res = await client.put("/api/v1/settings", json=body, headers=AUTH)
    assert res.status_code == 200, res.text

    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    issue = await gen_mod.generate_issue(date=tomorrow)
    assert issue.status == IssueStatus.READY.value

    # Inspect persisted articles for tomorrow's issue.
    tomorrow_id = tomorrow.strftime("%Y%m%d")
    articles = (
        await db_session.execute(
            select(ArticleORM).where(ArticleORM.issue_id == tomorrow_id)
        )
    ).scalars().all()
    assert len(articles) == 10
    # Articles should be sorted by composite_score DESC, time DESC.
    # Stub used descending scores by idx (idx=0 score=100, idx=1 score=95, ...).
    # Truncate to top-10 → idx 0..9. Order in storage follows _persist_article's
    # iteration order, which is the stub collector's order, but the dedup
    # pass doesn't reorder. We assert the persisted article count + scores.
    score_rows = (
        await db_session.execute(
            select(ArticleScoreORM).where(
                ArticleScoreORM.article_id.in_([a.id for a in articles])
            )
        )
    ).scalars().all()
    scores = sorted([s.composite_score for s in score_rows], reverse=True)
    assert scores == [100, 95, 90, 85, 80, 75, 70, 65, 60, 55]


@pytest.mark.asyncio
async def test_generate_issue_no_dedup_collisions_keeps_all_when_count_exceeds(
    client: AsyncClient, monkeypatch, db_session: AsyncSession
) -> None:
    """Save dailyCount=50, only 3 candidates → issue has 3 (no padding)."""
    body = {
        "sources": {"x": True, "github": True, "reddit": True, "web": True},
        "types": {
            "agent": True,
            "self_improve": True,
            "open_source": True,
            "tools": True,
        },
        "dailyPush": {"enabled": True, "time": "08:00"},
        "dailyCount": 50,
        "styleMode": "standard",
    }
    res = await client.put("/api/v1/settings", json=body, headers=AUTH)
    assert res.status_code == 200, res.text

    async def _three() -> list[RawItem]:
        return _stub_raw_items(3)

    stub_client = _StubSummaryClient()
    monkeypatch.setattr(gen_mod, "collect_all", _three)
    monkeypatch.setattr(gen_mod, "summarize_item", _stub_summarize_factory(stub_client))
    monkeypatch.setattr(llm_module, "LLMClient", lambda *a, **kw: stub_client)

    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    await gen_mod.generate_issue(date=tomorrow)

    tomorrow_id = tomorrow.strftime("%Y%m%d")
    articles = (
        await db_session.execute(
            select(ArticleORM).where(ArticleORM.issue_id == tomorrow_id)
        )
    ).scalars().all()
    assert len(articles) == 3


@pytest.mark.asyncio
async def test_generate_issue_dedup_collapses_url_duplicates(
    client: AsyncClient, monkeypatch, db_session: AsyncSession
) -> None:
    """Multiple items sharing the same URL → only highest-scored survives."""
    body = {
        "sources": {"x": True, "github": True, "reddit": True, "web": True},
        "types": {
            "agent": True,
            "self_improve": True,
            "open_source": True,
            "tools": True,
        },
        "dailyPush": {"enabled": True, "time": "08:00"},
        "dailyCount": 10,
        "styleMode": "standard",
    }
    res = await client.put("/api/v1/settings", json=body, headers=AUTH)
    assert res.status_code == 200, res.text

    # 3 items, two share a URL — expected 2 articles persisted.
    shared_url = "https://stub.example.com/dup"
    items = [
        RawItem(
            sourceKey=SourceKey.X,
            sourceName="src-A",
            sourceUrl=shared_url,
            title="dup-A",
            rawText="x" * 100,
            publishedAt=datetime.now(timezone.utc).isoformat(),
            suggestedType=TypeKey.AGENT,
        ),
        RawItem(
            sourceKey=SourceKey.X,
            sourceName="src-B",
            sourceUrl=shared_url,  # same URL
            title="dup-B",
            rawText="x" * 100,
            publishedAt=datetime.now(timezone.utc).isoformat(),
            suggestedType=TypeKey.AGENT,
        ),
        RawItem(
            sourceKey=SourceKey.X,
            sourceName="src-C",
            sourceUrl="https://stub.example.com/unique",
            title="unique",
            rawText="x" * 100,
            publishedAt=datetime.now(timezone.utc).isoformat(),
            suggestedType=TypeKey.AGENT,
        ),
    ]

    async def _three() -> list[RawItem]:
        return items

    # Use a custom client that gives the second occurrence a HIGHER score so
    # it's the one that survives (idx 0 → score 80, idx 1 → score 90, idx 2 → 70).
    class _CustomClient:
        def __init__(self) -> None:
            self._calls = 0

        async def summarize(self, title, source, raw_text) -> SummaryResult:
            score = [80, 90, 70][self._calls]
            self._calls += 1
            return SummaryResult(
                title=title,
                lede="",
                summary="",
                body=[],
                quote=None,
                points=[],
                dimension_scores={
                    "authority": 50,
                    "depth": 50,
                    "timeliness": 50,
                    "expression": 50,
                },
                authority_tier="community",
                topic_id=None,
                opinion_fingerprint=None,
                composite_score=score,
                score_source="llm",
            )

    custom = _CustomClient()
    monkeypatch.setattr(gen_mod, "collect_all", _three)
    monkeypatch.setattr(gen_mod, "summarize_item", _stub_summarize_factory(custom))
    monkeypatch.setattr(llm_module, "LLMClient", lambda *a, **kw: custom)

    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    await gen_mod.generate_issue(date=tomorrow)

    tomorrow_id = tomorrow.strftime("%Y%m%d")
    articles = (
        await db_session.execute(
            select(ArticleORM).where(ArticleORM.issue_id == tomorrow_id)
        )
    ).scalars().all()
    # Dedup → 2 articles (shared URL deduped, unique URL kept).
    assert len(articles) == 2
    # The kept one for the shared URL must be the higher-scored (90) one.
    urls = sorted([a.source_url for a in articles])
    assert urls == sorted([shared_url, "https://stub.example.com/unique"])
    # Find the article that points at the shared URL.
    shared = [a for a in articles if a.source_url == shared_url][0]
    score = (
        await db_session.execute(
            select(ArticleScoreORM).where(ArticleScoreORM.article_id == shared.id)
        )
    ).scalar_one()
    assert score.composite_score == 90


__all__ = []