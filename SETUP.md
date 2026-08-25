# 安装与配置指南（SETUP）

> 本文档面向人类用户与编程 agent（Claude Code / Codex / Cursor 等），描述如何在本机安装、配置并启动 AI 日报系统。如果你是 agent，请按顺序执行步骤 1-7，逐项完成文末验证清单；需要用户提供的信息（如 API Key）先向用户询问，不要编造。

## 成功标准

- 后端在 `http://127.0.0.1:8000` 正常运行，`GET /api/v1/healthz` 返回 `status: ok`
- 首次启动后 5-10 分钟，`GET /api/v1/daily/today` 返回 ready 状态的首期日报
- 未配置的可选源（X / Reddit 桥接 / GitHub PAT）静默降级，不阻塞出刊

## 前置要求

- Python 3.11.9+
- 操作系统：Windows 11 / macOS 14+ / Ubuntu 22.04+
- （可选）`twitter` CLI：启用 X (Twitter) 源，见 [X (Twitter) 源配置](#x-twitter-源配置)
- （可选）Node.js + `opencli`：启用 Reddit 浏览器桥接，见 [Reddit 源（opencli 桥接）](#reddit-源opencli-桥接)
- （可选）Docker：一键部署（`docker compose up -d`，后端 <http://localhost:8000/>）

## 步骤 1：准备环境

```bash
# 创建虚拟环境
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
```

## 步骤 2：安装后端依赖

```bash
cd backend/
pip install -e ".[dev]"
```

## 步骤 3：配置环境变量

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

## 步骤 4：（可选，仅启用 X 源）配置 twitter-cli

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

## 步骤 5：初始化数据库

```bash
cd backend/
alembic upgrade head
```

## 步骤 6：启动后端

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

首次启动会自动后台触发初始刊期生成（FR-001b），约 5-10 分钟后 `GET /daily/today` 返回 ready 状态。

## 步骤 7：打开前端

浏览器访问：<http://127.0.0.1:8000/>

> 开发模式（前后端分离）：`cd frontend/ && python -m http.server 3000`

## 步骤 8：（可选）配置企业微信推送

每期日报生成后可自动推送到企业微信群。全部在 Web 设置面板完成,无需改环境变量:

1. 在企微电脑版/手机版目标群里: **群设置 → 群机器人 → 添加机器人**,随意命名后复制它的 **Webhook 地址**(形如 `https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxxxxx`,该地址即凭据,不要外传)。
2. 打开日报页右上角 **设置 → 企微推送**:
   - 点「+ 添加群机器人」,填群名(1–20 字,需唯一)并粘贴 Webhook 地址;
   - 点该行「测试」——会先保存配置再向该群发一条测试消息,到群里确认收到即可;
   - 打开「推送开关」,保存偏好。之后每期日报就绪即自动推送(标题 + 最高分 Top N 条目摘要)。
3. **日报链接基地址**(可选):推送消息末尾的「查看完整日报」链接需要一个**手机能访问**的地址——
   - 留空:自动使用浏览器当前访问地址;通过内网穿透域名访问时即该域名;
   - 公网部署:可显式填域名,如 `https://your-domain.example.com`;
   - 手机无法访问当前地址时,才需显式填写(如 frp / cloudflared tunnel 映射到本服务的穿透地址)。
4. 多群:重复第 1–2 步,最多 5 个;同一期只会对每个群自动推送一次,失败可在设置面板看状态并点「重新推送当期」。

> Webhook 地址在界面与接口中始终以脱敏形式回显(`****` + 尾 4 位);日志与错误信息不含完整地址。

## 一键 Docker 部署

```bash
docker compose up -d
# 后端：http://localhost:8000/
```

详见 [`docker-compose.yml`](docker-compose.yml)。

## 验证清单

安装完成后逐项确认：

- [ ] `alembic current` 输出 head 版本，无报错
- [ ] `curl http://127.0.0.1:8000/api/v1/healthz` 返回 `{"status": "ok", ...}`
- [ ] 启动日志中可以看到自动生成的 `AIDAILY_BEARER_TOKEN`（若 .env 未设置）
- [ ] 5-10 分钟后 `curl http://127.0.0.1:8000/api/v1/daily/today` 返回 200（ready）
- [ ] 可选源未配置时，日志中出现跳过记录而非启动失败

---

## 环境变量参考

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

| 变量                        | 默认                  | 说明                                     |
| ------------------------- | ------------------- | -------------------------------------- |
| `AIDAILY_HOST`            | `127.0.0.1`         | 绑定地址                                   |
| `AIDAILY_PORT`            | `8000`              | 监听端口                                   |
| `AIDAILY_TZ`              | `Asia/Shanghai`     | 时区（影响刊期日期判定）                           |
| `AIDAILY_DB_PATH`         | `./data/aidaily.db` | SQLite 路径（`:memory:` 用于测试）             |
| `AIDAILY_DAILY_PUSH_TIME` | `08:00`             | 每日生成时刻兜底值；实际以设置面板「推送时间」为准（改后立即重排 cron） |
| `AIDAILY_WECOM_RETRY_BACKOFF_S` | `2`          | 企微推送重试退避基数（3 次重试依次 2/4/8 秒；测试里置 0 提速） |

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

## 故障排查提示

- 生成进度与采集失败详情见应用日志 `backend/logs/aidaily.log`（JSON 每行一条）
- 首期生成中 `GET /daily/today` 返回 `409 2003 generating` 属正常，等待即可
- LLM 花费超限会抛业务码 `9002`，可调高 `AIDAILY_LLM_DAILY_BUDGET_USD`
