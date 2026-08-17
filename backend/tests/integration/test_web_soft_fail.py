"""Integration test for the generator's web-source soft-failure path.

Cases:
- Web summarizer raises for all web items but x+github yield ≥4 candidates
  → issue.status == 'ready', web_sources_failed warning logged.
- Every source raises → issue.status == 'failed'.

Note: we monkeypatch `summarize_item` directly (single patch point —
generator holds a module-qualified reference) because the production
implementation falls back to a rule-derived SummaryResult on LLM failure,
which means an LLM-level failure does not raise out of summarize_item.
Injecting at the `summarize_item` boundary reproduces the realistic
"the entire web pipeline is broken" outage without depending on private
implementation details.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.infra.db import get_session_factory
from app.models.article import ArticleORM, RawItem
from app.models.daily_issue import DailyIssueORM, IssueStatus
from app.models.meta import SourceKey, TypeKey
from app.pipeline import summarizer
from app.pipeline.generator import generate_issue


def _make_raw(source: SourceKey, url: str) -> RawItem:
    return RawItem(
        sourceKey=source,
        sourceName=f"{source.value}.example",
        sourceUrl=url,
        title=f"{source.value} item {url[-3:]}",
        rawText=f"Raw text from {source.value}.",
        publishedAt=datetime.now(timezone.utc).isoformat(),
        suggestedType=TypeKey.TOOLS,
    )


class _SuccessClient:
    async def summarize(self, title, source, raw_text):
        from app.infra import llm as llm_module

        return llm_module._parse_summary_response(
            '{"title": "t", "lede": "l", "summary": "s", "body": ["p"], "quote": null, "points": ["x"], "compositeScore": 60, "topicId": null, "opinionFingerprint": null, "authorityTier": "tier2", "scoreSource": "llm"}'
        )


def _patch_summarize_to_raise_on(monkeypatch, source_filter):
    """Replace summarizer.summarize_item with one that raises SummarizerFailure
    for items whose sourceKey matches `source_filter(source_key)`.

    Single patch point: the generator calls summarize_item through the
    summarizer module (module-qualified reference), so patching the module
    attribute covers every consumer.
    """

    async def _stub_summarize(item, client=None, *, type_hint=None):
        from app.pipeline.summarizer import SummarizerFailure

        if source_filter(item.sourceKey):
            raise SummarizerFailure(f"{item.sourceKey.value} simulated outage")
        from app.infra import llm as llm_module
        from app.pipeline.summarizer import _augment_with_scoring

        return _augment_with_scoring(
            llm_module._parse_summary_response(
                '{"title": "t", "lede": "l", "summary": "s", "body": ["p"], "quote": null, "points": ["x"], "compositeScore": 60, "topicId": null, "opinionFingerprint": null, "authorityTier": "tier2", "scoreSource": "llm"}'
            ),
            item,
        )

    monkeypatch.setattr(summarizer, "summarize_item", _stub_summarize)


@pytest.mark.asyncio
async def test_web_all_fail_x_github_succeeds_issue_ready(monkeypatch, db_session, caplog):
    """Web summarizer fails on all web items; x+github yield ≥4 → status=ready."""

    async def _collector():
        return [
            _make_raw(SourceKey.WEB, "https://blog.example/a"),
            _make_raw(SourceKey.WEB, "https://blog.example/b"),
            _make_raw(SourceKey.X, "https://x.com/1"),
            _make_raw(SourceKey.X, "https://x.com/2"),
            _make_raw(SourceKey.GITHUB, "https://github.com/1"),
            _make_raw(SourceKey.GITHUB, "https://github.com/2"),
        ]

    _patch_summarize_to_raise_on(
        monkeypatch, lambda sk: sk == SourceKey.WEB
    )

    caplog.set_level(logging.WARNING, logger="aidaily.generator")
    issue = await generate_issue(
        date=datetime(2026, 8, 13, tzinfo=timezone.utc),
        inject_collector=_collector,
        llm_client=_SuccessClient(),
    )
    assert issue.status == IssueStatus.READY.value

    # web_sources_failed warning was emitted.
    matching = [r for r in caplog.records if r.message == "web_sources_failed"]
    assert matching, "expected web_sources_failed warning to be logged"
    # `extra={...}` keys are stored on record.__dict__, not as direct attrs.
    assert matching[0].__dict__.get("count") == 2

    # 4 articles persisted (x + github), 0 web.
    factory = get_session_factory()
    async with factory() as s:
        rows = (
            await s.execute(select(ArticleORM).where(ArticleORM.issue_id == issue.id))
        ).scalars().all()
        assert len(rows) == 4
        srcs = {r.src for r in rows}
        assert srcs == {"x", "github"}


@pytest.mark.asyncio
async def test_all_sources_fail_marks_issue_failed(monkeypatch, db_session):
    """Every source's summarizer raises → status=failed, 0 articles persisted."""

    async def _collector():
        return [
            _make_raw(SourceKey.WEB, "https://blog.example/a"),
            _make_raw(SourceKey.X, "https://x.com/1"),
            _make_raw(SourceKey.GITHUB, "https://github.com/1"),
        ]

    _patch_summarize_to_raise_on(monkeypatch, lambda _sk: True)

    issue = await generate_issue(
        date=datetime(2026, 8, 14, tzinfo=timezone.utc),
        inject_collector=_collector,
        llm_client=_SuccessClient(),
    )
    assert issue.status == IssueStatus.FAILED.value

    factory = get_session_factory()
    async with factory() as s:
        rows = (
            await s.execute(select(ArticleORM).where(ArticleORM.issue_id == issue.id))
        ).scalars().all()
        assert len(rows) == 0


@pytest.mark.asyncio
async def test_no_items_collected_returns_ready(monkeypatch, db_session):
    """Collector returns empty list → status=ready (preserves backward compat)."""

    async def _collector():
        return []

    monkeypatch.setattr(summarizer, "summarize_item", _stub_summarize_success)

    issue = await generate_issue(
        date=datetime(2026, 8, 15, tzinfo=timezone.utc),
        inject_collector=_collector,
        llm_client=_SuccessClient(),
    )
    assert issue.status == IssueStatus.READY.value
    factory = get_session_factory()
    async with factory() as s:
        rows = (
            await s.execute(select(ArticleORM).where(ArticleORM.issue_id == issue.id))
        ).scalars().all()
        assert len(rows) == 0


async def _stub_summarize_success(item, client=None, *, type_hint=None):
    from app.infra import llm as llm_module
    from app.pipeline.summarizer import _augment_with_scoring

    return _augment_with_scoring(
        llm_module._parse_summary_response(
            '{"title": "t", "lede": "l", "summary": "s", "body": ["p"], "quote": null, "points": ["x"], "compositeScore": 60, "topicId": null, "opinionFingerprint": null, "authorityTier": "tier2", "scoreSource": "llm"}'
        ),
        item,
    )