"""Issue generation pipeline (T040).

generate_issue(date) → DailyIssue:
1. Load current Settings snapshot.
2. Insert DailyIssue(status=generating, filtersApplied=snapshot).
3. Call collector → list[RawItem].
4. For each item, call summarizer (with FR-007a per-item tolerance).
5. Persist Articles.
6. Update DailyIssue.status → ready (or failed on summarizer-wide failure).

Idempotent on issueId: re-entry returns existing ready issue.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.infra.db import get_session_factory
from app.infra.errors import IssueGeneratingError
from app.models.article import ArticleORM, RawItem
from app.models.daily_issue import DailyIssueORM, IssueStatus
from app.models.meta import SourceKey, TypeKey
from app.pipeline import summarizer
from app.pipeline.collector import collect_all
from app.pipeline.dedup import dedup_candidates, truncate_diverse

logger = logging.getLogger("aidaily.generator")

# Editorial admission line: items below this composite score don't earn a
# slot at all (motivational tweets, empty repos). They used to sink to the
# bottom but still occupied daily_count budget. 45 sits below the lowest
# score a genuinely useful community item earns (~52) while absorbing the
# ±5 LLM scoring variance around junk (~41).
ADMISSION_FLOOR = 45

# Editorial top-N picks persisted as articles.is_must_read (specs/004 cand 1).
MUST_READ_TOP_N = 3


def _issue_id(date: datetime) -> str:
    """YYYYMMDD id for a given date (in configured tz)."""
    return date.strftime("%Y%m%d")


def _iso(date: datetime) -> str:
    return date.isoformat()


async def _load_settings_snapshot(session: AsyncSession) -> dict[str, Any]:
    """Return {sources: [...], types: [...], daily_count: int} from settings row.

    Default all-on if no settings row, default daily_count=30 if column missing.
    Filters by bool=True — disabled sources/types are excluded from filtersApplied.
    """
    from sqlalchemy import select

    from app.models.settings import SettingsORM

    orm = (
        await session.execute(select(SettingsORM).where(SettingsORM.id == 1))
    ).scalar_one_or_none()
    if orm is None:
        return {
            "sources": [s.value for s in SourceKey],
            "types": [t.value for t in TypeKey],
            "daily_count": 30,
        }
    sources_dict = dict(orm.sources or {})
    types_dict = dict(orm.types or {})
    return {
        "sources": [k for k, v in sources_dict.items() if bool(v)],
        "types": [k for k, v in types_dict.items() if bool(v)],
        "daily_count": int(getattr(orm, "daily_count", 30) or 30),
    }


async def _count_issues(session: AsyncSession) -> int:
    result = await session.execute(select(func.count(DailyIssueORM.id)))
    return int(result.scalar_one())


async def _get_issue(session: AsyncSession, issue_id: str) -> DailyIssueORM | None:
    result = await session.execute(
        select(DailyIssueORM).where(DailyIssueORM.id == issue_id)
    )
    return result.scalar_one_or_none()


async def _insert_generating_issue(
    session: AsyncSession, issue_id: str, date_iso: str, filters: dict[str, Any]
) -> DailyIssueORM:
    orm = DailyIssueORM(
        id=issue_id,
        date=date_iso,
        edition=1,
        status=IssueStatus.GENERATING.value,
        generated_at=None,
        filters_applied=filters,
    )
    session.add(orm)
    await session.commit()
    return orm


def _effective_type(raw: RawItem, summary_fields: Any) -> tuple[str, str]:
    """Return (effective_type, basis) for a (raw, summary_fields) pair.

    effective_type is what will be persisted to articles.type:
    - LLM-classified type when valid ('llm')
    - Otherwise rule-derived suggestedType, or TOOLS as last resort ('rule')

    Used both by _persist_article and by the settings filter so they agree.
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


def _filter_by_settings(
    candidates: list[tuple[RawItem, Any]],
    sources_allowed: list[str],
    types_allowed: list[str],
    issue_id: str,
) -> list[tuple[RawItem, Any]]:
    """Drop candidates whose source or effective type is disabled in settings.

    Logs dropped counts by source / type for observability. No-op when both
    allow-lists equal the full enum (the default all-on case).
    """
    if not candidates:
        return candidates
    full_sources = {s.value for s in SourceKey}
    full_types = {t.value for t in TypeKey}
    # Fast path: all-on → no filtering work.
    if set(sources_allowed) == full_sources and set(types_allowed) == full_types:
        return candidates

    src_allow = set(sources_allowed)
    type_allow = set(types_allowed)
    kept: list[tuple[RawItem, Any]] = []
    dropped_by_source = 0
    dropped_by_type = 0
    for raw, summary_fields in candidates:
        if raw.sourceKey.value not in src_allow:
            dropped_by_source += 1
            continue
        eff_type, _ = _effective_type(raw, summary_fields)
        if eff_type not in type_allow:
            dropped_by_type += 1
            continue
        kept.append((raw, summary_fields))
    if dropped_by_source or dropped_by_type:
        logger.info(
            "candidates_filtered_by_settings",
            extra={
                "issue_id": issue_id,
                "before": len(candidates),
                "after": len(kept),
                "dropped_by_source": dropped_by_source,
                "dropped_by_type": dropped_by_type,
                "sources_allowed": sorted(src_allow),
                "types_allowed": sorted(type_allow),
            },
        )
    return kept


async def _persist_article(
    session: AsyncSession,
    issue_id: str,
    index: int,
    raw: RawItem,
    summary_fields: Any,
) -> ArticleORM:
    article_id = f"{issue_id}-{index:04d}"
    # Compute time HH:mm from raw.publishedAt (UTC now fallback).
    time_label = _extract_time_label(raw.publishedAt)
    reading_minutes = max(1, len(raw.rawText) // 800)
    # Prefer the LLM-generated Chinese title; fall back to raw title only if LLM failed.
    llm_title = getattr(summary_fields, "title", "") or ""
    article_title = (llm_title or raw.title)[:200]
    # Type resolution via shared helper (kept in sync with _filter_by_settings).
    article_type, basis = _effective_type(raw, summary_fields)
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


async def generate_issue(
    date: datetime | None = None,
    *,
    llm_client: Any = None,
    inject_collector: Any = None,
) -> DailyIssueORM:
    """Generate the daily issue for `date` (defaults to today).

    Args:
        date: Target date (defaults to UTC now).
        llm_client: Inject LLMClient (for tests).
        inject_collector: Async callable returning list[RawItem] (for tests).

    Returns:
        DailyIssueORM (status=ready or failed).

    Idempotent: if a ready issue exists for the date, returns it directly.

    US2: applies three-layer dedup (URL → topic → opinion) and top-N
    truncate by composite_score DESC to the user's daily_count setting.
    Only surviving articles are persisted with the current issue_id;
    excluded ones are dropped entirely.
    """
    target = date or datetime.now(timezone.utc)
    issue_id = _issue_id(target)
    date_iso = target.strftime("%Y-%m-%d")
    factory = get_session_factory()
    async with factory() as session:
        existing = await _get_issue(session, issue_id)
        if existing is not None and existing.status == IssueStatus.READY.value:
            return existing
        if existing is not None and existing.status == IssueStatus.GENERATING.value:
            # A generation run is already in flight (e.g. scheduler beat us to
            # it). Surface the 2003 conflict instead of crashing on UNIQUE.
            raise IssueGeneratingError(f"今日刊正在生成: {issue_id}")
        if existing is not None and existing.status == IssueStatus.FAILED.value:
            # Allow regeneration.
            await session.delete(existing)
            await session.commit()

        snapshot = await _load_settings_snapshot(session)
        daily_count = int(snapshot.get("daily_count", 30))
        filters = {
            "sources": snapshot["sources"],
            "types": snapshot["types"],
            "daily_count": daily_count,
        }
        issue_orm = await _insert_generating_issue(session, issue_id, date_iso, filters)

        # Collect.
        if inject_collector is not None:
            raw_items: list[RawItem] = await inject_collector()
        else:
            raw_items = await collect_all()

        # Summarize per item with FR-007a tolerance (single failures skipped).
        # Hold (raw, summary_fields) pairs in memory; persist only after dedup+truncate.
        candidates: list[tuple[RawItem, Any]] = []
        summarizer_failures = 0
        web_failures = 0
        for raw in raw_items:
            try:
                summary_fields = await summarizer.summarize_item(
                    raw, client=llm_client
                )
            except summarizer.SummarizerFailure as exc:
                summarizer_failures += 1
                if raw.sourceKey == SourceKey.WEB:
                    web_failures += 1
                logger.warning(
                    "article_summarize_failed",
                    extra={
                        "source": raw.sourceKey.value,
                        "issue_id": issue_id,
                        "exception_type": type(exc).__name__,
                    },
                )
                continue
            except Exception as exc:
                summarizer_failures += 1
                if raw.sourceKey == SourceKey.WEB:
                    web_failures += 1
                logger.warning(
                    "article_summarize_failed",
                    extra={
                        "source": raw.sourceKey.value,
                        "issue_id": issue_id,
                        "exception_type": type(exc).__name__,
                    },
                )
                continue
            candidates.append((raw, summary_fields))

        # US3 settings enforcement: drop candidates whose source or effective
        # type is disabled by the user's settings snapshot. Done BEFORE dedup
        # so disabled content doesn't consume truncate budget.
        candidates = _filter_by_settings(
            candidates,
            sources_allowed=snapshot["sources"],
            types_allowed=snapshot["types"],
            issue_id=issue_id,
        )

        # US2 T030: three-layer dedup → top-N truncate → persist survivors.
        selected: list[tuple[RawItem, Any]] = _select_for_issue(
            candidates, daily_count
        )
        for idx, (raw, summary_fields) in enumerate(selected, start=1):
            await _persist_article(session, issue_id, idx, raw, summary_fields)

        await session.commit()

        # Finalize status.
        # Failure rule: 0 candidates survived → status=failed.
        # (FR-007a: single source collection failure → log + skip + continue.)
        # Web source can be entirely unavailable without failing the issue,
        # provided other sources (x + github) yielded ≥4 candidates.
        if web_failures:
            logger.warning(
                "web_sources_failed",
                extra={
                    "issue_id": issue_id,
                    "count": web_failures,
                },
            )
        all_failed = bool(raw_items) and not candidates
        issue_orm.status = (
            IssueStatus.FAILED.value if all_failed else IssueStatus.READY.value
        )
        issue_orm.generated_at = datetime.utcnow()
        await session.commit()
        return issue_orm


def _select_for_issue(
    candidates: list[tuple[RawItem, Any]],
    daily_count: int,
) -> list[tuple[RawItem, Any]]:
    """Apply US2 dedup + diversity-aware truncate to summarized candidates.

    Returns the (raw, summary_fields) pairs that should be persisted under the
    current issue_id, in display order (highest composite_score first, with a
    per-type quota so one type cannot crowd out the rest).
    """
    if not candidates:
        return []
    # Decorate each candidate with the dedup keys + a stable idx.
    items: list[dict] = []
    for idx, (raw, summary_fields) in enumerate(candidates):
        effective_type, _ = _effective_type(raw, summary_fields)
        items.append(
            {
                "idx": idx,
                "sourceUrl": raw.sourceUrl,
                "compositeScore": getattr(summary_fields, "composite_score", None)
                or 0,
                "publishedAt": raw.publishedAt,
                "topicId": getattr(summary_fields, "topic_id", None),
                "opinionFingerprint": getattr(
                    summary_fields, "opinion_fingerprint", None
                ),
                "type": effective_type,
            }
        )
    deduped = dedup_candidates(items)
    admitted = [it for it in deduped if it["compositeScore"] >= ADMISSION_FLOOR]
    dropped = len(deduped) - len(admitted)
    if dropped:
        logger.info(
            "candidates_below_admission_floor",
            extra={"dropped": dropped, "floor": ADMISSION_FLOOR},
        )
    top = truncate_diverse(admitted, daily_count)
    # Map surviving idx back to (raw, summary_fields) pairs, preserving
    # the descending-composite order produced by truncate_top_n.
    by_idx = {item["idx"]: (candidates[item["idx"]][0], candidates[item["idx"]][1])
              for item in top}
    return [by_idx[item["idx"]] for item in top if item["idx"] in by_idx]


__all__ = ["generate_issue"]
