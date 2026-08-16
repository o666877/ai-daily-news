"""LLM client: Anthropic-compatible adapter (T033).

Wraps the official Anthropic SDK with `base_url`/`api_key`/`model` config so
deployers can point at OneAPI/DeepSeek/Moonshot compatible endpoints.

Returns structured `SummaryResult` via JSON-mode prompt.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from typing import Any

try:
    import anthropic  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    anthropic = None  # type: ignore[assignment]

from app.config import get_settings

# 4 valid type values (must match TypeKey enum in app.models.meta).
_VALID_TYPES = {"agent", "self_improve", "open_source", "tools"}

logger = logging.getLogger("aidaily.llm")


class LLMProviderError(Exception):
    """Raised when LLM provider call fails after retries."""


class LLMRateLimitError(LLMProviderError):
    """Transient 429 / rate-limit from provider. Retryable — subclass of
    LLMProviderError so existing tenacity policy picks it up. Distinct from
    PipelineBusyError (budget exhaustion, non-retryable)."""


@dataclass(frozen=True)
class SummaryResult:
    """Structured summary returned by LLM for a single RawItem."""

    title: str
    lede: str
    summary: str
    # Markdown body (single string). Allowed subset: paragraphs, **bold**,
    # `inline code`, [links](url), bullet lists, > quotes. No headings,
    # tables, fenced code blocks or HTML — renderer whitelist matches.
    body: str
    quote: str | None
    points: list[str]
    # US1 scoring/dedup fields (research.md D4). authority is informational —
    # the system rule (classify_authority) overrides it downstream.
    dimension_scores: dict[str, int] | None = None
    authority_tier: str | None = None
    topic_id: str | None = None
    opinion_fingerprint: str | None = None
    # US1 computed fields (set by summarizer._augment_with_scoring or
    # _rule_fallback_summary, not directly by LLM).
    composite_score: int | None = None
    score_source: str | None = None
    # Type field (parsed from LLM JSON). One of "agent"/"self_improve"/
    # "open_source"/"tools", or None if missing/invalid. Generator overrides
    # articles.type with this when valid; otherwise rule suggestedType wins.
    llm_type: str | None = None


SYSTEM_PROMPT = """你是一名 AI 新闻编辑，负责把英文或混合语种的原始内容整理成中文简报。

【语言硬性要求 — 不可违反】
1. 无论原文是中文、英文还是其他语言，所有输出字段（title / lede / summary / body / quote / points）必须以简体中文为主。
2. quote 字段必须输出中文翻译版本；如果原文是英文/外文，必须翻译为中文，不允许直接复制原文。
3. summary / lede / points 字段同样必须以中文呈现，不允许直接保留外文原文。
4. 唯一允许保留外文的情况：专有名词（如 GPT、Claude、GitHub、PyTorch、OpenAI）、技术术语（如 LLM、RLHF）、代码标识符、URL。
5. 如果原文字符数不足以翻译为完整中文，请基于原文意思重写为通顺中文，而非复制原文。
6. 不得把人名、公司名音译；OpenAI 必须保留为 OpenAI，Elon Musk 可写为「马斯克」。

【输出格式】
输出严格的 JSON 对象，包含以下字段：
- title (string)：不超过 40 个汉字的中文标题；根据原标题重新撰写，不得简单音译或字母拼装；保留对识别有帮助的关键专有名词。
- lede (string)：60-120 个汉字的导语段落，概括新闻核心。
- summary (string)：一句话要点，不超过 80 个汉字。
- body (string)：2-4 段正文，单个 markdown 字符串（段落之间用空行分隔）。必须主动使用以下语法提升可读性：关键术语/项目名/公司名用 **粗体**；命令、API 名、代码标识符用 `行内代码`；提及相关项目或文档时可附 [链接](url)；并列特性可用无序列表。只允许：段落、粗体、行内代码、链接、无序列表、> 引用。禁止：标题（#）、表格、三反引号代码块、任何 HTML 标签。
- quote (string|null)：值得保留的引用，必须为中文；若原文非中文请翻译；无可引用则填 null。
- points (string[])：3-5 条要点，每条不超过 60 个汉字。
- type (string)：文章类型，必须是以下 4 个值之一："agent" / "self_improve" / "open_source" / "tools"。判定标准如下，**若不确定，优先选 "tools"**（tools 是兜底类，纯新闻 / 行业事件 / 安全研究都归此）：
  - "agent"：AI 助手产品、agent 框架、agent 评测基准、对话能力本身（autogen、langgraph、MCP、Claude/GPT 对话能力、agent benchmark）。
    例：「LangGraph 发布 1.0，正式支持多 agent 协作」
    反例：「Karpathy 评论 agent 能力被低估」→ 这种观点/评论应归 "tools"（行业观点）
  - "self_improve"：**仅限**模型自身的训练 / 微调 / RLHF / 持续学习 / 记忆机制 / agent 自进化的方法或论文。
    例：「论文：测试时通过记忆与持续学习提升 agent 表现」
    反例（**不要归此**）：思维链提取攻击、模型安全/隐私漏洞研究、对模型内部机制的分析揭秘 → 这类关于"安全/隐私/破解"的研究归 "tools"。
  - "open_source"：**仅限**有明确开源动作的内容 —— 新模型/数据集/工具发布并开放权重或源码、GitHub 仓库介绍、Apache/MIT 协议公告。
    例：「Meta 开源 Muse Glimmer，Apache 2.0 协议」
    反例（**不要归此**）：仅仅是讨论某个开源项目、教程/课程/科普视频、闭源模型新版本发布 → 归 "tools" 或对应技术类。
    加权规则：**来源为 GitHub 仓库的条目默认归 "open_source"**，除非其内容核心是对 agent 机制本身的深度解读。
  - "tools"：兜底类。效率工具、产品发布（非开源）、榜单、融资、会议、行业报告、**安全/隐私/漏洞研究**、**教育/科普/课程内容**、纯新闻报道、行业观点评论。
    例 1：「OpenAI o1 思维链遭窃取，7000 份样本泄露个人数据」
    例 2：「Karpathy 重启 YouTube 发布『从头构建 GPT』系列」
    例 3：「YC W25 榜单公布，三家 AI 公司入选」

【评分与去重信号字段】(可选，缺失可置 null)
- dimensionScores (object)：四个维度评分，整数 0-100。authority 字段仅供参考（系统会按来源规则覆盖），其余 depth / timeliness / expression 由你按内容判断。
  - depth：内容深度/信息密度（结构化要点、技术细节、引用数据 = 高分）。
  - timeliness：与"当下"的相关度（突发新闻、首次发布 = 高分）。
  - expression：表达力（叙事张力、金句、清晰度）。
- topicId (string|null)：文章所述事件核心实体（产品/项目/事件主名称）的规范英文标识符（小写、kebab-case）。**同一事件的所有报道必须生成完全相同的 topicId**：以实体名本身为主干，不要附加报道角度后缀。例：GPT-5 发布 → "gpt-5"（无论公告、评测还是复述）；Claude 4.7 上线 → "claude-4-7"；STORM 项目 → "storm"。长度 ≤128 字符。无法判断时填 null。
- opinionFingerprint (string|null)：观点指纹，格式必须是 **"主题实体:观点类型"**（如 "gpt-5:official-announcement"、"storm:first-person-praise"）。**禁止**输出不含实体的泛化标签（单独的 "official-announcement"、"open-source-release" 这类体裁标签会导致不同事件被误判为转载）。同一事件下的同质化报道才用相同指纹。长度 ≤128 字符。无法判断时填 null。

只返回 JSON 对象，禁止任何 markdown 代码块标记、解释或前缀文字。"""


TRANSLATION_SYSTEM_PROMPT = """你是一名专业的中英翻译。任务：把用户给的英文或外文内容翻译为简体中文。

硬性要求：
1. 输出必须是简体中文。
2. 唯一允许保留外文的情况：专有名词（如 GPT、Claude、PyTorch、GitHub、OpenAI）、产品名、代码标识符。
3. 不允许直接复制原文；必须翻译或重写为通顺中文。
4. 只返回翻译结果，不要解释、不要 markdown、不要前后缀文字。"""


def _fallback_title(lede: str) -> str:
    """Derive a Chinese title from lede when LLM omits the title field."""
    cleaned = (lede or "").strip().replace("\n", " ")
    return cleaned[:40] if cleaned else "未命名报道"


def _is_mostly_chinese(text: str | None) -> bool:
    """True iff text reads as Chinese: ratio≥0.30 AND no long contiguous English run.

    Two-stage check:
    1. chinese_chars / (chinese_chars + ascii_letters) >= 0.30 — lets short
       proper-noun-heavy quotes like "OpenAI 发布 GPT-5" (4/11=0.36) pass.
    2. No contiguous ASCII letter run longer than 8 chars — catches mixed
       strings where LLM kept the English original as a parenthetical, e.g.
       "该项目被定位为 'A workbench for language model research'（一个...）"
       has ratio 0.38 (passes stage 1) but contains "workbench" (9 chars),
       "language" (8), "research" (8) → fails stage 2.

    Proper nouns (OpenAI=6, Claude=6, PyTorch=7, Anthropic=9) — note
    Anthropic would trip stage 2. We keep threshold at 9 so PyTorch/GitHub
    (6/6) pass but a real English word like "workbench" (9) gets flagged.
    """
    if text is None:
        return True
    s = str(text)
    if not s:
        return True
    chinese_chars = sum(1 for ch in s if "一" <= ch <= "鿿")
    ascii_letters = sum(1 for ch in s if ch.isascii() and ch.isalpha())
    denom = chinese_chars + ascii_letters
    if denom == 0:
        return True
    if chinese_chars / denom < 0.30:
        return False
    # Find longest contiguous ASCII-letter run; >8 → likely untranslated prose.
    import re

    longest_run = max((len(m.group(0)) for m in re.finditer(r"[A-Za-z]+", s)), default=0)
    return longest_run <= 8


async def _translate_field(client: "LLMClient", text: str) -> str:
    """Call LLM to translate a single short field; raise LLMProviderError on failure."""
    prompt = f"请将以下内容翻译为简体中文（保留专有名词原样）：\n{text}"
    raw = await client.complete_json(
        prompt=prompt, system=TRANSLATION_SYSTEM_PROMPT, max_tokens=400
    )
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        lines = [ln for ln in lines if not ln.startswith("```")]
        cleaned = "\n".join(lines).strip()
    return cleaned or text


async def _ensure_chinese(
    result: SummaryResult, client: "LLMClient", original_text: str
) -> SummaryResult:
    """Post-process: re-translate any field that came back non-Chinese.

    For each of title/summary/lede/quote/points[*], if _is_mostly_chinese is
    False, issue a focused translation call. On translation error, keep the
    original (do not loop). original_text reserved for future context-aware
    retry; currently unused but accepted for symmetry with caller.
    """
    title = result.title
    lede = result.lede
    summary = result.summary
    quote = result.quote
    points = list(result.points)

    # Title
    if title and not _is_mostly_chinese(title):
        try:
            title = await _translate_field(client, title)
        except Exception as exc:  # noqa: BLE001 — never break on post-process
            logger.warning("ensure_chinese.title_failed error=%s", exc)

    # Lede
    if lede and not _is_mostly_chinese(lede):
        try:
            lede = await _translate_field(client, lede)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ensure_chinese.lede_failed error=%s", exc)

    # Summary
    if summary and not _is_mostly_chinese(summary):
        try:
            summary = await _translate_field(client, summary)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ensure_chinese.summary_failed error=%s", exc)

    # Quote
    if quote and not _is_mostly_chinese(quote):
        try:
            quote = await _translate_field(client, quote)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ensure_chinese.quote_failed error=%s", exc)

    # Points
    translated_points: list[str] = []
    for p in points:
        if p and not _is_mostly_chinese(p):
            try:
                translated_points.append(await _translate_field(client, p))
            except Exception as exc:  # noqa: BLE001
                logger.warning("ensure_chinese.point_failed error=%s", exc)
                translated_points.append(p)
        else:
            translated_points.append(p)

    return replace(
        result,
        title=title,
        lede=lede,
        summary=summary,
        quote=quote,
        points=translated_points,
    )


def _build_prompt(title: str, source: str, raw_text: str) -> str:
    return (
        f"Title: {title}\n"
        f"Source: {source}\n\n"
        f"Raw content:\n{raw_text[:8000]}\n\n"
        "Respond with the JSON object now."
    )


def normalize_type(value: object) -> str | None:
    """Normalize an LLM-returned type value to a valid TypeKey value or None.

    Accepts lowercase / uppercase / spaces / hyphens. Returns the canonical
    snake_case value if it matches a known TypeKey, else None.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    s = value.strip().lower().replace(" ", "_").replace("-", "_")
    if s in _VALID_TYPES:
        return s
    return None


def _parse_body_field(raw: object) -> str:
    """Coerce LLM body output to a single markdown string.

    Boundary tolerance for uncontrollable LLM output: accepts a string
    (pass-through), a legacy array of paragraphs (joined with blank lines,
    empty segments dropped), or null/missing → "".
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, (list, tuple)):
        return "\n\n".join(str(p).strip() for p in raw if str(p).strip())
    # dict/int/other shapes carry no narrative value — empty body lets the
    # generator fall back to the raw title instead of persisting a repr().
    return ""


def _parse_summary_response(text: str) -> SummaryResult:
    """Parse LLM JSON response into SummaryResult. Raises LLMProviderError on malformed."""
    # Strip markdown code fences if present.
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = [ln for ln in lines if not ln.startswith("```")]
        text = "\n".join(lines)
    try:
        data: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMProviderError(f"LLM returned non-JSON: {exc}") from exc
    lede = str(data.get("lede", "")).strip()
    title_raw = str(data.get("title", "")).strip()
    title = title_raw if title_raw else _fallback_title(lede)

    # US1 scoring/dedup fields (camelCase from LLM → snake_case here).
    # Tolerate missing/null: result fields stay None.
    dim_scores_raw = data.get("dimensionScores")
    dimension_scores: dict[str, int] | None = None
    if isinstance(dim_scores_raw, dict):
        # Keep only valid int-like values; LLM may return partial dict.
        sanitized: dict[str, int] = {}
        for k, v in dim_scores_raw.items():
            try:
                sanitized[str(k)] = int(v)
            except (ValueError, TypeError):
                continue
        if sanitized:
            dimension_scores = sanitized

    topic_id_raw = data.get("topicId")
    topic_id = str(topic_id_raw).strip() if topic_id_raw is not None else None

    opinion_raw = data.get("opinionFingerprint")
    opinion_fingerprint = (
        str(opinion_raw).strip() if opinion_raw is not None else None
    )

    llm_type = normalize_type(data.get("type"))

    return SummaryResult(
        title=title,
        lede=lede,
        summary=str(data.get("summary", "")).strip(),
        body=_parse_body_field(data.get("body")),
        quote=data.get("quote"),
        points=[str(p) for p in data.get("points", []) if str(p).strip()],
        dimension_scores=dimension_scores,
        topic_id=topic_id,
        opinion_fingerprint=opinion_fingerprint,
        llm_type=llm_type,
    )


class LLMClient:
    """Single Anthropic-compatible client."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        s = get_settings()
        self.base_url = base_url or s.llm_base_url
        self.api_key = api_key or s.llm_api_key or "test-key"
        self.model = model or s.llm_model
        self._client = None
        if anthropic is not None:
            try:
                self._client = anthropic.Anthropic(
                    base_url=self.base_url,
                    api_key=self.api_key,
                    max_retries=0,  # we use tenacity at caller level
                )
            except Exception:  # pragma: no cover - construction rarely fails
                self._client = None

    async def complete_json(
        self,
        prompt: str,
        system: str = SYSTEM_PROMPT,
        *,
        max_tokens: int = 1200,
    ) -> str:
        """Call LLM and return raw text response.

        Raises LLMRateLimitError on 429 (retryable via tenacity);
        LLMProviderError on other transport failures.
        """
        if self._client is None:
            raise LLMProviderError("Anthropic SDK unavailable")
        try:
            # SDK is sync; run in thread executor.
            import asyncio

            def _call() -> str:
                resp = self._client.messages.create(  # type: ignore[union-attr]
                    model=self.model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                )
                # Concatenate text blocks.
                chunks: list[str] = []
                for block in resp.content:
                    txt = getattr(block, "text", None)
                    if txt:
                        chunks.append(txt)
                # Track token usage.
                if resp.usage is not None:
                    logger.info(
                        "llm_tokens",
                        extra={
                            "component": "llm",
                            "input_tokens": getattr(resp.usage, "input_tokens", 0),
                            "output_tokens": getattr(resp.usage, "output_tokens", 0),
                        },
                    )
                return "".join(chunks)

            return await asyncio.to_thread(_call)
        except Exception as exc:
            # Detect rate limit (Anthropic raises RateLimitError; status 429).
            # Transient — surface as LLMRateLimitError so tenacity retries,
            # then rule_fallback if still failing. Budget exhaustion still
            # raises PipelineBusyError from check_budget (non-retryable).
            cls = type(exc).__name__
            if "RateLimit" in cls or "rate_limit" in str(exc).lower():
                raise LLMRateLimitError("LLM 限流") from exc
            raise LLMProviderError(f"LLM call failed: {exc}") from exc

    async def summarize(self, title: str, source: str, raw_text: str) -> SummaryResult:
        """Convenience: build prompt + parse result + ensure Chinese output."""
        prompt = _build_prompt(title, source, raw_text)
        raw = await self.complete_json(prompt)
        result = _parse_summary_response(raw)
        # Hard guarantee: re-translate any field that came back non-Chinese.
        # Failures here must never break the main summarization flow.
        try:
            result = await _ensure_chinese(result, self, raw_text)
        except Exception as exc:  # noqa: BLE001 — defensive
            logger.warning("ensure_chinese.skipped error=%s", exc)
        return result


__all__ = [
    "LLMClient",
    "LLMProviderError",
    "LLMRateLimitError",
    "SummaryResult",
    "TRANSLATION_SYSTEM_PROMPT",
    "_ensure_chinese",
    "_is_mostly_chinese",
    "normalize_type",
]
