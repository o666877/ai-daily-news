"""IssueService: get_today() returns (DailyIssue, summary, list[ArticleListItem])."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.errors import (
    IssueGeneratingError,
    IssueNotGeneratedError,
)
from app.models.article import ArticleListItem, ArticleORM
from app.models.daily_issue import (
    DailyIssue,
    DailyIssueORM,
    DailyIssueSummary,
    FiltersApplied,
    IssueStatus,
)
from app.models.meta import SOURCE_KEYS, TYPE_KEYS, SourceKey, TypeKey


async def _to_daily_issue(orm: DailyIssueORM, article_count: int) -> DailyIssue:
    filters = orm.filters_applied or {"sources": [], "types": []}
    return DailyIssue(
        id=orm.id,
        date=orm.date,
        edition=orm.edition,
        status=IssueStatus(orm.status),
        generatedAt=orm.generated_at.isoformat() if orm.generated_at else None,
        articleCount=article_count,
        filtersApplied=FiltersApplied(
            sources=[SourceKey(s) for s in filters.get("sources", [])],
            types=[TypeKey(t) for t in filters.get("types", [])],
        ),
    )


async def _compute_summary(
    session: AsyncSession, issue_id: str
) -> DailyIssueSummary:
    rows = await session.execute(
        select(ArticleORM.type, ArticleORM.src)
        .where(ArticleORM.issue_id == issue_id)
    )
    by_type = {k: 0 for k in TYPE_KEYS}
    by_source = {k: 0 for k in SOURCE_KEYS}
    for type_val, src_val in rows.all():
        if type_val in by_type:
            by_type[type_val] += 1
        if src_val in by_source:
            by_source[src_val] += 1
    return DailyIssueSummary(byType=by_type, bySource=by_source)


async def get_today(
    session: AsyncSession, now: datetime | None = None
) -> tuple[DailyIssue, DailyIssueSummary, list[ArticleListItem]]:
    """Return (issue, summary, articles_list) for today's issue.

    Raises:
        IssueNotGeneratedError (2002): no issue exists or status=failed.
        IssueGeneratingError (2003): issue exists and status=generating.
    """
    target = now or datetime.now(timezone.utc)
    issue_id = target.strftime("%Y%m%d")
    orm = await session.get(DailyIssueORM, issue_id)
    if orm is None or orm.status == IssueStatus.FAILED.value:
        raise IssueNotGeneratedError("今日刊尚未生成完成")
    if orm.status == IssueStatus.GENERATING.value:
        raise IssueGeneratingError("今日刊正在生成中")

    count_result = await session.execute(
        select(func.count(ArticleORM.id)).where(ArticleORM.issue_id == issue_id)
    )
    count = int(count_result.scalar_one())

    issue = await _to_daily_issue(orm, count)
    summary = await _compute_summary(session, issue_id)
    items_result = await session.execute(
        select(ArticleORM)
        .where(ArticleORM.issue_id == issue_id)
        .order_by(ArticleORM.id)
    )
    items = [
        ArticleListItem(
            id=a.id,
            title=a.title,
            excerpt=a.excerpt,
            type=TypeKey(a.type),
            src=SourceKey(a.src),
            time=a.time,
            readingMinutes=a.reading_minutes,
        )
        for a in items_result.scalars()
    ]
    return issue, summary, items


async def get_issue_by_id(
    session: AsyncSession, issue_id: str
) -> DailyIssueORM | None:
    return await session.get(DailyIssueORM, issue_id)


__all__ = ["get_today"]
