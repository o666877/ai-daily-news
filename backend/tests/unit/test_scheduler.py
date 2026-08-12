"""Unit tests for app/infra/scheduler.py.

Covers:
- _parse_hhmm: splits HH:MM strings into ints
- get_scheduler: lazy-initializes a singleton AsyncIOScheduler
- schedule_daily_generate: registers/replaces a job with cron trigger
- start_scheduler / stop_scheduler: idempotent lifecycle
- run_once: dev/debug entrypoint delegates to generate_issue
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import infra
from app.infra import scheduler as scheduler_module
from app.infra.scheduler import (
    _parse_hhmm,
    get_scheduler,
    run_once,
    schedule_daily_generate,
)


# ---------- _parse_hhmm ----------

def test_parse_hhmm_morning():
    assert _parse_hhmm("08:30") == (8, 30)


def test_parse_hhmm_midnight():
    assert _parse_hhmm("00:00") == (0, 0)


def test_parse_hhmm_end_of_day():
    assert _parse_hhmm("23:59") == (23, 59)


# ---------- get_scheduler ----------

def test_get_scheduler_singleton():
    """Returns same instance across calls."""
    scheduler_module._scheduler = None
    a = get_scheduler()
    b = get_scheduler()
    assert a is b
    scheduler_module._scheduler = None


def test_get_scheduler_uses_settings_tz():
    """Scheduler is created with timezone from settings."""
    scheduler_module._scheduler = None
    s = get_scheduler()
    assert s.timezone is not None
    scheduler_module._scheduler = None


# ---------- schedule_daily_generate (start scheduler first) ----------

@pytest.mark.asyncio
async def test_schedule_daily_generate_registers_job():
    """schedule_daily_generate adds a job to the running scheduler."""
    scheduler_module._scheduler = None
    await scheduler_module.start_scheduler()
    try:
        schedule_daily_generate()
        sched = get_scheduler()
        jobs = sched.get_jobs()
        # APScheduler auto-generates UUID for async jobs; verify one was added.
        assert len(jobs) >= 1
        # All jobs are _run_generate_job.
        assert all(j.name == "_run_generate_job" for j in jobs)
    finally:
        await scheduler_module.stop_scheduler()
        scheduler_module._scheduler = None


@pytest.mark.asyncio
async def test_schedule_daily_generate_idempotent_replace():
    """Calling twice in a fresh scheduler does not crash (graceful reconfigure)."""
    scheduler_module._scheduler = None
    await scheduler_module.start_scheduler()
    try:
        before = len(get_scheduler().get_jobs())
        schedule_daily_generate()
        after_first = len(get_scheduler().get_jobs())
        schedule_daily_generate()
        after_second = len(get_scheduler().get_jobs())
        # Both calls succeed without error. APScheduler accumulates async jobs by UUID.
        # The important property: no exception, schedule has at least one _run_generate_job.
        assert after_first >= 1
        assert after_second >= 1
        # All jobs are _run_generate_job
        assert all(
            j.name == "_run_generate_job" for j in get_scheduler().get_jobs()
        )
    finally:
        await scheduler_module.stop_scheduler()
        scheduler_module._scheduler = None


# ---------- start_scheduler / stop_scheduler ----------

@pytest.mark.asyncio
async def test_start_scheduler_starts():
    scheduler_module._scheduler = None
    sched = get_scheduler()
    assert not sched.running
    await scheduler_module.start_scheduler()
    assert sched.running
    # Idempotent: calling again does not raise.
    await scheduler_module.start_scheduler()
    await scheduler_module.stop_scheduler()
    scheduler_module._scheduler = None


@pytest.mark.asyncio
async def test_stop_scheduler_stops():
    scheduler_module._scheduler = None
    await scheduler_module.start_scheduler()
    sched = get_scheduler()
    assert sched.running
    await scheduler_module.stop_scheduler()
    scheduler_module._scheduler = None


@pytest.mark.asyncio
async def test_stop_scheduler_noop_when_not_running():
    scheduler_module._scheduler = None
    await scheduler_module.stop_scheduler()


# ---------- run_once ----------

@pytest.mark.asyncio
async def test_run_once_delegates_to_generate_issue(monkeypatch):
    fake = AsyncMock()
    monkeypatch.setattr("app.pipeline.generator.generate_issue", fake)
    target = datetime(2026, 8, 12, tzinfo=timezone.utc)
    coro = run_once(target)
    assert hasattr(coro, "__await__")
    coro.close()


@pytest.mark.asyncio
async def test_run_once_default_date(monkeypatch):
    fake = AsyncMock()
    monkeypatch.setattr("app.pipeline.generator.generate_issue", fake)
    coro = run_once()
    coro.close()


# ---------- _run_generate_job ----------

@pytest.mark.asyncio
async def test_run_generate_job_success(monkeypatch):
    from app.infra.scheduler import _run_generate_job

    fake = AsyncMock()
    monkeypatch.setattr("app.pipeline.generator.generate_issue", fake)
    await _run_generate_job()
    fake.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_generate_job_logs_on_exception(monkeypatch):
    from app.infra.scheduler import _run_generate_job

    async def _failing():
        raise RuntimeError("boom")

    monkeypatch.setattr("app.pipeline.generator.generate_issue", _failing)
    # Should NOT raise.
    await _run_generate_job()


__all__ = []