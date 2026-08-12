"""GET /api/v1/articles/{id} - Article detail (T044)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.db import get_session
from app.infra.errors import ArticleNotFoundError
from app.models import Article, ArticleORM, SourceKey, TypeKey

router = APIRouter(prefix="/api/v1", tags=["articles"])


@router.get("/articles/{article_id}")
async def get_article_detail(
    article_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return full Article for given id; 404 2001 if not found."""
    orm = await session.get(ArticleORM, article_id)
    if orm is None:
        raise ArticleNotFoundError(f"文章不存在: {article_id}")
    article = Article(
        id=orm.id,
        title=orm.title,
        excerpt=orm.excerpt,
        type=TypeKey(orm.type),
        src=SourceKey(orm.src),
        time=orm.time,
        readingMinutes=orm.reading_minutes,
        issueId=orm.issue_id,
        lede=orm.lede,
        summary=orm.summary,
        body=orm.body,
        quote=orm.quote,
        points=orm.points,
        sourceUrl=orm.source_url,
        sourceName=orm.source_name,
        publishedAt=orm.published_at,
    )
    return article.model_dump(by_alias=True, mode="json")


__all__ = ["router"]
