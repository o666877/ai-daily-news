"""X (Twitter) collector via RSSHub (T038).

Iterates AIDAILY_X_ACCOUNTS (or default list T032), fetches
{AIDAILY_X_RSSHUB_BASE_URL}/twitter/user/{username} concurrently.
- If AIDAILY_X_RSSHUB_BASE_URL empty → return empty list (silent skip).
- Per-account failures logged and skipped (FR-007a).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import feedparser
import httpx

from app.config import get_settings
from app.models.article import RawItem
from app.models.meta import SourceKey
from app.pipeline.defaults.x_accounts import get_accounts

logger = logging.getLogger("aidaily.collector.x")


async def collect_x_rsshub(client: httpx.AsyncClient | None = None) -> list[RawItem]:
    settings = get_settings()
    base_url = settings.x_rsshub_base_url.strip()
    if not base_url:
        # Silent skip: X source disabled when RSSHub URL unset.
        return []
    base_url = base_url.rstrip("/")
    accounts = get_accounts(settings.x_accounts)
    own_client = client or httpx.AsyncClient(timeout=15.0, follow_redirects=True)
    try:
        tasks = [_fetch_account(own_client, base_url, a) for a in accounts]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        if client is None:
            await own_client.aclose()

    items: list[RawItem] = []
    for account, result in zip(accounts, results, strict=False):
        if isinstance(result, Exception):
            logger.warning(
                "x_account_failed",
                extra={
                    "source": SourceKey.X.value,
                    "account": account,
                    "exception_type": type(result).__name__,
                },
            )
            continue
        items.extend(result)
    return items


async def _fetch_account(
    client: httpx.AsyncClient, base_url: str, username: str
) -> list[RawItem]:
    url = f"{base_url}/twitter/user/{username}"
    resp = await client.get(url, headers={"User-Agent": "aidaily/1.0"})
    resp.raise_for_status()
    return _parse_account_feed(username, resp.text)


def _parse_account_feed(username: str, xml_text: str) -> list[RawItem]:
    parsed = feedparser.parse(xml_text)
    items: list[RawItem] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for entry in parsed.entries:
        link = getattr(entry, "link", "") or ""
        if not link:
            continue
        title = getattr(entry, "title", "") or f"@{username}"
        summary = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
        published = (
            getattr(entry, "published", None)
            or getattr(entry, "updated", None)
            or now_iso
        )
        items.append(
            RawItem(
                sourceKey=SourceKey.X,
                sourceName=f"x.com/@{username}",
                sourceUrl=link,
                title=title,
                rawText=summary[:4000],
                publishedAt=str(published),
                extra={"author": username},
            )
        )
    return items


__all__ = ["collect_x_rsshub"]
