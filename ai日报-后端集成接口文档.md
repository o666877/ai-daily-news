# AI 日报 · 后端集成接口文档

- **版本**: v1.0
- **日期**: 2026-08-12
- **适用范围**: 正式版 Web 阅读器（当前前端原型：`v1 ai 日报.html`）
- **配套前端**: AI 日报 Web 阅读器（索引 + 阅读器双栏，含设置面板）

---

## 1. 文档说明

### 1.1 背景

AI 日报是「每天 5 分钟，跟上 AI 的脑回路」的个人 AI 资讯阅读器。当前前端为静态原型，数据为 mock（`ARTICLES` 内置 12 条）。正式版由后端提供真实数据与个性化能力：

- 采集管线：X / GitHub / Reddit / 全网聚合 四个信息源
- LLM 摘要：为每条采集内容生成导语、一句话总结、正文与要点
- 每日刊生成：默认每天 08:00 按用户偏好生成当日刊期
- 个性化：用户偏好（信息源开关、类型开关、每日推送）驱动采集范围

本文档定义 Web 前端与后端之间的全部集成接口。前端原型中的每一个交互点，均可在本文档中找到对应接口。

### 1.2 核心流程

```text
采集管线（X / GitHub / Reddit / 全网聚合）
        │
        ▼
  LLM 摘要（导语 / 总结 / 正文 / 要点）
        │
        ▼
 每日刊生成（08:00，按用户偏好过滤）
        │
        ▼
  前端展示（索引 + 阅读器 + 设置）
```

### 1.3 术语

| 术语 | 说明 |
|---|---|
| 刊期 Issue | 一天一刊，id 如 `20260812` |
| 条目 Article | 刊期内的一篇文章 / 帖子 |
| 信息源 Source | `x` / `github` / `reddit` / `web` |
| 信息类型 Type | `agent` / `self_improve` / `open_source` / `tools` |

---

## 2. 通用约定

| 约定项 | 规则 |
|---|---|
| Base URL | `https://{host}/api/v1`（联调环境由后端提供） |
| 协议 / 编码 | HTTPS；JSON；UTF-8 |
| 认证 | 读接口匿名可用；写接口需 `Authorization: Bearer <token>` |
| 请求 ID | 客户端可传 `X-Request-Id` 头，响应同值返回，便于排障 |
| 时间 | ISO 8601，时区 `Asia/Shanghai`（UTC+8） |
| 分页 | `page` 从 1 开始；`pageSize` 默认 20，最大 50 |
| 枚举 | 见 §4 数据模型；非法枚举返回业务码 `1002` |
| 幂等 | `PUT /settings` 全量覆盖，重复提交安全 |
| 限流 | 读 120 次/分钟/IP；写 30 次/分钟/用户 |

### 2.1 响应结构

成功：HTTP 2xx + 业务数据（各接口自行定义）。

错误：统一错误结构：

```json
{
  "code": 2002,
  "message": "刊期不存在或尚未生成",
  "requestId": "req_8f3a1c..."
}
```

### 2.2 错误码表

| HTTP | 业务码 | 含义 |
|---|---|---|
| 400 | 1001 | 缺少必填参数 |
| 400 | 1002 | 枚举值非法（type / src 等） |
| 401 | 1003 | 未认证或 token 失效 |
| 403 | 1004 | 无权限 |
| 404 | 2001 | 文章不存在 |
| 404 | 2002 | 刊期不存在或未生成完成 |
| 409 | 2003 | 刊期正在生成中，请稍后重试 |
| 422 | 1005 | 请求体校验失败 |
| 429 | 1006 | 触发限流 |
| 500 | 9001 | 服务内部错误 |
| 503 | 9002 | 采集 / 摘要管线繁忙 |

---

## 3. 接口总览

| # | 方法 | 路径 | 认证 | 用途 | 对应前端功能 |
|---|---|---|---|---|---|
| 1 | GET | `/daily/today` | 否 | 今日刊概览 | 报头日期/版次、今日索引、数量徽标 |
| 2 | GET | `/articles` | 否 | 列表 + 筛选 + 分页 | 类型/来源筛选联动、列表渲染 |
| 3 | GET | `/articles/{id}` | 否 | 条目详情 | 阅读器正文 |
| 4 | GET | `/meta` | 否 | 信息源/类型元数据 | 筛选 chips、设置面板开关列表 |
| 5 | GET | `/settings` | 是 | 获取用户偏好 | 设置面板回填 |
| 6 | PUT | `/settings` | 是 | 保存用户偏好（全量） | 保存偏好 |
| 7 | POST | `/settings/reset` | 是 | 恢复默认偏好 | 恢复默认 |
| 8 | POST | `/share` | 是 | 生成分享卡片 | 「分享这条」 |
| 9 | GET | `/healthz` | 否 | 健康检查 | 联调 / 监控 |

> **「阅读原文」不单独设接口**：前端直接使用 `article.sourceUrl` 打开。如需点击统计，后端可在 `sourceUrl` 上附加追踪参数。

---

## 4. 数据模型

### 4.1 Article（条目）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | 是 | 唯一标识，如 `20260812-0003` |
| `issueId` | string | 是 | 所属刊期，如 `20260812` |
| `type` | enum | 是 | `agent` / `self_improve` / `open_source` / `tools` |
| `src` | enum | 是 | `x` / `github` / `reddit` / `web` |
| `title` | string | 是 | 标题 |
| `excerpt` | string | 是 | 列表摘要（前端 ≤2 行截断） |
| `lede` | string | 是 | 导语（阅读器首段） |
| `summary` | string | 是 | 一句话总结（摘要框） |
| `body` | string[] | 是 | 正文段落 |
| `quote` | string / null | 否 | 引用块，可为空 |
| `points` | string[] | 是 | 要点列表 |
| `time` | string | 是 | 收录时间 `HH:mm` |
| `sourceUrl` | string | 是 | 原文链接 |
| `sourceName` | string | 是 | 原文站点名（如 `simonwillison.net`） |
| `readingMinutes` | number | 是 | 预计阅读分钟数 |
| `publishedAt` | string | 是 | 原文发布时间，ISO 8601 |

### 4.2 DailyIssue（刊期）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 刊期 id，如 `20260812` |
| `date` | string | `YYYY-MM-DD` |
| `edition` | number | 版次（第 N 版） |
| `status` | enum | `generating` / `ready` / `failed` |
| `generatedAt` | string | 生成完成时间 |
| `articleCount` | number | 条目总数 |
| `filtersApplied` | object | 本期实际采集范围 `{ sources: [], types: [] }`（来自用户偏好） |

### 4.3 Source / Type（元数据）

| 对象 | 字段 | 说明 |
|---|---|---|
| Source | `key` | `x` / `github` / `reddit` / `web` |
| Source | `name` | 展示名，如 `X (Twitter)`、`Reddit` |
| Source | `short` | 短名，如 `X`、`Reddit` |
| Source | `icon` | 前端图标 key：`x` / `github` / `reddit` / `globe` |
| Source | `description` | 一句话描述 |
| Type | `key` | `agent` / `self_improve` / `open_source` / `tools` |
| Type | `name` | 展示名，如 `Agent / 智能体` |
| Type | `shortName` | 短名，如 `Agent` |

### 4.4 Settings（用户偏好）

```json
{
  "sources": { "x": true, "github": true, "reddit": true, "web": true },
  "types": { "agent": true, "self_improve": true, "open_source": true, "tools": true },
  "dailyPush": { "enabled": true, "time": "08:00" },
  "updatedAt": "2026-08-12T10:30:00+08:00"
}
```

**生效时机**：保存后**下一期刊生成立即生效**（与前端提示语「明天的日报将按新口味调配」一致）。

---

## 5. 接口详情

### 5.1 获取今日刊概览

```http
GET /api/v1/daily/today
```

无参数。首页首屏一次调用即可完成：报头日期/版次、索引列表、数量徽标。

响应 `200 OK`：

```json
{
  "issue": {
    "id": "20260812",
    "date": "2026-08-12",
    "edition": 3,
    "status": "ready",
    "generatedAt": "2026-08-12T08:00:12+08:00",
    "articleCount": 12,
    "filtersApplied": {
      "sources": ["x", "github", "reddit", "web"],
      "types": ["agent", "self_improve", "open_source", "tools"]
    }
  },
  "summary": {
    "byType": { "agent": 3, "self_improve": 3, "open_source": 3, "tools": 3 },
    "bySource": { "x": 3, "github": 3, "reddit": 3, "web": 3 }
  },
  "articles": [
    {
      "id": "20260812-0001",
      "title": "…",
      "excerpt": "…",
      "type": "agent",
      "src": "x",
      "time": "09:12",
      "readingMinutes": 6
    }
  ]
}
```

**ArticleListItem**：`id` / `title` / `excerpt` / `type` / `src` / `time` / `readingMinutes`。

错误场景：

- `2003`（刊期生成中）→ 前端保留加载态并轮询；
- `2002`（今日刊未生成，如 08:00 前访问）→ 前端展示「正在翻今天的墙头」加载态。

### 5.2 条目列表（筛选 + 分页）

```http
GET /api/v1/articles?type=agent&src=reddit&page=1&pageSize=20
```

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `type` | enum | 否 | 信息类型过滤 |
| `src` | enum | 否 | 信息源过滤 |
| `issueId` | string | 否 | 刊期，默认今日 |
| `page` | number | 否 | 页码，默认 1 |
| `pageSize` | number | 否 | 默认 20，最大 50 |

响应 `200 OK`：

```json
{
  "items": [ /* ArticleListItem[] */ ],
  "page": 1,
  "pageSize": 20,
  "total": 4,
  "appliedFilters": { "type": "agent", "src": "reddit" }
}
```

前端每次切换筛选 chips 调用一次；`type` 与 `src` 可组合（原型「Reddit + Agent」场景）。

### 5.3 条目详情

```http
GET /api/v1/articles/20260812-0003
```

响应 `200 OK`：完整 Article 对象（§4.1）。

错误：`404` / `2001`（文章不存在）。

### 5.4 元数据

```http
GET /api/v1/meta
```

响应 `200 OK`：

```json
{
  "sources": [
    { "key": "x", "name": "X (Twitter)", "short": "X", "icon": "x", "description": "前沿哨兵，偶尔发疯但信息最快" },
    { "key": "github", "name": "GitHub", "short": "GitHub", "icon": "github", "description": "仓库动态、新项目、趋势榜单" },
    { "key": "reddit", "name": "Reddit", "short": "Reddit", "icon": "reddit", "description": "社区热帖与高赞讨论，一手开发者情报" },
    { "key": "web", "name": "全网聚合", "short": "全网", "icon": "globe", "description": "搜索引擎 + RSS 兜底，不放过漏网之鱼" }
  ],
  "types": [
    { "key": "agent", "name": "Agent / 智能体", "shortName": "Agent" },
    { "key": "self_improve", "name": "持续学习 / 自我进化", "shortName": "持续学习" },
    { "key": "open_source", "name": "开源项目", "shortName": "开源" },
    { "key": "tools", "name": "工具与效率", "shortName": "工具效率" }
  ]
}
```

正式版筛选 chips 与设置面板开关列表**由接口驱动**（不再硬编码），新增信息源无需前端发版。

### 5.5 获取用户偏好

```http
GET /api/v1/settings
Authorization: Bearer <token>
```

响应 `200 OK`：Settings 对象（§4.4）。

错误：`401` / `1003`（未认证）。

### 5.6 保存用户偏好（全量覆盖）

```http
PUT /api/v1/settings
Authorization: Bearer <token>
Content-Type: application/json

{ "sources": { "x": true, "github": false, "reddit": true, "web": true },
  "types": { "agent": true, "self_improve": true, "open_source": false, "tools": true },
  "dailyPush": { "enabled": true, "time": "08:00" } }
```

响应 `200 OK`：保存后的 Settings 对象；响应头 `X-Effective-At: 20260813`（生效刊期）。

- 前端「保存偏好」按钮提交**面板当前全部开关状态**（全量）；
- 保存后异步同步给采集调度器，下一期刊期按新偏好采集；
- 错误：`422` / `1005`（校验失败，如 `dailyPush.time` 非法）。

### 5.7 恢复默认偏好

```http
POST /api/v1/settings/reset
Authorization: Bearer <token>
```

响应 `200 OK`：默认 Settings 对象（全部开关开启，推送 08:00）。

对应前端「恢复默认」按钮：调用后回填返回的默认值。

### 5.8 生成分享卡片

```http
POST /api/v1/share
Authorization: Bearer <token>
Content-Type: application/json

{ "articleId": "20260812-0003" }
```

响应 `200 OK`：

```json
{
  "shareId": "shr_9f2c",
  "cardUrl": "https://{host}/share/shr_9f2c",
  "articleTitle": "…"
}
```

错误：`404` / `2001`（文章不存在）。

### 5.9 健康检查

```http
GET /api/v1/healthz
```

响应 `200 OK`：

```json
{
  "status": "ok",
  "version": "1.0.0",
  "pipeline": { "collector": "up", "summarizer": "up" }
}
```

---

## 6. 前端接入对照表（原型 → 接口）

| 原型交互 | 接口 | 备注 |
|---|---|---|
| 页面启动（报头日期、索引、数量徽标） | `GET /daily/today` | 一次调用渲染首屏 |
| 类型筛选 chips | `GET /articles?type=` | 切换即请求 |
| 来源筛选 chips | `GET /articles?src=` | 可组合类型筛选 |
| 列表条目点击 | `GET /articles/{id}` | 阅读器渲染 |
| 「阅读原文」 | `article.sourceUrl` | 前端直接打开 |
| 「分享这条」 | `POST /share` | 返回卡片链接 |
| 打开设置面板 | `GET /settings` + `GET /meta` | 回填开关 + 渲染开关列表 |
| 「保存偏好」 | `PUT /settings` | 全量提交 |
| 「恢复默认」 | `POST /settings/reset` | 回填默认值 |
| 每日推送开关 | `PUT /settings`（`dailyPush`） | 并入偏好保存 |
| 加载态（骨架屏） | — | 请求进行中，前端展示 |
| 空态（筛选无结果） | `GET /articles` 返回 `items: []` | 前端「今天的货架是空的」 |
| 刊期未就绪 | `GET /daily/today` 返回 `2002` / `2003` | 前端「正在翻今天的墙头」 |
| 错误提示 toast | 统一错误结构 | 前端读 `message` 展示 |

---

## 7. 枚举映射（原型 ↔ 接口）

前端原型使用 kebab-case 键，接口统一 snake_case，集成层需映射：

| 原型键 | 接口值 | 展示名 |
|---|---|---|
| `agent` | `agent` | Agent / 智能体 |
| `self-improve` | `self_improve` | 持续学习 |
| `open-source` | `open_source` | 开源项目 |
| `tools` | `tools` | 工具与效率 |
| `x` | `x` | X (Twitter) |
| `github` | `github` | GitHub |
| `blogs` | `reddit` | Reddit（2026-08-12 起，原「博客」源已更名） |
| `web` | `web` | 全网聚合 |

> **数据迁移**：历史数据中 `blogs` 枚举统一映射为 `reddit`；前端原型已于 2026-08-12 同步更新（索引、设置、图标）。

---

## 8. 与采集管线的协作

```text
PUT /settings（用户偏好）
      │
      ▼
采集调度器（异步）—— 下一期刊期抓取计划：sources/types 过滤 + 推送时间
      │
      ▼
采集（X / GitHub / Reddit / 全网）→ LLM 摘要 → 刊期状态机
      │
      ▼
generating ──► ready（推送触发，默认 08:00）
      │
      └──────► failed（摘要失败重试 2 次仍失败）
```

关键规则：

- **生效时机**：偏好保存后下一期刊期生效，当期不回溯；
- **状态流转**：`generating → ready / failed`；`failed` 时前端收到 `2002`；
- **推送**：刊期 `ready` 后按 `dailyPush` 配置触发（默认 08:00）；
- **失败重试**：摘要失败自动重试 2 次，仍失败标记 `failed`。

---

## 9. 联调自测清单

| 场景 | 调用 | 期望 |
|---|---|---|
| 首页加载 | `GET /daily/today` | 200，`issue.status = ready` |
| 组合筛选 | `GET /articles?src=reddit&type=agent` | `items` 全部为 `reddit + agent` |
| 详情 | `GET /articles/20260812-0003` | 200，全字段 |
| 保存偏好 | `PUT /settings` | 200 + 响应头 `X-Effective-At` |
| 未认证 | `GET /settings`（无 token） | 401 / `1003` |
| 非法枚举 | `GET /articles?src=wechat` | 400 / `1002` |
| 不存在 | `GET /articles/xxx` | 404 / `2001` |
| 未生成刊期 | `GET /daily/today`（08:00 前） | 404 / `2002` |
| 健康检查 | `GET /healthz` | 200，pipeline 全 up |

---

## 10. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-08-12 | 初稿：定义 9 个接口、数据模型、错误码与前端对照；信息源枚举 `blogs → reddit` |
