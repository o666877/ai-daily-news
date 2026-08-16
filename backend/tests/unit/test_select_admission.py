"""Admission floor + type diversity in _select_for_issue (v2)."""

from __future__ import annotations

from types import SimpleNamespace

from app.models.article import RawItem
from app.models.meta import SourceKey, TypeKey
from app.pipeline.generator import ADMISSION_FLOOR, _select_for_issue


def _raw(idx: int, src: SourceKey = SourceKey.WEB, stype: TypeKey = TypeKey.TOOLS) -> RawItem:
    return RawItem(
        sourceKey=src,
        sourceName=f"example.com/{idx}",
        sourceUrl=f"https://example.com/{idx}",
        title=f"item {idx}",
        rawText="x" * 500,
        publishedAt="2026-08-16T08:00:00+00:00",
        suggestedType=stype,
    )


def _cand(idx: int, score: int, type_: str = "tools") -> tuple[RawItem, SimpleNamespace]:
    raw = _raw(idx)
    fields = SimpleNamespace(
        composite_score=score,
        topic_id=f"topic-{idx}",
        opinion_fingerprint=f"fp-{idx}",
        llm_type=type_,
    )
    return raw, fields


def test_below_admission_floor_dropped() -> None:
    candidates = [_cand(1, 85), _cand(2, ADMISSION_FLOOR - 1), _cand(3, ADMISSION_FLOOR)]
    selected = _select_for_issue(candidates, 10)
    urls = [raw.sourceUrl for raw, _ in selected]
    assert urls == ["https://example.com/1", "https://example.com/3"]


def test_floor_keeps_high_value_only_when_pool_small() -> None:
    candidates = [_cand(i, 30 + i) for i in range(1, 6)]  # 31..35 all < 40
    assert _select_for_issue(candidates, 10) == []


def test_type_quota_applies_after_floor() -> None:
    candidates = [_cand(i, 90 - i, "open_source") for i in range(1, 9)]
    candidates += [_cand(20 + i, 60 - i, "agent") for i in range(4)]
    selected = _select_for_issue(candidates, 8)
    types = [f.llm_type for _, f in selected]
    assert len(selected) == 8
    assert types.count("open_source") <= 4


__all__ = []
