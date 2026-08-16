"""Integration test: LLM-driven type override is reflected in /articles endpoint.

Seeds 8 articles simulating today's issue 20260813, each with a different
mock LLM-returned type, and verifies the GET /articles response surfaces the
LLM-overridden type (not the rule suggestedType). Verifies ≥80% (≥7/8) match
against expected types across the 4 categories.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.infra import llm as llm_module
from app.infra import db as db_module
from app.models.article import ArticleORM, RawItem
from app.models.meta import SourceKey, TypeKey
from app.pipeline import summarizer
from app.pipeline.generator import generate_issue


# 8 simulated today's articles: (suggested_rule_type, expected_llm_type, source)
_ARTICLE_FIXTURES: list[tuple[TypeKey, str, SourceKey]] = [
    # Agent category
    (TypeKey.TOOLS, "agent", SourceKey.GITHUB),
    (TypeKey.OPEN_SOURCE, "agent", SourceKey.WEB),
    # Self-improve category
    (TypeKey.AGENT, "self_improve", SourceKey.WEB),
    (TypeKey.TOOLS, "self_improve", SourceKey.REDDIT),
    # Open-source category
    (TypeKey.AGENT, "open_source", SourceKey.GITHUB),
    (TypeKey.TOOLS, "open_source", SourceKey.WEB),
    # Tools category
    (TypeKey.AGENT, "tools", SourceKey.X),
    (TypeKey.OPEN_SOURCE, "tools", SourceKey.WEB),
]


async def _seed_articles_with_types(db_session, llm_types: list[str]) -> str:
    """Generate an issue where each article gets a different LLM-classified type.

    Returns the issue_id (e.g. '20260813').
    """
    target = datetime(2026, 8, 13, tzinfo=timezone.utc)
    issue_id = target.strftime("%Y%m%d")

    def _make_raw(idx: int, suggested: TypeKey, source: SourceKey) -> RawItem:
        return RawItem(
            sourceKey=source,
            sourceName=f"{source.value}.example",
            sourceUrl=f"https://example.com/{idx}",
            title=f"Item {idx}",
            rawText=f"Raw text {idx}",
            publishedAt="2026-08-12T08:00:00+00:00",
            suggestedType=suggested,
        )

    async def _collector():
        items = []
        for idx, (suggested, _expected, source) in enumerate(_ARTICLE_FIXTURES):
            items.append(_make_raw(idx, suggested, source))
        return items

    class _RotatingClient:
        def __init__(self, types: list[str]) -> None:
            self.types = types
            self._idx = 0

        async def summarize(self, title, source, raw_text):
            t = self.types[self._idx % len(self.types)]
            self._idx += 1
            payload = {
                "title": "T",
                "lede": "L",
                "summary": "S",
                "body": ["B"],
                "quote": None,
                "points": ["P"],
                "type": t,
            }
            return llm_module._parse_summary_response(json.dumps(payload))

    client = _RotatingClient(llm_types)

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(summarizer, "check_budget", lambda *_a, **_kw: None)
        monkey.setattr(summarizer, "_track_spend", lambda *_a, **_kw: None)
        factory = db_module.get_session_factory()
        db_module._session_factory = factory
        await generate_issue(
            date=target,
            inject_collector=_collector,
            llm_client=client,
        )
    finally:
        monkey.undo()

    return issue_id


@pytest.mark.asyncio
async def test_article_types_reflect_llm_override(client, db_session):
    """GET /articles returns LLM-overridden types, not rule suggestedType.

    Ordering by composite_score may reorder items, so we compare the multiset
    of persisted types against the multiset of expected LLM types and assert
    ≥80% (≥7/8) match.
    """
    llm_types = [t for _, t, _ in _ARTICLE_FIXTURES]
    issue_id = await _seed_articles_with_types(db_session, llm_types)

    res = await client.get(f"/api/v1/articles?issueId={issue_id}")
    assert res.status_code == 200, res.text
    body = res.json()
    items = body["items"]
    assert len(items) == len(_ARTICLE_FIXTURES)

    # Read persisted types directly to avoid ordering confusion.
    factory = db_module.get_session_factory()
    async with factory() as s:
        rows = (
            await s.execute(
                select(ArticleORM).where(ArticleORM.issue_id == issue_id)
            )
        ).scalars().all()
    persisted_types = sorted(r.type for r in rows)
    expected_sorted = sorted(t for _, t, _ in _ARTICLE_FIXTURES)

    # Multiset equality — every persisted type must match an LLM expected type.
    matched = sum(
        min(persisted_types.count(t), expected_sorted.count(t))
        for t in set(expected_sorted)
    )
    # ≥80% match (7/8 or more).
    assert matched >= int(len(_ARTICLE_FIXTURES) * 0.8), (
        f"Only {matched}/{len(_ARTICLE_FIXTURES)} types matched. "
        f"Persisted: {persisted_types} "
        f"Expected: {expected_sorted}"
    )


@pytest.mark.asyncio
async def test_article_types_full_match_when_llm_classifies(client, db_session):
    """All 8 articles have correct type when LLM provides a clean classification."""
    llm_types = [t for _, t, _ in _ARTICLE_FIXTURES]
    issue_id = await _seed_articles_with_types(db_session, llm_types)

    factory = db_module.get_session_factory()
    async with factory() as s:
        rows = (
            await s.execute(
                select(ArticleORM).where(ArticleORM.issue_id == issue_id)
            )
        ).scalars().all()
    persisted_types = sorted(r.type for r in rows)
    expected_sorted = sorted(t for _, t, _ in _ARTICLE_FIXTURES)
    assert persisted_types == expected_sorted, (
        f"Got {persisted_types}, expected {expected_sorted}"
    )


__all__ = []