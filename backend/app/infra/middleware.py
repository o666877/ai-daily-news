"""Request ID middleware.

Reads `X-Request-Id` header (generates UUIDv4 if missing), stores in
context var, echoes in response header.
"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.infra.context import set_request_id

REQUEST_ID_HEADER = "X-Request-Id"


def _generate_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:24]}"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Populate request_id context var and echo response header."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or _generate_request_id()
        set_request_id(request_id)
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


__all__ = ["REQUEST_ID_HEADER", "RequestIdMiddleware"]
