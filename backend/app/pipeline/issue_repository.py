"""刊期仓库 (issue repository): 刊期生成写路径的持久化 adapter (specs/004 cand 5).

Holds the mechanics of turning selected (raw, summary_fields) pairs into
persisted rows: article ORM construction, score ORM construction, time
label extraction, effective-type resolution, and the issue status
finalization. The generator orchestrates policy (settings filter, dedup,
admission, truncate) and delegates every DB write shape here.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import ArticleORM, RawItem
from app.models.daily_issue import DailyIssueORM, IssueStatus
from app.models.meta import TypeKey

logger = logging.getLogger("aidaily.generator")

# Editorial top-N picks persisted as articles.is_must_read (specs/004 cand 1).
MUST_READ_TOP_N = 3


def effective_type(raw: RawItem, summary_fields: Any) -> tuple[str, str]:
    """Return (effective_type, basis) for a (raw, summary_fields) pair.

    effective_type is what will be persisted to articles.type:
    - LLM-classified type when valid ('llm')
    - Otherwise rule-derived suggestedType, or TOOLS as last resort ('rule')

    Shared by the settings filter, issue selection, and persist_article so
    all three agree on the persisted type.
    """
    rule_type = (
        raw.suggestedType.value if raw.suggestedType else TypeKey.TOOLS.value
    )
    llm_type_raw = getattr(summary_fields, "llm_type", None)
    if isinstance(llm_type_raw, str) and llm_type_raw in {
        t.value for t in TypeKey
    }:
        return llm_type_raw, "llm"
    return rule_type, "rule"


async def persist_article(
    session: AsyncSession,
    issue_id: str,
    index: int,
    raw: RawItem,
    summary_fields: Any,
) -> ArticleORM:
    """Persist one article (+ its score row) at the given display index.

    `index` is the 1-based display order assigned by the generator's
    selection; it drives both the article id suffix and the is_must_read
    editorial flag.
    """
    article_id = f"{issue_id}-{index:04d}"
    # Compute time HH:mm from raw.publishedAt (UTC now fallback).
    time_label = _extract_time_label(raw.publishedAt)
    reading_minutes = max(1, len(raw.rawText) // 800)
    # Prefer the LLM-generated Chinese title; fall back to raw title only if LLM failed.
    llm_title = getattr(summary_fields, "title", "") or ""
    article_title = (llm_title or raw.title)[:200]
    article_type, basis = effective_type(raw, summary_fields)
    if basis == "llm":
        rule_type = (
            raw.suggestedType.value if raw.suggestedType else TypeKey.TOOLS.value
        )
        if article_type != rule_type:
            logger.info(
                "type_overridden_by_llm",
                extra={
                    "article_id": article_id,
                    "llm_type": article_type,
                    "rule_type": rule_type,
                },
            )
    orm = ArticleORM(
        id=article_id,
        issue_id=issue_id,
        type=article_type,
        src=raw.sourceKey.value,
        title=article_title,
        excerpt=(summary_fields.summary or raw.title)[:200],
        lede=summary_fields.lede or summary_fields.summary or raw.title,
        summary=summary_fields.summary[:150],
        body=summary_fields.body or raw.title,
        quote=summary_fields.quote,
        points=summary_fields.points or [raw.title],
        time=time_label,
        source_url=raw.sourceUrl,
        source_name=raw.sourceName[:200],
        reading_minutes=reading_minutes,
        published_at=raw.publishedAt,
        is_must_read=index <= MUST_READ_TOP_N,
    )
    session.add(orm)

    # US1 T019: persist ArticleScoreORM (1:1 with article).
    score_orm = _build_score_orm(article_id, summary_fields)
    if score_orm is not None:
        session.add(score_orm)

    return orm


def finalize_issue(issue_orm: DailyIssueORM, *, failed: bool) -> DailyIssueORM:
    """Stamp ready/failed + generated_at. Caller owns the commit."""
    issue_orm.status = (
        IssueStatus.FAILED.value if failed else IssueStatus.READY.value
    )
    issue_orm.generated_at = datetime.utcnow()
    return issue_orm


def _build_score_orm(article_id: str, summary_fields: Any):
    """Build ArticleScoreORM from summary_fields. Returns None if scoring data missing.

    Defensive: any missing composite/score_source aborts the row creation
    (older code paths that don't fill these fields skip scoring).
    """
    from app.models.article_score import ArticleScoreORM

    composite = getattr(summary_fields, "composite_score", None)
    dims = getattr(summary_fields, "dimension_scores", None) or {}
    tier = getattr(summary_fields, "authority_tier", None)
    source = getattr(summary_fields, "score_source", None) or "llm"
    topic = getattr(summary_fields, "topic_id", None)
    opinion = getattr(summary_fields, "opinion_fingerprint", None)

    if composite is None or tier is None:
        return None

    return ArticleScoreORM(
        article_id=article_id,
        composite_score=int(composite),
        dim_authority=int(dims.get("authority", 50)),
        dim_depth=int(dims.get("depth", 50)),
        dim_timeliness=int(dims.get("timeliness", 50)),
        dim_expression=int(dims.get("expression", 50)),
        dim_engagement=int(dims.get("engagement", 50)),
        authority_tier=tier,
        topic_id=topic,
        opinion_fingerprint=opinion,
        score_source=source,
        computed_at=datetime.utcnow(),
    )


def _extract_time_label(published_at: str) -> str:
    """Extract HH:mm from ISO timestamp; fall back to current UTC time."""
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        return dt.strftime("%H:%M")
    except Exception:
        return datetime.now(timezone.utc).strftime("%H:%M")


__all__ = [
    "MUST_READ_TOP_N",
    "effective_type",
    "finalize_issue",
    "persist_article",
]
