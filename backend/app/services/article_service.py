"""Article list queries for filtering and pagination.

US1: each item carries compositeScore (int | null). Ordering:
composite_score DESC, time DESC (legacy rows with NULL composite_score sort last).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.article import ArticleListItem, ArticleORM
from app.models.article_score import ArticleScoreORM
from app.models.meta import SourceKey, TypeKey


async def list_articles(
    session: AsyncSession,
    filters: dict[str, str | None],
    page: int,
    page_size: int,
) -> tuple[list[ArticleListItem], int, dict[str, str | None]]:
    """Return filtered article list, total count, and echoed filters.

    Ordering: composite_score DESC (NULLS LAST), time DESC, id DESC.
    """
    conditions = []
    type_value = filters.get("type")
    src_value = filters.get("src")
    issue_id = filters.get("issueId")
    if type_value is not None:
        conditions.append(ArticleORM.type == type_value)
    if src_value is not None:
        conditions.append(ArticleORM.src == src_value)
    if issue_id is not None:
        conditions.append(ArticleORM.issue_id == issue_id)

    count_result = await session.execute(
        select(func.count(ArticleORM.id)).where(*conditions)
    )
    total = int(count_result.scalar_one())

    # Outer join to article_scores so we can order by composite_score.
    # Use selectinload to fetch score row without N+1.
    rows = await session.execute(
        select(ArticleORM)
        .outerjoin(ArticleScoreORM, ArticleScoreORM.article_id == ArticleORM.id)
        .where(*conditions)
        .order_by(
            ArticleScoreORM.composite_score.desc().nullslast(),
            ArticleORM.time.desc(),
            ArticleORM.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
        .options(selectinload(ArticleORM.score))
    )
    items = [
        ArticleListItem(
            id=row.id,
            title=row.title,
            excerpt=row.excerpt,
            type=TypeKey(row.type),
            src=SourceKey(row.src),
            time=row.time,
            readingMinutes=row.reading_minutes,
            compositeScore=row.score.composite_score if row.score else None,
            mustRead=row.is_must_read,
        )
        for row in rows.scalars()
    ]
    applied = {key: value for key, value in filters.items() if value is not None}
    return items, total, applied


__all__ = ["list_articles"]
