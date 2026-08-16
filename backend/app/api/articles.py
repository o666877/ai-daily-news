"""Article detail and filtered list endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.infra.db import get_session
from app.infra.errors import ArticleNotFoundError, InvalidEnumError
from app.infra.pagination import PageParams, parse_page_params
from app.infra.ratelimit import read_limiter
from app.models import Article, ArticleORM, SourceKey, TypeKey
from app.services.article_service import list_articles
from app.services.issue_service import is_must_read

router = APIRouter(prefix="/api/v1", tags=["articles"])


_LIST_EXAMPLE = {
    "items": [
        {
            "id": "20260812-0003",
            "title": "LangChain 0.2 发布",
            "excerpt": "摘要…",
            "type": "agent",
            "src": "reddit",
            "time": "10:42",
            "readingMinutes": 5,
        }
    ],
    "page": 1,
    "pageSize": 20,
    "total": 4,
    "appliedFilters": {"type": "agent", "src": "reddit"},
}

_DETAIL_EXAMPLE = {
    "id": "20260812-0003",
    "issueId": "20260812",
    "type": "agent",
    "src": "reddit",
    "title": "LangChain 0.2 发布",
    "excerpt": "一句话摘要…",
    "lede": "导语段落…",
    "summary": "总结…",
    "body": "**正文段一**，关键术语加粗。\n\n正文段二提到 `pip install x`，详见 [文档](https://example.com/docs)。",
    "quote": "可空引用块",
    "points": ["要点 1", "要点 2", "要点 3"],
    "time": "10:42",
    "sourceUrl": "https://www.reddit.com/r/MachineLearning/comments/...",
    "sourceName": "reddit.com/r/MachineLearning",
    "readingMinutes": 5,
    "publishedAt": "2026-08-12T09:30:00+08:00",
}


@router.get(
    "/articles",
    response_model=None,
    responses={
        200: {
            "description": "Filtered + paginated articles list.",
            "content": {"application/json": {"example": _LIST_EXAMPLE}},
        },
        400: {
            "description": "1002 — 非法枚举值",
            "content": {
                "application/json": {
                    "example": {"code": 1002, "message": "枚举值非法", "requestId": "req_abc"}
                }
            },
        },
        422: {
            "description": "1005 — 分页参数越界",
            "content": {
                "application/json": {
                    "example": {"code": 1005, "message": "page 必须 ≥ 1", "requestId": "req_abc"}
                }
            },
        },
    },
    summary="条目列表（筛选 + 分页）",
    description="类型/来源双维 AND 筛选 + 分页。详见 `contracts/articles-list.md`。",
)
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


@router.get(
    "/articles/{article_id}",
    response_model=None,
    responses={
        200: {
            "description": "Full Article for detail view.",
            "content": {"application/json": {"example": _DETAIL_EXAMPLE}},
        },
        404: {
            "description": "2001 — 文章不存在",
            "content": {
                "application/json": {
                    "example": {"code": 2001, "message": "文章不存在", "requestId": "req_abc"}
                }
            },
        },
    },
    summary="条目详情",
    description="阅读器正文渲染所需全部字段。详见 `contracts/articles-detail.md`。",
)
async def get_article_detail(
    article_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return full Article for given id; 404 2001 if not found.

    US1: includes score sub-object (compositeScore + dimensionScores +
    authorityTier + scoreSource + topicId + opinionFingerprint). Null-safe
    — legacy rows without a score return score=null.
    """
    # Use selectinload to fetch score without greenlet issues.
    stmt = (
        select(ArticleORM)
        .where(ArticleORM.id == article_id)
        .options(selectinload(ArticleORM.score))
    )
    result = await session.execute(stmt)
    orm = result.scalar_one_or_none()
    if orm is None:
        raise ArticleNotFoundError(f"文章不存在: {article_id}")

    score_obj = None
    if orm.score is not None:
        score_obj = {
            "compositeScore": orm.score.composite_score,
            "dimensionScores": {
                "authority": orm.score.dim_authority,
                "depth": orm.score.dim_depth,
                "timeliness": orm.score.dim_timeliness,
                "expression": orm.score.dim_expression,
                "engagement": orm.score.dim_engagement,
            },
            "authorityTier": orm.score.authority_tier,
            "scoreSource": orm.score.score_source,
            "topicId": orm.score.topic_id,
            "opinionFingerprint": orm.score.opinion_fingerprint,
        }

    article = Article(
        id=orm.id,
        title=orm.title,
        excerpt=orm.excerpt,
        type=TypeKey(orm.type),
        src=SourceKey(orm.src),
        time=orm.time,
        readingMinutes=orm.reading_minutes,
        compositeScore=orm.score.composite_score if orm.score else None,
        issueId=orm.issue_id,
        lede=orm.lede,
        summary=orm.summary,
        body=orm.body,
        quote=orm.quote,
        points=orm.points,
        sourceUrl=orm.source_url,
        sourceName=orm.source_name,
        publishedAt=orm.published_at,
        score=score_obj,
        mustRead=is_must_read(orm.id),
    )
    return article.model_dump(by_alias=True, mode="json")


__all__ = ["router"]
