"""Reddit opencli bridge — logged-in browser session via `opencli` CLI.

Reddit 403s the `.json` API for anonymous clients on most proxy/datacenter
IPs (verified 2026-08-17: rdt-cli with valid cookies still blocked by exit
IP). The opencli browser bridge routes requests through the user's real
logged-in Chrome session, which passes. It also exposes score / comment
count / full selftext — metadata the anonymous Atom feed cannot provide.

This module is a pure bridge adapter: it shells out to
`opencli reddit subreddit <sub> --sort top --time week -f json`, parses the
JSON array, and builds RawItems. It knows nothing about the Atom fallback —
reddit.py owns the channel dispatch.

Execution model: strictly serial per subreddit. Browser tab leases are a
shared resource in one Chrome instance; concurrent commands contend for the
same lease and reproduce the "extension not always connected" flakiness
that killed the T036 attempt.

Known opencli adapter limitation (verified 2026-08-18): the `subreddit`
command returns `score: null` (only `comments` carries engagement signal),
while the `hot` command returns real scores but no `created_utc`. We use
`subreddit` because the 72h freshness filter depends on timestamps; a
missing score is only lost extra metadata, not lost filtering.

Per-sub failures (non-zero exit, JSON parse errors, timeouts, spawn
errors) are logged and skipped (FR-007a); the caller decides whether an
all-subs-empty result warrants falling back to the Atom feed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

from app.models.article import RawItem
from app.models.meta import SourceKey

logger = logging.getLogger("aidaily.collector.reddit.opencli")

PER_SUB_LIMIT: int = 10          # posts requested per subreddit
SUBPROCESS_TIMEOUT_S: float = 45.0  # browser navigation is slower than HTTP
RAW_TEXT_CAP: int = 4000         # keep summarizer input bounded
FRESH_WINDOW_HOURS: float = 72.0  # aligned with the Atom path's window

# Preflight self-heal: when the bridge is down (Chrome closed at the 08:00
# unattended run), each sub command would burn its full 45s timeout before
# reporting BROWSER_CONNECT — ~4 wasted minutes for 5 subs. Instead: probe
# connectivity (~1s), launch Chrome on Windows, reprobe within a ~15s budget,
# and yield to the Atom fallback immediately when rescue fails.
_DOCTOR_TIMEOUT_S: float = 10.0
_PREFLIGHT_RETRY_DELAYS: tuple[float, ...] = (8.0, 7.0)

_DISABLE_ENV = "AIDAILY_REDDIT_DISABLE_OPENCLI"
_BIN_ENV = "AIDAILY_OPENCLI_BIN"


def _resolve_bin() -> str:
    """Locate the opencli executable: env override → PATH probe.

    On Windows, npm installs three files: `opencli` (sh script, not a PE
    image — create_subprocess_exec cannot run it), `opencli.CMD`, and
    `opencli.ps1`. shutil.which("opencli") may return the sh script first,
    so probe the Windows-executable spellings before the bare name.
    """
    env_path = os.environ.get(_BIN_ENV, "").strip()
    if env_path and os.path.isfile(env_path):
        return env_path
    if sys.platform == "win32":
        for candidate in ("opencli.CMD", "opencli.exe", "opencli.cmd"):
            found = shutil.which(candidate)
            if found:
                return found
    return shutil.which("opencli") or ""


def opencli_available() -> bool:
    """True when the opencli binary is present and not disabled via env.

    Intentionally a pure PATH probe — no subprocess. A down daemon fails
    fast per-sub (bridge connection refused, well under the 45s timeout),
    so an all-subs-empty result reaches the Atom fallback quickly without
    a separate daemon-status round trip.
    """
    if os.environ.get(_DISABLE_ENV, "").strip().lower() in {"1", "true", "yes"}:
        return False
    return bool(_resolve_bin())


def _build_argv(bin_path: str, sub_name: str) -> list[str]:
    return [
        bin_path,
        "reddit", "subreddit", sub_name,
        "--sort", "top",
        "--time", "week",
        "--limit", str(PER_SUB_LIMIT),
        "-f", "json",
        "--window", "background",
    ]


async def collect_via_opencli(subs: list[str]) -> list[RawItem]:
    """Fetch top-of-week posts for each sub serially via the browser bridge.

    Returns a flat list across subs; per-sub failures are logged and skipped.
    A failed preflight self-heal returns [] — the dispatcher falls back to
    the Atom feed.
    """
    bin_path = _resolve_bin()
    if not bin_path:
        logger.warning(
            "reddit_opencli_no_binary",
            extra={"source": SourceKey.REDDIT.value},
        )
        return []

    if not await _ensure_bridge(bin_path):
        return []

    items: list[RawItem] = []
    for sub_name in subs:
        try:
            items.extend(await _fetch_one_sub(bin_path, sub_name))
        except Exception as exc:  # noqa: BLE001 — FR-007a per-sub isolation
            logger.warning(
                "reddit_opencli_sub_failed",
                extra={
                    "source": SourceKey.REDDIT.value,
                    "subreddit": sub_name,
                    "exception_type": type(exc).__name__,
                },
            )
    return items


async def _ensure_bridge(bin_path: str) -> bool:
    """Preflight: probe connectivity, attempt to rescue, reprobe.

    Outcomes logged as bridge_preflight: ok / launched / no_desktop /
    launch_failed. Returns True when the bridge is usable.
    """
    if await _bridge_reachable(bin_path):
        logger.info(
            "bridge_preflight",
            extra={"source": SourceKey.REDDIT.value, "outcome": "ok"},
        )
        return True

    if sys.platform != "win32":
        logger.warning(
            "bridge_preflight",
            extra={"source": SourceKey.REDDIT.value, "outcome": "no_desktop"},
        )
        return False

    _launch_chrome()
    for delay in _PREFLIGHT_RETRY_DELAYS:
        await asyncio.sleep(delay)
        if await _bridge_reachable(bin_path):
            logger.info(
                "bridge_preflight",
                extra={"source": SourceKey.REDDIT.value, "outcome": "launched"},
            )
            return True
    logger.warning(
        "bridge_preflight",
        extra={"source": SourceKey.REDDIT.value, "outcome": "launch_failed"},
    )
    return False


async def _bridge_reachable(bin_path: str) -> bool:
    """Run `opencli doctor` and check the connectivity line."""
    try:
        proc = await asyncio.create_subprocess_exec(
            bin_path, "doctor",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, _stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=_DOCTOR_TIMEOUT_S
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return False
    except (OSError, ValueError):
        return False
    out = stdout_b.decode("utf-8", errors="replace") if stdout_b else ""
    return "[OK] Connectivity" in out


def _launch_chrome() -> None:
    """Fire-and-forget Chrome start on Windows; harmless failure elsewhere.

    Called only on win32 — `cmd /c start chrome` resolves Chrome via App
    Paths. Failure is expected on headless Windows (server core) and logged.
    """
    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "", "chrome"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        logger.warning(
            "bridge_chrome_launch_failed",
            extra={"source": SourceKey.REDDIT.value, "exception_type": type(exc).__name__},
        )


async def _fetch_one_sub(bin_path: str, sub_name: str) -> list[RawItem]:
    """Run one opencli subreddit command; parse stdout into RawItems."""
    argv = _build_argv(bin_path, sub_name)
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, _stderr_b = await asyncio.wait_for(
            proc.communicate(), timeout=SUBPROCESS_TIMEOUT_S
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise

    if proc.returncode != 0:
        raise RuntimeError(f"opencli exit {proc.returncode}")

    stdout = stdout_b.decode("utf-8", errors="replace") if stdout_b else ""
    posts = _parse_stdout(stdout)

    now = datetime.now(tz=timezone.utc)
    items: list[RawItem] = []
    for post in posts:
        item = _build_item(sub_name, post, now)
        if item is not None:
            items.append(item)
    return items


def _parse_stdout(stdout: str) -> list[dict[str, Any]]:
    """opencli -f json emits a plain JSON array of post objects."""
    text = stdout.strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"opencli non-JSON stdout: {exc}") from exc
    if not isinstance(data, list):
        raise RuntimeError("opencli stdout is not a JSON array")
    return [p for p in data if isinstance(p, dict)]


def _build_item(
    sub_name: str,
    post: dict[str, Any],
    now: datetime,
) -> RawItem | None:
    """Convert one opencli post dict to a RawItem.

    Returns None when title/url is missing or the post is older than
    FRESH_WINDOW_HOURS. created_utc is unix seconds; posts without a
    parseable timestamp are kept (same policy as the Atom path).
    """
    title = str(post.get("title") or "").strip()
    if not title:
        return None
    url = str(post.get("url") or "").strip()
    if not url:
        return None

    published_at, age_h = _extract_time(post, now)
    if age_h is not None and age_h > FRESH_WINDOW_HOURS:
        return None
    if not published_at:
        published_at = now.isoformat()

    raw_text = str(post.get("selftext") or "").strip() or title
    raw_text = raw_text[:RAW_TEXT_CAP]

    post_id = str(post.get("id") or "").strip()
    extra: dict[str, Any] = {"subreddit": sub_name}
    if post_id:
        extra["post_id"] = post_id
    score = post.get("score")
    if isinstance(score, int):
        extra["score"] = score
    num_comments = post.get("comments")
    if isinstance(num_comments, int):
        extra["num_comments"] = num_comments
    post_hint = str(post.get("post_hint") or "").strip()
    if post_hint:
        extra["post_hint"] = post_hint
    if age_h is not None:
        extra["age_h"] = round(age_h, 1)

    return RawItem(
        sourceKey=SourceKey.REDDIT,
        sourceName=f"reddit.com/r/{sub_name}",
        sourceUrl=url,
        title=title,
        rawText=raw_text,
        publishedAt=published_at,
        extra=extra,
    )


def _extract_time(post: dict[str, Any], now: datetime) -> tuple[str, float | None]:
    """Return (iso_published, age_hours) from unix-seconds created_utc."""
    created = post.get("created_utc")
    if not isinstance(created, (int, float)) or isinstance(created, bool):
        return "", None
    try:
        dt = datetime.fromtimestamp(float(created), tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return "", None
    iso = dt.isoformat()
    age_h = (now - dt).total_seconds() / 3600.0
    return iso, age_h


__all__ = ["collect_via_opencli", "opencli_available"]
