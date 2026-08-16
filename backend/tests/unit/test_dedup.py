"""T024: Three-layer global dedup tests (US2, FR-007a).

Layer 1: same normalized URL → keep highest composite_score.
Layer 2: same topic_id → keep highest popularity (score × occurrence count).
Layer 3: same opinion_fingerprint → keep highest composite_score.

Items missing topic_id or opinion_fingerprint → corresponding layer skipped
for that item (defensive: empty key = no dedup dimension).
"""

from __future__ import annotations

from app.pipeline.dedup import (
    dedup_candidates,
    dedup_by_opinion,
    dedup_by_topic,
    dedup_by_url,
    truncate_diverse,
    truncate_top_n,
)


def _item(
    *,
    source_url: str,
    composite_score: int,
    topic_id: str | None = None,
    opinion_fingerprint: str | None = None,
    published_at: str = "2026-08-12T09:00:00+00:00",
    title: str = "stub",
    idx: int | None = None,
) -> dict:
    item: dict = {
        "sourceUrl": source_url,
        "compositeScore": composite_score,
        "publishedAt": published_at,
        "title": title,
    }
    if topic_id is not None:
        item["topicId"] = topic_id
    if opinion_fingerprint is not None:
        item["opinionFingerprint"] = opinion_fingerprint
    if idx is not None:
        item["idx"] = idx
    return item


# ---------------------------------------------------------------------------
# Layer 1 — URL dedup
# ---------------------------------------------------------------------------


def test_dedup_by_url_keeps_highest_score() -> None:
    items = [
        _item(source_url="https://example.com/a", composite_score=70, idx=1),
        _item(source_url="https://example.com/a", composite_score=90, idx=2),
    ]
    result = dedup_by_url(items)
    assert len(result) == 1
    assert result[0]["idx"] == 2  # higher score wins


def test_dedup_by_url_normalizes_query_and_trailing_slash() -> None:
    items = [
        _item(source_url="https://Example.com/a?x=1", composite_score=70, idx=1),
        _item(source_url="https://example.com/a/", composite_score=90, idx=2),
    ]
    result = dedup_by_url(items)
    assert len(result) == 1
    assert result[0]["idx"] == 2


def test_dedup_by_url_distinct_urls_all_kept() -> None:
    items = [
        _item(source_url="https://a.com/1", composite_score=50, idx=1),
        _item(source_url="https://a.com/2", composite_score=60, idx=2),
        _item(source_url="https://a.com/3", composite_score=70, idx=3),
    ]
    result = dedup_by_url(items)
    assert len(result) == 3


# ---------------------------------------------------------------------------
# Layer 2 — topic dedup
# ---------------------------------------------------------------------------


def test_dedup_by_topic_keeps_highest_popularity() -> None:
    # topic "x" appears 3 times → popularity = score × count
    #   - item1: 80 × 3 = 240
    #   - item2: 90 × 3 = 270 ← highest
    #   - item3: 70 × 3 = 210
    items = [
        _item(source_url="https://a.com/1", composite_score=80, topic_id="x", idx=1),
        _item(source_url="https://a.com/2", composite_score=90, topic_id="x", idx=2),
        _item(source_url="https://a.com/3", composite_score=70, topic_id="x", idx=3),
    ]
    result = dedup_by_topic(items)
    assert len(result) == 1
    assert result[0]["idx"] == 2


def test_dedup_by_topic_does_not_merge_different_topics() -> None:
    items = [
        _item(source_url="https://a.com/1", composite_score=80, topic_id="x", idx=1),
        _item(source_url="https://a.com/2", composite_score=90, topic_id="y", idx=2),
    ]
    result = dedup_by_topic(items)
    assert len(result) == 2


def test_dedup_by_topic_merges_separator_variants() -> None:
    """Real-world regressions: same entity, different LLM separator choices."""
    # 20260816 real data: "deepseek-harness" vs "deep-seek-harness"
    items = [
        _item(
            source_url="https://a.com/1",
            composite_score=74,
            topic_id="deepseek-harness",
            idx=1,
        ),
        _item(
            source_url="https://a.com/2",
            composite_score=60,
            topic_id="deep-seek-harness",
            idx=2,
        ),
    ]
    result = dedup_by_topic(items)
    assert len(result) == 1
    assert result[0]["idx"] == 1  # higher score wins

    # 20260816 real data: "gemini-3.7-flash" vs "gemini-3-7-flash"
    items = [
        _item(
            source_url="https://b.com/1",
            composite_score=61,
            topic_id="gemini-3.7-flash",
            idx=3,
        ),
        _item(
            source_url="https://b.com/2",
            composite_score=54,
            topic_id="gemini-3-7-flash",
            idx=4,
        ),
    ]
    result = dedup_by_topic(items)
    assert len(result) == 1
    assert result[0]["idx"] == 3


def test_dedup_by_topic_merges_long_prefix_variants() -> None:
    """Suffix variants of the same entity fold onto the base key.

    20260816 real data: "deepseek-harness" vs "deepseek-harness-dsh-handbook".
    """
    items = [
        _item(
            source_url="https://a.com/1",
            composite_score=64,
            topic_id="deepseek-harness",
            idx=1,
        ),
        _item(
            source_url="https://a.com/2",
            composite_score=57,
            topic_id="deepseek-harness-dsh-handbook",
            idx=2,
        ),
    ]
    result = dedup_by_topic(items)
    assert len(result) == 1
    assert result[0]["idx"] == 1


def test_dedup_by_topic_short_prefix_not_merged() -> None:
    """Short base keys must NOT absorb longer distinct entities.

    "openai" (6 chars) vs "openai-swarm" are different events.
    """
    items = [
        _item(source_url="https://a.com/1", composite_score=80, topic_id="openai", idx=1),
        _item(
            source_url="https://a.com/2",
            composite_score=70,
            topic_id="openai-swarm",
            idx=2,
        ),
    ]
    result = dedup_by_topic(items)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# Layer 3 — opinion dedup
# ---------------------------------------------------------------------------


def test_dedup_by_opinion_keeps_highest_score() -> None:
    items = [
        _item(
            source_url="https://a.com/1",
            composite_score=60,
            opinion_fingerprint="op-1",
            idx=1,
        ),
        _item(
            source_url="https://a.com/2",
            composite_score=80,
            opinion_fingerprint="op-1",
            idx=2,
        ),
    ]
    result = dedup_by_opinion(items)
    assert len(result) == 1
    assert result[0]["idx"] == 2


# ---------------------------------------------------------------------------
# Layer skip semantics
# ---------------------------------------------------------------------------


def test_dedup_by_topic_skips_empty_topic_id() -> None:
    items = [
        _item(source_url="https://a.com/1", composite_score=80, topic_id=None, idx=1),
        _item(source_url="https://a.com/2", composite_score=80, topic_id=None, idx=2),
    ]
    result = dedup_by_topic(items)
    assert len(result) == 2  # no topic → no layer-2 merging


def test_dedup_by_opinion_skips_empty_fingerprint() -> None:
    items = [
        _item(source_url="https://a.com/1", composite_score=60, opinion_fingerprint=None, idx=1),
        _item(source_url="https://a.com/2", composite_score=80, opinion_fingerprint=None, idx=2),
    ]
    result = dedup_by_opinion(items)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# Layered pipeline
# ---------------------------------------------------------------------------


def test_dedup_layered_in_order() -> None:
    # URL collision on idx=1/idx=2 → URL layer keeps idx=2.
    # Topic collision on idx=2/idx=3 (topic "y") → topic layer (after URL) keeps
    #   higher popularity. Pre-URL count of topic "y" = 2, popularity = score×2.
    #   idx=2 (score 90 → 180), idx=3 (score 70 → 140) → idx=2 survives.
    # Opinion collision on idx=2/idx=4 (opinion "op-1") → opinion layer keeps
    #   higher score: idx=2 (90) > idx=4 (75) → idx=2 survives.
    items = [
        _item(source_url="https://a.com/1", composite_score=60, topic_id="y", idx=1),
        _item(source_url="https://a.com/1", composite_score=90, topic_id="y", idx=2),
        _item(source_url="https://a.com/3", composite_score=70, topic_id="y", idx=3),
        _item(source_url="https://a.com/4", composite_score=75, topic_id="y",
              opinion_fingerprint="op-1", idx=4),
        _item(source_url="https://a.com/5", composite_score=80, topic_id="z",
              opinion_fingerprint="op-1", idx=5),
    ]
    result = dedup_candidates(items)
    indices = sorted(r["idx"] for r in result)
    # idx=1 dropped by URL (idx=2 same URL higher score)
    # idx=3 dropped by topic (idx=2 same topic higher popularity)
    # idx=4 dropped by opinion (idx=2 same opinion higher score)
    # idx=5 has unique URL/topic/opinion → kept
    assert indices == [2, 5]


def test_dedup_empty_input_returns_empty() -> None:
    assert dedup_candidates([]) == []


def test_dedup_single_item_returns_that_item() -> None:
    items = [_item(source_url="https://a.com/1", composite_score=80, idx=1)]
    result = dedup_candidates(items)
    assert len(result) == 1
    assert result[0]["idx"] == 1

# ---------------------------------------------------------------------------
# truncate_diverse — per-type quota (v2 editorial diversity)
# ---------------------------------------------------------------------------


def _titem(idx: int, score: int, type_: str) -> dict:
    return _item(
        source_url=f"https://a.com/{idx}",
        composite_score=score,
        idx=idx,
        title=f"item-{idx}",
    ) | {"type": type_}


def test_truncate_diverse_single_type_degrades_to_top_n() -> None:
    items = [_titem(i, 100 - i, "open-source") for i in range(1, 11)]
    result = truncate_diverse(items, 5)
    assert [it["idx"] for it in result] == [1, 2, 3, 4, 5]


def test_truncate_diverse_caps_dominant_type() -> None:
    """10 open-source (high scores) + 4 tools (lower) → top 8 must mix."""
    items = [_titem(i, 100 - i, "open-source") for i in range(1, 11)]
    items += [_titem(20 + i, 40 - i, "tools") for i in range(4)]
    result = truncate_diverse(items, 8)
    types = [it["type"] for it in result]
    assert len(result) == 8
    # Cap = ceil(8*0.5) = 4 → open-source cannot take all 8 slots.
    assert types.count("open-source") == 4
    assert types.count("tools") == 4


def test_truncate_diverse_backfills_when_pool_too_small() -> None:
    """If quota leaves the issue under-filled, deferred items return in order."""
    items = [_titem(i, 100 - i, "open-source") for i in range(1, 7)]
    items += [_titem(10, 50, "tools"), _titem(11, 45, "agent")]
    result = truncate_diverse(items, 6)
    assert len(result) == 6
    # open-source capped at 3, but only 2 other types exist → backfill.
    types = [it["type"] for it in result]
    assert types.count("open-source") == 4


def test_truncate_diverse_preserves_score_order_within_selection() -> None:
    items = [
        _titem(1, 95, "agent"),
        _titem(2, 90, "agent"),
        _titem(3, 85, "tools"),
        _titem(4, 80, "tools"),
        _titem(5, 75, "open-source"),
    ]
    result = truncate_diverse(items, 5)
    scores = [it["compositeScore"] for it in result]
    assert scores == [95, 90, 85, 80, 75]


def test_truncate_diverse_empty_and_zero() -> None:
    assert truncate_diverse([], 10) == []
    assert truncate_diverse([_titem(1, 50, "agent")], 0) == []


def test_truncate_diverse_typeless_items_pass_through() -> None:
    """Items without a type key are never deferred (quota only applies to typed)."""
    items = [_item(source_url=f"https://a.com/{i}", composite_score=90 - i, idx=i)
             for i in range(1, 5)]
    items.append(_titem(99, 10, "agent"))
    result = truncate_diverse(items, 5)
    assert len(result) == 5
