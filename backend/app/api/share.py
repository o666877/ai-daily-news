"""T078 / T079: share-card endpoints.

- POST /api/v1/share           — generate card (auth + write_limiter)
- GET  /share/{shareId}        — public HTML page (no auth)

The HTML page deliberately does not use the SPA shell — it's a self-contained
minimal page that works whether or not the JS bundle is loaded, so a recipient
opening the URL from any chat client gets a clean preview.
"""

from __future__ import annotations

import html
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.auth import require_auth
from app.infra.db import get_session
from app.infra.errors import MissingParamError
from app.infra.ratelimit import write_limiter
from app.models.article import ArticleORM
from app.models.share_card import ShareCardORM, ShareCardOut
from app.services.share_service import ShareService


# Two separate routers so that the public viewer can live at the bare
# /share/{shareId} prefix (no /api/v1) while the write endpoint stays under
# the versioned API namespace.
api_router = APIRouter(prefix="/api/v1", tags=["share"])
page_router = APIRouter(tags=["share"])


def _service(session: AsyncSession = Depends(get_session)) -> ShareService:
    return ShareService(session)


_SHARE_EXAMPLE = {
    "shareId": "shr_9f2c4a71",
    "cardUrl": "http://127.0.0.1:8000/share/shr_9f2c4a71",
    "articleTitle": "LangChain 0.2 发布",
}


@api_router.post(
    "/share",
    response_model=None,
    responses={
        200: {
            "description": "Share card generated.",
            "content": {"application/json": {"example": _SHARE_EXAMPLE}},
        },
        400: {
            "description": "1001 — 缺 articleId",
            "content": {
                "application/json": {
                    "example": {"code": 1001, "message": "缺少 articleId", "requestId": "req_abc"}
                }
            },
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
    summary="生成分享卡片",
    description="「分享这条」生成可复制/可打开的卡片链接；公开页面无需鉴权。详见 `contracts/share.md`。",
)
@write_limiter.limit("30/minute")
async def post_share(
    request: Request,
    payload: dict,
    _user: dict = Depends(require_auth),
    service: ShareService = Depends(_service),
) -> JSONResponse:
    """Generate a share card for an article; returns shareId + cardUrl + title."""
    article_id = payload.get("articleId") if isinstance(payload, dict) else None
    if not article_id or not isinstance(article_id, str):
        raise MissingParamError("缺少 articleId")

    card = await service.generate(article_id)
    body = ShareCardOut(
        shareId=card.share_id,
        cardUrl=card.card_url,
        articleTitle=card.article_title,
    ).model_dump(by_alias=True, mode="json")
    return JSONResponse(content=body)


@page_router.get("/share/{share_id}")
async def get_share_page(
    share_id: str,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """Public share-card page — no auth; renders minimal HTML."""
    card = await session.get(ShareCardORM, share_id)
    if card is None:
        return HTMLResponse(
            content="<h1>卡片不存在或已失效</h1>",
            status_code=404,
        )

    article = await session.get(ArticleORM, card.article_id)
    if article is None:
        return HTMLResponse(
            content="<h1>原文章已被删除</h1>",
            status_code=404,
        )

    safe_title = html.escape(card.article_title)
    safe_source_name = html.escape(article.source_name)
    safe_source_url = html.escape(article.source_url, quote=True)
    safe_excerpt = html.escape(article.excerpt)
    created = (card.created_at or datetime.utcnow()).strftime("%Y-%m-%d %H:%M UTC")

    body = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta property="og:title" content="{safe_title}" />
<meta property="og:description" content="{safe_excerpt}" />
<meta property="og:type" content="article" />
<title>{safe_title} · AI 日报分享</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
          "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
          margin: 0; padding: 2rem 1.5rem; max-width: 640px; margin: 0 auto;
          background: #fafafa; color: #1a1a1a; }}
  h1 {{ font-size: 1.75rem; line-height: 1.3; margin: 0 0 1rem; }}
  .meta {{ color: #666; font-size: 0.875rem; margin-bottom: 1.5rem; }}
  .excerpt {{ background: #fff; padding: 1rem 1.25rem; border-radius: 8px;
              border: 1px solid #eaeaea; margin-bottom: 1.5rem; }}
  a.button {{ display: inline-block; padding: 0.625rem 1.5rem; background: #1f6feb;
              color: #fff; border-radius: 6px; text-decoration: none; font-weight: 500; }}
  a.button:hover {{ background: #1a5fc9; }}
  .footer {{ margin-top: 2rem; color: #888; font-size: 0.75rem; }}
</style>
</head>
<body>
  <h1>{safe_title}</h1>
  <p class="meta">{safe_source_name} · 分享于 {created}</p>
  <div class="excerpt">{safe_excerpt}</div>
  <a class="button" href="{safe_source_url}" target="_blank" rel="noopener noreferrer">阅读原文</a>
  <p class="footer">本卡片由 AI 日报系统生成 · {html.escape(share_id)}</p>
</body>
</html>
"""
    return HTMLResponse(content=body)


__all__ = ["api_router", "page_router"]
