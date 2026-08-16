"""Unit tests for LLM-driven type classification.

Verifies:
- normalize_type() handles all 4 valid values + bad inputs.
- Generator._persist_article() prefers llm_type over rule suggestedType.
- Generator falls back to rule suggestedType when LLM type is invalid/missing.
- Generator falls back to rule suggestedType when LLM summarization failed
  entirely (rule_fallback path).
- All 4 type categories are correctly applied end-to-end.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.infra import llm as llm_module
from app.infra.db import get_session_factory
from app.models.article import ArticleORM, RawItem
from app.models.daily_issue import IssueStatus
from app.models.meta import SourceKey, TypeKey
from app.pipeline import summarizer
from app.pipeline.generator import generate_issue


# ---------- normalize_type() ----------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("agent", "agent"),
        ("self_improve", "self_improve"),
        ("open_source", "open_source"),
        ("tools", "tools"),
        ("AGENT", "agent"),
        ("Self_Improve", "self_improve"),
        ("open-source", "open_source"),
        ("open source", "open_source"),
        (" Self-Improve ", "self_improve"),
        ("not-a-type", None),
        ("", None),
        (None, None),
        (123, None),
    ],
)
def test_normalize_type(raw, expected):
    assert llm_module.normalize_type(raw) == expected


def test_parse_summary_response_includes_type_when_valid():
    raw = json.dumps(
        {
            "title": "t",
            "lede": "l",
            "summary": "s",
            "body": ["b"],
            "quote": None,
            "points": ["p"],
            "type": "Open-Source",
        },
        ensure_ascii=False,
    )
    result = llm_module._parse_summary_response(raw)
    assert result.llm_type == "open_source"


def test_parse_summary_response_type_invalid_is_none():
    raw = json.dumps(
        {
            "title": "t",
            "lede": "l",
            "summary": "s",
            "body": ["b"],
            "quote": None,
            "points": ["p"],
            "type": "bogus",
        },
        ensure_ascii=False,
    )
    result = llm_module._parse_summary_response(raw)
    assert result.llm_type is None


def test_parse_summary_response_type_missing_is_none():
    raw = json.dumps(
        {
            "title": "t",
            "lede": "l",
            "summary": "s",
            "body": ["b"],
            "quote": None,
            "points": ["p"],
        },
        ensure_ascii=False,
    )
    result = llm_module._parse_summary_response(raw)
    assert result.llm_type is None


# ---------- _persist_article override behavior ----------


def _make_raw_with_suggested(suggested: TypeKey | None, url: str) -> RawItem:
    from datetime import datetime, timezone

    return RawItem(
        sourceKey=SourceKey.WEB,
        sourceName="example.com",
        sourceUrl=url,
        title="Some title",
        rawText="Some raw content about something.",
        publishedAt=datetime.now(timezone.utc).isoformat(),
        suggestedType=suggested,
    )


class _TypedClient:
    """LLMClient mock that returns a fixed llm_type."""

    def __init__(self, llm_type: str | None) -> None:
        self.llm_type = llm_type

    async def summarize(self, title, source, raw_text):
        payload = {
            "title": "T",
            "lede": "L",
            "summary": "S",
            "body": ["B"],
            "quote": None,
            "points": ["P"],
        }
        if self.llm_type is not None:
            payload["type"] = self.llm_type
        return llm_module._parse_summary_response(json.dumps(payload))


class _AlwaysFailClient:
    async def summarize(self, title, source, raw_text):
        raise llm_module.LLMProviderError("always fails")


async def _generate_one_article_with(
    db_session, llm_client, suggested: TypeKey | None
):
    """Generate a 1-article issue and return the persisted ArticleORM row.

    Uses the same session factory bound by the db_session fixture.
    """
    from app.infra import db as db_module

    async def _collector():
        return [_make_raw_with_suggested(suggested, "https://example.com/x")]

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(summarizer, "check_budget", lambda *_a, **_kw: None)
        monkey.setattr(summarizer, "_track_spend", lambda *_a, **_kw: None)
        # Ensure global factory points at the test engine.
        factory = db_module.get_session_factory()
        db_module._session_factory = factory
        issue = await generate_issue(
            date=datetime(2026, 8, 13, tzinfo=timezone.utc),
            inject_collector=_collector,
            llm_client=llm_client,
        )
    finally:
        monkey.undo()

    assert issue.status == IssueStatus.READY.value
    factory = db_module.get_session_factory()
    async with factory() as s:
        rows = (
            await s.execute(
                select(ArticleORM).where(ArticleORM.issue_id == issue.id)
            )
        ).scalars().all()
    assert len(rows) == 1
    return rows[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "llm_type_str,rule_suggested,expected",
    [
        ("agent", TypeKey.TOOLS, "agent"),
        ("self_improve", TypeKey.TOOLS, "self_improve"),
        ("open_source", TypeKey.TOOLS, "open_source"),
        ("tools", TypeKey.AGENT, "tools"),
        # LLM type invalid → kept rule type.
        ("not-a-type", TypeKey.AGENT, "agent"),
        # LLM type missing (None) → kept rule type.
        (None, TypeKey.OPEN_SOURCE, "open_source"),
    ],
)
async def test_persist_article_llm_type_overrides_rule(
    db_session, llm_type_str, rule_suggested, expected
):
    """When LLM returns a valid type, it overrides the rule suggestedType."""
    row = await _generate_one_article_with(
        db_session, _TypedClient(llm_type_str), rule_suggested
    )
    assert row.type == expected


@pytest.mark.asyncio
async def test_persist_article_llm_failure_keeps_rule_type(db_session):
    """When LLM call fails entirely (rule_fallback path), rule suggestedType wins."""
    row = await _generate_one_article_with(
        db_session, _AlwaysFailClient(), TypeKey.SELF_IMPROVE
    )
    assert row.type == TypeKey.SELF_IMPROVE.value


@pytest.mark.asyncio
async def test_persist_article_llm_failure_no_rule_type_defaults_tools(
    db_session,
):
    """When LLM fails AND rule suggestedType is None, fall back to TOOLS."""
    from app.infra import db as db_module

    async def _collector():
        return [_make_raw_with_suggested(None, "https://example.com/x")]

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(summarizer, "check_budget", lambda *_a, **_kw: None)
        monkey.setattr(summarizer, "_track_spend", lambda *_a, **_kw: None)
        factory = db_module.get_session_factory()
        db_module._session_factory = factory
        issue = await generate_issue(
            date=datetime(2026, 8, 13, tzinfo=timezone.utc),
            inject_collector=_collector,
            llm_client=_AlwaysFailClient(),
        )
    finally:
        monkey.undo()

    factory = db_module.get_session_factory()
    async with factory() as s:
        rows = (
            await s.execute(
                select(ArticleORM).where(ArticleORM.issue_id == issue.id)
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].type == TypeKey.TOOLS.value


__all__ = []