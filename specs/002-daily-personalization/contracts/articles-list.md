# Contract: GET /articles (v2 扩展)

**接口 #2 · 文章列表（带筛选）** · 认证：否 · 用途：分页浏览与筛选

> 本契约在 [001 系统契约](../../001-ai-daily-news/contracts/articles-list.md) 基础上扩展：每条目新增 `compositeScore`，列表已按综合评分降序。

## Request

```http
GET /api/v1/articles?issueId=20260813&type=agent&src=web&page=1&limit=20
```

| Query | 必填 | 默认 | 说明 |
|---|---|---|---|
| `issueId` | 否 | 今日 | 刊期 ID（YYYYMMDD） |
| `type` | 否 | 全部 | 类型枚举；非法 → `1002` |
| `src` | 否 | 全部 | 来源枚举；非法 → `1002` |
| `page` | 否 | 1 | 页码（1-based） |
| `limit` | 否 | 20 | 每页大小（≤50） |

## Response 200 OK

```json
{
  "data": [
    {
      "id": "20260813-0001",
      "title": "OpenAI 发布 GPT-5",
      "excerpt": "摘要…",
      "type": "agent",
      "src": "web",
      "time": "09:12",
      "readingMinutes": 6,
      "compositeScore": 92
    }
  ],
  "meta": {
    "page": 1,
    "limit": 20,
    "total": 87,
    "totalPages": 5,
    "appliedFilters": {"type": "agent", "src": "web"}
  }
}
```

### Data 字段（每条目 8 字段）

与 [/daily/today](./daily-today.md) 的 articles 数组字段完全一致（含 `compositeScore`）。

### Meta 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `page` | int | 当前页 |
| `limit` | int | 每页大小 |
| `total` | int | 筛选后总条数 |
| `totalPages` | int | 总页数 |
| `appliedFilters` | object | 实际生效的筛选条件（key 缺失表示未应用） |

## 排序语义（**新增**）

`data` 数组按 `compositeScore DESC, time DESC` 排序（与 /daily/today 一致）。分页是稳定切片——同刊期多次请求顺序一致。

## Error Scenarios

| HTTP | 业务码 | 触发 | 前端 |
|---|---|---|---|
| 400 | 1002 | type/src 非法枚举 | chips 提示 |
| 404 | 2002 | issueId 不存在 | 空态 |
| 429 | 1006 | 触发读限流 120/min/ip | Toast |

## Performance Budget

- P95 ≤ 300 ms

## Example

```bash
curl -s "http://127.0.0.1:8000/api/v1/articles?type=agent&page=1&limit=20" | jq '.meta'
```
