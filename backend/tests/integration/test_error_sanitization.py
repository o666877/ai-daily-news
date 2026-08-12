"""T081 + T086: Security regression for unified error response shape.

Verifies the global exception handler never leaks:
- raw exception messages (potentially containing SQL, secrets, env var values)
- stack traces
- extra JSON fields beyond the documented {code, message, requestId} contract

Also covers all 11 business codes defined in contracts/README.md.
"""

from __future__ import annotations

import re
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.infra.errors import (
    AppException,
    ArticleNotFoundError,
    ForbiddenError,
    InternalError,
    InvalidEnumError,
    IssueGeneratingError,
    IssueNotGeneratedError,
    MissingParamError,
    PipelineBusyError,
    RateLimitError,
    UnauthorizedError,
    ValidationError,
    register_exception_handlers,
)


# A payload that simulates a leaked secret (DB connection string) which
# must NEVER appear in the HTTP response body — only the handler's safe
# generic message should be returned.
LEAKY_PAYLOAD = (
    "DB connection error: postgres://user:secret123@db.internal.example.com:5432/ai_daily"
)
SENSITIVE_SUBSTRINGS = [
    "secret123",
    "postgres://",
    "db.internal.example.com",
    "Traceback",
    'File "',
    "line ",
]


# ---------------------------------------------------------------------------
# Test app: minimal FastAPI app with only the error handlers wired + a few
# routes that trigger each business code.
# ---------------------------------------------------------------------------


@pytest.fixture
def sanitizer_app() -> FastAPI:
    """Build a minimal FastAPI app to exercise error sanitization in isolation."""
    app = FastAPI()

    @app.middleware("http")
    async def _request_id_middleware(request, call_next):
        # Mirror app.infra.middleware behaviour so error handler sees a UUID rid.
        import uuid

        from app.infra.context import set_request_id

        rid = str(uuid.uuid4())
        set_request_id(rid)
        response = await call_next(request)
        return response

    register_exception_handlers(app)

    @app.get("/boom/unhandled")
    async def boom_unhandled():
        # Simulate a programmer error with sensitive payload.
        raise Exception(LEAKY_PAYLOAD)

    @app.get("/boom/missing-param")
    async def boom_missing_param():
        raise MissingParamError()

    @app.get("/boom/invalid-enum")
    async def boom_invalid_enum():
        raise InvalidEnumError()

    @app.get("/boom/unauthorized")
    async def boom_unauthorized():
        raise UnauthorizedError()

    @app.get("/boom/forbidden")
    async def boom_forbidden():
        raise ForbiddenError()

    @app.get("/boom/validation")
    async def boom_validation():
        raise ValidationError()

    @app.get("/boom/rate-limit")
    async def boom_rate_limit():
        raise RateLimitError()

    @app.get("/boom/article-not-found")
    async def boom_article_not_found():
        raise ArticleNotFoundError()

    @app.get("/boom/issue-not-generated")
    async def boom_issue_not_generated():
        raise IssueNotGeneratedError()

    @app.get("/boom/issue-generating")
    async def boom_issue_generating():
        raise IssueGeneratingError()

    @app.get("/boom/internal")
    async def boom_internal():
        raise InternalError()

    @app.get("/boom/pipeline-busy")
    async def boom_pipeline_busy():
        raise PipelineBusyError()

    return app


@pytest.fixture
async def sanitizer_client(sanitizer_app) -> AsyncClient:
    # raise_server_exceptions=False: let Starlette run the global handler
    # instead of re-raising the exception to the test client.
    transport = ASGITransport(app=sanitizer_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# T081: unhandled exception must never leak raw message / stack / SQL / env.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unhandled_exception_response_shape(sanitizer_client: AsyncClient):
    """9001 response body has EXACTLY {code, message, requestId} — nothing else."""
    res = await sanitizer_client.get("/boom/unhandled")
    assert res.status_code == 500
    body = res.json()
    # Exact key set — no extra fields leaked.
    assert set(body.keys()) == {"code", "message", "requestId"}, body
    assert body["code"] == 9001
    # Generic safe message; never the raw exception text.
    assert body["message"] == "服务内部错误"
    # No sensitive substrings anywhere in the body.
    raw = res.text
    for needle in SENSITIVE_SUBSTRINGS:
        assert needle not in raw, f"Sensitive substring leaked: {needle!r}"


@pytest.mark.asyncio
async def test_unhandled_exception_request_id_is_uuid_string(
    sanitizer_client: AsyncClient,
):
    """requestId is a non-empty UUID-format string."""
    res = await sanitizer_client.get("/boom/unhandled")
    body = res.json()
    rid = body.get("requestId")
    assert isinstance(rid, str) and rid, "requestId must be a non-empty string"
    # Must parse as UUID.
    uuid.UUID(rid)


@pytest.mark.asyncio
async def test_unhandled_exception_content_type_is_json(sanitizer_client: AsyncClient):
    res = await sanitizer_client.get("/boom/unhandled")
    assert res.headers["content-type"].startswith("application/json")
    # Status must be 500, not 500 with HTML error page.
    assert res.status_code == 500


# ---------------------------------------------------------------------------
# T086: every business code (1001..9002) returns the same envelope, no extras.
# ---------------------------------------------------------------------------


CASES = [
    ("/boom/missing-param", 1001, 400, "缺少必填参数"),
    ("/boom/invalid-enum", 1002, 400, "枚举值非法"),
    ("/boom/unauthorized", 1003, 401, "未认证或 token 失效"),
    ("/boom/forbidden", 1004, 403, "无权限"),
    ("/boom/validation", 1005, 422, "请求体校验失败"),
    ("/boom/rate-limit", 1006, 429, "操作太频繁，稍后再试"),
    ("/boom/article-not-found", 2001, 404, "文章不存在"),
    ("/boom/issue-not-generated", 2002, 404, "今日刊尚未生成完成"),
    ("/boom/issue-generating", 2003, 409, "今日刊正在生成中"),
    ("/boom/internal", 9001, 500, "服务内部错误"),
    ("/boom/pipeline-busy", 9002, 503, "采集或摘要管线繁忙"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("path,expected_code,expected_status,expected_msg", CASES)
async def test_business_code_response_shape(
    sanitizer_client: AsyncClient,
    path: str,
    expected_code: int,
    expected_status: int,
    expected_msg: str,
):
    res = await sanitizer_client.get(path)
    assert res.status_code == expected_status, res.text
    body = res.json()
    # Exact key set.
    assert set(body.keys()) == {"code", "message", "requestId"}, body
    assert body["code"] == expected_code
    assert body["message"] == expected_msg
    # requestId present, UUID-shaped.
    rid = body["requestId"]
    assert isinstance(rid, str) and rid
    uuid.UUID(rid)


# ---------------------------------------------------------------------------
# Extra regression: 9001 specifically triggered via unhandled sensitive
# payload — no SQL fragment, no env var, no path leaks.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_9001_strips_sensitive_payload_completely(
    sanitizer_client: AsyncClient,
):
    res = await sanitizer_client.get("/boom/unhandled")
    raw = res.text
    # No fragment of the secret-bearing payload.
    assert "secret123" not in raw
    assert "postgres://" not in raw
    # No Python stack trace fragments.
    assert "Traceback" not in raw
    assert "raise " not in raw
    # No common env var patterns.
    assert re.search(r"\b[A-Z][A-Z0-9_]{2,}=[^&\s]+", raw) is None
    # No absolute file paths in the body.
    assert "/app/" not in raw and "C:\\" not in raw and "/usr/" not in raw
