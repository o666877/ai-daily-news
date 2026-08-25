"""Spec 006 / Ticket 02: 企微 webhook 发送 — respx 只挡 qyapi 外部边界."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.pipeline.wecom import send_markdown

BASE_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
URL_A = f"{BASE_URL}?key=abcd1234efgh5678"
URL_B = f"{BASE_URL}?key=wxyz9876abcd4321"


def _ok_body() -> dict:
    return {"errcode": 0, "errmsg": "ok"}


@pytest.mark.asyncio
@respx.mock
async def test_success_returns_ok() -> None:
    route = respx.post(URL_A).mock(return_value=httpx.Response(200, json=_ok_body()))
    result = await send_markdown(URL_A, "hello")
    assert result.ok is True
    assert result.errcode == 0
    assert route.call_count == 1
    body = route.calls.last.request.content
    assert b"markdown" in body and b"hello" in body


@pytest.mark.asyncio
@respx.mock
async def test_500_then_success_retries() -> None:
    route = respx.post(URL_A).mock(
        side_effect=[
            httpx.Response(500, text="boom"),
            httpx.Response(200, json=_ok_body()),
        ]
    )
    result = await send_markdown(URL_A, "hello")
    assert result.ok is True
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_rate_limited_http_45009_then_success_retries() -> None:
    route = respx.post(URL_A).mock(
        side_effect=[
            httpx.Response(45009, json={"errcode": 45009, "errmsg": "api limited"}),
            httpx.Response(200, json=_ok_body()),
        ]
    )
    result = await send_markdown(URL_A, "hello")
    assert result.ok is True
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_errcode_rate_limit_in_200_body_retries() -> None:
    route = respx.post(URL_A).mock(
        side_effect=[
            httpx.Response(200, json={"errcode": 45009, "errmsg": "api limited"}),
            httpx.Response(200, json=_ok_body()),
        ]
    )
    result = await send_markdown(URL_A, "hello")
    assert result.ok is True
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_invalid_webhook_fails_fast_without_retry() -> None:
    route = respx.post(URL_A).mock(
        return_value=httpx.Response(200, json={"errcode": 93000, "errmsg": "invalid webhook"})
    )
    result = await send_markdown(URL_A, "hello")
    assert result.ok is False
    assert result.errcode == 93000
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_exhausted_retries_returns_failure() -> None:
    route = respx.post(URL_A).mock(return_value=httpx.Response(500, text="down"))
    result = await send_markdown(URL_A, "hello")
    assert result.ok is False
    assert route.call_count == 4  # 1 initial + 3 retries


@pytest.mark.asyncio
@respx.mock
async def test_malformed_errcode_fails_fast_without_raise() -> None:
    route = respx.post(URL_A).mock(
        return_value=httpx.Response(200, json={"errcode": "abc", "errmsg": "junk"})
    )
    result = await send_markdown(URL_A, "hello")
    assert result.ok is False
    assert route.call_count == 1
    assert URL_A not in result.errmsg


@pytest.mark.asyncio
@respx.mock
async def test_push_to_webhooks_fans_out_and_isolates_failures() -> None:
    from app.pipeline.wecom import push_to_webhooks

    ok_route = respx.post(URL_A).mock(
        return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})
    )
    bad_route = respx.post(URL_B).mock(return_value=httpx.Response(500, text="down"))
    results = await push_to_webhooks(
        [
            {"name": "a", "url": URL_A},
            {"name": "b", "url": URL_B},
            {"name": "c"},  # 缺 url:跳过但不中断
        ],
        "hello",
    )
    assert ok_route.call_count == 1
    assert bad_route.call_count == 4  # b 走满重试
    by_name = dict(results)
    assert by_name["a"].ok is True
    assert by_name["b"].ok is False
    assert by_name["c"].ok is False


@pytest.mark.asyncio
@respx.mock
async def test_transport_error_returns_failure_without_url_leak() -> None:
    respx.post(URL_A).mock(side_effect=httpx.ConnectError("Connection refused"))
    result = await send_markdown(URL_A, "hello")
    assert result.ok is False
    # 错误信息绝不含完整 webhook URL
    assert URL_A not in result.errmsg
    assert "abcd1234efgh5678" not in result.errmsg
    assert "ConnectError" in result.errmsg


@pytest.mark.asyncio
@respx.mock
async def test_send_targets_only_given_url() -> None:
    a = respx.post(URL_A).mock(return_value=httpx.Response(200, json=_ok_body()))
    b = respx.post(URL_B).mock(return_value=httpx.Response(200, json=_ok_body()))
    await send_markdown(URL_B, "hello")
    assert a.call_count == 0
    assert b.call_count == 1
