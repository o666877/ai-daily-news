"""Reddit collector — opencli browser bridge first, Atom `.rss` fallback.

Channel history:
1. (early) Anonymous `.json` HTTP fetches — 403 for all non-logged-in
   clients on datacenter / many ISP IPs.
2. (T036) OpenCLI bridge — abandoned when the browser extension was not
   always connected (no fallback meant a dead source).
3. Anonymous Atom feed `top.rss` — still works, but carries no score /
   comment metadata.
4. (current) opencli browser bridge as primary channel (logged-in Chrome
   session passes the IP blocks and exposes score / num_comments /
   selftext), with the Atom feed retained as automatic fallback when the
   bridge is unavailable or every sub fails.

Dispatch lives in `collect_reddit()`: probe opencli (PATH + env kill
switch) → bridge; probe failure or all-subs-empty → Atom path
(`_collect_via_atom`). Every decision logs a `channel=` field so the
serving channel of a run is greppable.

Kill switch: AIDAILY_REDDIT_DISABLE_OPENCLI=1 skips the probe entirely.

Public surface preserved: `async def collect_reddit() -> list[RawItem]`.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any

import feedparser
import httpx

from app.config import get_settings
from app.models.article import RawItem
from app.models.meta import SourceKey
from app.pipeline.collectors import reddit_opencli

logger = logging.getLogger("aidaily.collector.reddit")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# AI-relevant subreddits. Mix of research, applied AI, open source, and
# broad community hubs so a single sub going quiet doesn't zero the source.
# Verified via opencli bridge probe 2026-08-18 (AI_Agents 10 posts,
# ChatGPTCoding 10 posts under top/week).
SUBREDDITS: list[str] = [
    "MachineLearning",  # research papers, releases — slow but authoritative
    "artificial",       # general AI news, broad community
    "OpenAI",           # vendor releases / discussion
    "Anthropic",        # vendor releases / discussion
    "localLLaMA",       # open-source LLM releases, high signal
    "AI_Agents",        # agent-specific sub — agent topic gap
    "ChatGPTCoding",    # agent frameworks / tools practice posts — tools gap
]

TIME_RANGE: str = "week"          # Reddit `t=` param; week gives the 72h filter room.
PER_SUB_LIMIT_PARAM: int = 25     # passed in the URL; Reddit caps around 100.
FRESH_WINDOW_HOURS: int = 72      # drop posts older than this (aligns with web collector).
REQUEST_TIMEOUT: float = 10.0     # per-request budget; subs run concurrently.
CONCURRENCY: int = 5              # bounded parallelism safety net.
RAW_TEXT_CAP: int = 4000          # cap body so giant posts don't blow up the LLM.

# Reddit 403s the default httpx UA on most IPs; caller may override via AIDAILY_REDDIT_UA.
DEFAULT_USER_AGENT: str = "aidaily/1.0 (research; +https://github.com/aidaily/aidaily)"

# Reddit embeds the post id in entry <id> like "/r/sub/comments/<id>/...".
_POST_ID_RE = re.compile(r"/comments/([a-z0-9]{3,12})", re.IGNORECASE)
# Simple tag stripper for the HTML <content> body.
_TAG_RE = re.compile(r"<[^>]+>")


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


async def collect_reddit() -> list[RawItem]:
    """Channel dispatch: opencli browser bridge first, Atom feed fallback.

    Order:
    1. opencli unavailable (no binary / kill switch) → Atom.
    2. Bridge returns items → done (Atom untouched).
    3. Bridge returns nothing (all subs failed or everything filtered) →
       Atom. The bridge is a volatile dependency (browser session); the
       Atom endpoint is the proven fallback — T036's lesson is that the
       bridge must never be a single point of failure.
    """
    if reddit_opencli.opencli_available():
        items = await reddit_opencli.collect_via_opencli(SUBREDDITS)
        if items:
            logger.info(
                "reddit_channel_selected",
                extra={
                    "source": SourceKey.REDDIT.value,
                    "channel": "opencli",
                    "count": len(items),
                },
            )
            return items
        logger.warning(
            "reddit_bridge_empty_falling_back",
            extra={"source": SourceKey.REDDIT.value, "channel": "opencli"},
        )
    else:
        logger.info(
            "reddit_channel_selected",
            extra={
                "source": SourceKey.REDDIT.value,
                "channel": "atom",
                "reason": "opencli_unavailable",
            },
        )
    return await _collect_via_atom()


async def _collect_via_atom() -> list[RawItem]:
    """Fetch top-of-week posts for each configured subreddit via the public
    Atom `.rss` feed. Returns an empty list if all subs fail; per-sub
    failures are logged and skipped (FR-007a).
    """
    user_agent = _resolve_user_agent()
    sem = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(
        headers={
            "User-Agent": user_agent,
            "Accept": "application/atom+xml, application/xml, text/xml, */*",
        },
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
    ) as client:
        results = await asyncio.gather(
            *(_collect_one_sub(sem, client, sub) for sub in SUBREDDITS),
            return_exceptions=True,
        )

    items: list[RawItem] = []
    failures = 0
    for sub_name, result in zip(SUBREDDITS, results, strict=False):
        if isinstance(result, Exception):
            failures += 1
            logger.warning(
                "reddit_sub_failed",
                extra={
                    "source": SourceKey.REDDIT.value,
                    "subreddit": sub_name,
                    "exception_type": type(result).__name__,
                },
            )
            continue
        items.extend(result)

    if failures == len(SUBREDDITS) and SUBREDDITS:
        logger.warning(
            "reddit_all_subs_failed",
            extra={"source": SourceKey.REDDIT.value, "sub_count": failures},
        )
    return items


# ---------------------------------------------------------------------------
# Per-subreddit implementation
# ---------------------------------------------------------------------------


async def _collect_one_sub(
    sem: asyncio.Semaphore,
    client: httpx.AsyncClient,
    sub_name: str,
) -> list[RawItem]:
    """Fetch one subreddit's top.rss, filter to fresh posts, build RawItems."""
    async with sem:
        url = (
            f"https://www.reddit.com/r/{sub_name}/top/.rss"
            f"?t={TIME_RANGE}&limit={PER_SUB_LIMIT_PARAM}"
        )
        response = await client.get(url)
        response.raise_for_status()
        content_bytes = response.content

    parsed = feedparser.parse(content_bytes)
    if not parsed.entries:
        if parsed.bozo:
            logger.warning(
                "reddit_sub_parse_error",
                extra={
                    "source": SourceKey.REDDIT.value,
                    "subreddit": sub_name,
                    "bozo_exception": repr(parsed.bozo_exception),
                },
            )
        else:
            logger.info(
                "reddit_sub_empty",
                extra={"source": SourceKey.REDDIT.value, "subreddit": sub_name},
            )
        return []

    items: list[RawItem] = []
    now = datetime.now(tz=timezone.utc)
    for entry in parsed.entries:
        item = _build_item(sub_name, entry, now)
        if item is not None:
            items.append(item)
    return items


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_user_agent() -> str:
    """Pull the configured Reddit UA, falling back to the module default."""
    try:
        ua = get_settings().reddit_ua
    except Exception:  # pragma: no cover — defensive; settings always available.
        ua = ""
    return (ua or "").strip() or DEFAULT_USER_AGENT


def _build_item(
    sub_name: str,
    entry: Any,
    now: datetime,
) -> RawItem | None:
    """Convert a feedparser entry to a RawItem.

    Returns None when title/link is missing, or when the post is older
    than FRESH_WINDOW_HOURS. Entries with unknown timestamps are kept.
    """
    title = (getattr(entry, "title", "") or "").strip()
    if not title:
        return None

    link = (getattr(entry, "link", "") or "").strip()
    if not link:
        return None

    published_at, age_h = _extract_time(entry)
    if age_h is not None and age_h > FRESH_WINDOW_HOURS:
        return None
    if not published_at:
        published_at = now.isoformat()

    raw_text = _extract_body(entry) or title
    raw_text = raw_text[:RAW_TEXT_CAP]

    post_id = _extract_post_id(link, entry)

    extra: dict[str, Any] = {
        "subreddit": sub_name,
        "post_id": post_id,
    }
    if age_h is not None:
        extra["age_h"] = round(age_h, 1)

    return RawItem(
        sourceKey=SourceKey.REDDIT,
        sourceName=f"reddit.com/r/{sub_name}",
        sourceUrl=link,
        title=title,
        rawText=raw_text,
        publishedAt=published_at,
        extra=extra,
    )


def _extract_time(entry: Any) -> tuple[str, float | None]:
    """Return (iso_published, age_hours). Age is None when no timestamp parses."""
    for attr in ("published_parsed", "updated_parsed"):
        st = getattr(entry, attr, None)
        if not st:
            continue
        try:
            dt = datetime(*st[:6], tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        iso = dt.isoformat()
        age_h = (datetime.now(tz=timezone.utc) - dt).total_seconds() / 3600.0
        return iso, age_h
    # Fall back to the raw string field if present (no age computable).
    for attr in ("published", "updated"):
        raw = getattr(entry, attr, None)
        if raw:
            return raw, None
    return "", None


def _extract_body(entry: Any) -> str:
    """Pull the post body, strip HTML tags, collapse whitespace."""
    for attr in ("content", "summary", "description"):
        value = getattr(entry, attr, None)
        if not value:
            continue
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, dict) and first.get("value"):
                value = first["value"]
            else:
                continue
        if isinstance(value, str) and value:
            text = _TAG_RE.sub(" ", value)
            return " ".join(text.split())
    return ""


def _extract_post_id(link: str, entry: Any) -> str:
    """Best-effort Reddit post id from the permalink or entry id."""
    m = _POST_ID_RE.search(link)
    if m:
        return m.group(1)
    entry_id = getattr(entry, "id", "") or ""
    m = _POST_ID_RE.search(entry_id)
    return m.group(1) if m else ""


__all__ = ["collect_reddit", "SUBREDDITS"]
