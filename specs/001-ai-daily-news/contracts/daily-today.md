# Contract: GET /daily/today

**接口 #1 · 今日刊概览** · 认证：否 · 用途：首页首屏一次调用完成（报头 + 索引 + 数量徽标）

## Request

```http
GET /api/v1/daily/today
```

无参数。无请求体。

## Response 200 OK

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

**字段说明**：

| 字段 | 说明 |
|---|---|
| `issue.*` | DailyIssue 实体，详见 [data-model.md](../data-model.md#1-dailyissue刊期) |
| `summary.byType` / `summary.bySource` | 数量徽标数据源；4 个固定 key 齐全；缺失项计为 0 |
| `articles[]` | ArticleListItem[]；仅 7 字段（详见 [data-model.md](../data-model.md#2-article资讯条目)） |
| `articles[].time` | 收录时间 `HH:mm`（注意：非 `time_label`） |

**前端行为约束**：
- 列表顺序由后端决定，前端不做客户端二次排序
- 长文字段（`lede` / `body` / `quote` / `points` / `sourceUrl` 等）需调用 `GET /articles/{id}` 获取

## Error Scenarios

| HTTP | 业务码 | 触发条件 | 前端表现 |
|---|---|---|---|
| 404 | `2002` | 当前时间早于刊期生成时间（如 08:00 前访问），或刊期生成失败 | 「正在翻今天的墙头」加载态 |
| 409 | `2003` | 刊期正在生成中（`status = generating`） | 保留骨架屏 + 轮询（建议间隔 5–10 秒） |

## Performance Budget

- P95 ≤ 500 ms（本地部署，不含采集管线）
- 不分页（首屏一次返回全部 ArticleListItem）

## Example (curl)

```bash
curl -s "https://{host}/api/v1/daily/today" \
  -H "X-Request-Id: req_$(date +%s)"
```
