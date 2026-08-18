"""Three-layer global dedup + top-N truncate (US2, FR-007a).

Pure functions (no DB / network). Easy to unit-test.

Layers (per research.md D5/D6):
  1. URL: same normalized URL → keep highest composite_score.
  2. Topic: same topic_id → keep highest popularity (score × occurrence count).
  3. Opinion: same opinion_fingerprint → keep highest composite_score.

Items missing topic_id or opinion_fingerprint skip the corresponding layer.

`truncate_top_n(items, n)`: sort by (compositeScore DESC, publishedAt DESC,
idx ASC), return first n. If len(items) <= n, return all items (no padding).
"""

from __future__ import annotations

import logging
import math
import re


# ---------------------------------------------------------------------------
# Item accessors — tolerate both snake_case + camelCase keys.
# Required: sourceUrl, compositeScore, publishedAt.
# Optional: topicId, opinionFingerprint, idx.
# ---------------------------------------------------------------------------


def _normalize_url(url: str) -> str:
    """Lowercase, strip trailing /, drop query + fragment."""
    return re.sub(r"[?#].*$", "", (url or "").strip().lower().rstrip("/"))


def _get_url(item: dict) -> str:
    return _normalize_url(item.get("sourceUrl") or item.get("source_url") or "")


def _norm_key(raw: str) -> str:
    """Separator-insensitive key normalization for topic/fingerprint dedup.

    The LLM emits the same entity with different separators across sources
    ("deepseek-harness" vs "deep-seek-harness", "gemini-3.7-flash" vs
    "gemini-3-7-flash"). Stripping every non-word character (keeping letters,
    digits and CJK) collapses those variants while distinct entities stay
    distinct.
    """
    return re.sub(r"[\W_]+", "", raw.strip().lower(), flags=re.UNICODE)


def _get_topic(item: dict) -> str:
    return _norm_key(item.get("topicId") or item.get("topic_id") or "")


# Minimum length for prefix-based topic merging. Long normalized keys that
# are a prefix of another key are near-certainly the same entity+event
# ("deepseekharness" ⊂ "deepseekharnessdshhandbook"); short ones are risky
# ("openai" ⊂ "openaiswarm" must NOT merge), so they require exact equality.
_TOPIC_PREFIX_MIN = 12


def _canonicalize_topics(keys: set[str]) -> dict[str, str]:
    """Map each topic key to its canonical form, merging long-prefix variants.

    LLM slug output varies across sources both by separator ("gemini-3.7" vs
    "gemini-3-7", handled by _norm_key) and by suffix ("deepseek-harness" vs
    "deepseek-harness-dsh-handbook"). A key whose normalized form starts with
    another key of length ≥ _TOPIC_PREFIX_MIN is folded onto that base key.
    """
    ordered = sorted(keys, key=len)
    canon: dict[str, str] = {}
    for k in ordered:
        base = next(
            (
                b
                for b in ordered
                if len(b) >= _TOPIC_PREFIX_MIN and len(b) < len(k) and k.startswith(b)
            ),
            None,
        )
        canon[k] = base if base is not None else k
    return canon


def _get_opinion(item: dict) -> str:
    return _norm_key(
        item.get("opinionFingerprint") or item.get("opinion_fingerprint") or ""
    )


def _get_score(item: dict) -> int:
    """Coerce composite_score to int; missing/None → 0 (sorts last)."""
    val = item.get("compositeScore")
    if val is None:
        val = item.get("composite_score")
    if val is None:
        return 0
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def _get_time(item: dict) -> str:
    return str(item.get("publishedAt") or item.get("published_at") or "")


def _get_idx(item: dict) -> int:
    val = item.get("idx")
    if val is None:
        return 0
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def _get_type(item: dict) -> str:
    return str(item.get("type") or item.get("effectiveType") or "").strip()


# ---------------------------------------------------------------------------
# Layer 1 — URL dedup
# ---------------------------------------------------------------------------


def dedup_by_url(items: list[dict]) -> list[dict]:
    """Same normalized URL → keep the item with highest composite_score.

    Tiebreak: keep the FIRST occurrence (stable insertion order).
    """
    best: dict[str, dict] = {}
    for item in items:
        key = _get_url(item)
        if key == "":
            # Empty URL — drop (defensive: never seen in practice).
            continue
        if key not in best or _get_score(item) > _get_score(best[key]):
            best[key] = item
    return list(best.values())


# ---------------------------------------------------------------------------
# Layer 2 — Topic dedup (popularity = score × count)
# ---------------------------------------------------------------------------


def dedup_by_topic(items: list[dict]) -> list[dict]:
    """Same topic_id → keep item with highest popularity (score × count).

    Topic keys are separator-insensitive and long-prefix merged (see
    _norm_key / _canonicalize_topics). Empty topic_id items are passed
    through unchanged (layer skipped). Popularity is computed across the
    FULL input list (so that lone items with high scores can still beat
    clusters of low-score items).
    """
    canon = _canonicalize_topics({t for t in map(_get_topic, items) if t})
    counts: dict[str, int] = {}
    for item in items:
        t = _get_topic(item)
        if t:
            t = canon[t]
            counts[t] = counts.get(t, 0) + 1

    best: dict[str, dict] = {}
    passthrough: list[dict] = []
    for item in items:
        t = _get_topic(item)
        if not t:
            passthrough.append(item)
            continue
        t = canon[t]
        popularity = _get_score(item) * counts[t]
        existing = best.get(t)
        if existing is None or popularity > _get_score(existing) * counts[t]:
            best[t] = item
    return list(best.values()) + passthrough


# ---------------------------------------------------------------------------
# Layer 3 — Opinion dedup
# ---------------------------------------------------------------------------


def dedup_by_opinion(items: list[dict]) -> list[dict]:
    """Same opinion_fingerprint → keep item with highest composite_score.

    Empty opinion_fingerprint items pass through unchanged.
    """
    best: dict[str, dict] = {}
    passthrough: list[dict] = []
    for item in items:
        op = _get_opinion(item)
        if not op:
            passthrough.append(item)
            continue
        existing = best.get(op)
        if existing is None or _get_score(item) > _get_score(existing):
            best[op] = item
    return list(best.values()) + passthrough


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def dedup_candidates(items: list[dict]) -> list[dict]:
    """Apply URL → topic → opinion dedup sequentially."""
    after_url = dedup_by_url(items)
    after_topic = dedup_by_topic(after_url)
    after_opinion = dedup_by_opinion(after_topic)
    return after_opinion


# ---------------------------------------------------------------------------
# Cross-issue exclusion (specs/005 part 1)
# ---------------------------------------------------------------------------


def exclude_published(
    items: list[dict],
    published_urls: set[str] | list[str],
    published_topics: set[str] | list[str],
) -> list[dict]:
    """Drop candidates already published in recent issues (hard exclusion).

    Matches on normalized URL or topic_id (separator-insensitive + long-prefix
    merged via the same canonicalization as the within-issue topic layer).
    Topic matching is deliberately exact-or-prefix — cross-issue we prefer
    missing a duplicate over killing a distinct-but-similar story. The fold
    is not transitive (candidate → intermediate candidate → published base
    is not caught); that tolerance is intentional.

    opinion_fingerprint intentionally does NOT participate: its semantics are
    same-issue opinion merging, and cross-issue it would kill follow-ups.
    """
    pub_urls = {_normalize_url(u) for u in published_urls if u and u.strip()}
    pub_topic_raw = {_norm_key(t) for t in published_topics if t and t.strip()}
    # Canonicalize published topics UNION candidate topics so a candidate
    # carrying a long-published base as prefix folds onto it (and vice versa).
    candidate_topics = {t for t in map(_get_topic, items) if t}
    canon = _canonicalize_topics(pub_topic_raw | candidate_topics)
    pub_topics = {canon[p] for p in pub_topic_raw}

    kept: list[dict] = []
    excluded = 0
    for item in items:
        url = _get_url(item)
        if url and url in pub_urls:
            excluded += 1
            continue
        topic = _get_topic(item)
        if topic and canon[topic] in pub_topics:
            excluded += 1
            continue
        kept.append(item)
    if excluded:
        logging.getLogger("aidaily.dedup").info(
            "cross_issue_excluded",
            extra={"excluded": excluded, "kept": len(kept)},
        )
    return kept


# ---------------------------------------------------------------------------
# Top-N truncate
# ---------------------------------------------------------------------------


def truncate_top_n(items: list[dict], n: int) -> list[dict]:
    """Return top n items by composite_score DESC, then publishedAt DESC, then idx ASC.

    If n <= 0 → []. If len(items) <= n → returns all items (sorted).

    Sort key (ascending): (-composite_score, idx_bucket, time_key, idx).
    - idx_bucket = 0 if score >= 0 else 1 keeps negative scores last.
    - time_key = negation trick: pack time as a tuple so reverse=True flips
      the outermost key only.
    """
    if n <= 0 or not items:
        return []

    # Sort ascending by (-score, time DESC, idx ASC). Python can't directly
    # negate a string for the second key. Use a tuple trick: pack the time
    # as (True, time) so the boolean sorts before any string; sort descending
    # on the outer sort so True comes last when we want time-ASC, and tweak
    # the boolean accordingly.
    # Simpler: do a custom key returning (neg_score, time, idx) and sort
    # ascending — time ASC means newest-last, so we flip:
    #   ascending sort on (-score, time, idx) places newest times LAST.
    # We want newest FIRST, so we need a 2-stage stable sort:
    sorted_items = sorted(items, key=lambda it: (_get_idx(it), _get_time(it)))
    sorted_items = sorted(sorted_items, key=lambda it: _get_time(it), reverse=True)
    sorted_items = sorted(sorted_items, key=lambda it: -_get_score(it))
    return sorted_items[:n]


def truncate_diverse(items: list[dict], n: int, max_share: float = 0.5) -> list[dict]:
    """Score-ordered top-N with a per-type quota (editorial diversity).

    A single type may occupy at most ceil(n * max_share) of the first-pass
    picks so a flood of same-type items (e.g. 20 open-source repos) cannot
    crowd out everything else. Deferred items are backfilled in score order
    when fewer than n survive the quota, so len(result) == min(n, len(items))
    always — with a single-type pool it degrades to truncate_top_n exactly.
    """
    if n <= 0 or not items:
        return []
    ranked = truncate_top_n(items, len(items))
    distinct_types = {_get_type(it) for it in ranked if _get_type(it)}
    if len(distinct_types) <= 1:
        return ranked[:n]
    cap = max(1, math.ceil(n * max_share))
    selected: list[dict] = []
    deferred: list[dict] = []
    counts: dict[str, int] = {}
    for it in ranked:
        if len(selected) >= n:
            break
        t = _get_type(it)
        if t and counts.get(t, 0) >= cap:
            deferred.append(it)
            continue
        selected.append(it)
        if t:
            counts[t] = counts.get(t, 0) + 1
    for it in deferred:
        if len(selected) >= n:
            break
        selected.append(it)
    return selected


__all__ = [
    "dedup_candidates",
    "dedup_by_opinion",
    "dedup_by_topic",
    "dedup_by_url",
    "exclude_published",
    "truncate_diverse",
    "truncate_top_n",
]