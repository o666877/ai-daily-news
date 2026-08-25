"""Spec 006 / Ticket 03: 生成 ready → 自动推送 + 记录 + 防重.

走 generate_issue 全流程(collector/summarizer monkeypatch,与
test_settings_effect 同接缝);respx 只挡 qyapi 外部边界。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import select

from app.infra.db import get_session_factory
from app.models.im_push_log import ImPushLogORM
from app.pipeline import generator as gen_mod
from app.pipeline import summarizer

AUTH = {"Authorization": "Bearer test-bearer-token"}

URL_A = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcd1234efgh5678"
URL_B = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=wxyz9876abcd4321"

BASE_BODY = {
    "sources": {"x": True, "github": True, "reddit": True, "web": True},
    "types": {
        "agent": True,
        "self_improve": True,
        "open_source": True,
        "tools": True,
        "commentary": True,
    },
    "dailyPush": {"enabled": True, "time": "08:00"},
    "dailyCount": 15,
}


def _raw_item(url: str, title: str) -> Any:
    from app.models.article import RawItem
    from app.models.meta import SourceKey

    return RawItem(
        sourceKey=SourceKey.X,
        sourceUrl=url,
        sourceName="x.com",
        title=title,
        rawText="body " * 50,
        publishedAt=datetime.now(timezone.utc).isoformat(),
    )


def _summary(title: str, composite: int) -> SimpleNamespace:
    return SimpleNamespace(
        title=title,
        summary=f"{title} 的一句话摘要",
        lede=f"{title} 的导语",
        body=f"{title} 的正文",
        llm_type="agent",
        composite_score=composite,
        dimension_scores={"dim_authority": 70, "dim_novelty": 80, "dim_engagement": 60},
        authority_tier="community",
        score_source="llm",
        topic_id=f"topic-{title}",
        opinion_fingerprint=f"fp-{title}",
        quote=None,
        points=["p1"],
    )


def _install_pipeline(monkeypatch, items: list[tuple[Any, SimpleNamespace]]) -> None:
    raws = [r for r, _ in items]

    async def fake_collect_all() -> list[Any]:
        return raws

    async def fake_summarize_item(raw: Any, client: Any = None) -> SimpleNamespace:
        return dict((id(r), s) for r, s in items)[id(raw)]

    monkeypatch.setattr(gen_mod, "collect_all", fake_collect_all)
    monkeypatch.setattr(summarizer, "summarize_item", fake_summarize_item)


async def _save_im_push(
    client: httpx.AsyncClient,
    *,
    enabled: bool = True,
    top_n: int = 5,
    link_base: str = "https://daily.example.com",
    webhooks: list[dict],
) -> None:
    body = dict(BASE_BODY)
    body["imPush"] = {
        "enabled": enabled,
        "topN": top_n,
        "linkBaseUrl": link_base,
        "webhooks": webhooks,
    }
    res = await client.put("/api/v1/settings", json=body, headers=AUTH)
    assert res.status_code == 200, res.text


def _tomorrow() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=1)


async def _log_rows() -> list[ImPushLogORM]:
    factory = get_session_factory()
    async with factory() as s:
        return list(
            (
                await s.execute(select(ImPushLogORM).order_by(ImPushLogORM.id))
            ).scalars().all()
        )


def _sent_markdown(route: respx.Route) -> str:
    sent = json.loads(route.calls.last.request.content.decode("utf-8"))
    return sent["markdown"]["content"]


@pytest.mark.asyncio
@respx.mock
async def test_ready_issue_pushes_and_logs(client, monkeypatch):
    await _save_im_push(
        client, webhooks=[{"name": "main", "url": URL_A}], top_n=5
    )
    _install_pipeline(
        monkeypatch,
        [(_raw_item("https://x/1", "低分文"), _summary("低分文标题", 60)),
         (_raw_item("https://x/2", "高分文"), _summary("高分文标题", 92))],
    )
    route = respx.post(URL_A).mock(
        return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})
    )

    issue = await gen_mod.generate_issue(date=_tomorrow())
    assert issue.status == "ready"

    assert route.call_count == 1
    content = _sent_markdown(route)
    assert "高分文标题" in content and "低分文标题" in content
    assert "高分文标题 的一句话摘要" in content
    assert "https://daily.example.com/" in content

    rows = await _log_rows()
    assert len(rows) == 1
    assert rows[0].issue_id == issue.id
    assert rows[0].webhook_name == "main"
    assert rows[0].ok is True


@pytest.mark.asyncio
@respx.mock
async def test_top_n_limits_items(client, monkeypatch):
    await _save_im_push(
        client, webhooks=[{"name": "main", "url": URL_A}], top_n=3
    )
    _install_pipeline(
        monkeypatch,
        [
            (_raw_item(f"https://x/{i}", f"文{i}"), _summary(f"标题{i}", composite))
            for i, composite in enumerate([92, 80, 60, 40], start=1)
        ],
    )
    route = respx.post(URL_A).mock(
        return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})
    )

    await gen_mod.generate_issue(date=_tomorrow())
    content = _sent_markdown(route)
    assert "标题1" in content and "标题2" in content and "标题3" in content
    assert "标题4" not in content  # topN=3 截断


@pytest.mark.asyncio
@respx.mock
async def test_no_link_base_degrades(client, monkeypatch):
    await _save_im_push(
        client, webhooks=[{"name": "main", "url": URL_A}], link_base=""
    )
    _install_pipeline(
        monkeypatch, [(_raw_item("https://x/1", "文"), _summary("标题", 70))]
    )
    route = respx.post(URL_A).mock(
        return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})
    )
    await gen_mod.generate_issue(date=_tomorrow())
    content = _sent_markdown(route)
    assert "http" not in content


@pytest.mark.asyncio
@respx.mock
async def test_regenerate_ready_issue_is_idempotent_and_dedup(client, monkeypatch):
    await _save_im_push(
        client, webhooks=[{"name": "main", "url": URL_A}]
    )
    _install_pipeline(
        monkeypatch, [(_raw_item("https://x/1", "文"), _summary("标题", 70))]
    )
    route = respx.post(URL_A).mock(
        return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})
    )

    await gen_mod.generate_issue(date=_tomorrow())
    # 幂等重入:ready 早退,不再触发推送
    await gen_mod.generate_issue(date=_tomorrow())
    assert route.call_count == 1

    # 手动再调 dispatch:防重跳过(已有 ok 记录)
    from app.pipeline.im_push import dispatch_daily_push

    await dispatch_daily_push(datetime.strftime(_tomorrow(), "%Y%m%d"))
    assert route.call_count == 1
    rows = await _log_rows()
    assert len(rows) == 1


@pytest.mark.asyncio
@respx.mock
async def test_partial_webhook_failure_isolated_and_issue_still_ready(client, monkeypatch):
    await _save_im_push(
        client,
        webhooks=[
            {"name": "good", "url": URL_A},
            {"name": "bad", "url": URL_B},
        ],
    )
    _install_pipeline(
        monkeypatch, [(_raw_item("https://x/1", "文"), _summary("标题", 70))]
    )
    respx.post(URL_A).mock(
        return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})
    )
    respx.post(URL_B).mock(return_value=httpx.Response(500, text="down"))

    issue = await gen_mod.generate_issue(date=_tomorrow())
    assert issue.status == "ready"  # 推送失败不拖垮生成

    rows = {(r.webhook_name): r for r in await _log_rows()}
    assert rows["good"].ok is True
    assert rows["bad"].ok is False


@pytest.mark.asyncio
@respx.mock
async def test_all_webhooks_fail_issue_still_ready_log_rows_written(client, monkeypatch):
    await _save_im_push(
        client, webhooks=[{"name": "main", "url": URL_A}]
    )
    _install_pipeline(
        monkeypatch, [(_raw_item("https://x/1", "文"), _summary("标题", 70))]
    )
    respx.post(URL_A).mock(side_effect=httpx.ConnectError("refused"))

    issue = await gen_mod.generate_issue(date=_tomorrow())
    assert issue.status == "ready"

    rows = await _log_rows()
    assert len(rows) == 1
    assert rows[0].ok is False
    assert URL_A not in (rows[0].errmsg or "")


@pytest.mark.asyncio
@respx.mock
async def test_disabled_push_is_zero_behaviour(client, monkeypatch):
    await _save_im_push(
        client, enabled=False, webhooks=[{"name": "main", "url": URL_A}]
    )
    _install_pipeline(
        monkeypatch, [(_raw_item("https://x/1", "文"), _summary("标题", 70))]
    )
    route = respx.post(URL_A).mock(
        return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})
    )

    issue = await gen_mod.generate_issue(date=_tomorrow())
    assert issue.status == "ready"
    assert route.call_count == 0
    assert await _log_rows() == []


@pytest.mark.asyncio
@respx.mock
async def test_failed_issue_never_pushes(client, monkeypatch):
    await _save_im_push(
        client, webhooks=[{"name": "main", "url": URL_A}]
    )
    # 采集有内容但摘要全失败 → all_failed → status=failed → 不推送
    async def fake_collect_all() -> list[Any]:
        return [_raw_item("https://x/1", "文")]

    async def boom(raw: Any, client: Any = None) -> SimpleNamespace:
        raise summarizer.SummarizerFailure("llm down")

    monkeypatch.setattr(gen_mod, "collect_all", fake_collect_all)
    monkeypatch.setattr(summarizer, "summarize_item", boom)
    route = respx.post(URL_A).mock(
        return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})
    )

    issue = await gen_mod.generate_issue(date=_tomorrow())
    assert issue.status == "failed"
    assert route.call_count == 0
