"""IM push dispatch: issue-ready → wecom fan-out with per-webhook records.

specs/006 ticket 03. Called from the generator right after an issue flips
ready. Best-effort: every failure is logged to im_push_logs and swallowed —
the push layer must never fail the generation pipeline.

防重: a webhook is skipped when THIS issue already has an ok row.
手动重推 (ticket 04) bypasses dispatch and appends rows directly.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.db import get_session_factory
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
    """Push one ready issue to all due webhooks; never raises.

    Owns a short session so a slow fan-out (retries can take ~14s per
    webhook) never holds the generator's session hostage.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            await _dispatch(session, issue_id)
        except Exception:
            await session.rollback()
            logger.exception(
                "im_push_dispatch_failed", extra={"issue_id": issue_id}
            )


async def _dispatch(session: AsyncSession, issue_id: str) -> None:
    settings_orm = (
        await session.execute(select(SettingsORM).where(SettingsORM.id == 1))
    ).scalar_one_or_none()
    im_push: dict[str, Any] = dict((settings_orm.im_push if settings_orm else None) or {})
    if not im_push.get("enabled"):
        return

    issue = await session.get(DailyIssueORM, issue_id)
    if issue is None or issue.status != IssueStatus.READY.value:
        return

    webhooks = [w for w in (im_push.get("webhooks") or []) if w.get("url")]
    if not webhooks:
        return

    succeeded = set(
        (
            await session.execute(
                select(ImPushLogORM.webhook_name).where(
                    ImPushLogORM.issue_id == issue_id, ImPushLogORM.ok.is_(True)
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

    top_n = int(im_push.get("top_n") or DEFAULT_TOP_N)
    items = await _top_items(session, issue_id, top_n)
    content = wecom.render_daily_markdown(
        title=DAILY_TITLE,
        date_label=str(issue.date or issue_id),
        items=items,
        link=_daily_link(im_push.get("link_base_url")),
    )

    for name, result in await wecom.push_to_webhooks(pending, content):
        session.add(
            ImPushLogORM(
                issue_id=issue_id,
                webhook_name=name[:20],
                ok=result.ok,
                errcode=result.errcode,
                errmsg=(result.errmsg or "")[:200],
            )
        )
    await session.commit()


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


__all__ = ["dispatch_daily_push"]
