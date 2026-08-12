# Tasks: AI 日报系统 (AI Daily News)

**Input**: Design documents from `/specs/001-ai-daily-news/`

**Prerequisites**: plan.md ✅ · spec.md ✅ · research.md ✅ · data-model.md ✅ · contracts/ ✅ · quickstart.md ✅

**Tests**: Constitution II 强制 TDD + 80% 覆盖率——所有用户故事均含契约/集成测试任务，先写测试再实现（Red→Green→Refactor）。

**Organization**: 任务按用户故事分组（US1=今日刊浏览 P1、US2=双维筛选 P2、US3=偏好配置 P3、US4=分享 P4、US5=异常态 P5）。每个故事可独立实现与测试。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成任务依赖）
- **[Story]**: 用户故事归属（US1–US5；Setup/Foundational/Polish 阶段无 Story 标签）
- 所有路径相对仓库根目录

## Path Conventions

- **Web 双栈**：`backend/app/`（后端）· `backend/tests/`（测试）· `frontend/`（静态前端，由后端 serve）
- 部署：`docker-compose.yml`（含 backend + RSSHub）

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 项目骨架与工具链初始化

- [x] T001 Create project structure per `specs/001-ai-daily-news/plan.md` (backend/, frontend/, migrations/, data/, logs/)
- [x] T002 Initialize Python 3.11 project in `backend/pyproject.toml` with dependencies: fastapi==0.110.3, uvicorn[standard]==0.29.0, slowapi==0.1.9, anthropic==0.27.0, tenacity==8.3.0, aiosqlite==0.20.0, sqlalchemy==2.0.30, alembic==1.13.1, pydantic==2.7.1, pydantic-settings==2.2.1, httpx==0.27.0, feedparser==6.0.11, trafilatura==1.10.0, selectolax==0.3.21, praw==7.7.1, apscheduler==3.10.4, tzdata==2024.1
- [x] T003 [P] Configure dev dependencies in `backend/pyproject.toml` optional `[dev]`: pytest==8.2.0, pytest-asyncio==0.23.7, pytest-cov==5.0.0, respx==0.21.1, pytest-playwright==1.44.0, ruff==0.4.7, mypy==1.10.0
- [x] T004 [P] Configure ruff + mypy in `backend/pyproject.toml` and `backend/ruff.toml` (line-length=100, target-py=3.11, strict mode)
- [x] T005 [P] Configure pytest in `backend/pyproject.toml` and `backend/pytest.ini` (asyncio_mode=auto, cov-fail-under=80, testpaths=tests)
- [x] T006 [P] Create `.gitignore` (Python venv, `data/*.db`, `logs/`, `.env`, `__pycache__/`, `.pytest_cache/`, `.coverage`)
- [x] T007 [P] Create `LICENSE` (MIT) and `.env.example` documenting all `AIDAILY_*` vars per `research.md` D5/D6/D7

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 所有用户故事都依赖的核心基础设施

**⚠️ CRITICAL**: 本阶段未完成前，禁止开始任何用户故事实现

- [x] T008 Implement environment config in `backend/app/config.py` using pydantic-settings: parse `AIDAILY_LLM_*`, `AIDAILY_BEARER_TOKEN`, `AIDAILY_DB_PATH`, `AIDAILY_HOST/PORT`, `AIDAILY_TZ`, `AIDAILY_DAILY_PUSH_TIME`, `AIDAILY_X_RSSHUB_BASE_URL`, `AIDAILY_X_ACCOUNTS`, `AIDAILY_GITHUB_TOKEN`, `AIDAILY_REDDIT_UA`, `AIDAILY_LLM_DAILY_BUDGET_USD` with defaults per `quickstart.md`
- [x] T009 [P] Initialize Alembic in `backend/alembic.ini` + `backend/migrations/` with SQLAlchemy autogenerate configured for `app.models`
- [x] T010 [P] Create database engine + session factory in `backend/app/infra/db.py` (aiosqlite async engine, sessionmaker, `get_session` FastAPI dependency)
- [x] T011 [P] Create base Pydantic schema mix-ins in `backend/app/models/_base.py` (CamelCase alias generator for interface compatibility, `model_config` shared)
- [x] T012 [P] Implement unified error response in `backend/app/infra/errors.py`: `ErrorOut(BaseModel){code:int, message:str, requestId:str}`, `AppException(code:int, http_status:int, message:str)`, exception→HTTP handler mapping for codes 1001/1002/1003/1004/1005/1006/2001/2002/2003/9001/9002 per `contracts/README.md` error table
- [x] T013 [P] Implement structured logging in `backend/app/infra/logging.py` (JSON formatter, request_id context var, daily rotation in `logs/aidaily.log`)
- [x] T014 [P] Implement Bearer auth dependency in `backend/app/infra/auth.py`: `get_authenticated_user(authorization: str = Header(None))` returns user or raises 1003; `require_auth` dependency for write endpoints; reads skip auth (FR-026); use `secrets.compare_digest`
- [x] T015 [P] Implement rate limiting in `backend/app/infra/ratelimit.py` using slowapi: per-IP 120/min limiter for reads, per-user 30/min limiter for writes (FR-027); raise 1006 on exceed
- [x] T016 [P] Implement request ID middleware in `backend/app/infra/middleware.py`: read `X-Request-Id` header (generate UUID if missing), set context var, echo in response header
- [x] T017 [P] Implement pagination validator in `backend/app/infra/pagination.py`: parse `page` (≥1, default 1) + `pageSize` (1–50, default 20); raise 1005 on violation (FR-015, FR-016)
- [x] T018 Create FastAPI app skeleton in `backend/app/main.py`: include router, register exception handlers (T012), add middleware (T014, T015, T016), mount `/static` for frontend, mount `/` → `frontend/index.html`; on startup run first-install auto-trigger check (FR-001b) and APScheduler init
- [x] T019 [P] Create frontend skeleton in `frontend/index.html`: left index panel + right reader panel layout per spec US1; vendor Alpine.js 3.14.1 + htmx 1.19.5 into `frontend/static/vendor/` (no CDN, no build step)
- [x] T020 [P] Create static asset mount + icon assets in `frontend/static/icons/`: x.svg, github.svg, reddit.svg, globe.svg (referenced by `/meta` icon keys per `data-model.md` Source)

**Checkpoint**: Foundation ready — 所有中间件、错误处理、DB 与日志基础设施就位，用户故事实现可并行启动

---

## Phase 3: User Story 1 - 阅读今日刊 (Priority: P1) 🎯 MVP

**Goal**: 用户打开首页，能在 1.5 秒内看到当日刊期（报头 + 数量徽标 + 索引列表），点击条目进入详情阅读，「阅读原文」跳转原文；首装自动触发初始生成

**Independent Test**: 启动后端 + 首装自动触发 → 5-10 分钟内 `GET /daily/today` 返回 ready 刊期 → 点击任意条目 → `GET /articles/{id}` 返回完整字段 → 「阅读原文」打开 sourceUrl

### Tests for User Story 1

> **NOTE**: 先写测试并确保 FAIL（Red），再实现（Green）

- [x] T021 [P] [US1] Contract test for `GET /daily/today` in `backend/tests/integration/test_daily_today.py`: 200 ready / 2002 not-generated / 2003 generating / empty articles
- [x] T022 [P] [US1] Contract test for `GET /articles/{id}` in `backend/tests/integration/test_articles_detail.py`: 200 full fields / 2001 not-found
- [x] T023 [P] [US1] Contract test for `GET /meta` in `backend/tests/integration/test_meta.py`: returns 4 sources + 4 types, keys exact
- [x] T024 [P] [US1] Contract test for `GET /healthz` in `backend/tests/integration/test_healthz.py`: status ok / version / pipeline up
- [x] T025 [P] [US1] Integration test for first-install auto-trigger (FR-001b) in `backend/tests/integration/test_first_install.py`: empty DB on startup → 2002 → 5-10 min later 200 ready (mock LLM/collectors via respx)
- [x] T026 [P] [US1] Unit test for LLM summarizer in `backend/tests/unit/test_summarizer.py`: 5 output fields (lede/summary/body/points + quote), retry 2x on RateLimitError then mark failed (respx mock Anthropic)
- [x] T027 [P] [US1] Unit test for partial failure tolerance (FR-007a) in `backend/tests/unit/test_collector.py`: 1 source fails → issue still ready; all summarizers fail → issue failed

### Models for User Story 1

- [x] T028 [P] [US1] Create `Article` SQLAlchemy model + Pydantic schema in `backend/app/models/article.py`: 16 fields per `data-model.md` §2; `ArticleListItem` 7-field subset for list responses
- [x] T029 [P] [US1] Create `DailyIssue` model + schema in `backend/app/models/daily_issue.py`: 7 fields, IssueStatus enum, `filtersApplied` JSON column
- [x] T030 [P] [US1] Create `Source` / `Type` metadata schemas in `backend/app/models/meta.py`: 4 fixed SourceKey enum + 4 TypeKey enum + response shape per `data-model.md` §3 §4
- [x] T031 Create Alembic migration 001 in `backend/migrations/versions/001_initial.py`: tables `daily_issues`, `articles`, `settings` (singleton id=1), `share_cards` per `data-model.md` storage mapping

### Pipeline for User Story 1

- [x] T032 [P] [US1] Create default X account list in `backend/app/pipeline/defaults/x_accounts.py`: ~25 AI KOL usernames (karpathy/ylecun/goodfellow_ian/_jasonwei/rasbt/swyx/simonw/miramurati/gdb/sama/emilymenonbender/fchollet/AnthropicAI/OpenAI/huggingface/StabilityAI/MistralAI + others); overridable by `AIDAILY_X_ACCOUNTS` env var
- [x] T033 [P] [US1] Implement LLM client in `backend/app/infra/llm.py`: `LLMClient(base_url, api_key, model)` using Anthropic SDK with `base_url` param; `async summarize(prompt) → SummaryResult`; `LLMProviderError` exception
- [x] T034 [US1] Implement summarizer in `backend/app/pipeline/summarizer.py`: take RawItem → call LLMClient with structured prompt → return 5 fields (lede/summary/body/quote/points); retry policy via tenacity (max 2 attempts, exponential backoff on RateLimitError/APITimeoutError); per-call token logging to `llm_calls` table; daily budget enforcement (raise 9002 if exceeded)
- [x] T035 [P] [US1] Implement GitHub collector in `backend/app/pipeline/collectors/github.py`: REST v3 search `/search/repositories?q=...&sort=stars` for trending AI repos created in last 7 days + `/users/:user/events/public` for watched maintainers; auth via `AIDAILY_GITHUB_TOKEN`; trending HTML fallback via selectolax when quota exhausted; returns `list[RawItem]`
- [x] T036 [P] [US1] Implement Reddit collector in `backend/app/pipeline/collectors/reddit.py`: PRAW; subreddits `MachineLearning`/`LocalLLaMA`/`OpenAI`/`singularity`/`AgentAI`; `top(day)` limit 10-15 per sub; auth via OAuth + `AIDAILY_REDDIT_UA`; returns `list[RawItem]`
- [x] T037 [P] [US1] Implement Web RSS collector in `backend/app/pipeline/collectors/web.py`: feedparser on curated OPML (Simon Willison / Stratechery / HF blog / Anthropic / OpenAI / Latent Space / Import AI); trafilatura for non-RSS discovered URLs; returns `list[RawItem]`
- [x] T038 [P] [US1] Implement X RSSHub collector in `backend/app/pipeline/collectors/x_rsshub.py`: iterate `AIDAILY_X_ACCOUNTS` (or default list T032), fetch `{AIDAILY_X_RSSHUB_BASE_URL}/twitter/user/{username}` concurrently via httpx, parse RSS via feedparser; if `AIDAILY_X_RSSHUB_BASE_URL` empty → return empty list (silent skip); per-account failures logged and skipped; returns `list[RawItem]`
- [x] T039 [US1] Implement collector orchestrator in `backend/app/pipeline/collector.py`: invoke 4 collectors concurrently via asyncio.gather(return_exceptions=True); per-source failures (FR-007a) → log structured warning + return successful items only; dedup by normalized `source_url`; classify `type` via LLM classification step (one extra LLM call per item OR rule-based keywords); returns `list[RawItem]`
- [x] T040 [US1] Implement issue generation pipeline in `backend/app/pipeline/generator.py`: `generate_issue(date) → DailyIssue` — load current Settings snapshot → call collector → call summarizer per item → persist DailyIssue(status=generating → ready/failed) → persist Articles → write `filtersApplied`; idempotent on issueId (re-entry returns existing ready issue)
- [x] T041 [US1] Implement scheduler integration in `backend/app/infra/scheduler.py`: APScheduler with SQLite jobstore; daily cron at `AIDAILY_DAILY_PUSH_TIME` (HH:mm Asia/Shanghai); `misfire_grace_time` for restart-tolerance; expose `run_once(date)` for dev/debug

### API & Frontend for User Story 1

- [x] T042 [US1] Implement `IssueService` in `backend/app/services/issue_service.py`: `get_today() → (DailyIssue, summary, list[ArticleListItem])`; `get_by_filters(...)` reused by US2
- [x] T043 [US1] Implement `GET /api/v1/daily/today` in `backend/app/api/daily.py`: call IssueService; return shape per `contracts/daily-today.md`; 200 ready / 404 2002 not-generated / 409 2003 generating
- [x] T044 [US1] Implement `GET /api/v1/articles/{id}` in `backend/app/api/articles.py`: return full Article; 404 2001 if not found (extend in US2 for `GET /articles`)
- [x] T045 [P] [US1] Implement `GET /api/v1/meta` in `backend/app/api/meta.py`: return 4 sources + 4 types per `contracts/meta.md` (no DB hit; built from `app/models/meta.py` constants)
- [x] T046 [P] [US1] Implement `GET /api/v1/healthz` in `backend/app/api/healthz.py`: return `{status, version, pipeline: {collector, summarizer}}` per `contracts/healthz.md`; pipeline status derived from last collector/summarizer outcomes
- [x] T047 [US1] Wire first-install auto-trigger in `backend/app/main.py` FastAPI startup event: query `SELECT COUNT(*) FROM daily_issues`; if 0 → schedule immediate background `generate_issue(today)` (FR-001b)
- [x] T048 [US1] Build left index panel in `frontend/index.html` + `frontend/static/app.js`: report header (date / edition / status badge), summary badges byType + bySource, articles list rendering 7 fields, skeleton state during loading, "正在翻今天的墙头" state on 2002
- [x] T049 [US1] Build right reader detail view in `frontend/static/app.js`: on article click → `GET /articles/{id}` → render lede/summary/body[]/quote/points/sourceName/readingMinutes/publishedAt; 「阅读原文」 button opens sourceUrl in new tab
- [x] T050 [US1] Wire `/meta` call on page load in `frontend/static/app.js`: cache to sessionStorage; never hardcode source/type lists (SC-008/SC-011)
- [x] T051 [US1] Add polling for 2003 generating state in `frontend/static/app.js`: exponential backoff (initial 5s, max 15s, up to 30 attempts)

**Checkpoint**: US1 MVP 可独立交付——首装 → 自动生成 → 今日刊浏览 → 详情阅读 → 阅读原文端到端跑通

---

## Phase 4: User Story 2 - 双维筛选今日刊 (Priority: P2)

**Goal**: 用户通过类型 chip + 来源 chip 组合筛选当日刊期，列表实时刷新，筛选 chips 由 `/meta` 驱动不硬编码

**Independent Test**: 在今日刊页面切换类型 chip / 来源 chip / 组合 → 列表刷新 → 空态显示「今天的货架是空的」→ 非法枚举值不发起请求

### Tests for User Story 2

- [x] T052 [P] [US2] Contract test for `GET /articles?type=&src=&page=&pageSize=` in `backend/tests/integration/test_articles_list.py`: 200 + appliedFilters echo / empty items[] / 1002 invalid enum / 1005 page out of range / 429 rate limit
- [x] T053 [P] [US2] Frontend E2E test in `backend/tests/e2e/test_filter.py`: click type chip → click source chip → assert list filtered

### Implementation for User Story 2

- [x] T054 [US2] Implement `ArticleService.list(filters, page, pageSize)` in `backend/app/services/article_service.py`: type/src/issueId filter via WHERE; pagination via LIMIT/OFFSET; returns `(items, total, appliedFilters)`
- [x] T055 [US2] Extend `GET /api/v1/articles` in `backend/app/api/articles.py`: parse type/src/page/pageSize via T017 pagination validator; raise 1002 on invalid enum (FR-013/014/015/016); shape per `contracts/articles-list.md`
- [x] T056 [US2] Build type filter chips UI in `frontend/static/app.js`: rendered from cached `/meta` types[]; on click → emit request with `?type=...`; highlight active chip; combined with source filter
- [x] T057 [US2] Build source filter chips UI in `frontend/static/app.js`: same pattern as type chips; combined filtering supported
- [x] T058 [US2] Add request debouncing in `frontend/static/app.js`: 250ms wait on rapid chip switching; cancel in-flight request via AbortController
- [x] T059 [US2] Add "今天的货架是空的" empty state in `frontend/index.html` + `frontend/static/app.js`: shown when `items: []` returned
- [x] T060 [US2] Validate invalid enum client-side in `frontend/static/app.js`: reject any chip key not in cached `/meta` (defense in depth) before request; show inline toast

**Checkpoint**: US2 完成——今日刊 + 双维筛选均独立可用

---

## Phase 5: User Story 3 - 配置我的偏好 (Priority: P3)

**Goal**: 用户在设置面板控制 4 源 + 4 类型开关、推送开关与时间，保存后系统告知下一期生效刊期；可恢复默认

**Independent Test**: 打开设置 → 回填当前偏好 → 修改开关 + 推送时间 → 保存 → 看到 X-Effective-At 提示 → 刷新验证持久化 → 恢复默认 → 验证回 08:00 全开

### Tests for User Story 3

- [x] T061 [P] [US3] Contract test for `GET /settings` in `backend/tests/integration/test_settings.py`: 200 with 4-source/4-type keys; 401 1003 no token
- [x] T062 [P] [US3] Contract test for `PUT /settings` in `backend/tests/integration/test_settings_put.py`: 200 + X-Effective-At header; 1005 missing key / invalid time / non-boolean; idempotent on repeat
- [x] T063 [P] [US3] Contract test for `POST /settings/reset` in `backend/tests/integration/test_settings_reset.py`: returns default Settings; same as first-time GET
- [x] T064 [P] [US3] Integration test for next-issue effect in `backend/tests/integration/test_settings_effect.py`: save {github: false} → trigger next-day generate → filtersApplied.sources excludes github

### Implementation for User Story 3

- [x] T065 [P] [US3] Create `Settings` model + schema in `backend/app/models/settings.py`: singleton row (id=1); 4 source booleans + 4 type booleans + dailyPush{enabled,time} + updatedAt; Pydantic `SettingsIn` (input, no updatedAt) vs `SettingsOut` (with updatedAt)
- [x] T066 [US3] Implement `SettingsService` in `backend/app/services/settings_service.py`: `get() → SettingsOut`; `save(s: SettingsIn) → (SettingsOut, effective_at_date)`; `reset() → SettingsOut`; `get_current_filters() → (sources[], types[])` for pipeline; `effective_at` computed as next calendar day in Asia/Shanghai
- [x] T067 [US3] Implement `GET /api/v1/settings` in `backend/app/api/settings.py`: require_auth; return SettingsOut
- [x] T068 [US3] Implement `PUT /api/v1/settings` in `backend/app/api/settings.py`: require_auth + rate-limit (writes); validate SettingsIn via Pydantic (raises 1005 on validation fail); set response header `X-Effective-At: YYYYMMDD`; idempotent (FR-022)
- [x] T069 [US3] Implement `POST /api/v1/settings/reset` in `backend/app/api/settings.py`: require_auth; call SettingsService.reset; set X-Effective-At header
- [x] T070 [US3] Build settings panel in `frontend/index.html` + `frontend/static/app.js`: rendered from `/meta` (sources[] + types[] switches) + dailyPush inputs (toggle + time picker); on open fetch `/settings` to backfill
- [x] T071 [US3] Implement save handler in `frontend/static/app.js`: PUT full state; read X-Effective-At from response header; toast 「明天的日报将按新口味调配（生效刊期: YYYY-MM-DD）」
- [x] T072 [US3] Implement reset button in `frontend/static/app.js`: POST `/settings/reset` → backfill form with returned defaults
- [x] T073 [US3] Add validation UI for `dailyPush.time` in `frontend/static/app.js`: HTML5 pattern + server-side 1005 error display in form

**Checkpoint**: US3 完成——偏好设置 + 下一期生效语义可端到端验证

---

## Phase 6: User Story 4 - 分享一条资讯 (Priority: P4)

**Goal**: 用户在详情视图对任意条目生成分享卡片，得到可复制/可打开的卡片链接

**Independent Test**: 在任意详情点击「分享这条」→ 收到 cardUrl → 复制可粘贴 → 在新标签页打开看到分享页

### Tests for User Story 4

- [x] T074 [P] [US4] Contract test for `POST /share` in `backend/tests/integration/test_share.py`: 200 + shareId shr_<8hex> + cardUrl + articleTitle; 2001 article not found; 1001 missing articleId; 1003 no token

### Implementation for User Story 4

- [x] T075 [P] [US4] Create `ShareCard` model + schema in `backend/app/models/share_card.py`: shareId (PK, format `shr_<8hex>`), articleId (FK), articleTitle (snapshot), cardUrl, createdAt
- [x] T076 Create Alembic migration 002 in `backend/migrations/versions/002_share_cards.py` (additive, no breaking change to existing tables)
- [x] T077 [US4] Implement `ShareService` in `backend/app/services/share_service.py`: `generate(articleId) → ShareCard`; verify article exists (raise 2001); generate shareId via `secrets.token_hex(4)`; build cardUrl as `{host}/share/{shareId}`; persist ShareCard; return shape per `contracts/share.md`
- [x] T078 [US4] Implement `POST /api/v1/share` in `backend/app/api/share.py`: require_auth; parse `{articleId}`; raise 1001 if missing; call ShareService
- [x] T079 [US4] Implement share card viewer page at `GET /share/{shareId}` in `backend/app/api/share.py`: return minimal HTML (articleTitle + link to article detail + 「阅读原文」 button using stored sourceUrl snapshot from Article); no auth (publicly shareable)
- [x] T080 [US4] Build 「分享这条」 button in detail view in `frontend/static/app.js`: POST `/share` with articleId; show returned cardUrl + articleTitle in modal; copy-to-clipboard via `navigator.clipboard.writeText`; open-in-new-tab button

**Checkpoint**: US4 完成——分享能力可用，其他用户故事不受影响

---

## Phase 7: User Story 5 - 异常态优雅呈现 (Priority: P5)

**Goal**: 在网络异常、限流、500/503 等场景下，UI 稳定呈现错误提示且可重试；错误响应永不泄露内部栈/SQL/密钥

**Independent Test**: 模拟 1001/1002/1003/1005/1006/9001/9002 错误响应 → 前端按错误码表稳定呈现 → 验证响应体仅含 code/message/requestId 三字段

### Tests for User Story 5

- [x] T081 [P] [US5] Security test in `backend/tests/integration/test_error_sanitization.py`: trigger 9001 via unhandled exception in test route → assert response body exactly `{code, message, requestId}` (no stack, no SQL, no env var values)

### Implementation for User Story 5

- [x] T082 [US5] Build global error toast component in `frontend/static/app.js`: read `message` from any non-2xx response; show transient toast; never display `requestId` to user (only console.log for debugging)
- [x] T083 [US5] Map business codes to UI behaviors in `frontend/static/app.js`: 1001/1005 → inline form field error; 1002 → chip-area inline message; 1003 → redirect to login panel; 1006 → toast「操作太频繁，稍后再试」; 2001/2002 → block-level empty state; 2003 → keep skeleton + poll; 9001/9002 → global error panel with retry button
- [x] T084 [US5] Add retry button for 9001/9002 in `frontend/index.html`: re-issue last failed request via cached request descriptor; preserve current filters & settings context
- [x] T085 [US5] Add 401 redirect hook in `frontend/static/app.js`: on 1003 from any write endpoint → show login panel (token input) → on submit cache token in localStorage → retry original request
- [x] T086 [US5] Verify error response contract in `backend/app/infra/errors.py`: handler strips all extra fields; assertion test added in T081 guards regression

**Checkpoint**: US5 完成——所有错误码均有稳定 UI 行为，安全契约验证通过

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: 跨故事一致性、可维护性与开源准备

- [ ] T087 [P] Write `README.md` at repo root: local startup steps, all `AIDAILY_*` env vars table, 9 API call examples (curl), RSSHub deploy snippet, log location, dev scripts
- [ ] T088 [P] Add `docker-compose.yml` at repo root: service `backend` (build `./backend`) + service `rsshub` (image `diygod/rsshub:latest`, port 1200) + volume for SQLite; one-command `docker compose up`
- [ ] T089 [P] Add `backend/Dockerfile` (Python 3.11-slim, install deps, copy app, run uvicorn)
- [ ] T090 [P] Configure GitHub Actions CI in `.github/workflows/ci.yml`: matrix Python 3.11 on ubuntu-latest; steps: install deps via uv → ruff check → mypy → pytest --cov --cov-fail-under=80 → playwright install + e2e
- [ ] T091 [P] Add OpenAPI auto-doc at `GET /docs` (FastAPI default) and `GET /openapi.json` for downstream SDK generation; document all 9 endpoints with response examples
- [ ] T092 [P] Add performance benchmark tests in `backend/tests/performance/test_perf_budgets.py`: locust or pytest-benchmark; assert `GET /daily/today` P95 ≤ 500ms, `GET /articles` P95 ≤ 300ms, `GET /articles/{id}` P95 ≤ 200ms (per Constitution IV)
- [ ] T093 [P] Add log rotation + structured JSON in `backend/app/infra/logging.py`: `RotatingFileHandler` 10MB × 5 files; include `request_id`/`source`/`issue_id` fields in every log line
- [ ] T094 [P] Add `CONTRIBUTING.md` + `CHANGELOG.md` at repo root for open-source readiness (dev setup, commit conventions, PR workflow)
- [ ] T095 Run all `quickstart.md` VS-1 ~ VS-10 + VS-9a + VS-9b scenarios end-to-end; document any remaining gaps in README "Known Limitations" section

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖，立即可启动
- **Foundational (Phase 2)**: 依赖 Phase 1 完成 → 阻塞所有用户故事
- **User Stories (Phase 3–7)**: 均依赖 Phase 2 完成
  - US1 (Phase 3) 是 MVP，**必须最先完成**
  - US2/US3/US4/US5 可并行（若团队容量允许）
  - 或按优先级顺序串行（US1 → US2 → US3 → US4 → US5）
- **Polish (Phase 8)**: 依赖所有目标用户故事完成

### User Story Dependencies

- **US1 (P1)**: 依赖 Phase 2 — 无其他用户故事依赖
- **US2 (P2)**: 依赖 Phase 2 — 复用 US1 的 Article 模型与 IssueService，但可独立测试
- **US3 (P3)**: 依赖 Phase 2 — 独立于 US1/US2/US4/US5
- **US4 (P4)**: 依赖 Phase 2 — 复用 US1 的 Article 模型（外键）
- **US5 (P5)**: 依赖 Phase 2 — 复用所有用户故事的 UI 行为，但仅添加错误处理层

### Within Each User Story

- Tests (Red) → Models → Pipeline/Services → API → Frontend → Integration (Green)
- Models 在 Services 之前；Services 在 API 之前；API 在 Frontend 之前
- 每个故事完成即提交，下一个故事开始前 commit 已落库

### Parallel Opportunities

- Phase 1 所有 T003–T007 [P] 任务可并行
- Phase 2 所有 T009–T017, T019–T020 [P] 任务可并行
- US1 中 T021–T031 [P] 测试与模型任务可并行
- US1 中 T035–T038 [P] 4 个 collector 可并行
- US3 / US4 / US5 完成后 US3 内 T061–T064 [P] 测试可并行
- 多开发者场景：US2/US3/US4/US5 可由不同人并行推进（US1 是 MVP，先完成）

---

## Parallel Example: User Story 1

```bash
# Parallel batch 1 — Tests (Red phase, all should fail initially):
Task: "T021 [P] [US1] Contract test GET /daily/today"
Task: "T022 [P] [US1] Contract test GET /articles/{id}"
Task: "T023 [P] [US1] Contract test GET /meta"
Task: "T024 [P] [US1] Contract test GET /healthz"
Task: "T025 [P] [US1] Integration test first-install auto-trigger"
Task: "T026 [P] [US1] Unit test summarizer"
Task: "T027 [P] [US1] Unit test partial failure tolerance"

# Parallel batch 2 — Models:
Task: "T028 [P] [US1] Article model + schema"
Task: "T029 [P] [US1] DailyIssue model + schema"
Task: "T030 [P] [US1] Source/Type metadata schemas"

# Parallel batch 3 — Collectors:
Task: "T035 [P] [US1] GitHub collector"
Task: "T036 [P] [US1] Reddit collector"
Task: "T037 [P] [US1] Web RSS collector"
Task: "T038 [P] [US1] X RSSHub collector"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only) — 推荐

1. 完成 Phase 1: Setup（T001–T007）
2. 完成 Phase 2: Foundational（T008–T020）— **CRITICAL，阻塞所有故事**
3. 完成 Phase 3: User Story 1（T021–T051）
4. **STOP & VALIDATE**: 运行 `quickstart.md` VS-1 + VS-3 + VS-9 + VS-9a，独立验证 US1
5. 可部署/演示——首装 → 5-10 分钟自动生成 → 今日刊浏览 → 详情阅读 → 阅读原文端到端跑通

### Incremental Delivery

1. Setup + Foundational → 基础设施就绪
2. + US1 → 独立测试 → 部署/演示（MVP!）
3. + US2 → 独立测试 → 双维筛选可用
4. + US3 → 独立测试 → 偏好下一期生效
5. + US4 → 独立测试 → 分享卡片
6. + US5 → 独立测试 → 异常态稳定
7. Phase 8 Polish → 开源发布就绪

### Parallel Team Strategy

多开发者场景：
1. 团队共同完成 Setup + Foundational
2. Foundational 完成后：
   - Dev A: US1（MVP，优先级最高）
   - Dev B: US2（依赖 US1 的 Article/IssueService，可与 US1 后期并行）
   - Dev C: US3（完全独立）
3. US1 完成后：
   - Dev A: US4 或 US5
4. 各故事完成时独立集成测试，互不阻塞

---

## Notes

- **TDD 强制**：Constitution II 要求 Red→Green→Refactor；每个用户故事的 Tests 部分必须先完成且失败验证
- **覆盖率门槛**：CI 中 `pytest --cov-fail-under=80`（T090）阻止覆盖率退化
- **Mock 边界**：仅 LLM (`respx`) 与外部源 HTTP 边界允许 mock；DB 与业务逻辑用真实本地 SQLite（Constitution II）
- **提交粒度**：每个任务或逻辑分组一个 commit；提交信息遵循 `<type>: <description>` 格式
- **检查点纪律**：每个用户故事完成后停止并独立验证；避免「全部做完再测」导致集成地狱
- **避免**：模糊任务、同文件冲突、跨故事依赖破坏独立性
- **路径约定**：所有后端路径相对 `backend/`，前端路径相对 `frontend/`，根目录文件（README/docker-compose）相对仓库根
