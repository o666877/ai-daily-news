"""T009: Unit tests for app/pipeline/authority.py.

Covers:
- 6 official_blog keywords (openai.com / anthropic.com / google.blog /
  deepmind.google / huggingface.co / research.google)
- 4 authoritative_media keywords (technologyreview.com / simonwillison.net /
  latent.space / stratechery.com)
- 3 community keywords (x.com / reddit.com / github.com)
- unknown source → community default
- empty string → community
- case-insensitive matching
"""

from __future__ import annotations

import pytest

from app.pipeline.authority import (
    AUTHORITATIVE_MEDIA_KEYWORDS,
    OFFICIAL_BLOG_KEYWORDS,
    classify_authority,
)


# ---------- official_blog (baseline 90) ----------

@pytest.mark.parametrize(
    "source",
    [
        "openai.com",
        "https://openai.com/blog/gpt-5",
        "openai.com/research/something",
        "anthropic.com",
        "https://anthropic.com/news/claude-update",
        "google.blog",
        "https://google.blog/2026/ai-update",
        "deepmind.google",
        "deepmind.google/discover/blog",
        "huggingface.co",
        "huggingface.co/blog/mistral",
        "research.google",
        "research.google/blog/transformer",
    ],
)
def test_classify_authority_official_blog(source: str):
    tier, baseline = classify_authority(source)
    assert tier == "official_blog"
    assert baseline == 90


# ---------- authoritative_media (baseline 70) ----------

@pytest.mark.parametrize(
    "source",
    [
        "technologyreview.com",
        "https://www.technologyreview.com/2026/ai",
        "simonwillison.net",
        "simonwillison.net/2026/August/claude",
        "latent.space",
        "https://latent.space/p/ai-update",
        "stratechery.com",
        "stratechery.com/2026/ai-platforms",
    ],
)
def test_classify_authority_authoritative_media(source: str):
    tier, baseline = classify_authority(source)
    assert tier == "authoritative_media"
    assert baseline == 70


# ---------- community (baseline 50) ----------

@pytest.mark.parametrize(
    "source",
    [
        "x.com",
        "x.com/@karpathy",
        "https://x.com/swyx/status/123",
        "reddit.com",
        "reddit.com/r/MachineLearning",
        "github.com",
        "github.com/openai/whisper",
    ],
)
def test_classify_authority_community(source: str):
    tier, baseline = classify_authority(source)
    assert tier == "community"
    assert baseline == 50


# ---------- unknown → community default ----------

def test_classify_authority_unknown_defaults_to_community():
    tier, baseline = classify_authority("medium.com/some-blog")
    assert tier == "community"
    assert baseline == 50


def test_classify_authority_empty_string_defaults_to_community():
    tier, baseline = classify_authority("")
    assert tier == "community"
    assert baseline == 50


# ---------- case-insensitive ----------

def test_classify_authority_case_insensitive_uppercase():
    tier, baseline = classify_authority("OPENAI.COM/BLOG")
    assert tier == "official_blog"
    assert baseline == 90


def test_classify_authority_case_insensitive_mixed_case():
    tier, baseline = classify_authority("TechnologyReview.com")
    assert tier == "authoritative_media"
    assert baseline == 70


def test_classify_authority_case_insensitive_x_upper():
    tier, baseline = classify_authority("X.COM/@karpathy")
    assert tier == "community"
    assert baseline == 50


# ---------- constants sanity ----------

def test_constants_have_expected_keywords():
    assert "openai.com" in OFFICIAL_BLOG_KEYWORDS
    assert "anthropic.com" in OFFICIAL_BLOG_KEYWORDS
    assert "google.blog" in OFFICIAL_BLOG_KEYWORDS
    assert "deepmind.google" in OFFICIAL_BLOG_KEYWORDS
    assert "huggingface.co" in OFFICIAL_BLOG_KEYWORDS
    assert "research.google" in OFFICIAL_BLOG_KEYWORDS
    assert len(OFFICIAL_BLOG_KEYWORDS) == 6

    assert "technologyreview.com" in AUTHORITATIVE_MEDIA_KEYWORDS
    assert "simonwillison.net" in AUTHORITATIVE_MEDIA_KEYWORDS
    assert "latent.space" in AUTHORITATIVE_MEDIA_KEYWORDS
    assert "stratechery.com" in AUTHORITATIVE_MEDIA_KEYWORDS
    assert len(AUTHORITATIVE_MEDIA_KEYWORDS) == 4


__all__ = []


# ---------------------------------------------------------------------------
# v2: institutional tier — academic orgs outrank generic media/community
# ---------------------------------------------------------------------------

def test_classify_authority_institutional_stanford() -> None:
    tier, score = classify_authority("github.com/stanford-oval/storm")
    assert tier == "authoritative_media"
    assert score == 80


def test_classify_authority_institutional_edu_domain() -> None:
    tier, score = classify_authority("mit.edu/news/ai-breakthrough")
    assert tier == "authoritative_media"
    assert score == 80


def test_classify_authority_institutional_arxiv() -> None:
    tier, score = classify_authority("arxiv.org/abs/2608.12345")
    assert tier == "authoritative_media"
    assert score == 80


def test_classify_authority_official_beats_institutional() -> None:
    tier, score = classify_authority("huggingface.co/stanford-model")
    assert tier == "official_blog"
    assert score == 90
