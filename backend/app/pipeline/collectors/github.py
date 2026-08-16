"""GitHub collector via `gh` CLI (official GitHub CLI with auth).

Strategy: run 2-3 complementary `gh search repos --json ...` queries via
`asyncio.create_subprocess_exec`, aggregate, dedup by sourceUrl, cap at 30.

Requirements:
- `gh` binary on PATH (verified via shutil.which).
- `gh auth status` reports logged-in (best-effort check; failure logs a warning
  but we still try — the per-query call will surface auth errors).

If `gh` is absent or not logged in, return [] and log one warning.
Per-query timeout 30s. Non-zero exit -> log + skip query.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from datetime import datetime, timedelta, timezone
from typing import Any

from app.models.article import RawItem
from app.models.meta import SourceKey

logger = logging.getLogger("aidaily.collector.github")

# Total cap to avoid hammering the LLM summarizer downstream.
MAX_ITEMS = 30
# Per-query subprocess timeout (seconds).
PER_QUERY_TIMEOUT = 30.0
# Per-query result limit passed to `gh search repos -L`.
PER_QUERY_LIMIT = 15
# rawText length cap (chars) — keeps summarizer input bounded.
RAW_TEXT_MAX = 2000

# JSON fields we ask gh to emit. Keep field names verbatim per `gh search repos --help`.
JSON_FIELDS: tuple[str, ...] = (
    "fullName",
    "description",
    "url",
    "stargazersCount",
    "createdAt",
    "updatedAt",
    "language",
)


def _recent_date(days: int) -> str:
    """ISO date YYYY-MM-DD for `days` ago in UTC."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


def _build_queries(since_recent: str, since_updated: str) -> list[list[str]]:
    """Construct 3 complementary `gh search repos` argv lists.

    Q1: New this week, Python, llm topic — surfaces fast-growing new repos.
    Q2: New this week, ai-agents topic — agent ecosystem, any language.
    Q3: Recently updated, Python, artificial-intelligence topic — active mature repos.
    """
    base = ["gh", "search", "repos"]
    json_arg = ",".join(JSON_FIELDS)
    common = ["--json", json_arg, "--sort", "stars", "--order", "desc", "-L", str(PER_QUERY_LIMIT)]
    return [
        base + ["--language", "python", "--topic", "llm", "--created", f">{since_recent}", *common],
        base + ["--topic", "ai-agents", "--created", f">{since_recent}", *common],
        base + ["--language", "python", "--topic", "artificial-intelligence", "--updated", f">{since_updated}", *common],
    ]


async def _run_gh_query(argv: list[str]) -> list[dict[str, Any]]:
    """Run one `gh search repos` subprocess; return parsed JSON list (possibly empty).

    Logs and returns [] on non-zero exit or timeout.
    """
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=PER_QUERY_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        logger.warning(
            "github_gh_query_timeout",
            extra={"query": " ".join(argv), "timeout_s": PER_QUERY_TIMEOUT},
        )
        return []

    stdout = stdout_b.decode("utf-8", errors="replace") if stdout_b else ""
    if proc.returncode != 0:
        stderr = stderr_b.decode("utf-8", errors="replace") if stderr_b else ""
        logger.warning(
            "github_gh_query_failed",
            extra={
                "query": " ".join(argv),
                "returncode": proc.returncode,
                "stderr": stderr.strip()[:300],
            },
        )
        return []

    try:
        parsed = json.loads(stdout) if stdout.strip() else []
    except json.JSONDecodeError as exc:
        logger.warning(
            "github_gh_query_bad_json",
            extra={"query": " ".join(argv), "error": str(exc)},
        )
        return []
    if not isinstance(parsed, list):
        return []
    return parsed


def _build_raw_item(repo: dict[str, Any]) -> RawItem | None:
    """Map one gh JSON repo dict to a RawItem. Return None if missing url/fullName."""
    full = (repo.get("fullName") or "").strip()
    url = (repo.get("url") or "").strip()
    if not full or not url:
        return None

    description = (repo.get("description") or "").strip()
    language = (repo.get("language") or "").strip() or "unknown"
    stars = int(repo.get("stargazersCount") or 0)
    created_at = repo.get("createdAt") or ""

    raw_text = description
    if len(raw_text) > RAW_TEXT_MAX:
        raw_text = raw_text[:RAW_TEXT_MAX]

    title = f"{full}: {description}" if description else full

    return RawItem(
        sourceKey=SourceKey.GITHUB,
        sourceName="github.com",
        sourceUrl=url,
        title=title,
        rawText=raw_text,
        publishedAt=created_at,
        suggestedType=None,
        extra={
            "stars": stars,
            "language": language,
            "topics": [],  # gh search repos does not emit topics in JSON
            "updatedAt": repo.get("updatedAt"),
        },
    )


def _dedup_by_url(items: list[RawItem]) -> list[RawItem]:
    """Remove duplicates by URL (case-insensitive, trailing slash normalized)."""
    seen: set[str] = set()
    out: list[RawItem] = []
    for item in items:
        key = item.sourceUrl.strip().lower().rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


async def _check_gh_available() -> bool:
    """Return True iff `gh` is on PATH. (Best-effort; auth check is delegated to queries.)"""
    return shutil.which("gh") is not None


async def collect_github() -> list[RawItem]:
    """Fetch trending AI repos via `gh` CLI. Returns RawItem list (possibly empty).

    Strategy: 3 complementary `gh search repos` queries aggregated + deduped + capped.
    Failures (gh missing, query error, timeout) -> log + skip; never raise.
    """
    if not await _check_gh_available():
        logger.warning("github_gh_missing", extra={"source": SourceKey.GITHUB.value})
        return []

    since_recent = _recent_date(days=7)
    since_updated = _recent_date(days=3)
    queries = _build_queries(since_recent, since_updated)

    # Run all queries concurrently; each handles its own errors and returns [].
    query_results = await asyncio.gather(*[_run_gh_query(q) for q in queries])

    items: list[RawItem] = []
    for repo_list in query_results:
        for repo in repo_list:
            item = _build_raw_item(repo)
            if item is not None:
                items.append(item)

    deduped = _dedup_by_url(items)
    if len(deduped) > MAX_ITEMS:
        deduped = deduped[:MAX_ITEMS]
    return deduped


__all__ = ["collect_github"]
