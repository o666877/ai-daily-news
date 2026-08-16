# Implementation Plan: 日报个性化（评分体系 + 数量 + 风格）

**Branch**: `002-daily-personalization` | **Date**: 2026-08-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-daily-personalization/spec.md`

## Summary

在 001 AI 日报系统基础上扩展三项个性化能力：(1) 每篇文章 0–100 综合评分 + 4 维子分（来源权威按平台类型三档规则映射 / 时效 / 内容深度 / 表达力），由 summarizer 同一次 LLM 调用产出，附带 `topic_id` 与 `opinion_fingerprint` 用于三层全局去重（URL 主键 / 同事件热度 / 观点同质化）；(2) 用户可在 settings 配置 `daily_count`（10/20/30/40/50 五档，默认 30），generator 在三层去重后按综合分降序截取 top-N；(3) 用户可配置 `style_mode`（concise / standard / detailed 三档，默认 standard）同时控制今日刊索引列表与详情页的字段白名单。两项 settings 字段均下一期生效（对齐 v1.x 无手动触发契约）。

## Technical Context

**Language/Version**: Python 3.12.7（继承 001 系统，已 `pytest 8` 通过 191 tests）

**Primary Dependencies**（继承 001，无新增）：
- **HTTP 框架**：FastAPI 0.110 + Uvicorn；Pydantic v2.7 用于 settings/score schema 扩展
- **LLM 集成**：Anthropic 兼容 SDK（`backend/app/infra/llm.py`），评分字段追加到现有 `SummaryResult` dataclass，prompt 扩展指令一次调用产出
- **采集**：`feedparser`（Web）、`httpx`（GitHub/Reddit）、subprocess（X via twitter-cli）— 已就绪
- **存储**：SQLAlchemy ORM + Alembic 迁移；本期新增 `article_scores` 表 + 扩展 `articles` 视图字段 + 扩展 `settings` JSON
- **校验**：Pydantic `Literal` 限制 `daily_count ∈ {10,20,30,40,50}`、`style_mode ∈ {concise,standard,detailed}`
- **前端**：原生 HTML/JS（`frontend/index.html`），新增评分徽标组件 + 三档字段白名单常量

**Storage**: SQLite（WAL）+ 新增表 `article_scores`（1:1 关联 articles）。settings 表新增两列 `daily_count INT DEFAULT 30`、`style_mode VARCHAR(16) DEFAULT 'standard'`。Alembic migration `003_personalization.py`。

**Testing**: pytest + pytest-asyncio + httpx ASGITransport + respx；新增评分器单测（规则映射 / LLM 输出解析 / 失败回退）、三层去重单测（URL / topic_id / opinion_fingerprint）、settings 校验单测、generator 截取单测、前端字段白名单 e2e。

**Target Platform**: 本地 PC 浏览器（继承 001）；后端本地 HTTP 服务。

**Project Type**: Web 服务 + 单页前端（继承 001 双栈）。

**Performance Goals**:
- `GET /daily/today` P95 ≤ 500 ms（不变，每条目额外 4 字节 int 评分不影响）
- `GET /articles/{id}` P95 ≤ 200 ms（不变，新增 dimensionScores dict 仅 ~200 字节）
- 评分计算不引入独立 LLM 调用（与摘要合并），SC-004 ≤ 30% token 成本增幅
- 三档切换前端重渲染 ≤ 500 ms（SC-003）

**Constraints**:
- 评分维度权重本期固定（35% 来源权威 + 25% 内容深度 + 20% 时效 + 20% 表达），暴露给用户调整属 v3
- 三档字段白名单是产品决策（系统内置枚举常量），用户自定义字段属 v3
- `daily_count` 修改下一期生效，本期不提供立即重生成
- LLM 评分失败必须回退到规则评分（标记 `score_source = 'rule_fallback'`），与 001 FR-007a 容错策略一致
- 三层去重算法的"同事件/同观点"判定必须由 LLM 在 summarizer 阶段产出（`topic_id` + `opinion_fingerprint` 字符串），不允许独立 LLM 调用

**Scale/Scope**: 单用户本地部署；新增 1 张表（article_scores）+ 扩展 settings 2 字段；扩展 5 个 REST 接口的响应字段（不新增端点）；前端新增 1 个评分组件 + 1 个字段白名单 helper；约 4 个核心改动模块（评分器 / 去重器 / settings / 前端渲染）。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

依据 `.specify/memory/constitution.md` v1.0.0：

| 原则 | 关键要求 | 本期对齐方案 | 状态 |
|---|---|---|---|
| I. Code Quality | 函数 ≤ 50 行、文件 ≤ 400 行（≤ 800 上限）、不可变数据、显式错误处理、系统边界校验 | 新增 `backend/app/pipeline/scorer.py`（评分器，纯函数 ≤ 200 行）、`backend/app/pipeline/dedup.py`（三层去重器，≤ 150 行）；评分/去重逻辑独立模块，不污染现有 generator；所有 LLM 输出在边界做 schema 校验（dimensionScores dict / topic_id str / opinion_fingerprint str），失败回退不抛 | ✅ PASS |
| II. Testing Standards | TDD、覆盖率 ≥ 80%、三层测试、Mock 仅打边界 | 评分器：维度计算单测 + 权重合成单测 + LLM 失败回退单测；去重器：三层独立单测 + 组合测试；settings：新字段枚举校验测试（10/20/30/40/50 / 三档）；generator：截取 top-N 单测；前端：三档字段白名单渲染 e2e；继续使用真实 SQLite（不假 DB）；目标覆盖率 ≥ 88%（继承 001 的 88.8%） | ✅ PASS |
| III. UX Consistency | 一致设计系统、可访问性、显式反馈、零硬编码文案 | 评分徽标沿用现有 chip 视觉语言（颜色/字号一致）；三档切换在 settings 与阅读器顶部使用同一组件；权威等级文案集中常量（`AUTHORITY_TIER_LABELS`）；空态/错误态：评分缺失显示 "—"，切换档位失败 toast 统一；颜色对比度 ≥ WCAG AA（评分徽标用现有调色板） | ✅ PASS |
| IV. Performance Requirements | 性能预算、关键路径不退化、证据驱动优化、CI 跑基准 | 现有 4 个 P95 预算不变；新增 SC-003（切换重渲染 ≤ 500 ms）与 SC-004（token 成本 ≤ 30% 增幅）写入 benchmark；评分/去重在 summarizer 异步管线产出，不阻塞读接口；列表多 1 个 int 字段不显著增加响应体 | ✅ PASS |

**GATE 结论**：无违规项。所有原则可在本期对齐，进入 Phase 0。

## Project Structure

### Documentation (this feature)

```text
specs/002-daily-personalization/
├── spec.md               # /speckit-specify 输出
├── plan.md               # 本文件 /speckit-plan 输出
├── research.md           # Phase 0 输出（评分权重 / 去重算法 / 字段白名单 / prompt 扩展 决策）
├── data-model.md         # Phase 1 输出（ArticleScore 实体 + Settings 扩展）
├── quickstart.md         # Phase 1 输出（端到端验证脚本）
├── contracts/            # Phase 1 输出（5 个扩展后的接口契约）
│   ├── README.md
│   ├── daily-today.md            # 扩展：articles 列表新增 composite_score
│   ├── articles-list.md          # 扩展：每条目新增 composite_score
│   ├── articles-detail.md        # 扩展：新增 dimensionScores / authorityTier / scoreSource
│   ├── settings-get.md           # 扩展：新增 dailyCount / styleMode
│   └── settings-put.md           # 扩展：新增 dailyCount / styleMode 校验
└── tasks.md              # Phase 2 输出（/speckit-tasks 后续生成）
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── models/
│   │   ├── article.py         # 扩展 ArticleORM：新增 composite_score 列；保留 raw 关联
│   │   ├── article_score.py   # 新增：ArticleScoreORM 1:1 关联 articles（综合分 + 4 维子分 + authority_tier + score_source + topic_id + opinion_fingerprint）
│   │   └── settings.py        # 扩展 SettingsORM：新增 daily_count / style_mode 列；扩展 SettingsIn/Out Pydantic
│   ├── pipeline/
│   │   ├── summarizer.py      # 扩展 SummaryResult：新增 composite_score / dimension_scores / authority_tier / topic_id / opinion_fingerprint
│   │   ├── scorer.py          # 新增：纯函数 score_with_rules() 规则回退评分（authority 启发 + 长度 + 时效）
│   │   ├── dedup.py           # 新增：三层去重 dedup_candidates(items) → items
│   │   ├── generator.py       # 扩展：summarize 后持久化 score；调用 dedup；按 settings.daily_count 截取 top-N
│   │   └── authority.py       # 新增：source_name → authority_tier 规则映射（official_blog / authoritative_media / community）
│   ├── infra/
│   │   └── llm.py             # 扩展 SYSTEM_PROMPT 追加评分字段输出指令；扩展 _parse_summary_response 解析新字段
│   ├── api/
│   │   ├── articles.py        # 扩展响应：article list/detail 增加 composite_score / dimensionScores / authorityTier / scoreSource
│   │   └── settings.py        # 扩展 GET/PUT：增加 dailyCount / styleMode 字段（Literal 校验）
│   └── services/
│       └── settings_service.py # 扩展 default_settings() 含 daily_count=30 / style_mode='standard'
├── migrations/
│   └── versions/
│       └── 003_personalization.py  # 新增迁移：article_scores 表 + settings 两列
└── tests/
    ├── unit/
    │   ├── test_scorer.py             # 新增：规则评分单测
    │   ├── test_dedup.py              # 新增：三层去重单测
    │   ├── test_authority.py          # 新增：平台 → 等级映射单测
    │   ├── test_llm.py                # 扩展：新字段解析单测
    │   └── test_summarizer.py         # 扩展：评分/去重字段产出单测
    ├── integration/
    │   ├── test_articles_detail.py    # 扩展：断言新字段
    │   ├── test_articles_list.py      # 扩展：断言 composite_score
    │   ├── test_settings_get.py       # 扩展：断言 dailyCount / styleMode
    │   ├── test_settings_put.py       # 扩展：断言 dailyCount / styleMode 校验
    │   └── test_daily_today.py        # 扩展：断言截取 top-N + 排序
    └── e2e/
        └── test_style_mode.py         # 新增：三档字段白名单 e2e

frontend/
├── index.html                 # 扩展：评分徽标组件；字段白名单 helper（getFields(style_mode)）；style_mode 临时切换按钮（阅读器顶部）
└── static/
    └── styles.css             # 扩展：评分徽标样式（沿用 chip 视觉语言）

specs/001-ai-daily-news/contracts/*.md  # 不动；002 contracts/ 取而代之描述当前真实契约
```

**Structure Decision**: 沿用 001 系统的 `backend/ + frontend/` 双栈布局（Option 2 Web application 模板），不引入新顶层目录。本期改动以"扩展"为主：3 个新文件（scorer.py / dedup.py / authority.py）+ 1 张新表 + 2 列扩展 + 5 个接口响应字段扩展。最小爆炸半径。
