"""IM push dispatch: issue-ready → wecom fan-out with per-webhook records.

specs/006 ticket 03/04. dispatch_daily_push runs from the generator right
after an issue flips ready: best-effort, every failure logged to
im_push_logs and swallowed — the push layer must never fail generation.
manual_repush is the explicit user action (ticket 04): no dedup, raises
business errors, returns per-webhook results.

防重 (auto path): a webhook is skipped when THIS issue already has an
ok row. Manual repush bypasses that and appends rows directly.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.db import get_session_factory
from app.infra.errors import IssueNotGeneratedError, WebhookNotFoundError
from app.models.article import ArticleORM
from app.models.article_score import ArticleScoreORM
from app.models.daily_issue import DailyIssueORM, IssueStatus
from app.models.im_push_log import ImPushLogORM
from app.models.settings import SettingsORM, default_im_push
from app.pipeline import wecom

logger = logging.getLogger("aidaily.im_push")

DAILY_TITLE = "AI 日报"
DEFAULT_TOP_N = int(default_im_push()["top_n"])


async def dispatch_daily_push(issue_id: str) -> None:
    """Auto path: push one ready issue to all due webhooks; never raises.

    Owns a short session so a slow fan-out (retries can take ~14s per
    webhook) never holds the generator's session hostage.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            im_push = await _load_im_push(session)
            if not im_push.get("enabled"):
                return
            issue = await _load_ready_issue(session, issue_id)
            webhooks = _configured_webhooks(im_push)
            if issue is None or not webhooks:
                return

            succeeded = set(
                (
                    await session.execute(
                        select(ImPushLogORM.webhook_name).where(
                            ImPushLogORM.issue_id == issue_id,
                            ImPushLogORM.ok.is_(True),
                        )
                    )
                )
                .scalars()
                .all()
            )
            pending = [w for w in webhooks if w.get("name") not in succeeded]
            if not pending:
                logger.info("im_push_dedup_skipped issue_id=%s", issue_id)
                return

            content = await _build_content(session, issue, im_push)
            await _push_and_log(session, issue_id, pending, content)
        except Exception:
            await session.rollback()
            logger.exception("im_push_dispatch_failed", extra={"issue_id": issue_id})


async def manual_repush(issue_id: str) -> list[dict[str, Any]]:
    """Manual path (ticket 04): re-push NOW, bypassing dedup.

    Deliberately ignores im_push.enabled — this is an explicit user
    action (the auto path's "enabled=false 零行为" rule doesn't apply).
    Raises IssueNotGeneratedError when the issue is missing/not ready,
    WebhookNotFoundError when nothing is configured. Errors from wecom
    itself come back as ok=False results, not exceptions.
    """
    factory = get_session_factory()
    async with factory() as session:
        issue = await _load_ready_issue(session, issue_id)
        if issue is None:
            raise IssueNotGeneratedError(f"刊期不存在或未就绪: {issue_id}")
        im_push = await _load_im_push(session)
        webhooks = _configured_webhooks(im_push)
        if not webhooks:
            raise WebhookNotFoundError("未配置任何可用的企微 webhook")

        content = await _build_content(session, issue, im_push)
        return await _push_and_log(session, issue_id, webhooks, content)


async def latest_statuses(session: AsyncSession, issue_id: str) -> list[dict[str, Any]]:
    """Per configured webhook: its latest push record for the issue.

    Caller validates the issue exists. Unpushed webhooks report
    pushed=False so the UI can show 未推送.
    """
    im_push = await _load_im_push(session)
    names = [str(w.get("name", "")) for w in _configured_webhooks(im_push)]

    rows = (
        await session.execute(
            select(ImPushLogORM)
            .where(ImPushLogORM.issue_id == issue_id)
            .order_by(ImPushLogORM.id.desc())
        )
    ).scalars().all()
    latest: dict[str, ImPushLogORM] = {}
    for row in rows:  # id desc → first hit per name wins
        latest.setdefault(row.webhook_name, row)

    statuses: list[dict[str, Any]] = []
    for name in names:
        row = latest.get(name)
        statuses.append(
            {
                "name": name,
                "pushed": row is not None,
                "ok": bool(row.ok) if row else None,
                "errcode": row.errcode if row else None,
                "errmsg": row.errmsg if row else "",
                "pushedAt": row.pushed_at.isoformat() + "Z" if row else None,
            }
        )
    return statuses


# ---------------------------------------------------------------------------
# Shared internals
# ---------------------------------------------------------------------------


async def _load_im_push(session: AsyncSession) -> dict[str, Any]:
    orm = (
        await session.execute(select(SettingsORM).where(SettingsORM.id == 1))
    ).scalar_one_or_none()
    return dict((orm.im_push if orm else None) or {})


async def _load_ready_issue(
    session: AsyncSession, issue_id: str
) -> DailyIssueORM | None:
    issue = await session.get(DailyIssueORM, issue_id)
    if issue is None or issue.status != IssueStatus.READY.value:
        return None
    return issue


def _configured_webhooks(im_push: dict[str, Any]) -> list[dict[str, Any]]:
    return [w for w in (im_push.get("webhooks") or []) if w.get("url")]


async def _build_content(
    session: AsyncSession, issue: DailyIssueORM, im_push: dict[str, Any]
) -> str:
    top_n = int(im_push.get("top_n") or DEFAULT_TOP_N)
    items = await _top_items(session, str(issue.id), top_n)
    return wecom.render_daily_markdown(
        title=DAILY_TITLE,
        date_label=str(issue.date or issue.id),
        items=items,
        link=_daily_link(im_push.get("link_base_url")),
    )


async def _push_and_log(
    session: AsyncSession, issue_id: str, webhooks: list[dict[str, Any]], content: str
) -> list[dict[str, Any]]:
    results_out: list[dict[str, Any]] = []
    for name, result in await wecom.push_to_webhooks(webhooks, content):
        session.add(
            ImPushLogORM(
                issue_id=issue_id,
                webhook_name=name[:20],
                ok=result.ok,
                errcode=result.errcode,
                errmsg=(result.errmsg or "")[:200],
            )
        )
        results_out.append(
            {
                "name": name,
                "ok": result.ok,
                "errcode": result.errcode,
                "errmsg": result.errmsg or "",
            }
        )
    await session.commit()
    return results_out


async def _top_items(
    session: AsyncSession, issue_id: str, top_n: int
) -> list[tuple[str, str]]:
    """Highest-composite articles of the issue, as (title, summary) pairs."""
    rows = (
        await session.execute(
            select(ArticleORM.title, ArticleORM.summary)
            .outerjoin(ArticleScoreORM, ArticleScoreORM.article_id == ArticleORM.id)
            .where(ArticleORM.issue_id == issue_id)
            .order_by(ArticleScoreORM.composite_score.desc().nullslast(), ArticleORM.id)
            .limit(top_n)
        )
    ).all()
    return [(title, summary) for title, summary in rows]


def _daily_link(link_base_url: str | None) -> str | None:
    """Frontend root serves today's issue; empty base → no link section."""
    base = (link_base_url or "").strip().rstrip("/")
    return f"{base}/" if base else None


__all__ = ["dispatch_daily_push", "latest_statuses", "manual_repush"]
