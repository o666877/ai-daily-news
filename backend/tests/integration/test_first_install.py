"""T025: First-install auto-trigger (FR-001b).

Scenario: empty DB → startup hook fires background generate_issue(today).
We test the helper directly (network-free) by injecting a fake collector +
fake LLM, then verifying an issue transitions to ready.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.infra.db import get_session_factory
from app.models.article import RawItem
from app.models.daily_issue import DailyIssueORM
from app.models.meta import SourceKey, TypeKey
from app.pipeline.generator import generate_issue


@pytest.mark.asyncio
async def test_first_install_generates_issue(test_engine, db_session, patch_llm_success):
    """generate_issue on empty DB creates a ready issue with articles."""

    async def _fake_collector():
        return [
            RawItem(
                sourceKey=SourceKey.GITHUB,
                sourceName="github.com",
                sourceUrl="https://github.com/test/repo",
                title="Test Repo",
                rawText="A great new AI repo for agents.",
                publishedAt="2026-08-12T08:00:00+00:00",
                suggestedType=TypeKey.AGENT,
            )
        ]

    target_id = "20260812"
    issue = await generate_issue(
        date=__import__("datetime").datetime(2026, 8, 12, tzinfo=__import__("datetime").timezone.utc),
        inject_collector=_fake_collector,
    )

    assert issue.status == "ready"
    assert issue.id == target_id

    # Verify article was persisted in DB with the LLM-generated Chinese title
    # (not the raw source title "Test Repo").
    from app.models.article import ArticleORM

    factory = get_session_factory()
    async with factory() as s:
        rows = (await s.execute(select(ArticleORM).where(ArticleORM.issue_id == target_id))).scalars().all()
        assert len(rows) == 1
        assert rows[0].title == "测试用中文标题"
        assert rows[0].type == "agent"
