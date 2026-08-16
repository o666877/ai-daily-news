"""Web collector via direct RSS/Atom feed parsing (T037 v3, feedparser edition).

Replaces the previous Jina-Reader-based collector. Rationale: anonymous Jina
Reader calls have been blocked by Cloudflare since mid-2025 (jina-ai/reader#1184),
and the project's principle is "no paid services". Direct RSS parsing with
`feedparser` is free, pure-Python, and needs no external proxy service.

Design:
- Curated list of (source_name, feed_url) pairs at bottom of file.
- Per-source: fetch RSS/Atom XML via httpx.AsyncClient (browser-like UA,
  follow redirects), parse with feedparser.parse(bytes).
- Caps: PER_SOURCE_LIMIT entries per feed, TOTAL_LIMIT overall.
- MIT Tech Review: full feed includes non-AI topics; filter by URL
  containing `/artificial-intelligence/`.
- Per-source failures (HTTP 4xx/5xx, parse errors, timeouts) are logged
  and skipped (FR-007a).
- Concurrency bounded by asyncio.Semaphore(5).
- No anti-bot detection needed — feeds are public XML.

Public surface preserved: `async def collect_web() -> list[RawItem]`.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import feedparser
import httpx

from app.models.article import RawItem
from app.models.meta import SourceKey

logger = logging.getLogger("aidaily.collector.web")

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

PER_SOURCE_LIMIT: int = 5
TOTAL_LIMIT: int = 30
CONCURRENCY: int = 5
REQUEST_TIMEOUT: float = 30.0
RAW_TEXT_CAP: int = 4000
FRESH_WINDOW_HOURS: int = 72  # Soft threshold for staleness tolerance.

# Browser-like User-Agent — some CDNs reject default httpx UA.
USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# Curated AI news / blog source list
# ---------------------------------------------------------------------------
#
# Each entry: (display_name, feed_url). Verified 2026-08-13 via `feedparser`.
# Health (n=entries / fresh24h=≤24h / oldest_h):
#   Simon Willison       n= 30 f24=3 f72=7  oldest=207h
#   Hugging Face Blog    n=839 f24=2 f72=5  oldest=56936h
#   MIT Tech Review      n= 10 f24=4 f72=10 oldest=72h
#   DeepMind Blog        n=100 f24=1 f72=1  oldest=7041h
#   Latent Space         n= 20 f24=1 f72=4  oldest=484h
#   Stratechery          n= 10 f24=1 f72=3  oldest=551h
#   Google Research Blog n=100 f24=1 f72=2  oldest=7860h
#   AWS ML Blog          n= 20 f24=4 f72=11 oldest=161h
#   KD Nuggets           n= 10 f24=2 f72=7  oldest=161h
#   Hacker News AI       n= 20 f24=20 f72=20 oldest=3h
# Blocked / unreachable feeds are kept below as `# blocked:` comments so we
# remember not to re-add them without a verified replacement.
#
DEFAULT_SOURCES: list[tuple[str, str]] = [
    ("Simon Willison", "https://simonwillison.net/atom/everything/"),
    ("Hugging Face Blog", "https://huggingface.co/blog/feed.xml"),
    # Full feed; we filter entries by URL containing `/artificial-intelligence/`.
    ("MIT Tech Review AI", "https://www.technologyreview.com/feed/"),
    ("DeepMind Blog", "https://deepmind.google/blog/rss.xml"),
    ("Latent Space", "https://www.latent.space/feed"),
    ("Stratechery", "https://stratechery.com/feed/"),
    ("Google Research Blog", "https://research.google/blog/rss/"),
    ("AWS ML Blog", "https://aws.amazon.com/blogs/machine-learning/feed/"),
    ("KD Nuggets", "https://www.kdnuggets.com/feed"),
    ("Hacker News AI", "https://hnrss.org/newest?q=AI"),
]

# Backwards-compatible alias for any code/tests referencing the old name.
DEFAULT_FEEDS: list[tuple[str, str]] = DEFAULT_SOURCES

# blocked: ("Anthropic News", "https://www.anthropic.com/news/rss.xml"),  # 404 (Cloudflare). RSS endpoint removed.
# blocked: ("The Batch (DeepLearning.AI)", "https://www.deeplearning.ai/the-batch/feed/"),  # 308 -> /the-batch/feed -> 404.
# blocked: ("Mistral News", "https://mistral.ai/news/rss.xml"),  # 0 entries returned.
# blocked: ("Meta AI Blog", "https://ai.meta.com/blog/rss/"),  # 0 entries returned.

# Topic filter applied per-source by URL substring.
_TOPIC_FILTERS: dict[str, str] = {
    "MIT Tech Review AI": "/artificial-intelligence/",
}


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


async def collect_web() -> list[RawItem]:
    """Fetch all RSS/Atom feeds concurrently; return collected RawItems.

    Per-source failures are logged and skipped per FR-007a.
    Caps: PER_SOURCE_LIMIT entries per feed, TOTAL_LIMIT overall.
    """
    sem = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "application/rss+xml, application/atom+xml, "
                "application/xml, text/xml, */*"
            ),
        },
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
    ) as client:
        results = await asyncio.gather(
            *(_collect_one_source(sem, client, name, url) for name, url in DEFAULT_SOURCES),
            return_exceptions=True,
        )

    items: list[RawItem] = []
    for (name, _url), result in zip(DEFAULT_SOURCES, results, strict=False):
        if isinstance(result, Exception):
            logger.warning(
                "web_source_failed",
                extra={
                    "source": SourceKey.WEB.value,
                    "feed": name,
                    "exception_type": type(result).__name__,
                },
            )
            continue
        items.extend(result)

    return items[:TOTAL_LIMIT]


# ---------------------------------------------------------------------------
# Per-source implementation
# ---------------------------------------------------------------------------


async def _collect_one_source(
    sem: asyncio.Semaphore,
    client: httpx.AsyncClient,
    name: str,
    feed_url: str,
) -> list[RawItem]:
    """Fetch one feed, parse XML, build RawItems for its entries."""
    async with sem:
        response = await client.get(feed_url)
        response.raise_for_status()
        content_bytes = response.content

    # feedparser handles both RSS and Atom, and accepts bytes (it sniffs
    # encoding from the XML declaration or HTTP headers).
    parsed = feedparser.parse(content_bytes)

    # parse() never raises; on failure it returns a feed with bozo bit set
    # and an empty entries list. We treat "bozo + no entries" as a failure
    # so we can log it; partial parses (bozo + some entries) still count.
    if not parsed.entries:
        if parsed.bozo:
            logger.warning(
                "web_feed_parse_error",
                extra={
                    "source": SourceKey.WEB.value,
                    "feed": name,
                    "bozo_exception": repr(parsed.bozo_exception),
                },
            )
        else:
            logger.warning(
                "web_feed_empty",
                extra={"source": SourceKey.WEB.value, "feed": name},
            )
        return []

    # Soft 72h freshness window: drop entries older than FRESH_WINDOW_HOURS.
    # Sources that end up empty after filtering are tagged fresh=False so the
    # generator can decide whether to skip health gating. We log at info
    # level only — stale feeds are tolerated, not warned.
    fresh_entries, stale_count = _filter_fresh(
        parsed.entries, hours=FRESH_WINDOW_HOURS
    )
    if stale_count and not fresh_entries:
        # Whole feed outside window → record stale info for diagnostics.
        oldest_h = _oldest_age_hours(parsed.entries)
        logger.info(
            "web_feed_stale",
            extra={
                "source": SourceKey.WEB.value,
                "feed": name,
                "stale_entries": stale_count,
                "hours": FRESH_WINDOW_HOURS,
                "oldest_h": oldest_h,
            },
        )

    topic_filter = _TOPIC_FILTERS.get(name)
    items: list[RawItem] = []
    for entry in fresh_entries:
        link = getattr(entry, "link", "") or ""
        if topic_filter and topic_filter not in link:
            continue
        item = _build_item(name, feed_url, entry, link)
        if item is not None:
            items.append(item)
        if len(items) >= PER_SOURCE_LIMIT:
            break
    return items


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_item(
    source_name: str,
    feed_url: str,
    entry: object,
    link: str,
) -> RawItem | None:
    """Convert a feedparser entry into a RawItem. Skip entries missing a link."""
    if not link:
        return None

    title = (getattr(entry, "title", "") or "").strip() or "(untitled)"

    # Prefer full content, then summary, then description.
    raw_text = ""
    for attr in ("content", "summary", "description"):
        value = getattr(entry, attr, None)
        if not value:
            continue
        if isinstance(value, list) and value:
            # content field is a list of {value, type, ...} dicts.
            first = value[0]
            if isinstance(first, dict) and first.get("value"):
                raw_text = first["value"]
                break
        if isinstance(value, str) and value:
            raw_text = value
            break
    raw_text = raw_text.strip()
    if not raw_text:
        raw_text = title
    raw_text = raw_text[:RAW_TEXT_CAP]

    published_at = _extract_published(entry)
    age_h = _entry_age_hours(entry)
    # Unknown timestamp → default to fresh=True so we don't accidentally drop
    # undated entries (we already filter to fresh in _collect_one_source).
    fresh = age_h is None or age_h <= FRESH_WINDOW_HOURS

    return RawItem(
        sourceKey=SourceKey.WEB,
        sourceName=source_name,
        sourceUrl=link,
        title=title,
        rawText=raw_text,
        publishedAt=published_at,
        extra={
            "source_index": feed_url,
            "age_h": age_h,
            "fresh": fresh,
        },
    )


def _extract_published(entry: object) -> str:
    """Return ISO-8601 published/updated timestamp; fall back to now().isoformat().

    feedparser exposes parsed `published_parsed` / `updated_parsed` as
    time.struct_time (UTC). If absent, fall back to the raw string fields;
    if those are missing too, use current time.
    """
    for attr in ("published_parsed", "updated_parsed"):
        st = getattr(entry, attr, None)
        if st:
            try:
                dt = datetime(*st[:6], tzinfo=timezone.utc)
                return dt.isoformat()
            except (TypeError, ValueError):
                continue
    for attr in ("published", "updated"):
        raw = getattr(entry, attr, None)
        if raw:
            return raw
    return datetime.now(tz=timezone.utc).isoformat()


def _entry_age_hours(entry: object) -> float | None:
    """Return age in hours (UTC now minus published/updated) or None if unknown."""
    for attr in ("published_parsed", "updated_parsed"):
        st = getattr(entry, attr, None)
        if not st:
            continue
        try:
            dt = datetime(*st[:6], tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        delta = datetime.now(tz=timezone.utc) - dt
        return delta.total_seconds() / 3600.0
    return None


def _filter_fresh(
    entries: list[object], hours: int = FRESH_WINDOW_HOURS
) -> tuple[list[object], int]:
    """Drop entries older than `hours` (default 72h soft threshold).

    Returns (kept_entries, dropped_count). Entries without a parseable
    timestamp are kept (we don't punish missing dates).
    """
    kept: list[object] = []
    dropped = 0
    for entry in entries:
        age = _entry_age_hours(entry)
        if age is None or age <= hours:
            kept.append(entry)
        else:
            dropped += 1
    return kept, dropped


def _oldest_age_hours(entries: list[object]) -> float | None:
    """Largest age_h across entries; None if all entries lack timestamps."""
    ages = [a for a in (_entry_age_hours(e) for e in entries) if a is not None]
    return max(ages) if ages else None


__all__ = ["collect_web", "DEFAULT_FEEDS", "DEFAULT_SOURCES"]
