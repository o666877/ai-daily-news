"""APScheduler integration (T041).

- SQLite jobstore (shares app's data.db).
- Cron at AIDAILY_DAILY_PUSH_TIME (HH:mm Asia/Shanghai).
- misfire_grace_time for restart-tolerance.
- expose run_once(date) for dev/debug.
"""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession
import logging
from datetime import datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from app.config import get_settings

logger = logging.getLogger("aidaily.scheduler")

_scheduler: AsyncIOScheduler | None = None


def _parse_hhmm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler  # noqa: PLW0603
    if _scheduler is None:
        settings = get_settings()
        _scheduler = AsyncIOScheduler(timezone=settings.tz)
    return _scheduler


def schedule_daily_generate(hhmm: str | None = None, *, enabled: bool = True) -> None:
    """Register the daily cron job; enabled=False removes it instead.

    `hhmm` comes from the saved settings row's dailyPush.time; None falls
    back to the AIDAILY_DAILY_PUSH_TIME env default (startup before any
    settings row exists).
    """
    sched = get_scheduler()
    settings = get_settings()
    job_id = "daily_generate"

    # Remove old job if exists (idempotent reconfigure / disable path).
    existing = sched.get_job(job_id)
    if existing is not None:
        sched.remove_job(job_id)
    if not enabled:
        return

    hour, minute = _parse_hhmm(hhmm or settings.daily_push_time)
    trigger = CronTrigger(hour=hour, minute=minute, timezone=settings.tz)
    sched.add_job(
        _run_generate_job,
        trigger=trigger,
        id=job_id,
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )


def apply_push_schedule(enabled: bool, hhmm: str) -> None:
    """Re-apply the daily job from saved settings.

    No-op unless the scheduler is running: tests boot the app with a noop
    lifespan, and registering jobs on a stopped scheduler would leak state
    across test cases.
    """
    sched = get_scheduler()
    if not sched.running:
        return
    schedule_daily_generate(hhmm, enabled=enabled)


async def resolve_push_schedule(session: AsyncSession) -> tuple[bool, str]:
    """(enabled, time) from the settings row; env defaults when no row.

    Missing daily_push keys tolerate legacy rows: enabled defaults True,
    time falls back to the env default.
    """
    from sqlalchemy import select

    from app.models.settings import SettingsORM

    settings = get_settings()
    result = await session.execute(
        select(SettingsORM).where(SettingsORM.id == 1)
    )
    orm = result.scalar_one_or_none()
    if orm is None:
        return True, settings.daily_push_time
    dp = dict(orm.daily_push or {})
    enabled = bool(dp.get("enabled", True))
    hhmm = str(dp.get("time") or settings.daily_push_time)
    return enabled, hhmm


async def _run_generate_job() -> None:
    """Job entrypoint: invoke generator, swallow and log exceptions."""
    try:
        from app.pipeline.generator import generate_issue

        await generate_issue()
    except Exception as exc:
        logger.exception(
            "scheduler_job_failed",
            extra={"exception_type": type(exc).__name__},
        )


async def start_scheduler() -> None:
    sched = get_scheduler()
    if not sched.running:
        sched.start()
        schedule_daily_generate()


async def stop_scheduler() -> None:
    sched = get_scheduler()
    if sched.running:
        sched.shutdown(wait=False)


def run_once(date: datetime | None = None) -> Any:
    """Dev/debug helper: trigger an immediate generation (returns awaitable)."""
    from app.pipeline.generator import generate_issue

    return generate_issue(date)


__all__ = [
    "apply_push_schedule",
    "get_scheduler",
    "resolve_push_schedule",
    "run_once",
    "schedule_daily_generate",
    "start_scheduler",
    "stop_scheduler",
]
