"""GitHub collector (T035).

- Primary: REST v3 `/search/repositories?q=...&sort=stars` for trending AI repos
  created in last 7 days.
- Auth via AIDAILY_GITHUB_TOKEN (raises quota usage; if empty, trending HTML fallback).
- Returns list[RawItem].
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.config import get_settings
from app.models.article import RawItem
from app.models.meta import SourceKey

logger = logging.getLogger("aidaily.collector.github")

GITHUB_API = "https://api.github.com"
SEARCH_QUERY_TEMPLATE = "created:{since}..{until} topic:ai stars:>50"


async def collect_github(client: httpx.AsyncClient | None = None) -> list[RawItem]:
    """Fetch trending AI repos from GitHub. Returns RawItem list (possibly empty)."""
    settings = get_settings()
    if settings.github_token:
        try:
            return await _collect_via_api(settings.github_token, client)
        except Exception as exc:
            logger.warning(
                "github_api_failed",
                extra={"source": SourceKey.GITHUB.value, "exception_type": type(exc).__name__},
            )
    # Fallback: scrape github.com/trending (best-effort, ToS-friendly public page).
    try:
        return await _collect_via_trending(client)
    except Exception as exc:
        logger.warning(
            "github_trending_failed",
            extra={"source": SourceKey.GITHUB.value, "exception_type": type(exc).__name__},
        )
        return []


async def _collect_via_api(
    token: str, client: httpx.AsyncClient | None
) -> list[RawItem]:
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    until = now.strftime("%Y-%m-%d")
    query = SEARCH_QUERY_TEMPLATE.format(since=since, until=until)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "aidaily/1.0",
    }
    own_client = client or httpx.AsyncClient(timeout=20.0)
    try:
        resp = await own_client.get(
            f"{GITHUB_API}/search/repositories",
            params={"q": query, "sort": "stars", "order": "desc", "per_page": 15},
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
    finally:
        if client is None:
            await own_client.aclose()
    items: list[RawItem] = []
    for repo in data.get("items", []):
        full = repo.get("full_name", "")
        url = repo.get("html_url", "")
        if not url:
            continue
        desc = repo.get("description") or ""
        stars = repo.get("stargazers_count", 0)
        items.append(
            RawItem(
                sourceKey=SourceKey.GITHUB,
                sourceName="github.com",
                sourceUrl=url,
                title=full,
                rawText=f"{desc}\n\nStars: {stars}\nTopics: {', '.join(repo.get('topics', []) or [])}".strip(),
                publishedAt=now.isoformat(),
                suggestedType=None,
                extra={"stars": stars},
            )
        )
    return items


async def _collect_via_trending(client: httpx.AsyncClient | None) -> list[RawItem]:
    """Fallback: scrape github.com/trending (zero auth)."""
    try:
        from selectolax.parser import HTMLParser
    except ImportError:  # pragma: no cover
        return []
    own_client = client or httpx.AsyncClient(timeout=20.0)
    try:
        resp = await own_client.get(
            "https://github.com/trending?since=weekly",
            headers={"User-Agent": "aidaily/1.0"},
        )
        resp.raise_for_status()
        tree = HTMLParser(resp.text)
    finally:
        if client is None:
            await own_client.aclose()

    items: list[RawItem] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for article in tree.css("article.Box-row"):
        h2 = article.css_first("h2 a")
        if h2 is None:
            continue
        href = h2.attributes.get("href", "").strip()
        if not href:
            continue
        full = href.lstrip("/")
        url = f"https://github.com{href}"
        desc_node = article.css_first("p")
        desc = desc_node.text(strip=True) if desc_node else ""
        items.append(
            RawItem(
                sourceKey=SourceKey.GITHUB,
                sourceName="github.com",
                sourceUrl=url,
                title=full,
                rawText=desc,
                publishedAt=now_iso,
                extra={},
            )
        )
    return items


__all__ = ["collect_github"]
