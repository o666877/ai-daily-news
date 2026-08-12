"""End-to-end fixtures: spawn backend uvicorn and expose a Playwright page."""

from __future__ import annotations

import socket
import threading
import time
import urllib.request
from collections.abc import Iterator

import pytest
import uvicorn
from playwright.sync_api import sync_playwright


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _wait_ready(url: str, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:  # noqa: S310
                if resp.status < 500:
                    return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("server not ready")


@pytest.fixture(scope="session")
def base_url(tmp_path_factory) -> Iterator[str]:
    import os
    import subprocess
    import sys
    from pathlib import Path

    db_path = tmp_path_factory.mktemp("data") / "e2e.db"
    port = _free_port()
    env = {
        **os.environ,
        "AIDAILY_DB_PATH": str(db_path),
        "AIDAILY_BEARER_TOKEN": "test-bearer-token",
        "AIDAILY_LLM_API_KEY": "test-key",
        "AIDAILY_LLM_BASE_URL": "https://api.example.com",
        "AIDAILY_LLM_MODEL": "claude-test-model",
        "AIDAILY_TZ": "UTC",
        "AIDAILY_DAILY_PUSH_TIME": "08:00",
    }
    script = (
        "import asyncio, sys\n"
        "from datetime import datetime, timezone\n"
        "from app import models  # noqa\n"
        "from app.config import reset_settings_cache\n"
        "from app.infra import db as db_module\n"
        "from app.infra.db import init_db\n"
        "from app.models.article import ArticleORM\n"
        "from app.models.daily_issue import DailyIssueORM\n"
        "async def seed():\n"
        "    db_module._engine = None\n"
        "    db_module._session_factory = None\n"
        "    engine = db_module.make_engine(sys.argv[1])\n"
        "    await init_db(engine)\n"
        "    factory = db_module.get_session_factory()\n"
        "    async with factory() as session:\n"
        "        session.add(DailyIssueORM(id='20260812', date='2026-08-12', edition=1, status='ready', generated_at=datetime(2026,8,12,8,0,tzinfo=timezone.utc), filters_applied={'sources':['x','github','reddit','web'],'types':['agent','self_improve','open_source','tools']}))\n"
        "        session.add(ArticleORM(id='20260812-0001', issue_id='20260812', type='agent', src='reddit', title='Reddit Agent Post', excerpt='Reddit agent excerpt', lede='Reddit lede', summary='Reddit one-liner', body=['Body para 1','Body para 2'], quote=None, points=['Point 1','Point 2'], time='09:00', source_url='https://reddit.com/r/example/1', source_name='reddit.com/r/MachineLearning', reading_minutes=4, published_at='2026-08-12T09:00:00+00:00'))\n"
        "        await session.commit()\n"
        "    await engine.dispose()\n"
        "asyncio.run(seed())\n"
    )
    subprocess.run([sys.executable, "-c", script, str(db_path)], env=env, check=True, cwd=Path(__file__).resolve().parents[2])

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        env=env,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    try:
        _wait_ready(f"http://127.0.0.1:{port}/api/v1/healthz")
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        proc.wait(timeout=5)


@pytest.fixture()
def page(base_url: str):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        page = context.new_page()
        yield page
        context.close()
        browser.close()
