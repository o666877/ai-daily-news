# Phase 0 Research: AI 日报系统

**Date**: 2026-08-12
**Status**: Updated 2026-08-12 — D5/D7 simplified per clarify session (Anthropic-only + RSSHub for X)

## Summary of Decisions

- **D1**: Python 3.11 (CPython)
- **D2**: FastAPI 0.110 + Uvicorn + Starlette middleware
- **D3**: SQLite (WAL mode) via `aiosqlite` + Alembic migrations
- **D4**: pytest + pytest-asyncio + httpx (integration) + Playground E2E (Playwright Python)
- **D5**: **单一 Anthropic 兼容协议适配器**（不支持 OpenAI / Gemini）；`AIDAILY_LLM_BASE_URL` + `AIDAILY_LLM_MODEL` + `AIDAILY_LLM_API_KEY` 三参数配置，可指向官方 API 或任何兼容转发服务（OneAPI / DeepSeek / Moonshot）
- **D6**: Static Bearer token via `AIDAILY_BEARER_TOKEN` env var (no JWT, no session)
- **D7**: X = **自部署 RSSHub `/twitter/user/:id`**（默认 20-30 个 AI KOL 账号清单，可经 `AIDAILY_X_ACCOUNTS` 覆盖）；GitHub = REST API v3 + trending scraper fallback；Reddit = PRAW (Reddit API)；web = RSS + httpx with readability
- **D8**: In-process APScheduler 3.10 with SQLite jobstore + manual retry
- **D9**: Vanilla HTML + Alpine.js 3 + htmx (no build step), `<script type="module">`
- **D10**: Pydantic v2 (`BaseModel`, `StrictStr`, `Field`)

---

## D1: Language/Version

**Decision**: **Python 3.11** (CPython, latest stable patch within 3.11.x)

**Rationale**:
- **LLM SDK maturity**: `openai`, `anthropic`, and `google-generativeai` are first-party, officially maintained Python SDKs. They lead Node SDKs by weeks on protocol changes (e.g., Anthropic's prompt caching, OpenAI's structured outputs). LangChain is also Python-first.
- **Scraping ecosystem**: `httpx`, `selectolax`, `trafilatura`, `readability-lxml`, `feedparser` form the strongest scraping stack across the three candidates. Trafilatura's boilerplate extraction is the best-in-class for the `web` source.
- **TDD tooling**: pytest is the gold standard — fixtures, parametrize, `pytest-asyncio` for async, deterministic SQLite test DBs, parallel via `pytest-xdist`. Coverage via `pytest-cov` enforces the ≥80% constitution requirement natively.
- **Single-user ops**: A single-user PC web app benefits most from one language across backend, scheduler, and collectors. Python's `uvicorn` + `apscheduler` run in-process; deploy = `python -m aidaily` or PyInstaller one-file exe for non-technical users.
- **LLM cost control**: Python's typing + Pydantic enable structured-output enforcement which materially reduces retry spend — relevant given the Open Risk on token cost.

**Alternatives Considered**:
- **Node.js 20 LTS + TypeScript** — Strong types via Zod and excellent `puppeteer`/`playwright` for scraping, but LLM SDK feature lag (Anthropic caching shipped 3+ weeks late in TS), weaker readability extraction (`@mozilla/readability` is fine but the surrounding ecosystem is thinner), and the build step (tsx/ts-node) complicates the "open-source, no build" philosophy for the prototype-matching frontend.
- **Go 1.22** — Best single-binary deploy (truly static, cross-compile to Windows from anywhere) and top-tier HTTP stack (`chi`/`echo`), but LLM SDKs are community-maintained (`sashabaranov/go-openai`), scraping is painful (no good readability port, `colly` is decent but verbose), and the verbose error-handling style slows TDD red-green-refactor cycles. Go's strength (concurrency at scale) is irrelevant for a single-user daily cron.

**Versions pinned**: CPython 3.11.9, managed via `uv` for reproducible lockfile.

---

## D2: HTTP Framework

**Decision**: **FastAPI 0.110+** on Uvicorn 0.29 (ASGI), with Starlette middleware components.

**Rationale**:
- **Bearer auth middleware**: Native `HTTPBearer` security scheme + dependency injection. Reads-only vs writes-only split is a one-line `Depends` on write routes (FR-026).
- **Rate limiting**: `slowapi` (Starlette middleware) — supports per-route limits. Configure `Limiter(key_func=get_remote_address)` with two policies: `120/minute` on reads (keyed by IP) and `30/minute` on writes (keyed by user/token). Maps directly to FR-027 and returns 1006 business code on exceed.
- **Request ID propagation**: Starlette middleware reads `X-Request-Id` header (or generates UUIDv7), stores in `request.state`, echoes back via `Response.headers`. Trivially composes with the unified error response (`requestId` field).
- **Custom `X-Effective-At` header**: Return `Response` object from `PUT /settings` with explicit `headers={"X-Effective-At": "20260813"}` (FR-018). FastAPI's response model + explicit response object split makes this clean.
- **Unified error structure**: Custom `app.exception_handler` for business exceptions → maps to `{code, message, requestId}` JSON (FR-028). FastAPI's `HTTPException` + custom `BusinessError` class covers all 9 error codes (1001/1002/1003/1004/1005/1006/2001/2002/2003/9001/9002).
- **Async-native**: Uvicorn ASGI + `httpx.AsyncClient` for upstream LLM/scraping = real I/O concurrency under one worker, which is how a single-process local app should behave.
- **OpenAPI auto-generated**: Spec compliance testable — wire the 9 endpoints, FastAPI emits OpenAPI 3.1, then assert contract matches the interface doc automatically.

**Alternatives Considered**:
- **Flask 3 + Flask-RESTful** — Synchronous; would need `flask-limiter` (different syntax from slowapi) and a custom `X-Request-Id` middleware. WSGI hurts when the app holds 4 concurrent upstream HTTP calls per request.
- **Litestar 2** — Excellent feature set (built-in DTOs, ASGI-native), but smaller community and less battle-tested for the specific middleware combo we need. FastAPI's ecosystem depth wins.
- **Django + DRF** — Overkill. ORM, admin, sessions, CSRF we don't need; performance budget would be harder to hit.

**Versions pinned**: `fastapi==0.110.3`, `uvicorn[standard]==0.29.0`, `slowapi==0.1.9`.

---

## D3: Storage

**Decision**: **SQLite** (system SQLite ≥ 3.44 for JSON1 + RETURNING) accessed via `aiosqlite` with **WAL mode**. Migrations via **Alembic**.

**Rationale**:
- **Zero-ops**: Single file `~/.aidaily/data.db`. Process restart recovers automatically. No service install, no port, no user creation. Matches "本地单用户" deployment perfectly.
- **Scale fit**: ≤50 articles/day × 365 days = ~18k rows/year. SQLite handles millions effortlessly; vacuum quarterly at most.
- **WAL mode**: Concurrent reads during writes — the scheduler writes while the web server reads without blocking. `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;` for the right perf/safety tradeoff.
- **Schema migrations**: Alembic with autogenerate against SQLAlchemy 2.0 declarative models. Each migration is a reviewed, versioned file under `migrations/versions/` — matches the constitution's "schema migrations" requirement.
- **Settings persistence**: Single-row `settings` table with `id=1` sentinel. Updates are immutable in code (return new object) but persisted via parameterized UPSERT.
- **Share card tracking**: `share_cards` table with FK to `articles`. Idempotent generation by `(article_id, user_id)` unique constraint (FR-022-style idempotency for shares).

**Schema sketch** (decisive, not exhaustive):
- `issues(id TEXT PK, date TEXT, edition INT, status TEXT, generated_at TEXT, filters_applied JSON)`
- `articles(id TEXT PK, issue_id TEXT FK, type TEXT, src TEXT, title TEXT, excerpt TEXT, lede TEXT, summary TEXT, body JSON, quote TEXT NULL, points JSON, time TEXT, source_url TEXT, source_name TEXT, reading_minutes INT, published_at TEXT)`
- `sources(key TEXT PK, name TEXT, short TEXT, icon TEXT, description TEXT)`
- `types(key TEXT PK, name TEXT, short_name TEXT)`
- `settings(id INT PK DEFAULT 1, sources JSON, types JSON, daily_push JSON, updated_at TEXT)`
- `share_cards(share_id TEXT PK, article_id TEXT FK, created_at TEXT)`
- `alembic_version(version_num TEXT PK)`

**Alternatives Considered**:
- **PostgreSQL** — Strictly better database, but adds service install + port + user. Violates "zero-ops" assumption. Applicable only if v2 goes multi-user.
- **File-based (one JSON per issue)** — Tempting given the daily-cadence read pattern, but ad-hoc query support (filter by `type=agent AND src=reddit`) requires loading everything into memory. SQLite gives us SQL for free.

**Versions pinned**: `aiosqlite==0.20.0`, `sqlalchemy==2.0.30`, `alembic==1.13.1`.

---

## D4: Testing Framework

**Decision**: **pytest 8.x** ecosystem for unit + integration; **Playwright Python** for E2E.

**Rationale**:
- **pytest** is the canonical Python test runner. Fixtures, parametrize, `pytest-asyncio` mode = `auto`, parallel via `pytest-xdist -n auto`.
- **Unit**: Pure-Python test of LLM providers, business logic, schema validators, rate-limit middleware. LLM/external-source boundaries mocked via `respx` (httpx mock) — no network, deterministic, fast.
- **Integration**: Real local SQLite (in-memory `:memory:` or temp file via fixture). Spin FastAPI via `httpx.AsyncClient(transport=ASGITransport(app=app))` — full HTTP stack including middleware without binding a port. Tests every endpoint of the 9, with real DB writes/reads. This is what FR-001 through FR-030 are validated against.
- **E2E (Playwright Python)**: Headless Chromium drives the actual frontend against the real backend. Covers the 5 User Stories' acceptance scenarios — User Story 1 P95 timing, User Story 2 chip combos, User Story 3 preferences persistence, User Story 4 share flow, User Story 5 error states. Use `pytest-playwright` plugin for unified report.
- **TDD red-green-refactor**: pytest's fast feedback loop (single test <100ms) supports the loop natively. Constitution mandates TDD; pytest + `--cov=src --cov-fail-under=80` enforces ≥80% coverage as a CI gate.
- **Fixtures over factories**: Use JSON fixtures under `tests/fixtures/` for source payloads (X tweet, GitHub repo event, Reddit submission, web article HTML). Factory functions only where mutability aids test readability (`make_article(**overrides)`).

**Alternatives Considered**:
- **unittest + requests**: Built-in but verbose; async support awkward; no fixture sharing; coverage tools external.
- **Nose2**: Unmaintained de facto.
- **Hypothesis for property-based**: Tempting for pagination/filter logic, but adds cognitive load for a 9-endpoint system. Defer.

**Versions pinned**: `pytest==8.2.0`, `pytest-asyncio==0.23.7`, `pytest-cov==5.0.0`, `pytest-xdist==3.5.0`, `respx==0.21.1`, `pytest-playwright==1.44.0`.

---

## D5: LLM Provider Abstraction

**Decision**: **单一 Anthropic 兼容协议适配器**（不支持 OpenAI / Gemini）。使用 **Anthropic 官方 Python SDK** `anthropic==0.27.0`，通过三个环境变量配置端点与模型：

```bash
AIDAILY_LLM_BASE_URL=https://api.anthropic.com   # 默认；可改为 OneAPI / DeepSeek / Moonshot 转发层
AIDAILY_LLM_MODEL=claude-haiku-4-5-20251001      # 默认；可改为任何 Anthropic 协议兼容模型
AIDAILY_LLM_API_KEY=sk-ant-...                    # 必填
```

**Rationale**（clarify session 2026-08-12 用户决议，覆盖原 D5）：
- **单一协议降低复杂度**：clarify Q5 决议采用 Anthropic 兼容协议作为唯一集成层；移除 OpenAI / Gemini 适配器后，代码量减少约 60%，CI 测试只需一个 fixture。
- **`base_url` 可配 = 兼容转发生态**：国内主流 LLM 网关（OneAPI / DeepSeek / Moonshot / 智谱等）均提供 Anthropic 协议兼容端点；部署者只需切换 `AIDAILY_LLM_BASE_URL` 即可指向自部署网关，无需改代码。
- **官方 SDK 仍是首选**：Anthropic 官方 Python SDK 直接支持 `base_url` 参数（`Anthropic(base_url=..., api_key=...)`），无需自行实现协议；保留 prompt caching、streaming、tool calling 等高级特性。
- **LangChain 仍被拒绝**：与原 D5 一致——抽象了成本控制点、增加依赖体积、与 Pydantic schema 冲突。
- **接口简化**：
  ```python
  class LLMClient:
      def __init__(self, base_url: str, api_key: str, model: str): ...
      async def summarize(self, article: ArticleInput) -> ArticleSummary: ...
  ```
  不再需要 ABC + 多 adapter；单一类即可。
- **Retry (max 2)**：仍使用 `tenacity==8.3.0`，指数退避（1s, 4s），针对 `RateLimitError` / `APITimeoutError` / 瞬时 HTTP 5xx。符合 FR-007。
- **成本护栏**：所有调用记录 input/output token 数到 `llm_calls` 表；日预算上限（`AIDAILY_LLM_DAILY_BUDGET_USD=2.00`）超限时标记刊期 `failed` 并返回业务码 `9002`。
- **fail-fast**：启动时校验 `AIDAILY_LLM_API_KEY` 必填；`AIDAILY_LLM_BASE_URL` / `AIDAILY_LLM_MODEL` 缺省时使用默认值。

**Alternatives Considered**:
- **多 provider ABC（原 D5）**：被 clarify Q5 否决——单一协议足矣，多 provider 抽象属过度工程。
- **LangChain / LangGraph**：拒绝（同上）。
- **LiteLLM**：拒绝——虽然统一多 provider，但与「单一 Anthropic 协议」目标冲突，且增加第三方依赖风险。
- **裸 HTTP 调用（无 SDK）**：拒绝——自行实现 Anthropic 协议、auth 刷新、streaming 不值得；官方 SDK 已支持 `base_url` 参数，无需绕过。

**Versions pinned**: `anthropic==0.27.0`, `tenacity==8.3.0`。

---

## D6: Auth for Local Single-User

**Decision**: **Static Bearer token** via `AIDAILY_BEARER_TOKEN` env var. Reads anonymous; writes require `Authorization: Bearer <token>`.

**Rationale**:
- **Matches FR-026 exactly**: Reads open, writes authenticated. No sessions, no JWT lifecycle, no refresh tokens.
- **Single-user**: One user = one token. No need for user tables, no rotation policy beyond "regenerate env var on leak".
- **No JWT**: A signed JWT requires a secret to sign with — same secret we'd use for the static token, but now with extra base64 and expiry logic. Adds complexity, removes no risk.
- **No session**: Sessions need cookies + CSRF + expiry. Reads need to work anonymous per the contract; sessions buy nothing.
- **Constant-time comparison**: `secrets.compare_digest()` on the bearer token. Prevents timing-attack token recovery.
- **Token in env, not config file**: Config files get committed by accident. Env vars don't. Provide `AIDAILY_BEARER_TOKEN` in `.env` (gitignored) or system env.
- **Fail-fast on missing**: If `AIDAILY_BEARER_TOKEN` unset at startup, log warning and generate a random one, printing it once to stdout (so the user can copy it). Writes work immediately.
- **Frontend integration**: Frontend stores token in `localStorage` after user paste; sends `Authorization` header only on writes. Reads omit it.

**Alternatives Considered**:
- **JWT (HS256)**: Over-engineered. Single subject, no expiry policy needed for local app.
- **HTTP Basic with username:password**: Sends credentials every request; worse than bearer.
- **Cookie + CSRF token**: Adds CSRF token plumbing for zero benefit when there's no session.
- **No auth on writes**: Violates FR-026. The interface contract explicitly requires authentication on writes.

---

## D7: Source-Specific Collection

**Decision per source**:

**X (Twitter)** — **自部署 RSSHub `/twitter/user/:id` 路由**（clarify session 2026-08-12 决议：部署者无 X API token，改用 RSSHub 包装；不再使用 `tweepy`）。
- 部署者通过 `AIDAILY_X_RSSHUB_BASE_URL`（如 `http://localhost:1200`）指向自部署或公共 RSSHub 实例；未配置时 X 源静默跳过，不影响其他源。
- **默认账号清单**（约 20-30 个 AI 领域 KOL，硬编码在 `app/pipeline/defaults/x_accounts.py`，可经 `AIDAILY_X_ACCOUNTS` 环境变量覆盖）：模型与训练（@karpathy / @ylecun / @goodfellow_ian / @_jasonwei / @rasbt）、Agent / 智能体（@swyx / @simonw / @miramurati / @gdb）、工具与基建（@sama / @emilymenonbender / @fchollet）、研究机构（@AnthropicAI / @OpenAI / @huggingface / @StabilityAI / @MistralAI）。完整清单在 `tasks.md` 实现阶段最终敲定。
- **抓取模式**：对清单中每个账号并发请求 `{RSSHUB_BASE_URL}/twitter/user/{username}`，`feedparser` 解析返回的 RSS feed。
- **失败容错**：单账号失败跳过；整个 RSSHub 实例不可达 → X 源整源跳过（FR-007a 部分失败容错），其余 3 源继续采集。
- **ToS**：RSSHub 是开源社区维护的公共 RSS 包装器，部署者需自行评估目标平台 ToS；本期不直接抓 x.com。
**GitHub** — **REST API v3** via `httpx` (no SDK needed; auth via `AIDAILY_GITHUB_TOKEN` Personal Access Token, 5,000 req/hour).
- Primary: `/search/repositories?q=...&sort=stars&order=desc` for trending repos created in last 7 days.
- Secondary: `/users/:user/events/public` for activity from watched AI maintainers.
- Fallback: **scrape github.com/trending** with `httpx` + `selectolax` when API quota exhausted. Trending page is ToS-friendly (public, no auth wall).

**Reddit** — **PRAW 7.7** (Python Reddit API Wrapper) via Reddit API.
- Subreddits: `r/MachineLearning`, `r/LocalLLaMA`, `r/OpenAI`, `r/singularity`, `r/AgentAI`.
- Sort by `top` over `day`, take top 10–15 posts.
- Reddit API Free tier = 100 queries/minute per OAuth client; plenty for single-user daily.
- **No web scraping Reddit** — aggressive anti-bot, ToS violation, gets IP banned fast.

**Web (全网聚合)** — **RSS aggregation + httpx + trafilatura**.
- Curated OPML of 30–50 AI blogs/newsletters (Simon Willison, Stratechery, Hugging Face blog, Anthropic news, OpenAI blog, Latent Space, Import AI, etc.).
- `feedparser` for RSS/Atom parsing.
- For non-RSS sources discovered via search: `httpx` fetch + `trafilatura.extract()` for boilerplate stripping.
- **No general web scraping**: avoids anti-bot cat-and-mouse. RSS-first is ToS-friendly.

**Common scheduler pattern**: Each collector returns `list[RawItem]`; dedup by `(source_url_normalized)`; handoff to summarizer.

**ToS summary**: X = RSSHub 包装（无 x.com 直爬）；GitHub = official API + trending public page; Reddit = official API only; web = RSS only. Zero headless-browser scraping of authenticated/anti-bot pages.

**Alternatives Considered**:
- **X API v2 Free tier (`tweepy`)**: clarify session 已确认部署者无 token，否决。
- **Nitter 公共实例**: Nitter 实例 2024 年起大批关停，稳定性极差；自部署 RSSHub 是社区主流替代方案。
- **Scraping all sources with Playwright**: Universal but slow (10x LLM latency budget), fragile (UI changes break collection weekly), and ToS-violating for X/Reddit. Rejected.
- **Browserless / Scrapfly / Bright Data**: Paid SaaS scraping — out of scope for an open-source single-user tool.

**Versions pinned**: `praw==7.7.1`, `feedparser==6.0.11`, `trafilatura==1.10.0`, `selectolax==0.3.21`.（移除 `tweepy`，X 源改用 RSSHub）

---

## D8: Scheduler

**Decision**: **In-process APScheduler 3.10** with SQLite jobstore (shares the app's `data.db` via separate table prefix).

**Rationale**:
- **Single process**: Uvicorn worker + APScheduler `BackgroundScheduler` in same process. Avoids OS cron (which would require a second process / CLI command and cross-process locking).
- **User-configurable time**: Cron trigger `CronTrigger(hour=H, minute=M, timezone="Asia/Shanghai")`. H:M pulled from Settings on every fire. Reschedule when settings change (FR-018 effective next issue = re-arming trigger with new time).
- **Retry on failure**: APScheduler's `misfire_grace_time` + our own try/except wrapper. On failure, retry the whole job once after 5 minutes; if still failing, mark issue `failed` (FR-007).
- **Idempotent per issue ID**: Job logic first checks `SELECT 1 FROM issues WHERE id = :today`. If exists and `status='ready'`, no-op. If `status='failed'`, attempt regeneration. Otherwise generate. This makes the scheduler safe to fire multiple times (e.g., after app restart mid-generation).
- **Timezone correctness**: APScheduler uses `pytz`/`zoneinfo` natively. Hardcode `Asia/Shanghai` as default, never trust server local time. Avoids DST issues (China has no DST but the discipline matters).
- **Persists across restarts**: SQLite jobstore means even if the user closes the app at 07:59 and reopens at 08:01, the missed job fires (`misfire_grace_time=3600`).
- **Manual trigger (future)**: Constitution says v2 = manual immediate generate. APScheduler's `add_job(run_now=True)` is the obvious hook when v2 lands.

**Alternatives Considered**:
- **OS cron (Windows Task Scheduler / crontab)**: Requires separate CLI entrypoint, cross-process state coordination (file lock on `data.db`), and platform-specific install scripts. Much higher friction for a local single-user tool.
- **Celery + Redis**: Multi-process, needs Redis install. Absurd for 1 job/day.
- **Custom `asyncio.create_task` with `asyncio.sleep`**: Reinvents cron parsing + misfire recovery. APScheduler has 10 years of edge cases baked in.

**Versions pinned**: `apscheduler==3.10.4`, `tzdata==2024.1` (Windows tz database).

---

## D9: Frontend Approach

**Decision**: **Vanilla HTML + Alpine.js 3.14 + htmx 1.19**, served as static files by FastAPI (`app.mount("/static", StaticFiles(...))`). No build step. CDN tags optional; vendor the JS locally for offline support.

**Rationale**:
- **No build step**: Critical for the open-source friendliness criterion. Contributors open `v1 ai 日报.html`, edit, refresh. No `npm install`, no Vite, no transpile, no source maps.
- **Alpine.js**: ~15KB gzipped. Provides reactive `x-data`, `x-for`, `x-show`, `x-text` directives — enough for chips toggle, list filter, settings panel, modal, toast. Drop-in replacement for the static prototype's mock data.
- **htmx**: For swapping article detail pane on chip click. `hx-get="/api/v1/articles/20260812-0003" hx-target="#reader"`. Eliminates hand-rolled fetch + DOM mutation. Reduces JS surface area.
- **`/meta`-driven dynamic rendering**: Alpine component fetches `/api/v1/meta` on load, `x-for` renders chips and toggle switches from response. Zero hardcoded source/type literals — directly satisfies SC-008, SC-011, FR-003.
- **Skeleton/empty/error states**: Alpine `x-show` based on state machine `loading | ready | empty | error`. CSS skeleton shimmer via 3 lines of CSS. Error toast component fed from `{code, message, requestId}` body.
- **Preserves prototype**: The existing `v1 ai 日报.html` becomes the production template. Replace `ARTICLES` mock with `fetch('/api/v1/daily/today')`. Same DOM, same CSS, same UX.
- **Token storage**: `localStorage.setItem('aidaily_token', ...)`. Alpine reads, attaches to write requests. Reads work without it.

**Alternatives Considered**:
- **React (Vite)**: Heavy for 5 user stories. Adds 200KB+ JS, build step, JSX. The prototype is plain HTML — porting to JSX is a rewrite.
- **Vue 3 SFC**: Same issues as React.
- **SvelteKit**: Build step, SSR overkill.
- **Pure vanilla (no Alpine)**: Doable but reimplements reactivity (`addEventListener` + `querySelector` everywhere). Triple the JS code for no benefit.

**Versions pinned**: Alpine.js 3.14.1 (vendored), htmx 1.19.5 (vendored). Both checked into `/static/vendor/`.

---

## D10: Validation Library

**Decision**: **Pydantic v2** (`pydantic==2.7.1`) for request/response models, query params, and settings DTO.

**Rationale**:
- **FastAPI native**: FastAPI uses Pydantic schemas for `Body(...)`, `Query(...)`, `Depends(...)`. Validation is automatic and errors map to 422 by default — perfect for FR-021 / business code 1005.
- **Strict enums**: `Literal["agent", "self_improve", "open_source", "tools"]` for type fields. Invalid value → 422 → caught by custom exception handler → business code 1002 (FR-016). Conversion layer in exception handler distinguishes "bad enum" (1002) from "bad body shape" (1005).
- **HH:mm validation**: `dailyPush.time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")`. Invalid → 422 → 1005.
- **Immutability**: Pydantic v2 supports `model_config = ConfigDict(frozen=True)` for read-after-validate immutable models. Matches constitution's immutability rule.
- **Settings DTO roundtrip**: `Settings` model serializes to the exact JSON shape in §4.4 of the interface doc. Pydantic's `model_dump_json()` produces canonical output — no manual `to_dict` drift.
- **OpenAPI emission**: FastAPI emits Pydantic schemas into OpenAPI. The auto-generated spec becomes our contract test fixture.
- **Performance**: Pydantic v2 core is Rust (`pydantic-core`). Validation of a 12-article list is sub-millisecond — well within the 500ms P95 budget.

**Alternatives Considered**:
- **marshmallow**: Older, slower, less FastAPI-friendly.
- **cerberus**: Lighter but no type system, no codegen. Wrong fit for typed response models.
- **Manual validation**: Would re-implement what Pydantic already gives us for free, with more bugs.

**Versions pinned**: `pydantic==2.7.1`, `pydantic-settings==2.2.1` (for env config), `email-validator==2.1.1` (optional, for future user features).

---

## Cross-cutting Concerns

### LLM Provider Switching Strategy
- **Env-driven factory**: `LLM_PROVIDER` env var selects adapter at startup. `LLMProviderFactory.from_env()` returns the concrete adapter. App depends only on `LLMProvider` ABC. Unit tests inject fake provider.
- **Cost-per-call logging**: Every call to any adapter writes `{provider, model, input_tokens, output_tokens, cost_usd, latency_ms}` to `llm_calls` table. Daily aggregation in `/healthz` (subsystem health includes LLM spend).
- **Model fallback chain** (future): `LLM_MODEL_FALLBACK=gpt-4o-mini,claude-3-5-haiku-latest` — try primary, on 5xx fall through. Not in v1 to avoid scope creep.
- **Structured output enforcement**: All adapters call the provider's structured-output API (OpenAI `response_format=json_schema`, Anthropic tool-use trick, Gemini `responseMimeType=application/json`). This eliminates JSON parse failures and reduces token spend on retries.

### Error Handling Pattern (internal exceptions → business codes)
- **`BusinessError` base class**: `BusinessError(code: int, message: str, http_status: int)`. Subclasses for each of the 11 codes (1001–9002).
- **Custom exception handlers** in FastAPI:
  - `BusinessError` → returns `{code, message, requestId}` with mapped HTTP status.
  - `RequestValidationError` → 1005 (422) for body errors, 1002 (400) for query enum errors (distinguish via error location).
  - `HTTPException` from Starlette (e.g., 404) → mapped to appropriate business code.
  - Catch-all `Exception` → 9001 (500), log full stack to file, never include in response.
  - LLM/collector `PipelineBusy` → 9002 (503).
- **Request ID plumbing**: Middleware sets `request.state.request_id` (from header or generated). All handlers read it from there. Error response builder pulls from `request.state`. Logger filter includes request ID on every line.
- **Immutability rule**: Errors are constructed, not mutated. `raise BusinessError(code=2001, message="文章不存在")` — no `err.set_code(...)` methods.

### Test Data Strategy
- **Fixtures over factories**: JSON files under `tests/fixtures/` for upstream payloads (`x_tweet.json`, `github_repo_event.json`, `reddit_submission.json`, `web_article.html`). These are real captured payloads (sanitized), committed to repo.
- **Factory functions** for entity creation in tests: `make_article(**overrides)` returns a valid `Article` instance with sensible defaults, overridden per-test. Reduces boilerplate without hiding setup.
- **Snapshot testing** rejected: For LLM summaries (the only "dynamic" output), use **golden-file comparison** under `tests/golden/` keyed by input hash. Updates require explicit `--update-golden` flag. Prevents silent regressions in summary quality.
- **Database fixture**: Each integration test gets a fresh in-memory SQLite (`sqlite+aiosqlite:///:memory:`) or temp-file DB via `tmp_path`. No shared state, no test ordering issues. Alembic migrations applied at fixture setup.
- **Mock boundaries**: LLM and external source HTTP calls mocked via `respx`. Database, scheduler, app code all real. This matches the "mock only at LLM/external boundaries" rule from the research question.

---

## Open Risks

### R1: X (Twitter) 内容采集 — LOW（已在 clarify session 解决）
- **Issue**: 原 R1 担忧 X API 可用性。
- **Resolution**（2026-08-12 clarify Q1）：采用自部署 RSSHub 方案，**不再依赖 X API**；部署者通过 `AIDAILY_X_RSSHUB_BASE_URL` + `AIDAILY_X_ACCOUNTS` 配置；未配置时 X 源静默跳过。
- **New Risk**: RSSHub 实例自身稳定性（公共实例限流/宕机）。缓解：推荐部署者自部署 RSSHub（Docker 单容器）；本期 README 提供部署指引。
- **默认账号清单覆盖度**：硬编码的 20-30 个 KOL 是否真能代表「AI 前沿哨兵」？缓解：清单可经 `AIDAILY_X_ACCOUNTS` 完全覆盖；用户反馈驱动迭代。

### R2: LLM Token Cost — LOW-MEDIUM
- **Issue**: ≤50 articles/day × ~3000 input tokens × ~800 output tokens = ~190k tokens/day。在 Anthropic Claude Haiku 4.5（默认推荐模型）费率下 ~$0.50–1.00/day；年化成本 ~$180–365。
- **Mitigation**: 默认 `claude-haiku-4-5-20251001`（廉价且摘要质量足够）；日预算硬上限 `AIDAILY_LLM_DAILY_BUDGET_USD=2.00`；摘要缓存（同 URL 7 天内复用）。clarify session 已确认采用 Anthropic 兼容协议，部署者可经 `AIDAILY_LLM_BASE_URL` 切换至任何低价兼容转发服务（如 DeepSeek、Moonshot）。

### R3: Reddit API Quota Tightening — LOW
- **Issue**: Reddit's 2023 API pricing changes affected third-party apps. Free tier for personal scripts still exists but rate limits are strict (100 req/min OAuth).
- **Mitigation**: Single-user daily pull of 5 subreddits × top-10 = ~50 calls. Well within quota. Monitor for 429s and back off via PRAW's built-in rate limiter.

### R4: Windows Path & Encoding — LOW
- **Issue**: Project deploys on Windows (per env). SQLite path with backslashes, file handle behavior differences, `zoneinfo` tz database not bundled on Windows.
- **Mitigation**: Use `pathlib.Path` everywhere. Add `tzdata` PyPI package as explicit dependency. Test on Windows in CI via GitHub Actions matrix.

### R5: Open-Source Licensing of Collected Content — LOW
- **Issue**: Redistributing LLM-summarized snippets of others' content in an open-source project. Fair use for personal use; murkier if shared via `POST /share`.
- **Mitigation**: Summaries are transformative and short (≤300 chars excerpt). Original article linked prominently. README states "for personal use; redistribution of share cards is user's responsibility." No full-text caching (FR-012).

### R6: First-Screen 1.5s Budget on Cold Start — LOW
- **Issue**: Local single-user, first request after process boot has import + DB pool warm-up cost.
- **Mitigation**: Uvicorn `--preload` loads app once at worker start. SQLite connection pool initialized in lifespan. LLM client initialized lazily (only when summarizer runs, not on read paths). Read endpoints (`/daily/today`, `/articles`, `/articles/{id}`, `/meta`) make zero external HTTP calls — pure SQLite reads, sub-50ms each.

---

**Research complete.** Decisions D1–D10 are concrete with pinned versions. Open Risks R1–R6 documented with mitigations. Ready to proceed to Phase 1 (planning) — produce `plan.md` with task breakdown referencing these decisions.
