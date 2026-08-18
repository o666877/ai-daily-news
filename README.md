# AI 日报系统 (AI Daily News)

> 一个本地优先的 AI 资讯聚合日报系统。每日自动从 X (Twitter)、GitHub、Reddit、全网 RSS 抓取 AI 领域资讯，经 LLM 摘要后以本地 Web 应用形式呈现，支持双维筛选、偏好配置、分享卡片。

[![CI](https://github.com/your-org/ai-daily-news/actions/workflows/ci.yml/badge.svg)](.github/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 项目简介

AI 日报系统面向 AI 开发者、研究者与重度爱好者，每日 08:00 (Asia/Shanghai) 自动生成一期「AI 日报」，包含：

- **今日刊**：当日 4 大来源 + 5 大分类聚合，每篇含 LLM 摘要（导语/正文/引用/要点）
- **双维筛选**：5 类型 × 4 来源任意组合（Reddit+Agent、X+开源 等）
- **偏好配置**：信息源/类型开关、日报条数（10/15/20/30）、推送时间，下一期自动生效
- **分享卡片**：一键生成可公开的卡片链接
- **首装自动触发**：第一次启动无需等到次日，5-10 分钟内出首期

### 信息源 & 类型

| Source (`src`)                                      | Type (`type`)                |
| --------------------------------------------------- | ---------------------------- |
| `x` (X / Twitter via twitter-cli)                   | `agent` (Agent / 智能体)        |
| `github` (GitHub trending + maintainer events)      | `self_improve` (持续学习 / 自我进化) |
| `reddit` (opencli 浏览器桥接 + Atom 兜底)                  | `open_source` (开源项目)         |
| `web` (RSS: Simon Willison, Anthropic, OpenAI, ...) | `tools` (工具与效率)              |
|                                                     | `commentary` (观点时评)          |

---

## 快速开始 (本地启动)

### 前置要求

- Python 3.11.9+
- 操作系统：Windows 11 / macOS 14+ / Ubuntu 22.04+
- （可选）`twitter` CLI：用于启用 X (Twitter) 源，见 [X 源配置](#x-twitter-源配置)
- （可选）Docker：用于一键部署

### 步骤 1：克隆 + 准备环境

```bash
git clone https://github.com/your-org/ai-daily-news.git
cd ai-daily-news

# 创建虚拟环境
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
```

### 步骤 2：安装后端依赖

```bash
cd backend/
pip install -e ".[dev]"
```

### 步骤 3：配置环境变量

```bash
cp ../.env.example ../.env
# 编辑 .env，至少填入 AIDAILY_LLM_API_KEY
```

最小必填项只有 LLM Key：

```dotenv
AIDAILY_LLM_API_KEY=sk-ant-...         # Anthropic 或兼容网关 API Key
```

X 源（twitter-cli）、Reddit 桥接（opencli）、GitHub PAT 均为可选增强，未配置时对应通道降级或跳过。

`AIDAILY_BEARER_TOKEN` 缺失时，后端首次启动会自动生成并打印到 stdout 一次。

### 步骤 4：（可选，仅启用 X 源）配置 twitter-cli

X 源通过本地 `twitter` CLI 子进程抓取，详见 [X (Twitter) 源配置](#x-twitter-源配置)。最小配置：

```dotenv
# .env —— 二选一：
# a) 显式凭据（x.com Cookie 中的值）
TWITTER_AUTH_TOKEN=...
TWITTER_CT0=...
# b) 复用本机浏览器登录态（Windows DPAPI）
AIDAILY_X_ALLOW_BROWSER_COOKIES=1
```

未配置时 X 源静默跳过，其余 3 源正常出刊。

### 步骤 5：初始化数据库

```bash
cd backend/
alembic upgrade head
```

### 步骤 6：启动后端

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

首次启动会自动后台触发初始刊期生成（FR-001b），约 5-10 分钟后 `GET /daily/today` 返回 ready 状态。

### 步骤 7：打开前端

浏览器访问：<http://127.0.0.1:8000/>

> 开发模式（前后端分离）：`cd frontend/ && python -m http.server 3000`

### 一键 Docker 部署

```bash
docker compose up -d
# 后端：http://localhost:8000/
```

详见 [`docker-compose.yml`](docker-compose.yml)。

---

## 环境变量

所有变量前缀 `AIDAILY_`，详见 [`.env.example`](.env.example)。

### LLM（必填）

| 变量                             | 默认                          | 说明                               |
| ------------------------------ | --------------------------- | -------------------------------- |
| `AIDAILY_LLM_API_KEY`          | —                           | Anthropic 兼容 API 密钥（必填）          |
| `AIDAILY_LLM_BASE_URL`         | `https://api.anthropic.com` | 可改为 OneAPI/DeepSeek/Moonshot 转发层 |
| `AIDAILY_LLM_MODEL`            | `claude-haiku-4-5-20251001` | Anthropic 协议兼容模型                 |
| `AIDAILY_LLM_DAILY_BUDGET_USD` | `2.00`                      | 日花费上限，超出抛业务码 `9002`              |

### 鉴权（可选）

| 变量                     | 默认  | 说明                                  |
| ---------------------- | --- | ----------------------------------- |
| `AIDAILY_BEARER_TOKEN` | —   | 写接口鉴权 token；缺失则启动时随机生成并打印 stdout 一次 |

### 服务器与调度

| 变量                        | 默认                  | 说明                         |
| ------------------------- | ------------------- | -------------------------- |
| `AIDAILY_HOST`            | `127.0.0.1`         | 绑定地址                       |
| `AIDAILY_PORT`            | `8000`              | 监听端口                       |
| `AIDAILY_TZ`              | `Asia/Shanghai`     | 时区（影响刊期日期判定）               |
| `AIDAILY_DB_PATH`         | `./data/aidaily.db` | SQLite 路径（`:memory:` 用于测试） |
| `AIDAILY_DAILY_PUSH_TIME` | `08:00`             | 每日生成时刻（`HH:mm` 24h）        |

### 信息源凭据

| 变量                                   | 默认                          | 说明                                                              |
| ------------------------------------ | --------------------------- | --------------------------------------------------------------- |
| `TWITTER_AUTH_TOKEN` + `TWITTER_CT0` | —                           | X 源鉴权（x.com Cookie 值）；缺失且未开浏览器 Cookie → X 源静默跳过                 |
| `AIDAILY_X_ALLOW_BROWSER_COOKIES`    | `false`                     | `1`/`true` 时复用本机浏览器 x.com 登录态                                   |
| `AIDAILY_TWITTER_BIN`                | PATH 自动探测                   | `twitter` CLI 可执行文件路径                                           |
| `AIDAILY_X_ACCOUNTS`                 | 内置 28 KOL                   | 逗号分隔的 X 用户名列表                                                   |
| `AIDAILY_GITHUB_TOKEN`               | —                           | GitHub PAT，提升速率限制（缺失走 trending HTML）                            |
| `AIDAILY_OPENCLI_BIN`                | PATH 自动探测                   | `opencli` CLI 路径（Reddit 桥接通道，见 [Reddit 源](#reddit-源opencli-桥接)） |
| `AIDAILY_REDDIT_DISABLE_OPENCLI`     | `false`                     | `1` = 跳过 opencli 桥接，直接走 Atom 兜底                                 |
| `AIDAILY_REDDIT_UA`                  | `ai-daily/1.0 by anonymous` | Atom 兜底通道的 HTTP User-Agent（建议覆盖）                                |

---

## API 接口

完整契约见 [`specs/001-ai-daily-news/contracts/`](specs/001-ai-daily-news/contracts/)。
交互式文档（Swagger UI）：<http://127.0.0.1:8000/docs>
OpenAPI Schema：<http://127.0.0.1:8000/openapi.json>

### 公开接口（无需鉴权）

#### 1. `GET /api/v1/daily/today` — 今日刊概览

```bash
curl -s "http://127.0.0.1:8000/api/v1/daily/today" \
  -H "X-Request-Id: req_$(date +%s)"
```

返回 `{issue, summary, articles[]}`。状态码：`200 ready` / `404 2002 not-generated` / `409 2003 generating`。

#### 2. `GET /api/v1/articles?type=&src=&page=&pageSize=` — 双维筛选

```bash
# Reddit + Agent 组合
curl -s "http://127.0.0.1:8000/api/v1/articles?src=reddit&type=agent&page=1&pageSize=20"
```

返回 `{items[], page, pageSize, total, appliedFilters}`。非法枚举值 → `400 1002`。

#### 3. `GET /api/v1/articles/{id}` — 条目详情

```bash
curl -s "http://127.0.0.1:8000/api/v1/articles/20260812-0003"
```

返回完整 Article（含 `lede/summary/body/quote/points/sourceUrl/...`）。不存在 → `404 2001`。

#### 4. `GET /api/v1/meta` — 信息源/类型元数据

```bash
curl -s "http://127.0.0.1:8000/api/v1/meta"
```

返回 `{sources[4], types[5]}`。供脚本与集成方使用（前端目前硬编码 chips 与开关文案）。

#### 5. `GET /api/v1/healthz` — 健康检查

```bash
curl -s "http://127.0.0.1:8000/api/v1/healthz"
```

```json
{
  "status": "ok",
  "version": "1.0.0",
  "pipeline": { "collector": "up", "summarizer": "up" }
}
```

### 写接口（需 `Authorization: Bearer <token>`）

> 令牌在 `.env` 中设置 `AIDAILY_BEARER_TOKEN`，或从启动 stdout 复制。

#### 6. `GET /api/v1/settings` — 读取偏好

```bash
curl -s "http://127.0.0.1:8000/api/v1/settings" \
  -H "Authorization: Bearer $AIDAILY_BEARER_TOKEN"
```

#### 7. `PUT /api/v1/settings` — 保存偏好（下一期生效）

```bash
curl -s -X PUT "http://127.0.0.1:8000/api/v1/settings" \
  -H "Authorization: Bearer $AIDAILY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "sources": {"x": true, "github": false, "reddit": true, "web": true},
    "types": {"agent": true, "self_improve": true, "open_source": false, "tools": true, "commentary": true},
    "dailyPush": {"enabled": true, "time": "08:00"},
    "dailyCount": 15
  }' \
  -D -  # 显示响应头以验证 X-Effective-At
```

响应头含 `X-Effective-At: 20260813`（明日刊期生效）。**所有字段必填**（sources/types 键必须齐全，`dailyCount` 取值 `10/15/20/30`）。校验失败 → `422 1005`。

#### 8. `POST /api/v1/settings/reset` — 恢复默认

```bash
curl -s -X POST "http://127.0.0.1:8000/api/v1/settings/reset" \
  -H "Authorization: Bearer $AIDAILY_BEARER_TOKEN" -D -
```

#### 9. `POST /api/v1/share` — 生成分享卡片

```bash
curl -s -X POST "http://127.0.0.1:8000/api/v1/share" \
  -H "Authorization: Bearer $AIDAILY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"articleId": "20260812-0003"}'
```

返回 `{shareId, cardUrl, articleTitle}`。`cardUrl` 可在浏览器直接打开（公开页面，无需鉴权）。

### 公开分享页

```bash
# 浏览器打开 cardUrl 即可
open "http://127.0.0.1:8000/share/shr_9f2c4a71"
```

---

## X (Twitter) 源配置

X 源通过本地 `twitter` CLI 子进程抓取：并发执行
`twitter user-posts <account> -n 20 --json`，遍历账号列表，单账号失败重试一次后跳过并记 ERROR 日志。无需 RSSHub、无需官方 X API。

### 安装

```bash
pip install twitter-cli   # 提供 `twitter` 命令（github.com/jackwener/twitter-cli）
twitter --version         # 验证安装
```

### 鉴权（二选一）

1. **环境变量**：设置 `TWITTER_AUTH_TOKEN` + `TWITTER_CT0`（x.com Cookie 中的 `auth_token` / `ct0`）
2. **浏览器 Cookie**：本机浏览器已登录 x.com 时，设置 `AIDAILY_X_ALLOW_BROWSER_COOKIES=1`（Windows 经 DPAPI 读取 Chrome/Arc/Edge/Firefox/Brave Cookie 库）

两者皆不可用时 X 源静默跳过。

### 账号列表

```dotenv
# .env —— 覆盖默认 KOL 列表（默认内置 28 个，见 backend/app/pipeline/defaults/x_accounts.py）
AIDAILY_X_ACCOUNTS=karpathy,ylecun,simonw,swyx
```

### 其他参数

| 变量                          | 说明                                                      |
| --------------------------- | ------------------------------------------------------- |
| `AIDAILY_TWITTER_BIN`       | `twitter` 可执行文件路径（默认 PATH 自动探测 + Windows pip --user 目录） |
| `AIDAILY_X_RETRY_BACKOFF_S` | 单账号失败重试间隔（默认 `0.5`）                                     |

### 禁用 X 源

不设置 `TWITTER_AUTH_TOKEN`/`TWITTER_CT0` 且不开浏览器 Cookie，或移除 `twitter` CLI，系统即静默跳过 X 源，其余 3 源正常出刊。

---

## Reddit 源（opencli 桥接）

Reddit 对匿名/数据中心 IP 的 `.json` API 返回 403。当前方案：**opencli 浏览器桥接优先**（借本机已登录 Chrome 会话抓取，能拿到 score / 评论数 / 正文），桥接不可用或全部 sub 失败时**自动回退匿名 Atom feed**（可用但无互动数据）。

### 安装

```bash
npm install -g @jackwener/opencli   # 提供 `opencli` 命令
opencli doctor                      # 验证安装与浏览器连接
```

### 使用条件

- 本机 Chrome 已登录 reddit（桥接通过真实登录态绕过 IP 封锁）
- 采集命令：`opencli reddit subreddit <sub> --sort top --time week -f json`（逐 sub 串行执行）

### 环境变量

| 变量                               | 说明                                                      |
| -------------------------------- | ------------------------------------------------------- |
| `AIDAILY_OPENCLI_BIN`            | `opencli` 可执行文件路径（默认 PATH 探测，Windows 优先找 `opencli.CMD`） |
| `AIDAILY_REDDIT_DISABLE_OPENCLI` | `1` = 跳过桥接，直接走 Atom 兜底                                  |

> `twitter-cli` 与 `opencli` 出自同一作者（jackwener），鉴权思路一致：优先显式凭据，其次复用本机浏览器登录态。

---

## 日志

| 类型   | 位置                         | 格式                                               |
| ---- | -------------------------- | ------------------------------------------------ |
| 应用日志 | `backend/logs/aidaily.log` | JSON 每行一条；含 `ts/level/logger/message/request_id` |
| 滚动策略 | 10 MB × 5 文件               | `RotatingFileHandler`                            |
| 控制台  | stdout                     | 同 JSON 格式                                        |

每条日志可选字段（按场景填充）：`source` / `issue_id` / `exception_type` / `user` / `module`。

**示例查询**（排查某次失败）：

```bash
# 按 request_id 串联请求链
grep '"request_id":"req_abc123"' backend/logs/aidaily.log

# 找出 X 源采集失败
grep '"source":"x"' backend/logs/aidaily.log | grep ERROR

# 统计今日刊期生成事件
grep '"issue_id":"20260812"' backend/logs/aidaily.log
```

---

## 开发脚本

> 所有命令在 `backend/` 目录下运行。

```bash
# 安装开发依赖（含 pytest, ruff, mypy, respx 等）
pip install -e ".[dev]"

# 跑全部测试（不含 e2e）+ 80% 覆盖率门槛
pytest --cov=app --cov-fail-under=80 --ignore=tests/e2e -v

# 跑 e2e（需先 pip install pytest-playwright && playwright install chromium）
pytest tests/e2e/

# 跑性能基准（标记 @pytest.mark.perf，慢 CI 可跳过）
pytest tests/performance/ -v

# 静态检查
ruff check backend/
mypy backend/app

# 数据库迁移
alembic upgrade head          # 应用至最新
alembic revision --autogenerate -m "msg"  # 生成新迁移

# 启动开发服务器（热重载）
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

---

## 项目结构

```
ai-daily-news/
├── backend/                    # Python FastAPI 后端
│   ├── app/
│   │   ├── api/                # 路由：settings / articles / daily / meta / share / healthz
│   │   ├── config.py           # pydantic-settings 配置
│   │   ├── infra/              # db/auth/logging/middleware/ratelimit/...
│   │   ├── models/             # SQLAlchemy ORM + Pydantic schemas
│   │   ├── pipeline/           # collector + summarizer + generator
│   │   ├── services/           # 业务服务层
│   │   └── main.py             # FastAPI ASGI 入口
│   ├── migrations/             # Alembic 迁移
│   ├── tests/                  # unit + integration + e2e + performance
│   ├── alembic.ini
│   ├── pyproject.toml
│   ├── Dockerfile
│   └── pytest.ini
├── frontend/                   # 静态前端（原生 ES Module，无构建步骤）
│   ├── index.html
│   └── static/
│       ├── js/                 # api / state / actions / render / ui / markdown / main
│       ├── icons/              # SVG 图标
│       ├── marked.min.js       # Markdown 渲染（vendor）
│       └── purify.min.js       # HTML 消毒（vendor）
├── specs/001-ai-daily-news/    # 设计文档（contracts/plan/research/...）
├── .github/workflows/ci.yml    # GitHub Actions CI
├── docker-compose.yml          # 一键部署
├── .env.example
├── LICENSE                     # MIT
└── README.md
```

---

## 已知限制

- **X 源依赖本地 `twitter` CLI**：v1.x 未集成官方 X API（成本与 OAuth 复杂度考量）；未配置鉴权或找不到 CLI 时 X 源静默跳过，其余 3 源正常。
- **LLM 依赖单一 provider**：当前仅支持 Anthropic 协议；OpenAI 协议支持规划在 v1.1。
- **本地 SQLite**：单机部署；多副本水平扩展需替换为 PostgreSQL（v2 规划）。
- **无用户体系**：单用户 Bearer token；多租户在 v2 路线图。
- **无 OAuth/SSO**：分享卡片为公开链接，无 TTL 过期（v2 可加）。
- **首屏渲染未做 SSR**：纯客户端原生 ES Module SPA，SEO 不友好（设计取舍，PC 本地应用场景优先）。
- **E2E 测试默认不在 CI 主路径**：依赖 Playwright + Chromium 下载，标记在 `tests/e2e/`，可单独触发（详见 [`.github/workflows/ci.yml`](.github/workflows/ci.yml)）。
- **首装自动生成需 5-10 分钟**：取决于 LLM 响应速度与各源速率限制。
- **`/daily/today` 在 08:00 之前访问**：返回 `404 2002`，前端展示「正在翻今天的墙头」加载态，等到 08:00 触发后转 ready。

---

## License

[MIT](LICENSE) © 2026 AI Daily News Contributors
