"""Article detail and filtered list endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.db import get_session
from app.infra.errors import ArticleNotFoundError, InvalidEnumError
from app.infra.pagination import PageParams, parse_page_params
from app.infra.ratelimit import read_limiter
from app.models import Article, ArticleORM, SourceKey, TypeKey
from app.services.article_service import list_articles

router = APIRouter(prefix="/api/v1", tags=["articles"])


@router.get("/articles")
@read_limiter.limit("120/minute")
async def get_articles(
    request: Request,
    type: str | None = Query(default=None),
    src: str | None = Query(default=None),
    issue_id: str | None = Query(default=None, alias="issueId"),
    page_params: PageParams = Depends(parse_page_params),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return articles filtered by type, source, and issue with pagination."""
    try:
        type_key = TypeKey(type) if type is not None else None
        src_key = SourceKey(src) if src is not None else None
    except ValueError:
        raise InvalidEnumError("枚举值非法或参数错误") from None

    filters = {
        "type": type_key.value if type_key else None,
        "src": src_key.value if src_key else None,
        "issueId": issue_id or datetime.now(timezone.utc).strftime("%Y%m%d"),
    }
    items, total, applied = await list_articles(
        session, filters, page_params.page, page_params.pageSize
    )
    return {
        "items": [item.model_dump(by_alias=True, mode="json") for item in items],
        "page": page_params.page,
        "pageSize": page_params.pageSize,
        "total": total,
        "appliedFilters": {
            key: value for key, value in applied.items() if key != "issueId"
        },
    }


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
