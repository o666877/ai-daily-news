"""Dev-only seeding: generate today's issue through the REAL pipeline
(LLM summarizer, 5-dim scoring, dedup, diversity quota) with an injected
collector fixture, for when external networks are unreachable.

Usage: python -m scripts.dev_seed_demo
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.models.article import RawItem
from app.models.meta import SourceKey, TypeKey


def _ts(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _x(text: str, hours: float, author: str = "@ai_insider") -> RawItem:
    return RawItem(
        sourceKey=SourceKey.X,
        sourceName=author,
        sourceUrl=f"https://x.com/{author[1:]}/status/{int(datetime.now().timestamp()*1000)%10**9 + len(text)*7}",
        title=text[:80],
        rawText=text,
        publishedAt=_ts(hours),
        suggestedType=TypeKey.AGENT,
        extra={"author": author},
    )


def _gh(name: str, desc: str, stars: int, hours: float, lang: str = "Python") -> RawItem:
    return RawItem(
        sourceKey=SourceKey.GITHUB,
        sourceName=f"github.com/{name}",
        sourceUrl=f"https://github.com/{name}",
        title=name,
        rawText=f"{name}: {desc} Language: {lang}. Stars: {stars}.",
        publishedAt=_ts(hours),
        suggestedType=TypeKey.OPEN_SOURCE,
        extra={"stars": stars, "language": lang},
    )


def _web(host: str, title: str, body: str, hours: float, stype: TypeKey) -> RawItem:
    return RawItem(
        sourceKey=SourceKey.WEB,
        sourceName=host,
        sourceUrl=f"https://{host}/news/{abs(hash(title)) % 99999}",
        title=title,
        rawText=body,
        publishedAt=_ts(hours),
        suggestedType=stype,
    )


def _reddit(sub: str, title: str, body: str, hours: float) -> RawItem:
    return RawItem(
        sourceKey=SourceKey.REDDIT,
        sourceName=f"reddit.com/r/{sub}",
        sourceUrl=f"https://reddit.com/r/{sub}/comments/{abs(hash(title)) % 99999}",
        title=title,
        rawText=body,
        publishedAt=_ts(hours),
        suggestedType=TypeKey.TOOLS,
    )


async def collect_fixture() -> list[RawItem]:
    return [
        # X — fast-moving agent chatter
        _x(
            "刚试了 Claude Code 的 autonomous mode，让它自己修了 3 个 issue，"
            "全程零干预，diff 质量比上周的 swarm 方案好太多。多 agent 协作的关键"
            "居然是让 subagent 只读不写。附 thread 分析 🧵",
            3,
        ),
        _x(
            "OpenAI 内部据说在测试 agent-native 浏览器，能记住你所有的操作习惯。"
            "如果下周发布会属实，RPA 行业可以直接退休了。信息密度极高的一晚。",
            6,
            "@sama_watch",
        ),
        _x(
            "提醒：用 LangGraph 搭 production agent 的同学，checkpoint 序列化"
            "在 v0.2 有 breaking change，升级前先跑 migration 脚本。踩坑 2 小时换来的教训。",
            10,
            "@py_ml_daily",
        ),
        _x(
            "今天的 agent 生态观察：MCP 已经事实性赢了。三家大厂同时官宣支持，"
            "工具调用层的标准之争基本结束，接下来拼的是 context engineering。",
            14,
            "@ai_insider",
        ),
        # GitHub — stars drive engagement dim
        _gh(
            "mendableai/firecrawl",
            "Turn entire websites into LLM-ready markdown. Crawl + scrape + structured extraction. 30k stars this year.",
            32000,
            5,
            "TypeScript",
        ),
        _gh(
            "stanford-oval/storm",
            "Write Wikipedia-like articles from scratch with LLM+agentic research. Paper-backed. Used by 500+ researchers.",
            14500,
            8,
        ),
        _gh(
            "nerfstudio-project/nerfstudio",
            "NeRF toolbox. Major release 1.1 adds gaussian splatting editor.",
            11800,
            30,
            "Python",
        ),
        _gh(
            "tinygrad-china/miniagent",
            "Minimal agent loop in 300 lines. Educational. No magic.",
            820,
            12,
        ),
        _gh(
            "openai/swarm",
            "Educational framework exploring ergonomic lightweight multi-agent orchestration.",
            17800,
            26,
            "Python",
        ),
        _gh(
            "someone/tiny-llm-util",
            "Small helper script I wrote over the weekend.",
            40,
            4,
            "Python",
        ),
        # Web — official blogs / media
        _web(
            "openai.com",
            "GPT-5 发布：推理、代理与长上下文的三大跃迁",
            "OpenAI 正式发布 GPT-5。推理基准 AIME 提升 18%，代理任务 SWE-bench "
            "达到 71.2%。128k 有效上下文窗口，工具调用可靠性提升 3 倍。"
            "定价与 4o 持平。详见 https://openai.com/gpt-5 发布页。",
            4,
            TypeKey.AGENT,
        ),
        _web(
            "anthropic.com",
            "Claude 4.7 Opus 与 Agent SDK 正式可用",
            "Anthropic 发布 Claude 4.7 Opus：编码能力 SWE-bench 82.4%，"
            "同时推出 Agent SDK（原 Claude Agent SDK），支持 MCP、子代理、"
            "与钩子机制。长任务自主运行可达 8 小时。"
            "详见 https://anthropic.com/claude-4-7。",
            7,
            TypeKey.AGENT,
        ),
        _web(
            "huggingface.co",
            "开源 70B 推理模型 OpenReasoner-N1：数学推理逼近 o1-mini",
            "HuggingFace 联合发布 OpenReasoner-N1-70B，AIME 2026 达 78.3%，"
            "Apache 2.0 协议，权重与训练数据全开源。"
            "包含 2.4M 条验证过的推理链数据集。8×A100 可复现训练。",
            9,
            TypeKey.SELF_IMPROVE,
        ),
        _web(
            "simonwillison.net",
            "对 GPT-5 的第一手评测：代理是真的能干活了",
            "实测 12 个真实任务：航班改签、跨应用报表、代码迁移。"
            "10 个一次通过，2 个需要一次纠偏。错误模式分析："
            "仍会在第 7 步以上的长链推理中丢失约束。附 prompt 与 trace 全文。",
            11,
            TypeKey.AGENT,
        ),
        _web(
            "technologyreview.com",
            "AI 自我改进研究年度盘点：从 RLHF 到自举推理",
            "2026 上半年 23 篇顶会论文梳理：自我奖励、过程监督、"
            "自生成课程三大路线。结论：自我改进在可验证域（数学/代码）"
            "增益稳定 15-30%，开放域仍无突破。",
            20,
            TypeKey.SELF_IMPROVE,
        ),
        _web(
            "latent.space",
            "Context Engineering 深度长文：为什么 prompt 工程已经不够了",
            "长文分析 agent 系统的上下文管理：压缩、分层记忆、工具结果"
            "路由。引用 14 个生产系统案例，给出 5 条可落地的上下文预算分配原则。",
            26,
            TypeKey.AGENT,
        ),
        # Reddit — tools & discussion
        _reddit(
            "LocalLLaMA",
            "本地跑 70B 推理模型实测：4090×2 也能流畅 15 tok/s",
            "量化到 Q4 后双 4090 跑 OpenReasoner-N1-70B，"
            "生成速度 15 tok/s，数学题正确率掉 4 个点。"
            "附 ollama modelfile 和启动参数，显存分配明细表。",
            13,
        ),
        _reddit(
            "ChatGPT",
            "我做了个浏览器插件：任何网页一键发给 Claude Code 处理",
            "开源了，300 行。选中内容 → 右键 → 自动建 issue 带上下文。"
            "解决了我在看文档时随手记录需求的工作流。求反馈。",
            16,
        ),
        _reddit(
            "AutoGPT",
            "停止用框架写 agent，先读这 300 行代码",
            "miniagent 源码走读帖：agent 循环的本质就是 while + tool call。"
            "讨论了为什么 90% 的框架抽象是负资产。1.2k upvotes 争论中。",
            18,
        ),
        _reddit(
            "singularity",
            "GPT-5 发布线程：价格不变 + 8 小时自主任务意味着什么",
            "讨论帖：agent 小时费率已低于外包程序员的 1/10。"
            "顶楼预测 2027 年 SaaS 将按任务而非按席位收费。",
            5,
        ),
        # 一组同主题条目 — 触发 topic dedup
        _x(
            "GPT-5 发布了！推理提升巨大，价格不变，所有人都能用。重复热议中。",
            4.5,
            "@tech_reposter",
        ),
        _web(
            "techcrunch.com",
            "GPT-5 is here: everything you need to know",
            "GPT-5 launch coverage: reasoning +18%, agents, pricing unchanged. "
            "Same story as the official announcement, recapped for startups.",
            5.5,
            TypeKey.AGENT,
        ),
        # 低价值条目 — 应被排序挤下去
        _x("早安！今天也要元气满满地学习 AI 呀 ☀️ 加油！", 2, "@ai_motivation"),
        _gh("user/hello-world", "My first repo. README only.", 3, 2),
    ]


async def main() -> None:
    from app.pipeline.generator import generate_issue

    issue = await generate_issue(inject_collector=collect_fixture)
    print("issue:", issue.id, issue.status)


if __name__ == "__main__":
    asyncio.run(main())
