"""T025: truncate_top_n tests (US2, FR-007a).

Sort: compositeScore DESC, publishedAt DESC. If len(items) <= n, return all
items (no padding).
"""

from __future__ import annotations

from app.pipeline.dedup import truncate_top_n


def _item(idx: int, score: int, time: str = "2026-08-12T09:00:00+00:00") -> dict:
    return {
        "idx": idx,
        "sourceUrl": f"https://a.com/{idx}",
        "compositeScore": score,
        "publishedAt": time,
        "title": f"item-{idx}",
    }


def test_truncate_top_n_returns_n_highest_in_desc_order() -> None:
    items = [_item(i, score=50 + i) for i in range(100)]  # scores 50..149
    result = truncate_top_n(items, 10)
    assert len(result) == 10
    scores = [r["compositeScore"] for r in result]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == 149
    assert scores[-1] == 140


def test_truncate_top_n_stable_tiebreak_by_time_desc() -> None:
    items = [
        _item(idx=1, score=80, time="2026-08-12T08:00:00+00:00"),
        _item(idx=2, score=80, time="2026-08-12T10:00:00+00:00"),  # newer
        _item(idx=3, score=80, time="2026-08-12T09:00:00+00:00"),
    ]
    result = truncate_top_n(items, 3)
    assert [r["idx"] for r in result] == [2, 3, 1]


def test_truncate_n_equals_len_returns_all() -> None:
    items = [_item(i, score=50 + i) for i in range(5)]
    result = truncate_top_n(items, 5)
    assert [r["idx"] for r in result] == [4, 3, 2, 1, 0]


def test_truncate_n_exceeds_len_returns_all_no_padding() -> None:
    items = [_item(i, score=50 + i) for i in range(3)]
    result = truncate_top_n(items, 10)
    assert len(result) == 3
    assert [r["idx"] for r in result] == [2, 1, 0]


def test_truncate_n_zero_returns_empty() -> None:
    items = [_item(i, score=50 + i) for i in range(3)]
    assert truncate_top_n(items, 0) == []


def test_truncate_empty_input_returns_empty() -> None:
    assert truncate_top_n([], 5) == []


def test_truncate_handles_missing_score_as_last() -> None:
    items = [
        _item(1, score=80),
        _item(2, score=None),  # type: ignore[arg-type]
        _item(3, score=60),
    ]
    items[1]["compositeScore"] = None  # missing scoring
    result = truncate_top_n(items, 2)
    # Items with score: idx=1 (80), idx=3 (60). Missing sorts last → dropped.
    assert [r["idx"] for r in result] == [1, 3]