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
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.db import get_session_factory
from app.infra.errors import IssueGeneratingError
from app.models.article import RawItem
from app.models.daily_issue import DailyIssueORM, IssueStatus
from app.models.meta import SOURCE_KEYS, TYPE_KEYS, SourceKey, TypeKey
from app.models.settings import merged_bool_map
from app.pipeline import summarizer
from app.pipeline.collector import collect_all
from app.pipeline.dedup import dedup_candidates, exclude_published, truncate_diverse
from app.pipeline.issue_repository import (
    effective_type,
    finalize_issue,
    persist_article,
    recent_published_keys,
)
from app.pipeline.scorer import compose_score, score_with_rules

logger = logging.getLogger("aidaily.generator")

# Editorial admission line: items below this composite score don't earn a
# slot at all (motivational tweets, empty repos). They used to sink to the
# bottom but still occupied daily_count budget. 45 sits below the lowest
# score a genuinely useful community item earns (~52) while absorbing the
# ±5 LLM scoring variance around junk (~41).
ADMISSION_FLOOR = 45

# Cross-issue dedup lookback (specs/005): the 72h collection window spans at
# most 3 daily issues, so one appearance anywhere in the last 3 issues
# excludes a candidate from all later issues — no more, no less.
CROSS_ISSUE_LOOKBACK = 3


def _rule_proxy_score(raw: RawItem) -> int:
    """LLM-free composite for pre-LLM gating.

    Reuses the rule-fallback scorer's four deterministic dims (authority /
    timeliness / engagement / depth; expression pinned at neutral 50). The
    proxy cannot see expression quality — that residual is exactly the
    gate's accepted error, measured via the issue_funnel log.
    """
    dims = score_with_rules(
        source_name=raw.sourceName,
        published_at=raw.publishedAt,
        raw_text=raw.rawText,
        source_key=raw.sourceKey.value,
        extra=raw.extra,
    )
    return compose_score(
        {
            "authority": dims["dim_authority"],
            "depth": dims["dim_depth"],
            "timeliness": dims["dim_timeliness"],
            # Pinned to the neutral literal on purpose: if the rule scorer
            # ever computes a real expression dim, the gate must still see
            # the spec'd neutral value until the calibration data says so.
            "expression": 50,
            "engagement": dims["dim_engagement"],
        }
    )


def _gate_for_llm(
    raw_items: list[RawItem],
    sources_allowed: list[str],
    daily_count: int,
) -> tuple[list[RawItem], dict[str, Any]]:
    """Pre-LLM gate: source settings filter + per-source rule-score quota.

    1. Items whose source is disabled in settings are dropped before any
       LLM spend (type-level filtering still happens post-LLM — effective
       type needs the LLM's override).
    2. Each enabled source keeps its top `daily_count` items by rule proxy
       score; leftovers backfill globally (score order) up to
       len(sources_allowed) × daily_count total.

    Returns (gated items in original collection order, funnel stats).
    """
    collected_by_source = Counter(
        raw.sourceKey.value for raw in raw_items
    )
    src_allow = set(sources_allowed)
    enabled = [raw for raw in raw_items if raw.sourceKey.value in src_allow]
    source_filtered = len(raw_items) - len(enabled)

    # Decorate with (proxy_score, collection_index); sorts below are stable
    # so equal scores keep collection order.
    scored = [(_rule_proxy_score(raw), i, raw) for i, raw in enumerate(enabled)]
    quota = daily_count
    total_cap = len(src_allow) * quota

    kept: list[tuple[int, int, RawItem]] = []
    leftovers: list[tuple[int, int, RawItem]] = []
    by_source: dict[str, list[tuple[int, int, RawItem]]] = {}
    for item in scored:
        by_source.setdefault(item[2].sourceKey.value, []).append(item)
    for items in by_source.values():
        ranked = sorted(items, key=lambda t: -t[0])
        kept.extend(ranked[:quota])
        leftovers.extend(ranked[quota:])

    if len(kept) < total_cap and leftovers:
        leftovers.sort(key=lambda t: -t[0])
        kept.extend(leftovers[: total_cap - len(kept)])

    gated = [raw for _, _, raw in sorted(kept, key=lambda t: t[1])]
    # Recompute per-source pass counts: backfilled items count towards
    # their own source (a source may exceed `quota` via global backfill).
    final_by_source = Counter(raw.sourceKey.value for raw in gated)
    stats: dict[str, Any] = {
        "collected": len(raw_items),
        "collected_by_source": collected_by_source,
        "source_filtered": source_filtered,
        "gate_quota": quota,
        "gate_passed_by_source": final_by_source,
        "gate_dropped": len(enabled) - len(gated),
        # Not funnel material: proxy scores of every enabled item, keyed by
        # URL. Popped by generate_issue to build the proxy-vs-LLM pairs.
        "proxy_by_url": {raw.sourceUrl: score for score, _, raw in scored},
    }
    return gated, stats


def _issue_id(date: datetime) -> str:
    """YYYYMMDD id for a given date (in configured tz)."""
    return date.strftime("%Y%m%d")


def _iso(date: datetime) -> str:
    return date.isoformat()


async def _load_settings_snapshot(session: AsyncSession) -> dict[str, Any]:
    """Return {sources: [...], types: [...], daily_count: int} from settings row.

    Default all-on if no settings row, default daily_count=15 if column missing.
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
            "daily_count": 15,
        }
    sources_dict = dict(orm.sources or {})
    types_dict = dict(orm.types or {})
    return {
        "sources": [
            k for k, v in merged_bool_map(sources_dict, SOURCE_KEYS).items() if v
        ],
        "types": [
            k for k, v in merged_bool_map(types_dict, TYPE_KEYS).items() if v
        ],
        "daily_count": int(getattr(orm, "daily_count", 15) or 15),
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
        eff_type, _ = effective_type(raw, summary_fields)
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
    target = date or datetime.now(UTC)
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
        daily_count = int(snapshot.get("daily_count", 15))
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

        # Pre-LLM gate: disabled sources never spend tokens; each enabled
        # source keeps its top `daily_count` by rule proxy score (global
        # backfill up to len(enabled) × daily_count total).
        gated_items, gate_stats = _gate_for_llm(
            raw_items, snapshot["sources"], daily_count
        )
        proxy_by_url: dict[str, int] = gate_stats.pop("proxy_by_url", {})

        # Summarize per item with FR-007a tolerance (single failures skipped).
        # Hold (raw, summary_fields) pairs in memory; persist only after dedup+truncate.
        candidates: list[tuple[RawItem, Any]] = []
        summarizer_failures = 0
        web_failures = 0
        for raw in gated_items:
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

        # specs/005: cross-issue exclusion — candidates already published in
        # the last CROSS_ISSUE_LOOKBACK issues are dropped before within-issue
        # dedup. Regeneration is safe: the issue's rows are deleted first.
        published_urls, published_topics = await recent_published_keys(
            session, before_issue_id=issue_id, issues=CROSS_ISSUE_LOOKBACK
        )

        # US2 T030: three-layer dedup → top-N truncate → persist survivors.
        select_stats: dict[str, Any] = {}
        selected: list[tuple[RawItem, Any]] = _select_for_issue(
            candidates, daily_count,
            published_urls=published_urls, published_topics=published_topics,
            stats_out=select_stats,
        )
        for idx, (raw, summary_fields) in enumerate(selected, start=1):
            await persist_article(session, issue_id, idx, raw, summary_fields)

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
        finalize_issue(issue_orm, failed=all_failed)
        await session.commit()

        # specs/006: issue 就绪即推送(任何生成入口;幂等重入在早退路径,
        # 不会到这里)。推送是尽力而为,内部自吞异常,不影响 issue 状态。
        if issue_orm.status == IssueStatus.READY.value:
            from app.pipeline.im_push import dispatch_daily_push

            await dispatch_daily_push(issue_id)

        # Single funnel event: numbers ride in the message itself so any
        # logging handler (incl. regen_today's basicConfig stdout) shows
        # them; extras carry the same data structured.
        funnel = {
            **gate_stats,
            "summarized_ok": len(candidates),
            "summarize_failed": summarizer_failures,
            "web_summarize_failed": web_failures,
            **select_stats,
            "selected": len(selected),
        }
        logger.info(
            "issue_funnel"
            f" collected={funnel['collected']}"
            f" source_filtered={funnel['source_filtered']}"
            f" gate_dropped={funnel['gate_dropped']}"
            f" summarized_ok={funnel['summarized_ok']}"
            f" summarize_failed={funnel['summarize_failed']}"
            f" web_summarize_failed={funnel['web_summarize_failed']}"
            f" cross_issue_excluded={funnel.get('cross_issue_excluded', 0)}"
            f" in_issue_dedup={funnel.get('in_issue_dedup', 0)}"
            f" below_floor={funnel.get('below_floor', 0)}"
            f" truncated={funnel.get('truncated', 0)}"
            f" selected={funnel['selected']}",
            extra={
                "issue_id": issue_id,
                **funnel,
                # Proxy-vs-LLM pairs for the selected items: lets one issue's
                # log quantify how well the gate's rule score tracks the real
                # composite (gate calibration data).
                "proxy_vs_llm": [
                    [
                        proxy_by_url.get(raw.sourceUrl),
                        getattr(summary_fields, "composite_score", None),
                    ]
                    for raw, summary_fields in selected
                ],
            },
        )
        return issue_orm


def _select_for_issue(
    candidates: list[tuple[RawItem, Any]],
    daily_count: int,
    *,
    published_urls: set[str] | None = None,
    published_topics: set[str] | None = None,
    stats_out: dict[str, Any] | None = None,
) -> list[tuple[RawItem, Any]]:
    """Apply US2 dedup + diversity-aware truncate to summarized candidates.

    Cross-issue exclusion (specs/005) runs first: candidates whose URL or
    topic_id was published in the lookback window are dropped outright.

    Returns the (raw, summary_fields) pairs that should be persisted under the
    current issue_id, in display order (highest composite_score first, with a
    per-type quota so one type cannot crowd out the rest). When `stats_out`
    is given, stage counts (cross_issue_excluded / in_issue_dedup /
    below_floor / truncated) are written into it for the funnel log.
    """
    if not candidates:
        if stats_out is not None:
            stats_out.update(
                {"cross_issue_excluded": 0, "in_issue_dedup": 0,
                 "below_floor": 0, "truncated": 0}
            )
        return []
    # Decorate each candidate with the dedup keys + a stable idx.
    items: list[dict] = []
    for idx, (raw, summary_fields) in enumerate(candidates):
        eff_type_value, _ = effective_type(raw, summary_fields)
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
                "type": eff_type_value,
            }
        )
    if published_urls or published_topics:
        before_exclude = len(items)
        items = exclude_published(items, published_urls or set(), published_topics or set())
        cross_excluded = before_exclude - len(items)
    else:
        cross_excluded = 0
    deduped = dedup_candidates(items)
    in_issue_dedup = len(items) - len(deduped)
    admitted = [it for it in deduped if it["compositeScore"] >= ADMISSION_FLOOR]
    below_floor = len(deduped) - len(admitted)
    if below_floor:
        logger.info(
            "candidates_below_admission_floor",
            extra={"dropped": below_floor, "floor": ADMISSION_FLOOR},
        )
    top = truncate_diverse(admitted, daily_count)
    if stats_out is not None:
        stats_out.update(
            {
                "cross_issue_excluded": cross_excluded,
                "in_issue_dedup": in_issue_dedup,
                "below_floor": below_floor,
                "truncated": len(admitted) - len(top),
            }
        )
    # Map surviving idx back to (raw, summary_fields) pairs, preserving
    # the descending-composite order produced by truncate_top_n.
    by_idx = {item["idx"]: (candidates[item["idx"]][0], candidates[item["idx"]][1])
              for item in top}
    return [by_idx[item["idx"]] for item in top if item["idx"] in by_idx]


__all__ = ["generate_issue"]
