"""T064: Settings effect on next-issue generation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.infra.db import get_session_factory
from app.models.article import ArticleORM, RawItem, SourceKey, TypeKey


AUTH = {"Authorization": "Bearer test-bearer-token"}


def _raw_item(idx: int) -> RawItem:
    """Build a minimal RawItem for pipeline stub."""
    return RawItem(
        sourceKey=SourceKey.X if idx % 2 == 0 else SourceKey.GITHUB,
        sourceName="Stub",
        sourceUrl=f"https://example.com/{idx}",
        title=f"item-{idx}",
        rawText=f"raw-{idx}",
        publishedAt=datetime.now(timezone.utc).isoformat(),
    )


async def _stub_collector() -> list[RawItem]:
    return [_raw_item(i) for i in range(1, 4)]


async def _stub_summarize(raw: RawItem, **_kwargs: Any) -> "SummaryResult":
    """Return a SummaryResult-shaped object so generator's attribute access works."""
    from app.infra.llm import SummaryResult

    return SummaryResult(
        title=raw.title,
        lede="lede",
        summary=f"summary-{raw.title}",
        body="body",
        quote=None,
        points=["p"],
        dimension_scores={
            "authority": 50,
            "depth": 50,
            "timeliness": 50,
            "expression": 50,
        },
        authority_tier="community",
        topic_id=None,
        opinion_fingerprint=None,
        composite_score=50,
        score_source="llm",
        llm_type=None,  # let _effective_type fall back to rule suggestedType
    )


@pytest.mark.asyncio
async def test_save_settings_then_generate_filters_github(client: AsyncClient, monkeypatch):
    """Save {github: false} → generate next-day issue → filtersApplied.sources excludes github."""
    # 1. PUT settings with github=false
    body = {
        "sources": {"x": True, "github": False, "reddit": True, "web": True},
        "types": {"agent": True, "self_improve": True, "open_source": True, "tools": True, "commentary": True},
        "dailyPush": {"enabled": True, "time": "08:00"},
        "dailyCount": 30,
        "styleMode": "standard",
    }
    res = await client.put("/api/v1/settings", json=body, headers=AUTH)
    assert res.status_code == 200, res.text

    # 2. Import generator + monkey-patch collector + summarizer
    from app.pipeline import generator as gen_mod
    from app.pipeline import summarizer

    async def fake_collect_all() -> list[RawItem]:
        return await _stub_collector()

    async def fake_summarize_item(raw: RawItem, **kwargs: Any) -> "SummaryResult":
        return await _stub_summarize(raw, **kwargs)

    monkeypatch.setattr(gen_mod, "collect_all", fake_collect_all)
    monkeypatch.setattr(summarizer, "summarize_item", fake_summarize_item)

    # 3. Trigger generate_issue for tomorrow
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    issue = await gen_mod.generate_issue(date=tomorrow)

    # 4. Inspect filtersApplied: github must be excluded; x/reddit/web included
    assert issue.filters_applied is not None
    sources_list = issue.filters_applied.get("sources", [])
    types_list = issue.filters_applied.get("types", [])
    assert "github" not in sources_list
    assert {"x", "reddit", "web"}.issubset(set(sources_list))
    # Types all-on by default
    assert set(types_list) == {"agent", "self_improve", "open_source", "tools", "commentary"}

    # 5. NEW (US3 enforcement): github candidates must actually be excluded
    # from the persisted issue. Stub alternates X/GITHUB by idx parity, so
    # with github disabled only the X item should survive.
    from sqlalchemy import select as _select
    from app.models.article import ArticleORM as _ArticleORM
    from app.infra.db import get_session_factory as _gsf

    factory = _gsf()
    async with factory() as s:
        rows = (
            await s.execute(
                _select(_ArticleORM.src).where(_ArticleORM.issue_id == issue.id)
            )
        ).scalars().all()
    assert "github" not in rows, f"github leaked into issue: {rows}"
    assert "x" in rows, f"x should be present: {rows}"


@pytest.mark.asyncio
async def test_save_settings_then_generate_filters_by_type(client: AsyncClient, monkeypatch):
    """Save {tools: false} → generate next-day issue → no article persisted with type=tools."""
    body = {
        "sources": {"x": True, "github": True, "reddit": True, "web": True},
        "types": {
            "agent": True,
            "self_improve": True,
            "open_source": True,
            "tools": False,
            "commentary": True,
        },
        "dailyPush": {"enabled": True, "time": "08:00"},
        "dailyCount": 30,
        "styleMode": "standard",
    }
    res = await client.put("/api/v1/settings", json=body, headers=AUTH)
    assert res.status_code == 200, res.text

    from app.pipeline import generator as gen_mod
    from app.pipeline import summarizer
    from app.models.article import RawItem, SourceKey, TypeKey

    # Stub: every item's suggestedType is TOOLS → all should be filtered out
    async def fake_collect_all() -> list[RawItem]:
        return [
            RawItem(
                sourceKey=SourceKey.X,
                sourceName="Stub",
                sourceUrl=f"https://example.com/{i}",
                suggestedType=TypeKey.TOOLS,
                title=f"item-{i}",
                rawText=f"raw-{i}",
                publishedAt=datetime.now(timezone.utc).isoformat(),
            )
            for i in range(1, 4)
        ]

    async def fake_summarize_item(raw, **kwargs):
        # No llm_type → effective type falls back to raw.suggestedType (TOOLS)
        return await _stub_summarize(raw, **kwargs)

    monkeypatch.setattr(gen_mod, "collect_all", fake_collect_all)
    monkeypatch.setattr(summarizer, "summarize_item", fake_summarize_item)

    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    issue = await gen_mod.generate_issue(date=tomorrow)

    # Issue is READY (raw_items non-empty, but 0 candidates survived filter
    # → all_failed=False because the failure is user-induced, not system).
    # Actually: with 0 candidates, all_failed=True → status=FAILED.
    # That's the current contract; this test just verifies no article persisted
    # with type=tools.
    from sqlalchemy import select as _select
    from app.models.article import ArticleORM as _ArticleORM
    from app.infra.db import get_session_factory as _gsf

    factory = _gsf()
    async with factory() as s:
        rows = (
            await s.execute(
                _select(_ArticleORM.type).where(_ArticleORM.issue_id == issue.id)
            )
        ).scalars().all()
    assert "tools" not in rows, f"tools leaked into issue: {rows}"