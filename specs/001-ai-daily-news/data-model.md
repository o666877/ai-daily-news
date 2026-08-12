# Data Model: AI 日报系统

**Date**: 2026-08-12
**Phase**: 1 (Design & Contracts)
**Source of truth**: `ai日报-后端集成接口文档.md` §4 + `spec.md` Key Entities

## Entity Overview

```text
DailyIssue (1) ──< Article (N)
                     │
                     └─── (src) ──→ Source (4 固定枚举)
                     └─── (type) ──→ Type (4 固定枚举)

Settings (1, 单用户) ──→ 引用 Source[] + Type[] 控制采集范围

Article (1) ──< ShareCard (N) （分享卡片持久化，便于 cardUrl 解析）

DailyIssue.filtersApplied ──→ 来源 Settings 当前快照
```

## Enums

### SourceKey（4 固定信息源）

| key | name | short | icon | description |
|---|---|---|---|---|
| `x` | X (Twitter) | X | `x` | 前沿哨兵，偶尔发疯但信息最快 |
| `github` | GitHub | GitHub | `github` | 仓库动态、新项目、趋势榜单 |
| `reddit` | Reddit | Reddit | `reddit` | 社区热帖与高赞讨论，一手开发者情报 |
| `web` | 全网聚合 | 全网 | `globe` | 搜索引擎 + RSS 兜底，不放过漏网之鱼 |

**迁移规则**：历史 `blogs` 枚举统一映射为 `reddit`。非法值返回业务码 `1002`。

### TypeKey（4 固定内容类型）

| key | name | shortName |
|---|---|---|
| `agent` | Agent / 智能体 | Agent |
| `self_improve` | 持续学习 / 自我进化 | 持续学习 |
| `open_source` | 开源项目 | 开源 |
| `tools` | 工具与效率 | 工具效率 |

### IssueStatus（刊期状态机）

```text
                    ┌────────────────────────┐
                    │                        │
                    ▼                        │
   [scheduled] ──► generating ──► ready      │ (LLM 摘要重试 2 次仍失败)
                    │            ▲           │
                    │            │           ▼
                    └──────────► └──────► failed
                         (失败)
```

- `generating`：调度触发后立刻进入；前端收到业务码 `2003`
- `ready`：所有条目 LLM 摘要完成；前端收到 200 + `issue.status = ready`
- `failed`：LLM 摘要重试 2 次仍失败；前端行为与「未生成」一致（业务码 `2002`）

**幂等性**：同一 `issueId`（YYYYMMDD）重复触发不会生成两份；重入时若已 `ready` 直接返回，若 `failed` 允许重试。

## Entities

### 1. DailyIssue（刊期）

| 字段 | 类型 | 必填 | 约束 / 校验 |
|---|---|---|---|
| `id` | string | 是 | `YYYYMMDD` 格式（如 `20260812`）；主键；唯一 |
| `date` | string | 是 | `YYYY-MM-DD` ISO 8601 |
| `edition` | number | 是 | 整数 ≥ 1；同日内重生成递增 |
| `status` | enum | 是 | `generating` / `ready` / `failed` |
| `generatedAt` | string | 否 | ISO 8601 datetime，时区 Asia/Shanghai；`generating` 时可为空 |
| `articleCount` | number | 是 | 整数 ≥ 0；等于该刊期下 Article 数量 |
| `filtersApplied` | object | 是 | `{ sources: SourceKey[], types: TypeKey[] }`；本期实际采集范围 |

**不变量**：
- `filtersApplied` 在 `generating → ready/failed` 全程不变（保存为刊期生成开始时的 Settings 快照）
- `articleCount` 仅在 `status = ready` 时与底层 Article 行数一致；`generating` 期间可为 0

### 2. Article（资讯条目）

| 字段 | 类型 | 必填 | 约束 / 校验 |
|---|---|---|---|
| `id` | string | 是 | `{issueId}-{NNNN}` 格式（如 `20260812-0003`）；主键；唯一 |
| `issueId` | string | 是 | 外键 → DailyIssue.id |
| `type` | enum | 是 | TypeKey 之一 |
| `src` | enum | 是 | SourceKey 之一 |
| `title` | string | 是 | 非空；长度 ≤ 200 |
| `excerpt` | string | 是 | 列表摘要；长度 ≤ 200；前端 ≤ 2 行截断展示 |
| `lede` | string | 是 | 导语（阅读器首段）；非空 |
| `summary` | string | 是 | 一句话总结；长度 ≤ 150 |
| `body` | string[] | 是 | 正文段落数组；元素 ≥ 1 |
| `quote` | string / null | 否 | 引用块；可为空 |
| `points` | string[] | 是 | 要点列表；元素 ≥ 1 |
| `time` | string | 是 | `HH:mm` 24 小时制（收录时间） |
| `sourceUrl` | string | 是 | URL；`https://` 或 `http://` |
| `sourceName` | string | 是 | 原文站点名（如 `simonwillison.net`） |
| `readingMinutes` | number | 是 | 整数 ≥ 1 |
| `publishedAt` | string | 是 | ISO 8601 datetime |

**视图子集（ArticleListItem）**：`id` / `title` / `excerpt` / `type` / `src` / `time` / `readingMinutes` —— 仅 7 字段，列表接口与今日刊接口返回；长文字段（`lede`/`body`/`quote`/`points`/`sourceUrl`/`sourceName`/`publishedAt`）仅在详情接口返回，避免列表请求体过大（性能预算 SC-010）。

### 3. Source（信息源元数据）

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `key` | enum | 是 | SourceKey 之一 |
| `name` | string | 是 | 展示名（如 `X (Twitter)`） |
| `short` | string | 是 | 短名（如 `X`） |
| `icon` | string | 是 | 前端图标 key（`x` / `github` / `reddit` / `globe`） |
| `description` | string | 是 | 一句话描述 |

### 4. Type（内容类型元数据）

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `key` | enum | 是 | TypeKey 之一 |
| `name` | string | 是 | 展示名（如 `Agent / 智能体`） |
| `shortName` | string | 是 | 短名（如 `Agent`） |

> **关键不变量**：`Source[]` 与 `Type[]` 由 `GET /meta` 返回，前端不硬编码；后端新增枚举值无需前端发版（SC-008 / SC-011）。

### 5. Settings（用户偏好）

| 字段 | 类型 | 必填 | 约束 / 校验 |
|---|---|---|---|
| `sources` | object | 是 | `{ x: bool, github: bool, reddit: bool, web: bool }`；4 键齐全 |
| `types` | object | 是 | `{ agent: bool, self_improve: bool, open_source: bool, tools: bool }`；4 键齐全 |
| `dailyPush.enabled` | boolean | 是 | — |
| `dailyPush.time` | string | 是 | `HH:mm` 24 小时制（`00:00`–`23:59`）；非法格式 → 业务码 `1005` |
| `updatedAt` | string | 否 | ISO 8601 datetime；由后端写入，前端只读 |

**默认值**（`POST /settings/reset` 返回）：4 源全开 + 4 类型全开 + `dailyPush = { enabled: true, time: "08:00" }`。

**生效语义**：
- `PUT /settings` 全量覆盖；幂等（重复提交安全）
- 响应头 `X-Effective-At: YYYYMMDD` 告知下一期生效刊期
- 当期不回溯；下一期刊期生成时按新偏好采集
- `PUT /settings` 不修改 `updatedAt` 以外的字段语义

### 6. ShareCard（分享卡片）

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `shareId` | string | 是 | 主键；格式 `shr_<8 hex>`（如 `shr_9f2c4a71`） |
| `cardUrl` | string | 是 | URL；指向分享卡片页面 |
| `articleId` | string | 是 | 外键 → Article.id；生成时校验存在，不存在 → 业务码 `2001` |
| `articleTitle` | string | 是 | 来自 Article.title 的快照（生成时复制，避免后续 Article 修改影响卡片展示） |
| `createdAt` | string | 否 | ISO 8601 datetime |

## State Transitions

### DailyIssue 状态机

| 当前状态 | 触发 | 目标状态 | 副作用 |
|---|---|---|---|
| (none) | 调度器在用户推送时间触发 | `generating` | 写入 `filtersApplied` 快照 |
| `generating` | 所有 Article 的 LLM 摘要完成 | `ready` | 写入 `generatedAt`；触发推送 |
| `generating` | LLM 摘要失败且重试 2 次仍失败 | `failed` | 写入 `generatedAt`；记录失败结构化日志 |
| `failed` | 用户主动重试（v2 接口，本期不暴露） | `generating` | — |

> 本期 v1.x 不暴露「立即生成」或「重算」接口（推迟到 v2，见 spec.md Assumptions）。

### Settings 状态机

无显式状态；单实例覆盖更新。`updatedAt` 是唯一单调递增字段。

## Validation Rules Summary

| 规则 | 触发接口 | 失败码 |
|---|---|---|
| 任何 `SourceKey` 不在 4 枚举值内 | `GET /articles?src=`、`PUT /settings.sources` | `1002` |
| 任何 `TypeKey` 不在 4 枚举值内 | `GET /articles?type=`、`PUT /settings.types` | `1002` |
| `dailyPush.time` 不匹配 `HH:mm` 24 小时制 | `PUT /settings` | `1005` |
| `Settings.sources` 缺 4 键之一 | `PUT /settings` | `1005` |
| `Settings.types` 缺 4 键之一 | `PUT /settings` | `1005` |
| 缺少必填参数（如 `articleId`） | `POST /share` | `1001` |
| 写接口缺 `Authorization: Bearer <token>` | `GET/PUT /settings`、`POST /share` | `1003` |
| `page < 1` 或 `pageSize < 1` 或 `pageSize > 50` | `GET /articles` | `1005` |

## Storage Mapping（参考，非实现约束）

D3 决定 SQLite + Alembic 迁移。表结构示意：

```text
daily_issues(id PK, date, edition, status, generated_at, filters_applied_json)
articles(id PK, issue_id FK, type, src, title, excerpt, lede, summary,
         body_json, quote, points_json, time, source_url, source_name,
         reading_minutes, published_at, created_at)
settings(id PK=1 [singleton], sources_json, types_json, daily_push_json, updated_at)
share_cards(share_id PK, article_id FK, article_title, card_url, created_at)
```

> JSON 字段（body/points/filtersApplied/sources/types/dailyPush）以 TEXT 列存储 JSON；查询时由 ORM/驱动反序列化。本期无基于 JSON 字段的 WHERE 谓词需求，全文检索推迟到 v2（`/search` 接口未提供）。
