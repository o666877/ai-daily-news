"""Unit tests for app/pipeline/scorer.py (v2 ranking signals).

Covers:
- compute_timeliness: power-law decay (now=100, 24h=66, 48h=52, 72h=44,
  7d=29), neutral 50 on missing/unparseable/future
- compute_engagement: GitHub stars log10 compression, neutral 50 without
  signals, 0 stars → 0
- compose_score: 5-dimension weighted sum (authority 0.25 / depth 0.25 /
  engagement 0.25 / timeliness 0.15 / expression 0.10)
- score_with_rules: rule_fallback path incl. engagement + density-aware
  depth heuristic
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.pipeline.scorer import (
    compose_score,
    compute_engagement,
    compute_timeliness,
    score_with_rules,
)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ---------- compute_timeliness (power-law decay) ----------

def test_compute_timeliness_now_is_100():
    """Article published this moment → ~100 (within rounding tolerance)."""
    now = datetime.now(timezone.utc)
    published = now - timedelta(seconds=30)
    score = compute_timeliness(_iso(published))
    assert score == 100


def test_compute_timeliness_24h_ago_is_66():
    """24h ago → 100*(24/48)^0.6 = 100*0.6598 ≈ 66."""
    now = datetime.now(timezone.utc)
    published = now - timedelta(hours=24)
    score = compute_timeliness(_iso(published))
    assert score == 66


def test_compute_timeliness_48h_ago_is_52():
    """48h ago → 100*(24/72)^0.6 ≈ 52 — retains value, no linear cliff."""
    now = datetime.now(timezone.utc)
    published = now - timedelta(hours=48)
    score = compute_timeliness(_iso(published))
    assert score == 52


def test_compute_timeliness_72h_ago_is_44():
    now = datetime.now(timezone.utc)
    published = now - timedelta(hours=72)
    score = compute_timeliness(_iso(published))
    assert score == 44


def test_compute_timeliness_7d_ago_is_29():
    """A week old → still ~29: long tail instead of zero."""
    now = datetime.now(timezone.utc)
    published = now - timedelta(days=7)
    score = compute_timeliness(_iso(published))
    assert score == 29


def test_compute_timeliness_monotonic_decrease():
    now = datetime.now(timezone.utc)
    scores = [
        compute_timeliness(_iso(now - timedelta(hours=h)))
        for h in (0, 6, 24, 48, 72, 168)
    ]
    assert scores == sorted(scores, reverse=True)


def test_compute_timeliness_handles_z_suffix():
    now = datetime.now(timezone.utc)
    published = now - timedelta(hours=24)
    iso_z = published.strftime("%Y-%m-%dT%H:%M:%S") + ".000Z"
    assert compute_timeliness(iso_z) == 66


def test_compute_timeliness_missing_returns_50():
    assert compute_timeliness(None) == 50
    assert compute_timeliness("") == 50


def test_compute_timeliness_future_returns_50():
    """Future timestamps are data errors, not hot news → neutral 50."""
    now = datetime.now(timezone.utc)
    future = now + timedelta(hours=10)
    assert compute_timeliness(_iso(future)) == 50


# ---------- compute_engagement ----------

def test_compute_engagement_none_extra_is_neutral_50():
    assert compute_engagement("github", None) == 50
    assert compute_engagement("web", {}) == 50


def test_compute_engagement_sources_without_signals_are_neutral():
    assert compute_engagement("x", {"author": "a", "tweet_id": "1"}) == 50
    assert compute_engagement("reddit", {"foo": "bar"}) == 50


def test_compute_engagement_zero_stars_is_0():
    """0-star repo: no crowd validation at all."""
    assert compute_engagement("github", {"stars": 0}) == 0


def test_compute_engagement_log10_compression():
    """Doubling stars adds sublinear score; 10★ < 2×(5★)."""
    s5 = compute_engagement("github", {"stars": 5})
    s10 = compute_engagement("github", {"stars": 10})
    s100 = compute_engagement("github", {"stars": 100})
    s1000 = compute_engagement("github", {"stars": 1000})
    assert 0 < s5 < s10 < s100 < s1000 <= 100
    # Early stars weigh more: +5★ from 5 is worth more than +5★ from 1000.
    assert (s10 - s5) > (compute_engagement("github", {"stars": 1005}) - s1000)


def test_compute_engagement_anchor_20k_is_100():
    assert compute_engagement("github", {"stars": 20_000}) == 100


def test_compute_engagement_100_stars_is_47():
    """100★ → 100*log10(101)/log10(20001) ≈ 46.6 → 47."""
    assert compute_engagement("github", {"stars": 100}) == 47


def test_compute_engagement_invalid_star_type_is_neutral():
    assert compute_engagement("github", {"stars": "not-a-number"}) == 50
    assert compute_engagement("github", {"stars": -5}) == 50


# ---------- compute_engagement: three-source dispatch (spec 004) ----------


def test_compute_engagement_x_likes_anchor_100k():
    """100k likes = 100; 100≈40, 1k≈60, 10k≈80 (log10 compression)."""
    assert compute_engagement("x", {"likes": 100_000}) == 100
    assert compute_engagement("x", {"likes": 100}) == 40
    assert compute_engagement("x", {"likes": 1_000}) == 60
    assert compute_engagement("x", {"likes": 10_000}) == 80


def test_compute_engagement_x_zero_likes_is_0():
    assert compute_engagement("x", {"likes": 0}) == 0


def test_compute_engagement_x_views_do_not_count():
    """Views measure exposure, not engagement — never part of the formula."""
    assert compute_engagement("x", {"views": 1_000_000}) == 50


def test_compute_engagement_x_invalid_likes_neutral():
    assert compute_engagement("x", {"likes": "viral"}) == 50
    assert compute_engagement("x", {"likes": -3}) == 50


def test_compute_engagement_reddit_comments_anchor_500():
    """500 comments = 100; 10≈39, 50≈63, 100≈74 (log10 compression)."""
    assert compute_engagement("reddit", {"num_comments": 500}) == 100
    assert compute_engagement("reddit", {"num_comments": 10}) == 39
    assert compute_engagement("reddit", {"num_comments": 50}) == 63
    assert compute_engagement("reddit", {"num_comments": 100}) == 74


def test_compute_engagement_reddit_invalid_comments_neutral():
    assert compute_engagement("reddit", {"num_comments": "hot"}) == 50
    assert compute_engagement("reddit", {"num_comments": -1}) == 50


def test_compute_engagement_signals_are_dimension_isolated():
    """A source only reads its own signal key — cross-source leakage is a bug."""
    assert compute_engagement("github", {"likes": 50_000}) == 50
    assert compute_engagement("x", {"stars": 50_000}) == 50
    assert compute_engagement("reddit", {"likes": 50_000}) == 50


# ---------- compose_score ----------

def test_compose_score_all_100_is_100():
    dims = {
        "authority": 100,
        "depth": 100,
        "engagement": 100,
        "timeliness": 100,
        "expression": 100,
    }
    assert compose_score(dims) == 100


def test_compose_score_all_0_is_0():
    dims = {
        "authority": 0,
        "depth": 0,
        "engagement": 0,
        "timeliness": 0,
        "expression": 0,
    }
    assert compose_score(dims) == 0


def test_compose_score_weighted_sum_v2():
    """90*0.25 + 50*0.25 + 60*0.25 + 100*0.15 + 50*0.10 = 22.5+12.5+15+15+5 = 70."""
    dims = {
        "authority": 90,
        "depth": 50,
        "engagement": 60,
        "timeliness": 100,
        "expression": 50,
    }
    assert compose_score(dims) == 70


def test_compose_score_missing_engagement_defaults_0():
    """Legacy 4-dim dicts: engagement missing → counts as 0."""
    dims = {"authority": 100, "depth": 100, "timeliness": 100, "expression": 100}
    assert compose_score(dims) == 75


def test_compose_score_clamps_to_100_on_overflow():
    dims = {
        "authority": 200,
        "depth": 100,
        "engagement": 100,
        "timeliness": 100,
        "expression": 100,
    }
    assert compose_score(dims) == 100


def test_compose_score_high_engagement_beats_low_when_rest_equal():
    base = {"authority": 50, "depth": 50, "timeliness": 50, "expression": 50}
    low = compose_score({"engagement": 20, **base})
    high = compose_score({"engagement": 90, **base})
    assert low < high


# ---------- score_with_rules ----------

def test_score_with_rules_official_blog_source():
    result = score_with_rules(
        source_name="openai.com/blog",
        published_at=None,  # → timeliness=50
        raw_text="x" * 4000,  # length 100, density 0 → depth (100+0)/2 = 50
    )
    assert result["dim_authority"] == 90
    assert result["authority_tier"] == "official_blog"
    assert result["dim_timeliness"] == 50
    assert result["dim_depth"] == 50
    assert result["dim_expression"] == 50
    assert result["dim_engagement"] == 50  # no extra → neutral
    assert result["score_source"] == "rule_fallback"


def test_score_with_rules_community_source():
    result = score_with_rules(
        source_name="medium.com/some-blog",
        published_at=None,
        raw_text="x" * 200,
    )
    assert result["dim_authority"] == 50
    assert result["authority_tier"] == "community"
    assert result["dim_timeliness"] == 50
    assert result["dim_depth"] == 20  # floor
    assert result["dim_expression"] == 50
    assert result["score_source"] == "rule_fallback"


def test_score_with_rules_short_text_uses_depth_floor_20():
    result = score_with_rules(
        source_name="x.com/@test",
        published_at=None,
        raw_text="short",
    )
    assert result["dim_depth"] == 20


def test_score_with_rules_empty_raw_text():
    result = score_with_rules(
        source_name="reddit.com/r/test",
        published_at=None,
        raw_text="",
    )
    assert result["dim_depth"] == 20


def test_score_with_rules_density_beats_plain_length():
    """Same length: text with code fences / URLs / numbers scores deeper."""
    plain = "x" * 2000
    dense = "```python\nprint(1)\n``` see https://a.com v2.0 42%\n" * 20
    r_plain = score_with_rules("a.com", None, plain)
    r_dense = score_with_rules("a.com", None, dense)
    assert r_dense["dim_depth"] > r_plain["dim_depth"]


def test_score_with_rules_with_published_at_power_law():
    now = datetime.now(timezone.utc)
    published = now - timedelta(hours=24)  # → 66
    result = score_with_rules(
        source_name="anthropic.com/news",
        published_at=_iso(published),
        raw_text="x" * 1000,
    )
    assert result["dim_timeliness"] == 66
    assert result["authority_tier"] == "official_blog"


def test_score_with_rules_uses_engagement_from_extra():
    result = score_with_rules(
        source_name="github.com/a/b",
        published_at=None,
        raw_text="x" * 500,
        source_key="github",
        extra={"stars": 10_000},
    )
    assert result["dim_engagement"] == 93


def test_score_with_rules_returns_all_required_keys():
    result = score_with_rules(
        source_name="github.com/test/repo",
        published_at=None,
        raw_text="x" * 500,
    )
    expected_keys = {
        "dim_authority",
        "dim_depth",
        "dim_timeliness",
        "dim_expression",
        "dim_engagement",
        "authority_tier",
        "score_source",
    }
    assert set(result.keys()) == expected_keys


def test_score_with_rules_authoritative_media_tier():
    result = score_with_rules(
        source_name="technologyreview.com",
        published_at=None,
        raw_text="x" * 500,
    )
    assert result["dim_authority"] == 70
    assert result["authority_tier"] == "authoritative_media"


__all__ = []
