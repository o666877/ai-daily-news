"""Pre-LLM gate: rule proxy score + per-source quota (token savings).

The gate decides which collected RawItems earn an LLM summarize call:
1. Drop items whose source is disabled in settings (source-level filter
   moved ahead of the LLM loop).
2. Rank each enabled source's items by the rule proxy composite
   (score_with_rules + compose_score — 4 LLM-free dims).
3. Each source keeps its top `daily_count`; leftovers backfill globally
   up to len(enabled_sources) × daily_count total. The quota only bites
   when total inflow exceeds that cap.
"""

from __future__ import annotations

from app.models.article import RawItem
from app.models.meta import SourceKey, TypeKey
from app.pipeline.generator import _gate_for_llm


def _raw(
    item_id: str,
    src: SourceKey,
    *,
    likes: int | None = None,
    stars: int | None = None,
) -> RawItem:
    extra: dict = {}
    if likes is not None:
        extra["likes"] = likes
    if stars is not None:
        extra["stars"] = stars
    return RawItem(
        sourceKey=src,
        sourceName=f"{src.value}.com",
        sourceUrl=f"https://{src.value}/{item_id}",
        title=f"item-{item_id}",
        rawText=f"substantive agent content {item_id} " * 20,
        publishedAt="2026-08-19T01:00:00+00:00",
        suggestedType=TypeKey.AGENT,
        extra=extra or None,
    )


ALL_SOURCES = ["x", "github", "reddit", "web"]


def test_gate_quota_bites_when_inflow_exceeds_cap():
    """x=20 + web=20, allowed 2 sources → cap 30; 15+15 kept, 10 dropped."""
    items = (
        [_raw(f"x{i:02d}", SourceKey.X, likes=100 + i) for i in range(20)]
        + [_raw(f"w{i:02d}", SourceKey.WEB) for i in range(20)]
    )
    gated, stats = _gate_for_llm(items, ["x", "web"], daily_count=15)
    assert len(gated) == 30
    assert stats["gate_passed_by_source"] == {"x": 15, "web": 15}
    assert stats["gate_dropped"] == 10


def test_gate_quota_keeps_top_by_rule_score_within_source():
    """Within x, the highest-like items survive the quota cut."""
    items = [
        _raw("x_low", SourceKey.X, likes=100),
        _raw("x_mid", SourceKey.X, likes=1_000),
        _raw("x_high", SourceKey.X, likes=10_000),
    ]
    gated, _ = _gate_for_llm(items, ["x"], daily_count=2)
    urls = {r.sourceUrl for r in gated}
    assert "https://x/x_high" in urls
    assert "https://x/x_low" not in urls


def test_gate_backfills_unused_quota_globally():
    """x has 30, web has 5, cap = 2×15 = 30 → x backfills 10 extra."""
    items = (
        [_raw(f"x{i:02d}", SourceKey.X, likes=100 + i) for i in range(30)]
        + [_raw(f"w{i:02d}", SourceKey.WEB) for i in range(5)]
    )
    gated, stats = _gate_for_llm(items, ["x", "web"], daily_count=15)
    assert len(gated) == 30
    assert stats["gate_passed_by_source"] == {"x": 25, "web": 5}
    assert stats["gate_dropped"] == 5


def test_gate_filters_disabled_sources_before_quota():
    """github disabled → its items never reach the gate; cap counts enabled only."""
    items = (
        [_raw(f"g{i:02d}", SourceKey.GITHUB, stars=1_000) for i in range(10)]
        + [_raw(f"x{i:02d}", SourceKey.X, likes=100 + i) for i in range(20)]
    )
    gated, stats = _gate_for_llm(items, ["x"], daily_count=15)
    assert all(r.sourceKey != SourceKey.GITHUB for r in gated)
    assert stats["source_filtered"] == 10
    # cap = 1 enabled source × 15, x has 20 → 15 pass
    assert len(gated) == 15


def test_gate_passes_everything_below_cap():
    """40 candidates < 4-source cap 60 → nothing dropped by the gate."""
    items = (
        [_raw(f"x{i:02d}", SourceKey.X, likes=100 + i) for i in range(20)]
        + [_raw(f"w{i:02d}", SourceKey.WEB) for i in range(20)]
    )
    gated, stats = _gate_for_llm(items, ALL_SOURCES, daily_count=15)
    assert len(gated) == 40
    assert stats["gate_dropped"] == 0


def test_gate_survivors_keep_collection_order():
    """Gated output preserves the original collection order (stable)."""
    items = [
        _raw("x_b", SourceKey.X, likes=5_000),
        _raw("w_a", SourceKey.WEB),
        _raw("x_a", SourceKey.X, likes=50_000),
    ]
    gated, _ = _gate_for_llm(items, ALL_SOURCES, daily_count=2)
    # All three survive (each source under its quota) in collection order.
    assert [r.sourceUrl for r in gated] == [
        "https://x/x_b",
        "https://web/w_a",
        "https://x/x_a",
    ]


def test_gate_empty_input_returns_empty():
    gated, stats = _gate_for_llm([], ALL_SOURCES, daily_count=15)
    assert gated == []
    assert stats["collected"] == 0
    assert stats["gate_dropped"] == 0
