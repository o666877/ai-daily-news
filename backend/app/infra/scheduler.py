"""APScheduler integration (T041).

- SQLite jobstore (shares app's data.db).
- Cron at AIDAILY_DAILY_PUSH_TIME (HH:mm Asia/Shanghai).
- misfire_grace_time for restart-tolerance.
- expose run_once(date) for dev/debug.
"""

from __future__ import annotations

import asyncio
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


def schedule_daily_generate() -> None:
    """Register the daily cron job for issue generation."""
    sched = get_scheduler()
    settings = get_settings()
    hour, minute = _parse_hhmm(settings.daily_push_time)
    trigger = CronTrigger(hour=hour, minute=minute, timezone=settings.tz)

    job_id = "daily_generate"

    # Remove old job if exists (idempotent reconfigure).
    existing = sched.get_job(job_id)
    if existing is not None:
        sched.remove_job(job_id)

    sched.add_job(
        _run_generate_job,
        trigger=trigger,
        job_id=job_id,
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )


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
    "get_scheduler",
    "run_once",
    "schedule_daily_generate",
    "start_scheduler",
    "stop_scheduler",
]
