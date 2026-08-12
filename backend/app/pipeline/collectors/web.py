"""Web RSS collector (T037).

Curated OPML of AI blogs; uses feedparser for RSS/Atom.
For non-RSS discovered URLs: trafilatura for boilerplate stripping.

Returns list[RawItem].
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import feedparser
import httpx

from app.models.article import RawItem
from app.models.meta import SourceKey

logger = logging.getLogger("aidaily.collector.web")

# Curated AI blogs/newsletters.
DEFAULT_FEEDS: list[tuple[str, str]] = [
    ("Simon Willison", "https://simonwillison.net/atom/everything/"),
    ("Anthropic News", "https://www.anthropic.com/news/rss.xml"),
    ("OpenAI Blog", "https://openai.com/blog/rss.xml"),
    ("Hugging Face Blog", "https://huggingface.co/blog/feed.xml"),
    ("Latent Space", "https://www.latent.space/feed"),
    ("Import AI", "https://importai.substack.com/feed"),
    ("Stratechery", "https://stratechery.com/feed/"),
    ("Google Research", "https://research.google/blog/rss/"),
]
PER_FEED_LIMIT = 5


async def collect_web(client: httpx.AsyncClient | None = None) -> list[RawItem]:
    """Fetch all feeds; return collected RawItems (failures skipped)."""
    own_client = client or httpx.AsyncClient(timeout=20.0, follow_redirects=True)
    items: list[RawItem] = []
    try:
        for name, url in DEFAULT_FEEDS:
            try:
                raw_xml = await _fetch_feed(own_client, url)
                feed_items = _parse_feed(name, url, raw_xml)
                items.extend(feed_items[:PER_FEED_LIMIT])
            except Exception as exc:
                logger.warning(
                    "web_feed_failed",
                    extra={
                        "source": SourceKey.WEB.value,
                        "feed": name,
                        "exception_type": type(exc).__name__,
                    },
                )
    finally:
        if client is None:
            await own_client.aclose()
    return items


async def _fetch_feed(client: httpx.AsyncClient, url: str) -> str:
    resp = await client.get(url, headers={"User-Agent": "aidaily/1.0"})
    resp.raise_for_status()
    return resp.text


def _parse_feed(name: str, url: str, xml_text: str) -> list[RawItem]:
    # feedparser is sync; cheap enough for ~30 entries per feed.
    parsed = feedparser.parse(xml_text)
    items: list[RawItem] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for entry in parsed.entries:
        link = getattr(entry, "link", "") or ""
        if not link:
            continue
        title = getattr(entry, "title", "") or "(untitled)"
        summary = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
        published = (
            getattr(entry, "published", None)
            or getattr(entry, "updated", None)
            or now_iso
        )
        items.append(
            RawItem(
                sourceKey=SourceKey.WEB,
                sourceName=_host_of(link) or name,
                sourceUrl=link,
                title=title,
                rawText=f"{summary}"[:6000],
                publishedAt=str(published),
                extra={"feed": name},
            )
        )
    return items


def _host_of(url: str) -> str:
    try:
        from urllib.parse import urlparse

        host = urlparse(url).netloc
        return host.replace("www.", "")
    except Exception:
        return ""


__all__ = ["DEFAULT_FEEDS", "collect_web"]
