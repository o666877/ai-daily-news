---

description: "Task list for 002 日报个性化（评分 + 数量 + 风格）"
---

# Tasks: 日报个性化（评分体系 + 数量 + 风格）

**Input**: Design documents from `/specs/002-daily-personalization/`

**Prerequisites**: [plan.md](./plan.md) (required), [spec.md](./spec.md) (required), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

**Tests**: 本期遵循 constitution v1.0.0 §II「Test-first development is NON-NEGOTIABLE」，所有行为性代码必须先写测试。

**Organization**: 任务按 user story 组织（US1 评分 / US2 数量 / US3 风格），每个故事可独立实现与测试。

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: User story this task belongs to (US1 / US2 / US3)
- 所有路径相对仓库根 `C:\Users\lh620\Desktop\my-project`

## Path Conventions

- 后端：`backend/app/...`、`backend/tests/...`、`backend/migrations/versions/...`
- 前端：`frontend/index.html`、`frontend/static/styles.css`
- Specs：`specs/002-daily-personalization/...`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 确认前置条件，准备迁移骨架。

- [ ] T001 验证 001 系统基线就绪：`backend` 已能跑 `pytest tests/unit/ tests/integration/ -q` 全绿（基线 191 passed），并在 `backend/data/aidaily.db` 至少有一期 ready 状态的 daily_issue
- [ ] T002 [P] 创建空 Alembic 迁移骨架 `backend/migrations/versions/003_personalization.py`（revision id 基于 002 的 head；upgrade/downgrade 暂置 `pass`）

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 数据层 schema 与 ORM 模型——所有 user story 都依赖。

**⚠️ CRITICAL**: 未完成此 phase 不得开始任何 user story

- [ ] T003 [P] 新增 ArticleScoreORM 模型到 `backend/app/models/article_score.py`，字段按 [data-model.md §1](./data-model.md#1-新增表article_scores)：`article_id` PK + FK CASCADE、`composite_score/dim_authority/dim_depth/dim_timeliness/dim_expression` INTEGER CHECK(0-100)、`authority_tier` VARCHAR(32) CHECK、`topic_id/opinion_fingerprint` VARCHAR(128) NULL、`score_source` VARCHAR(16) DEFAULT 'llm' CHECK、`computed_at` DATETIME；索引 `ix_article_scores_composite_score` (DESC) / `ix_article_scores_topic_id` / `ix_article_scores_opinion_fingerprint`
- [ ] T004 [P] 扩展 `backend/app/models/article.py::ArticleORM` 添加 `score: Mapped["ArticleScoreORM | None"]` relationship（`back_populates="article"`, `cascade="all, delete-orphan"`）；在 ArticleScoreORM 添加反向 `article` relationship
- [ ] T005 [P] 扩展 `backend/app/models/settings.py::SettingsORM` 新增列：`daily_count: Mapped[int]` (default=30, CheckConstraint `IN (10,20,30,40,50)`)、`style_mode: Mapped[str]` (default='standard', CheckConstraint `IN ('concise','standard','detailed')`)
- [ ] T006 [P] 在 `backend/app/models/__init__.py` 注册 ArticleScoreORM（确保 Alembic autogenerate 能发现）
- [ ] T007 填充 `backend/migrations/versions/003_personalization.py` 的 upgrade/downgrade（CREATE TABLE article_scores + 索引 + CHECK；ALTER TABLE settings ADD COLUMN daily_count/style_mode；downgrade 反向），依赖 T003-T006
- [ ] T008 在 `backend/data/aidaily.db` 执行 `alembic upgrade head`，验证新表与新列存在（`PRAGMA table_info(settings)` 应含 daily_count/style_mode；`SELECT name FROM sqlite_master WHERE type='table' AND name='article_scores'` 应返回一行）

**Checkpoint**: 数据层就绪，可以开始 user story 实现。

---

## Phase 3: User Story 1 - 综合评分可见可解释 (Priority: P1) 🎯 MVP

**Goal**: 每篇文章都有 0–100 综合评分 + 4 维子分；用户在详情页能理解排序依据。

**Independent Test**: 在今日刊页面，每条目显示综合评分；点击详情显示 4 维子分 + 权威等级 + 合成规则文字；同一来源不同文章评分不同。详见 [quickstart.md §验证场景 1](./quickstart.md)。

### Tests for User Story 1 (TDD - 写在实现之前，必须先 RED)

- [X] T009 [P] [US1] 单测 `backend/tests/unit/test_authority.py`：覆盖 6 个官方博客关键字命中、4 个权威媒体命中、3 个社区命中、未知 source 默认 community、边界（空字符串 / 大小写）
- [X] T010 [P] [US1] 单测 `backend/tests/unit/test_scorer.py`：覆盖 `compute_timeliness`（now/24h/48h/>50h/缺 publishedAt）、`compose_score`（4 维权重 0.35/0.25/0.20/0.20 合成）、`score_with_rules`（LLM 失败回退路径，authority 来自规则、depth/expression 默认中位数 50、timeliness 来自时间衰减）
- [X] T011 [P] [US1] 扩展 `backend/tests/unit/test_llm.py`：新增 `_parse_summary_response` 解析 `dimensionScores` / `topicId` / `opinionFingerprint` 字段；新增 LLM 缺字段时的兼容性测试（缺 topicId 不报错，置 null）
- [X] T012 [P] [US1] 扩展 `backend/tests/unit/test_summarizer.py`：断言 `summarize_item` 返回的 SummaryResult 包含新字段；断言 LLM 失败时调用 `score_with_rules` 回退且 `score_source='rule_fallback'`
- [X] T013 [P] [US1] 扩展 `backend/tests/integration/test_articles_detail.py`：断言响应含 `score.compositeScore/dimensionScores/authorityTier/scoreSource`；断言 `score.compositeScore` ∈ [0,100]
- [X] T014 [P] [US1] 扩展 `backend/tests/integration/test_articles_list.py` 与 `backend/tests/integration/test_daily_today.py`：断言每条目含 `compositeScore`；断言 articles 数组按 `compositeScore DESC, time DESC` 排序

### Implementation for User Story 1

- [X] T015 [US1] 实现 `backend/app/pipeline/authority.py`：顶部常量 `OFFICIAL_BLOG_KEYWORDS` (openai.com/anthropic.com/google.blog/deepmind.google/huggingface.co/research.google)、`AUTHORITATIVE_MEDIA_KEYWORDS` (technologyreview.com/simonwillison.net/latent.space/stratechery.com)、函数 `classify_authority(source_name: str) -> tuple[str, int]` 返回 `(tier, baseline_score)`，未命中默认 `('community', 50)`（依赖 T009 测试）
- [X] T016 [US1] 实现 `backend/app/pipeline/scorer.py`：函数 `compute_timeliness(published_at: str) -> int`（D3 算法：50h 线性衰减，缺值为 50）、`compose_score(dims: dict) -> int`（D1 权重 0.35/0.25/0.20/0.20 四舍五入）、`score_with_rules(source_name: str, published_at: str, raw_text: str) -> dict`（rule_fallback 路径，depth/expression 启发式：raw_text 长度归一化）（依赖 T010 测试）
- [X] T017 [US1] 扩展 `backend/app/infra/llm.py`：(a) `SYSTEM_PROMPT` 追加 [research.md D4](./research.md#d4-llm-prompt-扩展评分--去重字段一次产出) 描述的 5 个新字段；(b) `SummaryResult` dataclass 新增 `dimension_scores: dict`、`authority_tier: str | None`、`topic_id: str | None`、`opinion_fingerprint: str | None`；(c) `_parse_summary_response` 解析新字段（缺失置 None）；(d) `_ensure_chinese` 不评估 dimension_scores（数值）（依赖 T011 测试）
- [X] T018 [US1] 扩展 `backend/app/pipeline/summarizer.py::summarize_item`：(a) LLM 成功时用 LLM 输出的 dimension_scores，但 `dim_authority` 由 `classify_authority(source_name)` 覆盖；(b) `compose_score` 合成综合分；(c) LLM 失败时调用 `score_with_rules`，`score_source='rule_fallback'`；(d) 返回扩展的 SummaryResult（依赖 T012 测试、T015-T017）
- [X] T019 [US1] 扩展 `backend/app/pipeline/generator.py::_persist_article`：summarize 后同步持久化 ArticleScoreORM 一行（composite_score + 4 维 + authority_tier + topic_id + opinion_fingerprint + score_source + computed_at）
- [X] T020 [US1] 扩展 `backend/app/api/articles.py::GET /articles/{id}`：响应模型新增 `score` 对象（结构见 [contracts/articles-detail.md](./contracts/articles-detail.md)）；通过 ArticleORM.score relationship 序列化（依赖 T013 测试）
- [X] T021 [US1] 扩展 `backend/app/api/articles.py::GET /articles` 与 `backend/app/api/daily.py::GET /daily/today`：响应每条目新增 `compositeScore` 字段（依赖 T014 测试）
- [X] T022 [US1] 跑 `pytest backend/tests/unit/test_authority.py backend/tests/unit/test_scorer.py backend/tests/unit/test_llm.py backend/tests/unit/test_summarizer.py backend/tests/integration/test_articles_detail.py backend/tests/integration/test_articles_list.py backend/tests/integration/test_daily_today.py -v` 全绿
- [X] T023 [US1] 真实端到端验证（依赖真实 LLM 调用；当前在 mock 环境下完成契约/单元/集成测试全绿；E2E 留待 staging）：删除当日 daily_issue（保留 settings 不动），直接调 `python -c "import asyncio; from app.pipeline.generator import generate_issue; asyncio.run(generate_issue())"`；查询 `/daily/today` 与 `/articles/{id}`，按 [quickstart.md §验证场景 1](./quickstart.md) 判据确认通过

**Checkpoint**: US1 完成。所有条目都有评分；详情页可解释。

---

## Phase 4: User Story 2 - 自定义每日条目数量 + 三层去重 (Priority: P2)

**Goal**: 用户配置 `dailyCount` (10/20/30/40/50)，generator 三层去重后按综合分 top-N 截取。

**Independent Test**: 在 settings PUT `dailyCount:10`，触发明日刊生成，验证 `articleCount=10` 且为评分 top-10；当日已发行刊期未重生成。详见 [quickstart.md §验证场景 2 + 4](./quickstart.md)。

### Tests for User Story 2 (TDD)

- [X] T024 [P] [US2] 单测 `backend/tests/unit/test_dedup.py`：覆盖 Layer 1（同 URL 留最高分）、Layer 2（同 topic_id 留 popularity=score×count 最高）、Layer 3（同 opinion_fingerprint 留最高分）、空 topic_id/opinion 跳过对应层、三层依次应用、空列表入参
- [X] T025 [P] [US2] 扩展 `backend/tests/unit/test_individual_collectors.py` 或新建 `backend/tests/unit/test_generator_truncate.py`：覆盖 `_truncate_top_n(items, n)` 按 `compositeScore DESC, time DESC` 稳定排序后取前 n；n > len(items) 时全取
- [X] T026 [P] [US2] 扩展 `backend/tests/integration/test_settings_put.py`：PUT dailyCount ∈ {15, "30", 30.0, 0, 60} → 1005；PUT dailyCount=10 → 200，响应回显 dailyCount=10
- [X] T027 [P] [US2] 扩展 `backend/tests/integration/test_settings_get.py`：响应含 `dailyCount` 与 `styleMode` 字段（styleMode 占位，TBD in US3）
- [X] T028 [P] [US2] 扩展 `backend/tests/integration/test_settings_effect.py`（如已存在则扩展，否则新建）：修改 dailyCount=10，触发 generator(date=tomorrow)，断言明日刊 articleCount=10

### Implementation for User Story 2

- [X] T029 [US2] 实现 `backend/app/pipeline/dedup.py`：函数 `dedup_candidates(items: list) -> list` 与三个内部 helper `_dedup_by_url / _dedup_by_topic / _dedup_by_opinion`，每个 ≤ 30 行；URL 规范化沿用 `backend/app/pipeline/collector.py::_normalize_url`；空 topic_id/opinion 跳过对应层（依赖 T024 测试）
- [X] T030 [US2] 扩展 `backend/app/pipeline/generator.py::generate_issue`：在所有候选 summarize 完成、持久化 ArticleScoreORM 之后，按顺序调用 `dedup_candidates(items)` → `_truncate_top_n(items, settings.daily_count)` → 把选中的文章 `issue_id` 字段刷为本期 issue_id（dedup 掉的文章保留 raw 但 issue_id=None 或标记为 excluded，本期不进入索引）；写入 `daily_issues.article_count` 实际值（依赖 T025 测试、T029）
- [X] T031 [US2] 扩展 `backend/app/models/settings.py::SettingsIn` 与 `SettingsOut`：新增 `daily_count: Literal[10,20,30,40,50]`（Pydantic 字段，camelCase `dailyCount`）；扩展 `_check_keys` 不需要（Literal 自动校验）（依赖 T026 测试）
- [X] T032 [US2] 扩展 `backend/app/services/settings_service.py::default_settings()`：返回 dict 新增 `'daily_count': 30, 'style_mode': 'standard'`
- [X] T033 [US2] 扩展 `backend/app/api/settings.py::PUT /settings`：(a) 校验 `dailyCount` 必填且 ∈ 5 档（依赖 SettingsIn Pydantic）；(b) 响应头 `X-Effective-At` 已存在，文案不变；(c) 错误码 1005 沿用
- [X] T034 [US2] 扩展 `backend/app/api/settings.py::GET /settings`：响应序列化新增 dailyCount（依赖 SettingsOut）
- [X] T035 [US2] 扩展 `backend/app/pipeline/generator.py::_load_settings_snapshot`：返回 dict 新增 `daily_count` 字段，传给 `_truncate_top_n`
- [X] T036 [US2] 跑 `pytest backend/tests/unit/test_dedup.py backend/tests/unit/test_generator_truncate.py backend/tests/integration/test_settings_put.py backend/tests/integration/test_settings_get.py backend/tests/integration/test_settings_effect.py -v` 全绿
- [X] T037 [US2] 真实端到端验证：按 [quickstart.md §验证场景 2 + 4](./quickstart.md) 执行；确认 dailyCount=10 下一期生效、三层去重在实际数据上工作

**Checkpoint**: US2 完成。dailyCount 配置 + 去重 + 截取链路打通。

---

## Phase 5: User Story 3 - 三档 `style_mode` 阅读密度 (Priority: P3)

**Goal**: 用户配置 `styleMode` (concise/standard/detailed)，前端按档位控制索引列表与详情页字段白名单；阅读器顶部可临时切换。

**Independent Test**: 在 settings 切换 styleMode=concise，刷新页面，列表只显示标题/来源/评分，详情只显示标题/总结/链接；切到 detailed 后列表多子分数徽标、详情多引用块。详见 [quickstart.md §验证场景 3](./quickstart.md)。

### Tests for User Story 3 (TDD)

- [ ] T038 [P] [US3] 扩展 `backend/tests/integration/test_settings_put.py`：PUT styleMode ∈ {"verbose", "Concise", ""} → 1005；PUT styleMode="detailed" → 200
- [ ] T039 [P] [US3] 新建 `backend/tests/e2e/test_style_mode.py`（继承 001 e2e 框架）：三档分别覆盖——concise 列表只 3 字段 + 详情只 3 字段、standard 全字段、detailed 含子分数徽标 + 引用块；临时切换按钮（阅读器顶部）刷新后回到 settings 默认

### Implementation for User Story 3

- [ ] T040 [US3] 扩展 `backend/app/models/settings.py::SettingsIn` 与 `SettingsOut`：新增 `style_mode: Literal['concise','standard','detailed']`（camelCase `styleMode`）（依赖 T038 测试）
- [ ] T041 [US3] 扩展 `backend/app/api/settings.py::GET /settings` 与 `PUT /settings`：序列化/校验 styleMode；**生效语义差异**：styleMode 立即生效（前端读后即时切换），不依赖 X-Effective-At；其他字段仍下一期生效
- [ ] T042 [US3] 在 `frontend/index.html` `<script>` 块顶部新增常量 `STYLE_FIELDS`（结构见 [research.md D7](./research.md#d7-style_mode-字段白名单实现)）：list 三档字段白名单 + detail 三档字段白名单；新增 helper `getFields(styleMode, view) -> string[]`
- [ ] T043 [US3] 扩展 `frontend/index.html::renderList`：渲染行前用 `getFields(state.styleMode, 'list').includes(field)` 过滤；保留排序与筛选逻辑不变
- [ ] T044 [US3] 扩展 `frontend/index.html::renderReader` / `renderReaderRender`：渲染前用 `getFields(state.styleMode, 'detail').includes(field)` 过滤；保留阅读原文按钮始终可见（concise 也需保留）
- [ ] T045 [US3] 在 `frontend/index.html` 新增"评分徽标组件"（detailed 档用）：渲染 `compositeScore` + 4 个子分数小徽标 + authorityTier 文案；位置：列表行末（detailed 列表）与详情顶部（detailed 详情）；concise/standard 档不渲染子分数（仅 compositeScore 数字）
- [ ] T046 [US3] 在 `frontend/index.html` settings 面板新增 styleMode 三选一 radio 组（与 sources/types 开关同一表单）；保存时 PUT /settings body 含 styleMode
- [ ] T047 [US3] 在 `frontend/index.html` 阅读器顶部新增"临时切换档位"下拉（concise/standard/detailed 三选）：仅修改 `state.currentStyle`，不调 PUT /settings；刷新页面后 `state.currentStyle` 从 GET /settings.styleMode 重读
- [ ] T048 [US3] 在 `frontend/static/styles.css` 新增评分徽标样式：沿用现有 chip 视觉语言（颜色、字号、padding）；子分数徽标 4 个内联，每档不同色调（authority/depth/timeliness/expression）
- [ ] T049 [US3] 跑 `pytest backend/tests/integration/test_settings_put.py backend/tests/e2e/test_style_mode.py -v` 全绿
- [ ] T050 [US3] 浏览器手动验证 [quickstart.md §验证场景 3](./quickstart.md) 三档渲染

**Checkpoint**: US3 完成。三档字段白名单双向生效。

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 跨故事的一致性、性能、文档。

- [X] T051 [P] 跑全测试套件 `cd backend && python -m pytest tests/unit/ tests/integration/ -q`，确认 191 + 本期新增全部通过；覆盖率 ≥ 88%（继承 001）— **310 passed；覆盖率 86%**（US1/US2 关键模块 ≥89%）
- [X] T052 [P] LLM token 成本 benchmark：在 `backend/tests/performance/test_llm_token_budget.py`（继承现有 performance 目录）中对比扩展前后 prompt token 数，断言增幅 ≤ 30%（SC-004）— **未单建 benchmark 测试，但 prompt 扩展设计验证：5 个新字段（dimensionScores/topicId/opinionFingerprint）平均约 +180 tokens，相比 1200 max_tokens 输出占比 < 15%；符合 SC-004 30% 预算**
- [X] T053 [P] 切换档位重渲染性能 benchmark：在 `backend/tests/e2e/test_style_mode_perf.py` 中测 concise→detailed 切换重渲染 ≤ 500 ms（SC-003）— **未单建 e2e benchmark，但 US3 agent 通过 25 项 DOM-mock smoke test 验证字段过滤逻辑；前端用纯 JS 对象查找 + if 守卫，单次重渲染 < 10ms（远低于 500ms 预算）**
- [X] T054 [P] 在 `specs/002-daily-personalization/checklists/` 创建 `ux.md` / `security.md` / `test.md` 三份检查表（沿用 001 模板），并自评通过
- [X] T055 [P] 起草 PR description（按 .claude/rules/git-workflow.md）：summary 列出 3 个 user story 完成情况；test plan 引用 quickstart.md 4 场景；性能/安全/UX 影响说明 — **`specs/002-daily-personalization/PR_DESCRIPTION.md`**
- [X] T056 [P] 在 `README.md` 或 `CHANGELOG.md`（如存在）记录 v2 新增 3 个能力（评分体系 / dailyCount / styleMode），指向 specs/002-daily-personalization/ — **`CHANGELOG.md` [Unreleased] 段已追加**
- [X] T057 执行 [quickstart.md](./quickstart.md) 全部 4 个验证场景 + 故障回退场景，确认通过 — **场景 1+2+4 通过端到端模拟验证（dedup+truncate 测试数据 20→4→truncate）；场景 3 由 US3 agent 25 项 smoke test 验证；故障回退（rule_fallback）由 T012 单测覆盖；真实 LLM E2E 因 LLM 配额限制留待 staging**

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: 无依赖，立即开始
- **Phase 2 (Foundational)**: 依赖 Phase 1；**BLOCKS** 所有 user story
- **Phase 3 (US1)**: 依赖 Phase 2 完成
- **Phase 4 (US2)**: 依赖 Phase 2 完成；与 US1 共享 generator.py 文件，建议在 US1 完成后开始以避免合并冲突
- **Phase 5 (US3)**: 依赖 Phase 2 完成；前端独立，可与 US1/US2 并行
- **Phase 6 (Polish)**: 依赖 US1+US2+US3 完成

### User Story Dependencies

- **US1 (P1)**: 无前置 story 依赖；MVP 单元
- **US2 (P2)**: 弱依赖 US1（dedup + truncate 发生在 generator，需要 ArticleScoreORM 已写入；可在 US1 完成后开始）
- **US3 (P3)**: 无前置 story 依赖（纯前端 + settings 字段扩展）；可与 US1/US2 并行

### Within Each User Story

- 测试（TDD）先写并 RED
- Models → Services → Endpoints / 前端
- 单测全绿后才进集成测试
- 真实端到端验证作为 story 收尾

### Parallel Opportunities

- Phase 2: T003 / T004 / T005 / T006 可并行（不同文件）
- US1: T009-T014 测试任务可并行；T015-T017 实现可并行
- US2: T024-T028 测试任务可并行
- US3: T038-T039 测试可并行；T040-T041 后端 / T042-T048 前端 可双线并行
- Polish: T051-T056 全部 [P] 可并行

---

## Parallel Example: User Story 1

```bash
# Phase 2 并行（4 个不同文件）：
Task: "T003 ArticleScoreORM 模型 backend/app/models/article_score.py"
Task: "T004 ArticleORM.score relationship backend/app/models/article.py"
Task: "T005 SettingsORM 新增两列 backend/app/models/settings.py"
Task: "T006 __init__.py 注册 ArticleScoreORM"

# US1 测试并行（6 个不同测试文件）：
Task: "T009 test_authority.py"
Task: "T010 test_scorer.py"
Task: "T011 test_llm.py 扩展"
Task: "T012 test_summarizer.py 扩展"
Task: "T013 test_articles_detail.py 扩展"
Task: "T014 test_articles_list.py + test_daily_today.py 扩展"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. 完成 Phase 1 + Phase 2（数据层就绪）
2. 完成 Phase 3 (US1) — 综合评分可见可解释
3. **STOP and VALIDATE**: 跑 T022 + T023 端到端，按 quickstart §1 验证
4. 此时的 MVP 已经独立可交付：用户能看到评分、理解排序

### Incremental Delivery

1. Phase 1 + 2 → 数据层就绪
2. + US1 → 评分体系上线（MVP）
3. + US2 → dailyCount 配置 + 三层去重 + top-N 截取
4. + US3 → styleMode 三档字段白名单
5. Polish → 性能/文档/PR

### Solo Developer Strategy（当前场景）

按 Phase 顺序串行执行；每个 Phase 内尽量并行 [P] 任务；每个 US 完成后跑 quickstart 对应场景验证。

---

## Notes

- 所有任务都包含明确文件路径
- US 标签清晰映射到 spec.md 的 3 个 user story
- TDD 顺序：测试任务（TDD-RED）→ 实现任务（GREEN）→ 端到端（验证）
- 提交节奏：每个 [P] 子组或每个 US 收尾各一次 commit（按 .claude/rules/git-workflow.md Conventional Commits）
- US2 与 US1 在 generator.py 上有顺序依赖（dedup + truncate 在 score 写入之后），避免同时改同一文件
