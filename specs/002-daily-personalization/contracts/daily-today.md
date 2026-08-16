# Contract: GET /daily/today (v2 扩展)

**接口 #1 · 今日刊概览** · 认证：否 · 用途：首屏一次调用

> 本契约在 [001 系统契约](../../001-ai-daily-news/contracts/daily-today.md) 基础上扩展：每条目新增 `compositeScore` 字段，用于列表排序与评分展示。

## Request

```http
GET /api/v1/daily/today
```

无 query 参数，无 body。

## Response 200 OK

```json
{
  "issue": {
    "id": "20260813",
    "date": "2026-08-13",
    "edition": 1,
    "status": "ready",
    "generatedAt": "2026-08-13T08:00:12+08:00",
    "articleCount": 30,
    "filtersApplied": {
      "sources": ["x", "github", "reddit", "web"],
      "types": ["agent", "self_improve", "open_source", "tools"]
    }
  },
  "summary": {
    "byType": {"agent": 8, "self_improve": 7, "open_source": 8, "tools": 7},
    "bySource": {"x": 5, "github": 10, "reddit": 5, "web": 10}
  },
  "articles": [
    {
      "id": "20260813-0001",
      "title": "OpenAI 发布 GPT-5：多模态推理大幅提升",
      "excerpt": "摘要文本…",
      "type": "agent",
      "src": "web",
      "time": "09:12",
      "readingMinutes": 6,
      "compositeScore": 92
    },
    {
      "id": "20260813-0002",
      "title": "Anthropic 开源 Claude Tools SDK",
      "excerpt": "...",
      "type": "open_source",
      "src": "web",
      "time": "10:30",
      "readingMinutes": 4,
      "compositeScore": 88
    }
  ]
}
```

### Articles 数组字段（每条目 8 字段，001 + 1）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | 是 | 文章 ID |
| `title` | string | 是 | 标题 |
| `excerpt` | string | 是 | 摘要 |
| `type` | string | 是 | 类型枚举（agent / self_improve / open_source / tools） |
| `src` | string | 是 | 来源枚举（x / github / reddit / web） |
| `time` | string | 是 | 收录时间 HH:mm |
| `readingMinutes` | int | 是 | 预计阅读分钟数 |
| **`compositeScore`** | int \| null | 是 | 综合评分 0–100；**新增**。`null` 仅在迁移后未重新生成的旧 articles 上出现 |

### 排序语义（**新增**）

`articles` 数组按 `compositeScore DESC, time DESC` 稳定排序——已在 generator 截取 top-N 时确定，阅读期不重新排序。前端筛选（src/type）只是过滤已排序数组，不改变顺序。

## Response 404 — 2002

```json
{"code": 2002, "message": "今日刊尚未生成完成", "requestId": "req_abc"}
```

## Response 409 — 2003

```json
{"code": 2003, "message": "今日刊正在生成", "requestId": "req_abc"}
```

## Performance Budget

- P95 ≤ 500 ms（本地，不含采集）

## Example

```bash
curl -s "http://127.0.0.1:8000/api/v1/daily/today" | jq '.articles[0]'
```
