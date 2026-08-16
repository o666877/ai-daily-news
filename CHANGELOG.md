# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Pending

- 多租户 / 用户体系（v2 路线图）
- PostgreSQL 支持替换 SQLite（v2 路线图）
- OpenAI 协议兼容 LLM provider（v1.1 规划）
- 分享卡片 TTL 过期机制（v2 规划）

### Added — 002 日报个性化（评分 + 数量 + 风格）

**P1 — 综合评分体系**

- `ArticleScoreORM` 模型（11 列 + 3 索引 + 5 CHECK 约束），与 `ArticleORM` 1:1 关联
- `classify_authority(source_name)` in `pipeline/authority.py`：按平台类型规则映射到三档权威等级（`official_blog` / `authoritative_media` / `community`，基线分 90/70/50）
- `compute_timeliness` / `compose_score` / `score_with_rules` in `pipeline/scorer.py`：综合分 = `authority×0.35 + depth×0.25 + timeliness×0.20 + expression×0.20`；LLM 失败回退到规则评分
- `SummaryResult` dataclass 扩展 7 字段（`dimension_scores / authority_tier / topic_id / opinion_fingerprint / composite_score / score_source`），与摘要**同一次 LLM 调用**产出（不增加调用次数）
- Article 列表响应新增 `compositeScore`，详情响应新增 `score` 子对象
- Articles 在 DB 查询层按 `composite_score DESC, time DESC` 排序

**P2 — 自定义每日条目数量 + 三层全局去重**

- `dedup_candidates` in `pipeline/dedup.py`：URL 主键（保留最高分） → 同事件热度（同 `topic_id` 保留 `score × count` 最高） → 观点同质化（同 `opinion_fingerprint` 保留最高分）
- `truncate_top_n(items, n)`：综合分排序后取前 N，候选不足时全取（不补齐）
- `dailyCount` 字段加入 `SettingsIn/Out`（`Literal[10,20,30,40,50]`，默认 30）
- `generator.py::_select_for_issue` 编排：summarize → dedup → truncate → 仅 persist 入选的 articles

**P3 — 三档 styleMode 阅读密度**

- `styleMode` 字段加入 `SettingsIn/Out`（`Literal['concise','standard','detailed']`，默认 `standard`）
- `frontend/index.html::STYLE_FIELDS` 常量定义三档 × 列表/详情字段白名单
- `renderList` / `renderReader` 加字段过滤守卫（不改架构，仅加 guard）
- `renderScoreBadges(score)` 组件（detailed 档显示子分数徽标）
- 阅读器顶部临时切换按钮（仅修改 `state.currentStyle`，刷新后回退到 settings 默认）

**Database**

- 新增 `article_scores` 表（FK CASCADE on articles）
- 新增 `settings.daily_count` / `settings.style_mode` 两列 + CHECK 约束
- Alembic migration: `backend/migrations/versions/003_personalization.py`

**Test Counts**

- 191 → **310 tests passing**（+119 测试）
- 覆盖率 **86%**（US1/US2 关键模块 ≥89%）

**Documentation**

- `specs/002-daily-personalization/{spec,plan,research,data-model}.md`
- `specs/002-daily-personalization/contracts/`（5 个扩展接口契约）
- `specs/002-daily-personalization/quickstart.md`（4 个端到端验证场景）
- `specs/002-daily-personalization/tasks.md`（57 任务全部 [X]）
- `specs/002-daily-personalization/checklists/{requirements,ux,security,test}.md`
- `specs/002-daily-personalization/PR_DESCRIPTION.md`

---

## [1.0.0] - 2026-08-12

🚀 **首次开源发布**。AI 资讯聚合日报系统 v1.0 — MVP + 全部 5 个用户故事 + 开源准备就绪。

### Summary

完整的本地优先 AI 日报系统：每日自动从 X (Twitter)、GitHub、Reddit、全网 RSS 聚合 AI 资讯，经 LLM 摘要后以本地 Web 应用呈现，支持双维筛选、偏好配置、分享卡片与首装自动触发。

- **任务完成度**：95 / 95 (100%) — Phase 1 Setup + Phase 2 Foundational + Phase 3-7 (US1-US5) + Phase 8 Polish
- **测试**：172 个 unit + integration 测试全部通过；覆盖率 88.06%（门槛 80%）
- **性能**：P95 基准满足 Constitution IV（`/daily/today` ≤ 500ms / `/articles` ≤ 300ms / `/articles/{id}` ≤ 200ms）

### Added

#### Phase 1: Setup (T001-T007)
- 项目结构：`backend/`（FastAPI）+ `frontend/`（静态 SPA，零构建）+ `migrations/`（Alembic）+ `data/` + `logs/`
- `backend/pyproject.toml`：固定依赖（FastAPI 0.110.3 / uvicorn / SQLAlchemy 2.0.30 / alembic / pydantic 2.7.1 / anthropic / feedparser / trafilatura / selectolax / praw / apscheduler）
- 开发依赖：pytest / pytest-asyncio / pytest-cov / pytest-benchmark / respx / ruff / mypy
- `LICENSE` (MIT)、`.env.example`、`.gitignore`、`.dockerignore`
- ruff + mypy strict mode 配置；pytest asyncio_mode=auto + cov-fail-under=80

#### Phase 2: Foundational (T008-T020)
- `app/config.py`：pydantic-settings 全量 `AIDAILY_*` 配置（LLM/Auth/Server/DB/Scheduler/X/GitHub/Reddit）
- `app/infra/`：db engine/session factory / 错误处理（10 个业务码）/ 结构化 JSON 日志（含 `request_id` context var）/ Bearer auth / slowapi 限流（读 120/min/IP，写 30/min/user）/ request ID 中间件 / 分页校验
- `frontend/index.html`：左索引 + 右阅读器双面板布局，vendor Alpine.js 3.14.1 + htmx 1.19.5（无 CDN，无构建）
- `frontend/static/icons/`：x / github / reddit / globe SVG

#### Phase 3: User Story 1 - 今日刊 (T021-T051) — MVP
- **9 个 API 端点**中的 4 个：`GET /daily/today` / `GET /articles/{id}` / `GET /meta` / `GET /healthz`
- LLM 客户端（Anthropic SDK + `base_url` 兼容网关）+ summarizer（5 输出字段：lede/summary/body/quote/points + tenacity 重试 + 日花费预算）
- 4 个 collector（GitHub REST + trending HTML 兜底；Reddit PRAW；Web RSS + trafilatura；X via RSSHub）+ collector orchestrator（asyncio.gather + return_exceptions=True，单源失败不影响整体）
- issue generator（idempotent，状态机 generating → ready/failed）
- APScheduler 集成（SQLite jobstore + Asia/Shanghai cron + `misfire_grace_time`）
- **首装自动触发**（FR-001b）：DB 为空时启动后台 `generate_issue(today)`
- 前端索引面板 + 详情视图 + 元数据驱动 + 2003 轮询（指数退避）

#### Phase 4: User Story 2 - 双维筛选 (T052-T060)
- `GET /articles?type=&src=&page=&pageSize=` 接口；非法枚举值 → 业务码 1002
- 类型 chip + 来源 chip 双维 AND 筛选；防抖 250ms + AbortController 取消
- 元数据驱动：sources[]/types[] 完全来自 `/meta`，前端不硬编码（SC-008/SC-011）
- 空态「今天的货架是空的」+ 客户端枚举校验（defense in depth）

#### Phase 5: User Story 3 - 偏好配置 (T061-T073)
- `GET / PUT /api/v1/settings` + `POST /api/v1/settings/reset`
- 全量覆盖语义（缺字段抛 1005）；`X-Effective-At: YYYYMMDD` 响应头表示生效刊期
- 下一期生效（不重算当期）；幂等
- 设置面板：4 源开关 + 4 类型开关 + 推送开关 + 时间选择器（HTML5 pattern 校验）
- 「明天的日报将按新口味调配（生效刊期: YYYY-MM-DD）」toast

#### Phase 6: User Story 4 - 分享卡片 (T074-T080)
- `POST /api/v1/share`（鉴权 + 30/min 限流）+ 公开分享页 `GET /share/{shareId}`
- ShareCard ORM：`shareId` (PK, `shr_<8hex>`)、`articleId` (FK)、`articleTitle` 快照、`cardUrl`
- 「分享这条」按钮 → modal 展示 cardUrl + 复制到剪贴板 + 在新标签页打开
- 公开页面无需鉴权，自包含 minimal HTML（不依赖 SPA 加载）

#### Phase 7: User Story 5 - 异常态 (T081-T086)
- 业务码 → UI 行为映射：1001/1005 → 表单字段错误；1002 → chips 区提示；1003 → 跳登录；1006 → toast；2001/2002 → 区块空态；2003 → 骨架屏 + 轮询；9001/9002 → 全局错误态 + 重试
- 安全契约：错误响应仅含 `{code, message, requestId}` 三字段（无栈、无 SQL、无 env 值）
- 全局错误 toast：`requestId` 仅 console.log，绝不展示给用户
- 401 重定向 hook：localStorage 缓存 token + 自动重试原请求
- 集成测试 `test_error_sanitization.py` 验证 9001 响应体契约

#### Phase 8: Polish (T087-T095)
- `README.md`：完整项目说明 + 9 个 API curl 示例 + RSSHub 部署 + 日志查询 + 开发脚本 + 已知限制
- `docker-compose.yml`：backend + rsshub 两服务一键部署；含 healthcheck + volume 映射
- `backend/Dockerfile`：Python 3.11-slim + 系统依赖（gcc/libxml2/libxslt）+ alembic 自动迁移
- `.github/workflows/ci.yml`：4 jobs（lint+type / unit+integration / perf / e2e）+ coverage artifact
- OpenAPI 自动文档：所有 9 个端点添加 response examples（Swagger UI at `/docs`）
- 性能基准 `tests/performance/test_perf_budgets.py`：P95 预算断言（Constitution IV）
- 日志增强：`RotatingFileHandler` (10MB × 5) + JSON 格式 + `request_id/source/issue_id/user/module` extra 字段
- `CONTRIBUTING.md` + `CHANGELOG.md`：开源发布就绪
- 所有 quickstart VS-1 ~ VS-10 + VS-9a + VS-9b 场景端到端验证通过

### Fixed
- （Phase 8 修复）`logging.py` 改用 `RotatingFileHandler`，避免日志文件无限增长
- （Phase 8 修复）所有 API 端点添加 OpenAPI response examples，下游 SDK 可直接生成

### Security
- 所有写接口强制 Bearer auth + 30/min 限流
- 错误响应通过集成测试验证不含敏感字段（栈/SQL/env 值）
- Bearer token 缺失时启动自动生成（避免空 token 默认部署风险）
- `secrets.compare_digest` 防止 timing attack

### Performance
- `GET /daily/today` P95 ≤ 500 ms（含 12 篇文章 fixture）
- `GET /articles?type=agent&src=reddit` P95 ≤ 300 ms
- `GET /articles/{id}` P95 ≤ 200 ms
- 性能基准在 CI 中每次 PR 自动运行（`perf` job）

### Documentation
- `README.md`（中英混合）
- `CONTRIBUTING.md`（dev setup / commit 约定 / PR 流程 / 分支保护建议）
- `specs/001-ai-daily-news/contracts/*.md`：9 个端点的完整契约
- OpenAPI Swagger UI：<http://localhost:8000/docs>

---

## 版本号说明

本项目遵循 [Semantic Versioning](https://semver.org/spec/v2.0.0.html)：

- **MAJOR**：不兼容的 API 变更
- **MINOR**：向后兼容的功能新增（如新增端点 / 新增字段）
- **PATCH**：向后兼容的 Bug 修复

每个版本对应一个 GitHub Release + git tag。
