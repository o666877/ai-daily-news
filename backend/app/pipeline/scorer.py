"""Composite scoring (T016, US1) — v2 ranking signals.

Pure functions; no LLM, no DB. Compose 5-dimension (authority/depth/
timeliness/expression/engagement) 0-100 sub-scores into a single composite
score via weighted sum and provide a rule_fallback path for when the
LLM call fails.

v2 changes (informed by HN / Reddit / Feedly ranking research):
- New `engagement` dimension from raw platform signals (GitHub stars),
  log10-compressed so the first 10 stars ≈ next 100 (Reddit-style).
- Power-law time decay replaces linear decay: 100*(24/(age_h+24))^0.6.
  48h-old items keep ~52 pts instead of dropping to 0.
- Depth fallback heuristic now blends length with information-density
  signals (code fences, numbers, URLs) instead of raw length only.

Functions:
- compute_timeliness(published_at) -> int
- compute_engagement(source_key, extra) -> int
- compose_score(dims) -> int
- score_with_rules(source_name, published_at, raw_text, source_key, extra) -> dict
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from app.pipeline.authority import classify_authority

# v2 weights: engagement (raw crowd signal) promoted to a top factor;
# authority demoted from 0.35 since it double-counts brand over substance.
_WEIGHTS: dict[str, float] = {
    "authority": 0.25,
    "depth": 0.25,
    "engagement": 0.25,
    "timeliness": 0.15,
    "expression": 0.10,
}

# GitHub stars → engagement score anchor: 20k+ stars ≈ 100.
_ENGAGEMENT_STAR_ANCHOR = 20_000

_CODE_FENCE_RE = re.compile(r"```")
_URL_RE = re.compile(r"https?://\S+")
_NUMERIC_RE = re.compile(r"\d+(?:\.\d+)?")


def _clamp(value: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, value))


def compute_timeliness(published_at: str | None) -> int:
    """Return timeliness score in [0, 100] using power-law decay.

    score = 100 * (24/(age_hours+24))^0.6 — hyperbolic decay borrowed from
    HN/Reddit ranking: 0h=100, 6h≈87, 24h≈66, 48h≈52, 72h≈44, 7d≈29.
    Yesterday's strong content keeps value instead of hitting the old
    linear cliff (0 at 50h).
    None / empty / unparseable / future → 50 (neutral).
    """
    if not published_at:
        return 50
    try:
        ts = published_at.strip()
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age_hours = (now - dt).total_seconds() / 3600.0
    except (ValueError, TypeError, OverflowError):
        return 50
    if age_hours < 0:
        return 50
    score = round(100.0 * (24.0 / (age_hours + 24.0)) ** 0.6)
    return _clamp(score)


def compute_engagement(source_key: str, extra: dict | None) -> int:
    """Return engagement score in [0, 100] from raw platform signals.

    GitHub: log10-compressed star count (Reddit-style compression — early
    stars matter most). 10★≈24, 100★≈47, 1k★≈70, 10k★≈93, 20k★=100.
    Sources without measurable signals (X/Reddit feeds, web) → 50 neutral.
    """
    if not extra:
        return 50
    stars = extra.get("stars")
    if isinstance(stars, (int, float)) and stars >= 0:
        anchor = math.log10(1 + _ENGAGEMENT_STAR_ANCHOR)
        score = round(100.0 * math.log10(1 + stars) / anchor)
        return _clamp(score)
    return 50


def compose_score(dims: dict[str, int]) -> int:
    """Return weighted composite score in [0, 100].

    Weights: authority 0.25, depth 0.25, engagement 0.25, timeliness 0.15,
    expression 0.10. Missing dims default to 0. Result rounded then clamped.
    """
    total = 0.0
    for key, weight in _WEIGHTS.items():
        total += dims.get(key, 0) * weight
    return _clamp(round(total))


def _density_depth(raw_text: str) -> int:
    """Information-density heuristic: length blended with density signals.

    Length base (chars/40, floor 20) averaged with a density bonus from
    code fences, URLs and numeric facts per 1k chars.
    """
    text = raw_text or ""
    if not text:
        return 20
    length_score = min(100, len(text) // 40)
    per_kchar = 1000.0 / max(1, len(text))
    fences = min(30.0, len(_CODE_FENCE_RE.findall(text)) * 5.0 * per_kchar)
    urls = min(30.0, len(_URL_RE.findall(text)) * 3.0 * per_kchar)
    numerics = min(40.0, len(_NUMERIC_RE.findall(text)) * 1.0 * per_kchar)
    density_score = fences + urls + numerics
    return _clamp(round((length_score + density_score) / 2), 20, 100)


def score_with_rules(
    source_name: str,
    published_at: str | None,
    raw_text: str,
    source_key: str = "",
    extra: dict | None = None,
) -> dict:
    """Rule-fallback scoring path (used when LLM call fails).

    - authority: classify_authority(source_name) baseline (system rule)
    - timeliness: compute_timeliness(published_at) — gravity decay
    - engagement: compute_engagement(source_key, extra) — log10(stars)
    - depth: length + information-density heuristic
    - expression: neutral default 50

    Returns dict with 7 keys (snake_case): dim_authority/dim_depth/
    dim_timeliness/dim_expression/dim_engagement/authority_tier/score_source.
    """
    tier, dim_authority = classify_authority(source_name)
    dim_timeliness = compute_timeliness(published_at)
    dim_depth = _density_depth(raw_text)
    dim_expression = 50  # neutral default
    dim_engagement = compute_engagement(source_key, extra)
    return {
        "dim_authority": dim_authority,
        "dim_depth": dim_depth,
        "dim_timeliness": dim_timeliness,
        "dim_expression": dim_expression,
        "dim_engagement": dim_engagement,
        "authority_tier": tier,
        "score_source": "rule_fallback",
    }


__all__ = [
    "compose_score",
    "compute_engagement",
    "compute_timeliness",
    "score_with_rules",
]
