"""FastAPI ASGI entrypoint (T018, T047).

Wires:
- Exception handlers (T012)
- Request ID middleware (T016)
- Static frontend mount
- /api/v1 routers
- Startup hook: first-install auto-trigger (FR-001b) + APScheduler init (T041)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from app import __version__
from app.api.articles import router as articles_router
from app.api.daily import router as daily_router
from app.api.healthz import router as healthz_router
from app.api.meta import router as meta_router
from app.api.settings import router as settings_router
from app.api.share import api_router as share_api_router, page_router as share_page_router
from app.config import get_settings
from app.infra.context import set_request_id
from app.infra.db import Base, get_engine, init_db
from app.infra.errors import register_exception_handlers
from app.infra.logging import configure_logging, get_logger
from app.infra.middleware import RequestIdMiddleware

logger = get_logger("aidaily.main")

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
STATIC_DIR = FRONTEND_DIR / "static"


def _print_bearer_token_if_generated() -> None:
    """If bearer_token was auto-generated, print once to stdout."""
    settings = get_settings()
    if not settings.bearer_token.strip():
        # effective_bearer_token returns _generated_token (random).
        print(
            f"[aidaily] Generated bearer token (set AIDAILY_BEARER_TOKEN to override): "
            f"{settings.effective_bearer_token}",
            flush=True,
        )


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle hook."""
    configure_logging()
    logger.info("server_starting", extra={"component": "main", "version": __version__})
    _print_bearer_token_if_generated()
    await init_db(get_engine())
    # First-install auto-trigger (FR-001b).
    await _maybe_trigger_first_issue()
    # Start scheduler (env-default cron first, then override from saved
    # settings' dailyPush so the UI-configured time/enabled wins).
    try:
        from app.infra.db import get_session_factory
        from app.infra.scheduler import (
            apply_push_schedule,
            resolve_push_schedule,
            start_scheduler,
        )

        await start_scheduler()
        factory = get_session_factory()
        async with factory() as session:
            enabled, hhmm = await resolve_push_schedule(session)
        apply_push_schedule(enabled, hhmm)
    except Exception as exc:  # scheduler is best-effort
        logger.warning(
            "scheduler_start_failed",
            extra={"exception_type": type(exc).__name__},
        )
    yield
    # Shutdown.
    try:
        from app.infra.scheduler import stop_scheduler

        await stop_scheduler()
    except Exception:
        pass


async def _maybe_trigger_first_issue() -> None:
    """If 0 issues exist in DB, schedule a background generate_issue(today)."""
    from app.infra.db import get_session_factory
    from app.models.daily_issue import DailyIssueORM

    factory = get_session_factory()
    try:
        async with factory() as session:
            count = await session.scalar(
                select(func.count(DailyIssueORM.id))
            )
            count = int(count or 0)
        if count == 0:
            logger.info(
                "first_install_trigger",
                extra={"component": "main"},
            )
            asyncio.create_task(_first_install_generate())
    except Exception as exc:
        logger.warning(
            "first_install_check_failed",
            extra={"exception_type": type(exc).__name__},
        )


async def _first_install_generate() -> None:
    """Background task: generate first issue. Failures are logged."""
    try:
        from app.pipeline.generator import generate_issue

        await generate_issue()
    except Exception as exc:
        logger.exception(
            "first_install_generate_failed",
            extra={"exception_type": type(exc).__name__},
        )


def create_app() -> FastAPI:
    """Application factory."""
    settings = get_settings()
    app = FastAPI(
        title="AI Daily News",
        version=__version__,
        description="AI 资讯聚合日报系统",
        lifespan=lifespan,
    )

    # Middleware (outermost = first in, last out).
    app.add_middleware(RequestIdMiddleware)

    # Exception handlers.
    register_exception_handlers(app)

    # API routers.
    app.include_router(daily_router)
    app.include_router(articles_router)
    app.include_router(meta_router)
    app.include_router(settings_router)
    app.include_router(healthz_router)
    app.include_router(share_api_router)
    app.include_router(share_page_router)

    # Static frontend mount.
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Root → frontend/index.html (SPA entry).
    @app.get("/", include_in_schema=False)
    async def root_index() -> FileResponse:
        idx = FRONTEND_DIR / "index.html"
        if idx.exists():
            return FileResponse(str(idx))
        return JSONResponse(
            {"message": "frontend/index.html not built yet"}, status_code=404
        )

    return app


app = create_app()


__all__ = ["app", "create_app"]
