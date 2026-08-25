"""Spec 006 / Ticket 02: 企微 markdown 渲染 — 纯函数."""

from __future__ import annotations

from app.pipeline.wecom import (
    WECOM_MARKDOWN_BYTE_LIMIT,
    render_daily_markdown,
    render_test_markdown,
)


def _utf8_len(s: str) -> int:
    return len(s.encode("utf-8"))


class TestRenderTestMessage:
    def test_contains_marker_text(self) -> None:
        msg = render_test_markdown()
        assert "AI 日报" in msg
        assert "测试" in msg
        assert _utf8_len(msg) <= WECOM_MARKDOWN_BYTE_LIMIT


class TestRenderDaily:
    ITEMS = [(f"标题{i}", f"摘要{i}") for i in range(1, 6)]

    def test_full_structure_with_link(self) -> None:
        msg = render_daily_markdown(
            title="AI 日报", date_label="2026-08-25", items=self.ITEMS, link="https://d.example.com/daily"
        )
        assert "AI 日报" in msg and "2026-08-25" in msg
        for i in range(1, 6):
            assert f"标题{i}" in msg
            assert f"摘要{i}" in msg
        assert "https://d.example.com/daily" in msg
        assert _utf8_len(msg) <= WECOM_MARKDOWN_BYTE_LIMIT

    def test_no_link_degrades_gracefully(self) -> None:
        msg = render_daily_markdown(
            title="AI 日报", date_label="2026-08-25", items=self.ITEMS, link=None
        )
        assert "标题1" in msg
        assert "查看完整日报" not in msg
        assert "http" not in msg

    def test_truncation_keeps_link_and_stays_within_limit(self) -> None:
        huge = [(f"超长标题{i}" + "字" * 120, "摘要" + "内" * 400) for i in range(30)]
        msg = render_daily_markdown(
            title="AI 日报", date_label="2026-08-25", items=huge, link="https://d.example.com/daily"
        )
        assert _utf8_len(msg) <= WECOM_MARKDOWN_BYTE_LIMIT
        # 链接永远保留
        assert "https://d.example.com/daily" in msg
        # 条目被截断(30 条放不下)
        assert "超长标题30" not in msg
        # 至少有 header + 链接 + 若干条目
        assert "AI 日报" in msg

    def test_single_oversized_item_still_renders_something(self) -> None:
        msg = render_daily_markdown(
            title="AI 日报",
            date_label="2026-08-25",
            items=[("巨标题" + "长" * 3000, "巨摘要" + "细" * 3000)],
            link="https://d.example.com/daily",
        )
        assert _utf8_len(msg) <= WECOM_MARKDOWN_BYTE_LIMIT
        assert "https://d.example.com/daily" in msg
        assert "巨标题" in msg  # 标题保留,摘要被裁
