"""Issue generation pipeline (T040).

generate_issue(date) → DailyIssue:
1. Load current Settings snapshot.
2. Insert DailyIssue(status=generating, filtersApplied=snapshot).
3. Call collector → list[RawItem].
4. For each item, call summarizer (with FR-007a per-item tolerance).
5. Persist Articles.
6. Update DailyIssue.status → ready (or failed on summarizer-wide failure).

Idempotent on issueId: re-entry returns existing ready issue.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.infra.db import get_session_factory
from app.models.article import ArticleORM, RawItem
from app.models.daily_issue import DailyIssueORM, IssueStatus
from app.models.meta import SourceKey, TypeKey
from app.pipeline import summarizer
from app.pipeline.collector import collect_all
from app.pipeline.summarizer import SummarizerFailure, summarize_item

logger = logging.getLogger("aidaily.generator")


def _issue_id(date: datetime) -> str:
    """YYYYMMDD id for a given date (in configured tz)."""
    return date.strftime("%Y%m%d")


def _iso(date: datetime) -> str:
    return date.isoformat()


async def _load_settings_snapshot(session: AsyncSession) -> dict[str, Any]:
    """Return {sources: [...], types: [...]} from settings row; default all-on if missing."""
    from sqlalchemy import text

    row = (
        await session.execute(text("SELECT sources, types FROM settings WHERE id = 1"))
    ).first()
    if row is None:
        return {
            "sources": [s.value for s in SourceKey],
            "types": [t.value for t in TypeKey],
        }
    return {"sources": list(row[0].keys() or []), "types": list(row[1].keys() or [])}


async def _count_issues(session: AsyncSession) -> int:
    result = await session.execute(select(func.count(DailyIssueORM.id)))
    return int(result.scalar_one())


async def _get_issue(session: AsyncSession, issue_id: str) -> DailyIssueORM | None:
    result = await session.execute(
        select(DailyIssueORM).where(DailyIssueORM.id == issue_id)
    )
    return result.scalar_one_or_none()


async def _insert_generating_issue(
    session: AsyncSession, issue_id: str, date_iso: str, filters: dict[str, Any]
) -> DailyIssueORM:
    orm = DailyIssueORM(
        id=issue_id,
        date=date_iso,
        edition=1,
        status=IssueStatus.GENERATING.value,
        generated_at=None,
        filters_applied=filters,
    )
    session.add(orm)
    await session.commit()
    return orm


async def _persist_article(
    session: AsyncSession,
    issue_id: str,
    index: int,
    raw: RawItem,
    summary_fields: Any,
) -> ArticleORM:
    article_id = f"{issue_id}-{index:04d}"
    # Compute time HH:mm from raw.publishedAt (UTC now fallback).
    time_label = _extract_time_label(raw.publishedAt)
    reading_minutes = max(1, len(raw.rawText) // 800)
    orm = ArticleORM(
        id=article_id,
        issue_id=issue_id,
        type=raw.suggestedType.value if raw.suggestedType else TypeKey.TOOLS.value,
        src=raw.sourceKey.value,
        title=raw.title[:200],
        excerpt=(summary_fields.summary or raw.title)[:200],
        lede=summary_fields.lede or summary_fields.summary or raw.title,
        summary=summary_fields.summary[:150],
        body=summary_fields.body or [raw.title],
        quote=summary_fields.quote,
        points=summary_fields.points or [raw.title],
        time=time_label,
        source_url=raw.sourceUrl,
        source_name=raw.sourceName[:200],
        reading_minutes=reading_minutes,
        published_at=raw.publishedAt,
    )
    session.add(orm)
    return orm


def _extract_time_label(published_at: str) -> str:
    """Extract HH:mm from ISO timestamp; fall back to current UTC time."""
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        return dt.strftime("%H:%M")
    except Exception:
        return datetime.now(timezone.utc).strftime("%H:%M")


async def generate_issue(
    date: datetime | None = None,
    *,
    llm_client: Any = None,
    inject_collector: Any = None,
) -> DailyIssueORM:
    """Generate the daily issue for `date` (defaults to today).

    Args:
        date: Target date (defaults to UTC now).
        llm_client: Inject LLMClient (for tests).
        inject_collector: Async callable returning list[RawItem] (for tests).

    Returns:
        DailyIssueORM (status=ready or failed).

    Idempotent: if a ready issue exists for the date, returns it directly.
    """
    target = date or datetime.now(timezone.utc)
    issue_id = _issue_id(target)
    date_iso = target.strftime("%Y-%m-%d")
    factory = get_session_factory()
    async with factory() as session:
        existing = await _get_issue(session, issue_id)
        if existing is not None and existing.status == IssueStatus.READY.value:
            return existing
        if existing is not None and existing.status == IssueStatus.FAILED.value:
            # Allow regeneration.
            await session.delete(existing)
            await session.commit()

        filters = await _load_settings_snapshot(session)
        issue_orm = await _insert_generating_issue(session, issue_id, date_iso, filters)

        # Collect.
        if inject_collector is not None:
            raw_items: list[RawItem] = await inject_collector()
        else:
            raw_items = await collect_all()

        # Summarize per item with FR-007a tolerance (single failures skipped).
        persisted: list[ArticleORM] = []
        summarizer_failures = 0
        for idx, raw in enumerate(raw_items, start=1):
            try:
                summary_fields = await summarize_item(raw, client=llm_client)
            except SummarizerFailure as exc:
                summarizer_failures += 1
                logger.warning(
                    "article_summarize_failed",
                    extra={
                        "source": raw.sourceKey.value,
                        "issue_id": issue_id,
                        "exception_type": type(exc).__name__,
                    },
                )
                continue
            except Exception as exc:
                summarizer_failures += 1
                logger.warning(
                    "article_summarize_failed",
                    extra={
                        "source": raw.sourceKey.value,
                        "issue_id": issue_id,
                        "exception_type": type(exc).__name__,
                    },
                )
                continue
            orm = await _persist_article(session, issue_id, idx, raw, summary_fields)
            persisted.append(orm)

        await session.commit()

        # Finalize status.
        # Failure rule: ALL summarizers failed → status=failed.
        # (FR-007a: single source collection failure → log + skip + continue.)
        all_failed = bool(raw_items) and summarizer_failures == len(raw_items)
        issue_orm.status = (
            IssueStatus.FAILED.value if all_failed else IssueStatus.READY.value
        )
        issue_orm.generated_at = datetime.utcnow()
        await session.commit()
        return issue_orm


__all__ = ["generate_issue"]
