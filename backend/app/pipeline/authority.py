"""Authority classification (T015, US1).

Maps `sourceName` substring to one of three tiers with a baseline `authority`
dimension score. Per research.md D2:

- official_blog (90): primary-source blogs from AI labs
- institutional (80): universities / research orgs — mapped to the
  authoritative_media tier but with a higher baseline, so a Stanford
  release outranks a random blog yet stays below the vendor's own blog
- authoritative_media (70): trusted tech news / analysis
- community (50): default; X / Reddit / GitHub / unknown

Substring matching against lowercased `sourceName`. Order matters: most
specific tier checked first. Used by both LLM-success path (override) and
rule_fallback path.
"""

from __future__ import annotations

OFFICIAL_BLOG_KEYWORDS: tuple[str, ...] = (
    "openai.com",
    "anthropic.com",
    "google.blog",
    "deepmind.google",
    "huggingface.co",
    "research.google",
)

INSTITUTIONAL_KEYWORDS: tuple[str, ...] = (
    ".edu",
    "stanford",
    "berkeley",
    "mit-",
    "cmu",
    "arxiv.org",
    "nature.com",
    "science.org",
    "acm.org",
)

AUTHORITATIVE_MEDIA_KEYWORDS: tuple[str, ...] = (
    "technologyreview.com",
    "simonwillison.net",
    "latent.space",
    "stratechery.com",
)

_TIER_OFFICIAL = ("official_blog", 90)
_TIER_INSTITUTIONAL = ("authoritative_media", 80)
_TIER_MEDIA = ("authoritative_media", 70)
_TIER_COMMUNITY = ("community", 50)


def classify_authority(source_name: str) -> tuple[str, int]:
    """Return (tier, baseline) for the given source name.

    Substring match on lowercased source_name. Default: ('community', 50).
    """
    name = (source_name or "").lower()
    for kw in OFFICIAL_BLOG_KEYWORDS:
        if kw in name:
            return _TIER_OFFICIAL
    for kw in INSTITUTIONAL_KEYWORDS:
        if kw in name:
            return _TIER_INSTITUTIONAL
    for kw in AUTHORITATIVE_MEDIA_KEYWORDS:
        if kw in name:
            return _TIER_MEDIA
    return _TIER_COMMUNITY


__all__ = [
    "AUTHORITATIVE_MEDIA_KEYWORDS",
    "INSTITUTIONAL_KEYWORDS",
    "OFFICIAL_BLOG_KEYWORDS",
    "classify_authority",
]
