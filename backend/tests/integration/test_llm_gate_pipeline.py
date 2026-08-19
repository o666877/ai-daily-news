"""Integration: the pre-LLM gate caps summarize calls + issue_funnel log.

Uses the standard test DB fixtures with an injected collector and the
success-stubbed LLM; a counting wrapper around summarizer.summarize_item
verifies the gate actually saves LLM spend.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest

from app.models.article import RawItem
from app.models.meta import SourceKey, TypeKey
from app.pipeline import summarizer as summarizer_module
from app.pipeline.generator import generate_issue


def _raw(item_id: str, src: SourceKey) -> RawItem:
    return RawItem(
        sourceKey=src,
        sourceName=f"{src.value}.com",
        sourceUrl=f"https://{src.value}/{item_id}",
        title=f"item-{item_id}",
        rawText=f"substantive agent content {item_id} " * 20,
        publishedAt="2026-08-12T01:00:00+00:00",
        suggestedType=TypeKey.AGENT,
    )


def _install_call_counter(monkeypatch) -> list[str]:
    """Wrap summarizer.summarize_item, recording each call's source key."""
    calls: list[str] = []
    original = summarizer_module.summarize_item

    async def counting(raw, client=None):
        calls.append(raw.sourceKey.value)
        return await original(raw, client=client)

    monkeypatch.setattr(summarizer_module, "summarize_item", counting)
    return calls


@pytest.mark.asyncio
async def test_gate_caps_llm_calls_at_enabled_sources_times_daily_count(
    test_engine, db_session, patch_llm_success, monkeypatch
):
    """80 items across 4 sources, daily_count=15 → ≤ 60 summarize calls."""
    calls = _install_call_counter(monkeypatch)

    async def _collector():
        return (
            [_raw(f"x{i:02d}", SourceKey.X) for i in range(30)]
            + [_raw(f"g{i:02d}", SourceKey.GITHUB) for i in range(20)]
            + [_raw(f"r{i:02d}", SourceKey.REDDIT) for i in range(15)]
            + [_raw(f"w{i:02d}", SourceKey.WEB) for i in range(15)]
        )

    issue = await generate_issue(
        date=datetime(2026, 8, 12, tzinfo=UTC),
        inject_collector=_collector,
    )
    assert issue.status == "ready"
    assert len(calls) == 60  # exactly the 4 × 15 cap
    per_source = {s: calls.count(s) for s in set(calls)}
    assert per_source == {"x": 15, "github": 15, "reddit": 15, "web": 15}


@pytest.mark.asyncio
async def test_disabled_source_never_reaches_llm(
    test_engine, db_session, patch_llm_success, monkeypatch
):
    """Settings disable x + github → their items produce zero LLM calls."""
    from sqlalchemy import select

    from app.infra.db import get_session_factory
    from app.models.settings import SettingsORM

    factory = get_session_factory()
    async with factory() as s:
        orm = (
            await s.execute(select(SettingsORM).where(SettingsORM.id == 1))
        ).scalar_one_or_none()
        disabled = {"x": False, "github": False, "reddit": True, "web": True}
        if orm is None:
            s.add(SettingsORM(id=1, sources=disabled))
        else:
            orm.sources = disabled
        await s.commit()

    calls = _install_call_counter(monkeypatch)

    async def _collector():
        return (
            [_raw(f"x{i:02d}", SourceKey.X) for i in range(10)]
            + [_raw(f"g{i:02d}", SourceKey.GITHUB) for i in range(10)]
            + [_raw(f"r{i:02d}", SourceKey.REDDIT) for i in range(5)]
        )

    issue = await generate_issue(
        date=datetime(2026, 8, 13, tzinfo=UTC),
        inject_collector=_collector,
    )
    assert issue.status == "ready"
    assert calls.count("x") == 0
    assert calls.count("github") == 0
    assert calls.count("reddit") == 5


@pytest.mark.asyncio
async def test_issue_funnel_logged_with_numbers_in_message(
    test_engine, db_session, patch_llm_success, monkeypatch, caplog
):
    """issue_funnel event carries the funnel numbers inside the message."""
    _install_call_counter(monkeypatch)

    async def _collector():
        return [_raw(f"x{i:02d}", SourceKey.X) for i in range(5)]

    with caplog.at_level(logging.INFO, logger="aidaily.generator"):
        issue = await generate_issue(
            date=datetime(2026, 8, 14, tzinfo=UTC),
            inject_collector=_collector,
        )
    assert issue.status == "ready"
    funnel_records = [r for r in caplog.records if r.message.startswith("issue_funnel")]
    assert len(funnel_records) == 1
    msg = funnel_records[0].message
    for fragment in (
        "collected=5",
        "gate_dropped=0",
        "summarized_ok=5",
        "selected=",
    ):
        assert fragment in msg
    record = funnel_records[0]
    assert record.collected == 5
    assert record.collected_by_source == {"x": 5}
    # Calibration pairs: one per selected article, each [proxy:int, llm:int].
    from sqlalchemy import func, select

    from app.infra.db import get_session_factory
    from app.models.article import ArticleORM

    factory = get_session_factory()
    async with factory() as s:
        persisted = (
            await s.execute(
                select(func.count(ArticleORM.id)).where(ArticleORM.issue_id == issue.id)
            )
        ).scalar_one()
    pairs = record.proxy_vs_llm
    assert len(pairs) == persisted
    assert all(
        isinstance(p, list) and len(p) == 2 and isinstance(p[0], int) and p[1] is not None
        for p in pairs
    )
