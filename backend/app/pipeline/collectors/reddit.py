"""Reddit collector (T036).

Uses PRAW (Reddit OAuth). Subreddits: MachineLearning/LocalLLaMA/OpenAI/
singularity/AgentAI. Sort by top(day), limit 10-15 per sub.

PRAW is synchronous; runs in thread executor.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import get_settings
from app.models.article import RawItem
from app.models.meta import SourceKey

logger = logging.getLogger("aidaily.collector.reddit")

SUBREDDITS = ["MachineLearning", "LocalLLaMA", "OpenAI", "singularity", "AgentAI"]
PER_SUB_LIMIT = 12


async def collect_reddit() -> list[RawItem]:
    settings = get_settings()
    try:
        return await asyncio.to_thread(_collect_sync, settings.reddit_ua)
    except Exception as exc:
        logger.warning(
            "reddit_failed",
            extra={"source": SourceKey.REDDIT.value, "exception_type": type(exc).__name__},
        )
        return []


def _collect_sync(user_agent: str) -> list[RawItem]:
    try:
        import praw  # type: ignore[import-untyped]
    except ImportError:  # pragma: no cover
        logger.warning("praw_unavailable")
        return []
    # PRAW supports read-only mode without OAuth for limited access.
    reddit = praw.Reddit(
        client_id="anonymous",
        client_secret=None,
        user_agent=user_agent,
    )
    try:
        reddit.read_only = True
    except Exception:  # pragma: no cover
        pass
    items: list[RawItem] = []
    for sub_name in SUBREDDITS:
        try:
            sub = reddit.subreddit(sub_name)
            for submission in sub.top(time_filter="day", limit=PER_SUB_LIMIT):
                if not submission.title or not submission.permalink:
                    continue
                url = submission.url
                # If URL points back to reddit comments, use permalink.
                if "reddit.com" not in url:
                    pass
                else:
                    url = f"https://www.reddit.com{submission.permalink}"
                items.append(_to_raw_item(sub_name, submission, url))
        except Exception as exc:
            logger.warning(
                "reddit_sub_failed",
                extra={
                    "source": SourceKey.REDDIT.value,
                    "subreddit": sub_name,
                    "exception_type": type(exc).__name__,
                },
            )
    return items


def _to_raw_item(sub_name: str, submission: Any, url: str) -> RawItem:
    title = str(getattr(submission, "title", "")).strip()
    body_text = str(getattr(submission, "selftext", "")).strip()
    score = int(getattr(submission, "score", 0) or 0)
    created = float(getattr(submission, "created_utc", 0.0) or 0.0)
    from datetime import datetime, timezone

    published = (
        datetime.fromtimestamp(created, tz=timezone.utc).isoformat() if created else ""
    )
    raw = f"{title}\n\n{body_text}" if body_text else title
    return RawItem(
        sourceKey=SourceKey.REDDIT,
        sourceName=f"reddit.com/r/{sub_name}",
        sourceUrl=url,
        title=title,
        rawText=raw,
        publishedAt=published,
        extra={"score": score, "subreddit": sub_name},
    )


__all__ = ["collect_reddit"]
