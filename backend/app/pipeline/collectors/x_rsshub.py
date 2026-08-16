"""X (Twitter) collector via `twitter-cli` subprocess (replaces RSSHub).

Iterates AIDAILY_X_ACCOUNTS (or default KOL list) and shells out to
`twitter user-posts <account> -n N --json` concurrently via asyncio.

Auth strategy (T0xx fix for X=0):
  - twitter-cli resolves cookies itself, in this order:
      1. TWITTER_AUTH_TOKEN + TWITTER_CT0 env vars (if both set)
      2. browser cookie DB (Chrome/Arc/Edge/Firefox/Brave) via DPAPI
  - This module only short-circuits to [] when BOTH env vars are missing
    AND `AIDAILY_X_ALLOW_BROWSER_COOKIES` is not truthy. Set the latter
    to "1"/"true" in dev/desktop environments where the user is already
    logged into x.com in their browser.
  - Per-account failures (non-zero exit, JSON parse error, timeout) are
    retried once with backoff, then logged at ERROR and skipped (FR-007a).

Public function name `collect_x_rsshub` preserved so collector.py
orchestrator import is unchanged.

Note: settings.x_rsshub_base_url is intentionally ignored by this module
(kept in config.py for backwards compatibility).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import sys
from datetime import datetime, timezone

from app.config import get_settings
from app.models.article import RawItem
from app.models.meta import SourceKey
from app.pipeline.defaults.x_accounts import get_accounts

logger = logging.getLogger("aidaily.collector.x")

_PER_TWEET_LIMIT = 20
_SUBPROCESS_TIMEOUT_S = 30
_TEXT_MAX = 4000
_TITLE_MAX = 80
_MAX_ATTEMPTS = 2  # 1 initial + 1 retry
_STDERR_HEAD_CHARS = 200  # truncate stderr preview to avoid log bloat


def _retry_backoff_s() -> float:
    """Backoff between attempts. Overridable via AIDAILY_X_RETRY_BACKOFF_S."""
    raw = os.environ.get("AIDAILY_X_RETRY_BACKOFF_S", "").strip()
    try:
        return float(raw) if raw else 0.5
    except ValueError:
        return 0.5


def _resolve_twitter_bin() -> str:
    """Locate the twitter-cli executable.

    Order: AIDAILY_TWITTER_BIN env var → shutil.which("twitter") →
    Windows per-user Python Scripts dir (where pip --user installs it).
    Returns the path, or empty string if not found.
    """
    env_path = os.environ.get("AIDAILY_TWITTER_BIN", "").strip()
    if env_path and os.path.isfile(env_path):
        return env_path

    on_path = shutil.which("twitter") or shutil.which("twitter.exe")
    if on_path:
        return on_path

    if sys.platform == "win32":
        # pip install --user puts scripts under %APPDATA%/Python/PythonXY/Scripts
        appdata = os.environ.get("APPDATA", "")
        ver = f"Python{sys.version_info.major}{sys.version_info.minor}"
        candidate = os.path.join(appdata, "Python", ver, "Scripts", "twitter.exe")
        if os.path.isfile(candidate):
            return candidate

    return ""


async def collect_x_rsshub() -> list[RawItem]:
    """Fetch recent tweets for each configured X account via twitter-cli.

    Returns a flat list of RawItems across all accounts. Per-account failures
    are logged at ERROR and skipped (FR-007a).

    Auth gate: returns [] only when env cookies are missing AND
    AIDAILY_X_ALLOW_BROWSER_COOKIES is not truthy. Otherwise defers to
    twitter-cli, which falls back to the browser cookie DB.
    """
    if _should_skip_for_missing_cookies():
        logger.warning(
            "x_twitter_cli_skipped_missing_cookies",
            extra={
                "source": SourceKey.X.value,
                "hint": (
                    "set TWITTER_AUTH_TOKEN+TWITTER_CT0, or "
                    "AIDAILY_X_ALLOW_BROWSER_COOKIES=1 to use browser cookies"
                ),
            },
        )
        return []

    settings = get_settings()
    accounts = get_accounts(settings.x_accounts)

    tasks = [_fetch_account(a) for a in accounts]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    items: list[RawItem] = []
    for account, result in zip(accounts, results, strict=False):
        if isinstance(result, Exception):
            logger.error(
                "x_account_failed",
                extra={
                    "source": SourceKey.X.value,
                    "account": account,
                    "exception_type": type(result).__name__,
                    "exception_msg": str(result)[:200],
                },
            )
            continue
        items.extend(result)
    return items


def _should_skip_for_missing_cookies() -> bool:
    """True only when env cookies are absent AND browser-cookie fallback is off.

    AIDAILY_X_ALLOW_BROWSER_COOKIES truthy values: "1", "true", "yes", "on".
    """
    if _env("TWITTER_AUTH_TOKEN") and _env("TWITTER_CT0"):
        return False
    return _env("AIDAILY_X_ALLOW_BROWSER_COOKIES").lower() not in {
        "1", "true", "yes", "on"
    }


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


async def _fetch_account(account: str) -> list[RawItem]:
    """Spawn twitter-cli for one account, parse its JSON envelope.

    Retries once on transient failure (timeout / non-zero exit / error
    envelope) with a short backoff. Deterministic JSON parse errors are
    not retried.
    """
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            stdout = await _run_twitter_cli(account)
            return _tweets_to_raw_items(account, _parse_envelope(stdout))
        except (TimeoutError, RuntimeError) as exc:
            last_exc = exc
            if attempt < _MAX_ATTEMPTS:
                await asyncio.sleep(_retry_backoff_s() * attempt)
                continue
            break
        except Exception as exc:
            # ValueError (JSON) and others — do not retry.
            last_exc = exc
            break
    assert last_exc is not None  # loop only exits via break or return
    raise last_exc


async def _run_twitter_cli(account: str) -> str:
    """Spawn `twitter user-posts <account> -n N --json` with a timeout.

    Captures stderr to surface a concise failure reason to logs. Raises
    RuntimeError on non-zero exit or on an `{"ok": false}` envelope
    (e.g. not_authenticated); TimeoutError on timeout.
    """
    twitter_bin = _resolve_twitter_bin()
    if not twitter_bin:
        raise RuntimeError(
            "twitter-cli binary not found; set AIDAILY_TWITTER_BIN or install via "
            "`pip install --user twitter-cli`"
        )
    cmd = [twitter_bin, "user-posts", account, "-n", str(_PER_TWEET_LIMIT), "--json"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"twitter binary not executable: {twitter_bin}") from exc

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=_SUBPROCESS_TIMEOUT_S
        )
    except asyncio.TimeoutError as exc:
        if proc.returncode is None:
            proc.kill()
            with contextlib.suppress(Exception):
                await proc.wait()
        raise TimeoutError(
            f"twitter user-posts {account} timed out after {_SUBPROCESS_TIMEOUT_S}s"
        ) from exc

    stdout_text = stdout_bytes.decode("utf-8", errors="replace")

    if proc.returncode != 0:
        stderr_preview = (stderr_bytes or b"").decode("utf-8", errors="replace")[
            :_STDERR_HEAD_CHARS
        ]
        raise RuntimeError(
            f"twitter user-posts {account} exited with code {proc.returncode}"
            + (f"; stderr={stderr_preview!r}" if stderr_preview.strip() else "")
        )

    # twitter-cli exits 0 even for auth errors, emitting `{"ok": false, ...}`.
    # Surface that as RuntimeError so retry kicks in and the orchestrator log
    # carries the real reason (e.g. not_authenticated).
    _raise_on_error_envelope(account, stdout_text)
    return stdout_text


def _raise_on_error_envelope(account: str, stdout_text: str) -> None:
    """Raise RuntimeError if twitter-cli emitted `{"ok": false, ...}`.

    Silent no-op on success envelopes or non-JSON output. Avoids forcing a
    hard JSON dependency on the happy path — malformed JSON is handled by
    `_parse_envelope` upstream.
    """
    stripped = stdout_text.strip()
    if not stripped or not stripped.startswith("{"):
        return
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return
    if not isinstance(parsed, dict) or parsed.get("ok") is not False:
        return
    err = parsed.get("error") or {}
    code = err.get("code") if isinstance(err, dict) else None
    msg = err.get("message") if isinstance(err, dict) else None
    raise RuntimeError(
        f"twitter user-posts {account} returned error envelope"
        f" (code={code or 'unknown'}): {(msg or '')[:160]}"
    )


def _parse_envelope(stdout_text: str) -> list[dict]:
    """Parse twitter-cli's `{ok, schema_version, data: [...]}` JSON envelope.

    Falls back gracefully if the wrapper is absent or `data` is a single dict.
    Raises ValueError on invalid JSON.
    """
    text = stdout_text.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON from twitter-cli: {exc}") from exc

    if isinstance(parsed, dict):
        data = parsed.get("data", parsed)
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return []
        return [d for d in data if isinstance(d, dict)]
    if isinstance(parsed, list):
        return [d for d in parsed if isinstance(d, dict)]
    return []


def _tweets_to_raw_items(account: str, tweets: list[dict]) -> list[RawItem]:
    """Convert twitter-cli tweet dicts to RawItem list."""
    items: list[RawItem] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for tweet in tweets:
        tid = str(tweet.get("id") or "").strip()
        text = str(tweet.get("text") or "")
        published = (
            tweet.get("createdAtISO")
            or tweet.get("createdAt")
            or tweet.get("createdAtLocal")
            or now_iso
        )
        title = text.strip()[:_TITLE_MAX] or f"@{account}"
        url = _build_tweet_url(account, tid, tweet)
        items.append(
            RawItem(
                sourceKey=SourceKey.X,
                sourceName=f"x.com/@{account}",
                sourceUrl=url,
                title=title,
                rawText=text[:_TEXT_MAX],
                publishedAt=str(published),
                extra={"author": account, "tweet_id": tid},
            )
        )
    return items


def _build_tweet_url(account: str, tweet_id: str, tweet: dict) -> str:
    """Construct the canonical tweet URL from id/account, with fallbacks."""
    if tweet_id:
        return f"https://x.com/{account}/status/{tweet_id}"
    urls = tweet.get("urls") or []
    if isinstance(urls, list) and urls and isinstance(urls[0], str):
        return urls[0]
    return f"https://x.com/{account}"


__all__ = ["collect_x_rsshub"]
