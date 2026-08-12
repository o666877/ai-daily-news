# Implementation Plan: AI 日报系统 (AI Daily News)

**Branch**: `001-ai-daily-news` | **Date**: 2026-08-12 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-ai-daily-news/spec.md`

## Summary

构建 PC 本地网页端的 AI 资讯聚合日报系统：后端按用户偏好（4 信息源 × 4 类型开关）每日 08:00（Asia/Shanghai）采集 X（经 RSSHub 聚合，无 X API token 依赖）/ GitHub / Reddit / 全网聚合 → LLM 摘要（Anthropic 兼容协议，可指向官方 API 或 OneAPI/DeepSeek/Moonshot 转发层）→ 生成刊期（状态机 `generating → ready / failed`，单源采集失败容错跳过），前端单页应用（左侧索引 + 右侧阅读器）通过 9 个 REST 接口（Base URL `/api/v1`，读匿名/写 Bearer）完成今日刊浏览、双维筛选、详情阅读、分享卡片、偏好设置。首装时后端自动触发一次初始刊期生成（5-10 分钟内可读），无需等到次日 08:00。本期 v1.x 固定 4 源 4 类型，元数据接口驱动所有 chips/开关，偏好下一期刊期生效，严格对齐《后端集成接口文档 v1.0》。

## Technical Context

**Language/Version**: Python 3.11.9（详见 `research.md` D1）

**Primary Dependencies**（详见 `research.md` D2 / D5 / D7 / D8 / D9 / D10）：
- **HTTP 框架**：FastAPI 0.110 + Uvicorn；slowapi（限流）；Starlette middleware（Bearer/请求ID/`X-Effective-At`）
- **LLM 集成**：**Anthropic 官方 Python SDK**（单一协议适配器，不支持 OpenAI/Gemini）；通过 `AIDAILY_LLM_BASE_URL` + `AIDAILY_LLM_MODEL` + `AIDAILY_LLM_API_KEY` 配置，可指向官方 API 或任何兼容转发服务
- **采集 SDK**：`httpx`（X 经 RSSHub、Reddit 经 PRAW、Web 经 RSS+trafilatura）；GitHub 用 `httpx` 调 REST v3
- **调度器**：APScheduler 3.10（进程内，SQLite jobstore）
- **数据校验**：Pydantic v2.7（`Literal` 枚举 + `Field(pattern=...)`）
- **重试**：`tenacity`（LLM 摘要重试上限 2 次）

**Storage**: SQLite（WAL 模式）+ `aiosqlite` + Alembic 迁移（详见 `research.md` D3）。零运维，单文件，远期可平滑迁移至 PostgreSQL。条目原始数据增长可控（每日 ≤ 50 条）。

**Testing**: pytest 8 + pytest-asyncio + httpx ASGITransport（集成）+ Playwright Python（E2E）；`respx` 仅 mock LLM / 外部源 / RSSHub 边界（详见 `research.md` D4）。

**Target Platform**: 本地 PC（Windows / macOS / Linux 三平台浏览器访问）；后端为本地 HTTP 服务（HTTPS 由反向代理或自签证书提供）；时区 Asia/Shanghai；界面仅简体中文。

**Project Type**: Web 服务 + 单页前端（双栈）。前端为静态 HTML/JS（PRD 提及前端原型 `v1 ai 日报.html` 为静态文件）。

**Performance Goals**:
- `GET /daily/today` P95 ≤ 500 ms（本地，不含采集）
- `GET /articles` P95 ≤ 300 ms
- `GET /articles/{id}` P95 ≤ 200 ms
- 前端首屏可交互 ≤ 1.5 s（本地）
- LLM 摘要重试上限 2 次，刊期失败率 ≤ 5%

**Constraints**:
- 读接口 120 次/分钟/IP，写接口 30 次/分钟/用户
- 读接口匿名可用，写接口需 `Authorization: Bearer <token>`
- 时间统一 ISO 8601 / Asia/Shanghai（UTC+8）
- 错误响应仅含 `{code, message, requestId}`，绝不泄露栈/SQL/密钥
- 原文链接仅跳转，不缓存全文（版权）
- 信息源抓取需遵守 robots/ToS 并限速

**Scale/Scope**: 单用户本地部署；单刊期 ≤ 50 条；9 个 REST 接口；前端单页（左侧索引 + 右侧阅读器 + 设置面板 + 分享）；约 5 个核心模块（采集 / 摘要 / 刊期生成 / API / 前端）。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

依据 `.specify/memory/constitution.md` v1.0.0：

| 原则 | 关键要求 | 本期对齐方案 | 状态 |
|---|---|---|---|
| I. Code Quality | 高内聚低耦合、200-400 行/文件（≤ 800 上限）、不可变数据、显式错误处理、系统边界校验 | 模块按采集/摘要/刊期/API/前端拆分；每文件聚焦单一职责；Settings/Article 等实体采用不可变结构；所有外部输入（用户偏好参数、外部源响应、LLM 输出）在边界做 schema 校验 | ✅ PASS（设计阶段约束） |
| II. Testing Standards | TDD（Red→Green→Refactor）、覆盖率 ≥ 80%、三层（单元/集成/E2E）、Mock 仅打边界、不假数据库 | 9 个接口必出集成测试（含错误码 1001-9002 全量覆盖）；采集器/摘要器单测；首屏→筛选→详情→偏好 E2E；用真实本地 DB（SQLite in-memory 或临时文件），不 Mock 数据访问层 | ✅ PASS（tasks 阶段强制） |
| III. UX Consistency | 一致设计系统、可访问性（键盘导航、对比度、屏幕阅读器）、显式反馈、零硬编码文案 | 单页双栏布局由 `/meta` 驱动 chips；错误 toast 文案集中常量；骨架屏/空态/错误态三态全覆盖；颜色对比度 ≥ WCAG AA | ✅ PASS |
| IV. Performance Requirements | 性能预算、关键路径不退化、证据驱动优化、CI 跑性能基准 | 4 个 P95 预算（500/300/200 ms + 1.5 s 首屏）写入 benchmark；LLM 摘要走异步管线不阻塞读接口；列表 7 字段、详情全字段分离避免列表请求体过大 | ✅ PASS |

**GATE 结论**：无违规项，无需 Complexity Tracking 表。所有原则可在本期范围内对齐，进入 Phase 0。

## Project Structure

### Documentation (this feature)

```text
specs/001-ai-daily-news/
├── spec.md               # /speckit-specify 输出
├── plan.md               # 本文件 /speckit-plan 输出
├── research.md           # Phase 0 输出
├── data-model.md         # Phase 1 输出
├── contracts/            # Phase 1 输出（9 个接口契约）
│   ├── README.md
│   ├── daily-today.md
│   ├── articles-list.md
│   ├── articles-detail.md
│   ├── meta.md
│   ├── settings-get.md
│   ├── settings-put.md
│   ├── settings-reset.md
│   ├── share.md
│   └── healthz.md
├── quickstart.md         # Phase 1 输出（端到端验证指南）
└── checklists/
    └── requirements.md   # /speckit-specify 已生成
```

### Source Code (repository root)

**Structure Decision**：采用 Web 双栈结构（Option 2 变体）。后端单进程多模块，前端单页静态资源由后端直接 serve（本地部署免独立 Web 服务器）。具体路径在 research.md 决定语言后最终确定，下表给出 Python 与 Node 两种候选供 research 阶段裁决。

```text
# Python 候选（research.md 倾向方案）
backend/
├── app/
│   ├── api/              # 9 个接口的路由层（按接口一文件）
│   │   ├── daily.py
│   │   ├── articles.py
│   │   ├── meta.py
│   │   ├── settings.py
│   │   ├── share.py
│   │   └── healthz.py
│   ├── models/           # Pydantic schema：Article / DailyIssue / Settings / Share / Meta
│   ├── services/         # 业务逻辑：IssueService / SettingsService / ShareService
│   ├── pipeline/         # 采集 + 摘要 + 刊期生成（collector/summarizer/scheduler）
│   ├── infra/            # DB（SQLite/SQLAlchemy）、LLM client、外部源 client、auth、ratelimit、errors
│   ├── config.py         # 配置（LLM provider/token/源凭据/限流参数）
│   └── main.py           # ASGI 入口
├── tests/
│   ├── unit/             # 业务逻辑、prompt 构造、爬虫解析
│   ├── integration/      # 9 个接口契约 + DB 访问层（真实本地 DB）
│   └── e2e/              # 首屏 → 筛选 → 详情 → 偏好 主路径
├── frontend/
│   ├── index.html        # 单页入口（PRD 提及的 v1 ai 日报.html 正式版）
│   ├── static/
│   │   ├── app.js        # 或拆分为模块化 ES modules
│   │   ├── styles.css
│   │   └── icons/        # x/github/reddit/globe（/meta.icon 引用）
│   └── tests/            # 浏览器端 E2E（Playwright）
├── migrations/           # DB schema 版本化迁移脚本
├── pyproject.toml
└── README.md             # 本地启动、配置项、9 接口调用示例、日志位置
```

```text
# Node.js + TypeScript 候选（备选）
backend/
├── src/
│   ├── routes/           # 9 个接口路由
│   ├── schemas/          # Zod schema
│   ├── services/
│   ├── pipeline/
│   ├── infra/
│   └── app.ts
├── tests/{unit,integration,e2e}
├── frontend/             # 同上
├── migrations/
├── package.json
└── README.md
```

## Complexity Tracking

无 Constitution Check 违规项，本表留空。
