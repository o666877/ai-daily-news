"""企业微信群机器人 notifier (specs/006 ticket 02).

函数边界:渲染(markdown,超限截断保链接)+ 发送(tenacity 重试)。
不建 Notifier 协议/注册表——第二个渠道出现时再加抽象。
webhook URL 是凭据:错误信息与日志永不包含完整 URL。
"""

from __future__ import annotations

import logging
import os
import ssl

import httpx
from pydantic import BaseModel
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger("aidaily.wecom")

WECOM_MARKDOWN_BYTE_LIMIT = 4096
_MAX_ATTEMPTS = 4  # 1 initial + 3 retries → waits 2s/4s/8s (env-scalable)
_RETRYABLE_HTTP = {429, 45009}
_RETRYABLE_ERRCODES = {45009}


class WecomSendResult(BaseModel):
    """单次发送结果。errmsg 已脱敏,不含 URL。"""

    ok: bool
    errcode: int | None = None
    errmsg: str = ""


class _RetryableWecomError(Exception):
    """网络错误 / 限频 / 5xx —— 可安全重试。"""


def _retry_backoff_s() -> float:
    """Backoff base. Overridable via AIDAILY_WECOM_RETRY_BACKOFF_S (tests use 0)."""
    raw = os.environ.get("AIDAILY_WECOM_RETRY_BACKOFF_S", "").strip()
    try:
        return float(raw) if raw else 2.0
    except ValueError:
        return 2.0


# ---------------------------------------------------------------------------
# Rendering (pure)
# ---------------------------------------------------------------------------


def render_test_markdown() -> str:
    return "**AI 日报推送测试**\n配置成功。日报生成后将自动推送到本群。"


def render_daily_markdown(
    *,
    title: str,
    date_label: str,
    items: list[tuple[str, str]],
    link: str | None,
) -> str:
    """Render the daily digest as wecom markdown within the byte limit.

    Items are dropped (then summaries clipped) to stay under the limit;
    the header and the full-daily link always survive. `link=None` means
    no reachable base URL — degrade to items-only, no link section.
    """
    header = f"**{title} · {date_label}**\n"
    link_block = f"\n[查看完整日报]({link})" if link else ""

    budget = WECOM_MARKDOWN_BYTE_LIMIT - _utf8_len(header) - _utf8_len(link_block)
    if budget <= 0:
        # header+链接本身超限(极长 base_url):只剩裁剪后的头尾,无条目空间
        return _clip_utf8(header + link_block, WECOM_MARKDOWN_BYTE_LIMIT)
    lines: list[str] = []
    used = 0
    for idx, (item_title, summary) in enumerate(items, start=1):
        block = f"{idx}. **{item_title}**\n{summary}\n\n"
        if _utf8_len(block) + used > budget:
            if not lines:
                # 第一条也放不下:整块硬裁(保标题前缀与链接,砍摘要/标题尾部)
                lines.append(_clip_utf8(f"{idx}. **{item_title}**\n{summary}\n", budget))
            break
        lines.append(block)
        used += _utf8_len(block)

    body = header + "".join(lines).rstrip("\n") + link_block
    return _clip_utf8(body, WECOM_MARKDOWN_BYTE_LIMIT)


def _utf8_len(s: str) -> int:
    return len(s.encode("utf-8"))


def _clip_utf8(s: str, max_bytes: int) -> str:
    """Truncate to at most max_bytes of UTF-8 without splitting a char."""
    encoded = s.encode("utf-8")
    if len(encoded) <= max_bytes:
        return s
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


# ---------------------------------------------------------------------------
# Sending (IO, retried)
# ---------------------------------------------------------------------------


async def send_markdown(url: str, content: str) -> WecomSendResult:
    """POST a markdown message to one wecom bot webhook.

    Retries network errors / rate limits / 5xx up to 3 attempts with
    exponential backoff; invalid-webhook style errors fail fast. Never
    raises — failures come back as WecomSendResult(ok=False).
    """
    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    try:
        # trust_env=False: qyapi 是固定直连域名;跳过系统代理探测既省每次
        # ~0.7s 的启动开销,也避免带 key 的 URL 被转发给未知代理。
        async with httpx.AsyncClient(
            timeout=10.0, trust_env=False, verify=_ssl_context()
        ) as client:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type(_RetryableWecomError),
                stop=stop_after_attempt(_MAX_ATTEMPTS),
                wait=wait_exponential(multiplier=_retry_backoff_s()),
                reraise=True,
            ):
                with attempt:
                    return await _send_once(client, url, payload)
    except _RetryableWecomError as exc:
        # httpx 异常的 str 含完整 URL,只取类型名,绝不泄露 key。
        detail = str(exc) if isinstance(exc, _WecomApiError) else type(exc.__cause__).__name__
        result = WecomSendResult(ok=False, errmsg=f"网络错误: {detail}")
        logger.warning("wecom_send_failed errmsg=%s", result.errmsg)
        return result
    return WecomSendResult(ok=False, errmsg="unreachable")  # pragma: no cover - mypy


class _WecomApiError(_RetryableWecomError):
    """Retryable HTTP/errcode rejection, carries a URL-free message."""


_ssl_ctx: ssl.SSLContext | None = None


def _ssl_context() -> ssl.SSLContext:
    """Cached SSL context — creation loads the system cert store (~0.6s on
    Windows); per-send clients reuse it so each send doesn't pay that cost."""
    global _ssl_ctx
    if _ssl_ctx is None:
        _ssl_ctx = httpx.create_ssl_context()
    return _ssl_ctx


async def _send_once(client: httpx.AsyncClient, url: str, payload: dict) -> WecomSendResult:
    try:
        res = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        raise _RetryableWecomError from exc

    if res.status_code >= 500 or res.status_code in _RETRYABLE_HTTP:
        raise _WecomApiError(f"HTTP {res.status_code}")
    try:
        data = res.json()
        errcode = int(data.get("errcode", -1))
    except (ValueError, TypeError):
        # 外部边界:畸形 JSON 或 errcode 非数值 → 直接失败,不重试不抛出
        return WecomSendResult(ok=False, errmsg=f"HTTP {res.status_code} 响应非法")
    errmsg = str(data.get("errmsg", ""))
    if errcode in _RETRYABLE_ERRCODES:
        raise _WecomApiError(f"errcode {errcode}")
    if errcode != 0:
        return WecomSendResult(ok=False, errcode=errcode, errmsg=errmsg or f"errcode {errcode}")
    return WecomSendResult(ok=True, errcode=0, errmsg=errmsg or "ok")


async def push_to_webhooks(
    webhooks: list[dict], content: str
) -> list[tuple[str, WecomSendResult]]:
    """Send one message to every {name, url} webhook; per-webhook results.

    逐 webhook 串行发送(specs/006):一个群失败不影响其他群。
    """
    results: list[tuple[str, WecomSendResult]] = []
    for hook in webhooks:
        url = str(hook.get("url", ""))
        if not url:
            logger.warning("wecom_push_skip webhook=%s reason=missing_url", hook.get("name"))
            results.append(
                (
                    str(hook.get("name", "?")),
                    WecomSendResult(ok=False, errmsg="webhook 配置缺失 url"),
                )
            )
            continue
        result = await send_markdown(url, content)
        logger.info(
            "wecom_push_result webhook=%s ok=%s errcode=%s",
            hook.get("name"),
            result.ok,
            result.errcode,
        )
        results.append((str(hook.get("name", "?")), result))
    return results


__all__ = [
    "WECOM_MARKDOWN_BYTE_LIMIT",
    "WecomSendResult",
    "push_to_webhooks",
    "render_daily_markdown",
    "render_test_markdown",
    "send_markdown",
]
