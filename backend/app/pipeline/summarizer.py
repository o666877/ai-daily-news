"""Summarizer: RawItem → Article with LLM + tenacity retry (T034).

- Max 2 attempts, exponential backoff (1s, 4s) on RateLimitError/APITimeoutError.
- Per-call token logging to llm_calls table (deferred to v2 — we log to JSON for now).
- Daily budget enforcement: raises 9002 (PipelineBusyError) if budget exceeded.
- US1 T018: scoring fields merged into SummaryResult. Authority always
  overridden by classify_authority; composite computed via compose_score.
  LLM failure → rule_fallback path (still returns a SummaryResult, no raise).

SummarizerFailure raised only after retries exhausted AND rule_fallback also
fails (defensive — rule path is pure functions and should never raise).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import get_settings
from app.infra.errors import PipelineBusyError
from app.infra.llm import LLMClient, LLMProviderError, SummaryResult
from app.models.article import RawItem
from app.models.meta import SourceKey, TypeKey
from app.pipeline.authority import classify_authority
from app.pipeline.scorer import (
    compose_score,
    compute_engagement,
    score_with_rules,
)

logger = logging.getLogger("aidaily.summarizer")


class SummarizerFailure(Exception):
    """All retries exhausted AND rule_fallback also failed (defensive)."""


@dataclass(frozen=True)
class DailySpend:
    """Tracks daily LLM USD spend for budget enforcement."""

    spent_usd: float = 0.0
    call_count: int = 0


# Module-level in-memory spend tracker (resets per process).
_daily_spend: DailySpend = DailySpend()


def reset_daily_spend() -> None:
    global _daily_spend
    _daily_spend = DailySpend()


def get_daily_spend() -> DailySpend:
    return _daily_spend


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    """Rough cost estimate: $0.25/MTok input, $1.25/MTok output (Haiku tier)."""
    return (input_tokens * 0.25 + output_tokens * 1.25) / 1_000_000


def check_budget(additional_usd: float = 0.0) -> None:
    """Raise PipelineBusyError (9002) if daily budget would be exceeded."""
    settings = get_settings()
    if _daily_spend.spent_usd + additional_usd > settings.llm_daily_budget_usd:
        raise PipelineBusyError(
            f"日预算超限：已花费 ${_daily_spend.spent_usd:.2f} "
            f"≥ 预算 ${settings.llm_daily_budget_usd:.2f}"
        )


# Tenacity policy: 2 attempts, exp backoff, retry on provider transient errors.
retry_policy = retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((LLMProviderError,)),
    reraise=True,
)


@retry_policy
async def _summarize_with_retry(
    client: LLMClient, title: str, source: str, raw_text: str
) -> SummaryResult:
    """Inner retryable summarization call."""
    # Check budget before each attempt.
    check_budget()
    return await client.summarize(title, source, raw_text)


def _augment_with_scoring(
    result: SummaryResult, item: RawItem
) -> SummaryResult:
    """Override authority via rule + compute composite (US1 T018).

    Mutates a new SummaryResult copy:
    - dim_authority ← classify_authority(item.sourceName) baseline (system rule)
    - authority_tier ← tier from rule
    - composite_score ← compose_score(dimension_scores)
    - score_source stays as-is ('llm' for success path, set elsewhere for fallback)
    """
    tier, dim_authority = classify_authority(item.sourceName)
    existing = result.dimension_scores or {}
    # Start with whatever LLM returned for depth/timeliness/expression;
    # authority and engagement are objective signals computed by rules,
    # never trusted to the LLM. Missing LLM dims default to neutral 50.
    new_dims = {
        "authority": dim_authority,
        "depth": existing.get("depth", 50),
        "timeliness": existing.get("timeliness", 50),
        "expression": existing.get("expression", 50),
        "engagement": compute_engagement(item.sourceKey.value, item.extra),
    }
    composite = compose_score(new_dims)
    return replace(
        result,
        dimension_scores=new_dims,
        authority_tier=tier,
        composite_score=composite,
        score_source="llm",
    )


def _rule_fallback_summary(item: RawItem) -> SummaryResult:
    """Build a SummaryResult purely from rule_fallback path (US1 T018).

    No narrative content (lede/body/etc.) — LLM failed. Only scoring fields
    + minimal title/excerpt derived from rawText.
    """
    scored = score_with_rules(
        item.sourceName,
        item.publishedAt,
        item.rawText,
        source_key=item.sourceKey.value,
        extra=item.extra,
    )
    new_dims = {
        "authority": scored["dim_authority"],
        "depth": scored["dim_depth"],
        "timeliness": scored["dim_timeliness"],
        "expression": scored["dim_expression"],
        "engagement": scored["dim_engagement"],
    }
    composite = compose_score(new_dims)
    # Title fallback: use raw title; lede/summary empty (caller may still persist).
    title = (item.title or "")[:200] or "未命名报道"
    return SummaryResult(
        title=title,
        lede="",
        summary="",
        body="",
        quote=None,
        points=[],
        dimension_scores=new_dims,
        authority_tier=scored["authority_tier"],
        topic_id=None,
        opinion_fingerprint=None,
        composite_score=composite,
        score_source="rule_fallback",
    )


async def summarize_item(
    item: RawItem,
    client: LLMClient | None = None,
    *,
    type_hint: TypeKey | None = None,
) -> SummaryResult:
    """Summarize a single RawItem with rule_fallback safety net.

    Returns SummaryResult always (success: LLM fields + scoring; failure:
    rule-derived scoring + empty narrative). Only raises SummarizerFailure
    if rule path itself fails (defensive — should never happen).

    Raises PipelineBusyError only on budget exhaustion (caller must honor).
    """
    c = client or LLMClient()
    try:
        result = await _summarize_with_retry(
            c, item.title, item.sourceName, item.rawText
        )
    except PipelineBusyError:
        # Budget exhausted — propagate as 9002 to caller (will mark issue failed).
        raise
    except (RetryError, LLMProviderError, SummarizerFailure) as exc:
        logger.warning(
            "summarize_llm_failed_rule_fallback",
            extra={
                "source_url": item.sourceUrl,
                "exception_type": type(exc).__name__,
            },
        )
        return _rule_fallback_summary(item)

    # Approximate cost accounting (Haiku prices; real usage tracked via logging).
    estimated_input = min(len(item.rawText) // 4 + 200, 4000)
    estimated_output = 800
    _track_spend(_estimate_cost(estimated_input, estimated_output))

    # Augment with rule-derived authority override + composite score.
    return _augment_with_scoring(result, item)


def _track_spend(usd: float) -> None:
    global _daily_spend
    _daily_spend = DailySpend(
        spent_usd=_daily_spend.spent_usd + usd,
        call_count=_daily_spend.call_count + 1,
    )


__all__ = [
    "DailySpend",
    "SummarizerFailure",
    "check_budget",
    "get_daily_spend",
    "reset_daily_spend",
    "summarize_item",
]
