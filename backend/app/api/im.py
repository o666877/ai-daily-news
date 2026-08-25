"""IM push endpoints (specs/006).

POST /api/v1/settings/im-push/test   — 给指定企微 webhook 发测试消息 (ticket 02)
POST /api/v1/daily/issues/{issueId}/im-push — 手动重推当期日报 (ticket 04, 未实现)

body 走 `dict` + 手动校验(同 settings PUT):slowapi 装饰器会吞掉非内建
类型注解的解析,pydantic 模型直接声明会被降级成 query 参数。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.auth import require_auth
from app.infra.db import get_session
from app.infra.errors import ValidationError as BizValidationError
from app.infra.errors import WebhookNotFoundError
from app.infra.ratelimit import write_limiter
from app.pipeline import wecom
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/api/v1", tags=["im-push"])


class ImPushTestIn(BaseModel):
    name: str


@router.post(
    "/settings/im-push/test",
    response_model=None,
    responses={
        200: {
            "description": "发送结果(ok=false 表示企微侧拒绝,非服务端错误)",
            "content": {
                "application/json": {
                    "example": {"name": "main", "ok": True, "errcode": 0, "errmsg": "ok"}
                }
            },
        },
        401: {"description": "1003 — 未认证"},
        404: {"description": "2004 — webhook 不存在"},
        422: {"description": "1005 — body 校验失败"},
    },
    summary="发送企微测试消息",
    description="按 name 查找已配置的 webhook 并发送一条测试 markdown,用于验证配置。",
)
@write_limiter.limit("30/minute")
async def send_im_push_test(
    request: Request,
    payload: dict,
    _user: dict = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Fire a test message at one stored webhook; report the wecom verdict."""
    try:
        validated = ImPushTestIn.model_validate(payload)
    except ValidationError as exc:
        msg = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        ) or "请求体校验失败"
        raise BizValidationError(msg) from exc

    im_push = await SettingsService(session).get_im_push_raw()
    webhook = next(
        (w for w in im_push.get("webhooks", []) if w.get("name") == validated.name), None
    )
    url = str(webhook.get("url", "")) if webhook else ""
    if not url:
        raise WebhookNotFoundError(f"未找到名为 {validated.name} 的可用 webhook")

    result = await wecom.send_markdown(url, wecom.render_test_markdown())
    return JSONResponse(
        content={
            "name": validated.name,
            "ok": result.ok,
            "errcode": result.errcode,
            "errmsg": result.errmsg,
        }
    )


__all__ = ["router"]
