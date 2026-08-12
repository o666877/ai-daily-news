# Contract: GET /articles

**接口 #2 · 条目列表（筛选 + 分页）** · 认证：否 · 用途：类型/来源筛选联动、分页渲染

## Request

```http
GET /api/v1/articles?type=agent&src=reddit&issueId=20260812&page=1&pageSize=20
```

**Query 参数**：

| 参数 | 类型 | 必填 | 默认 | 约束 |
|---|---|---|---|---|
| `type` | enum | 否 | — | TypeKey 之一；非法 → 业务码 `1002` |
| `src` | enum | 否 | — | SourceKey 之一；非法 → 业务码 `1002` |
| `issueId` | string | 否 | 今日刊期 | `YYYYMMDD` 格式 |
| `page` | number | 否 | `1` | 整数 ≥ 1；非法 → 业务码 `1005` |
| `pageSize` | number | 否 | `20` | 整数 1–50；越界 → 业务码 `1005` |

`type` 与 `src` 可组合（AND 关系）。原型「Reddit + Agent」场景：`?src=reddit&type=agent`。

## Response 200 OK

```json
{
  "items": [
    {
      "id": "20260812-0003",
      "title": "…",
      "excerpt": "…",
      "type": "agent",
      "src": "reddit",
      "time": "10:42",
      "readingMinutes": 5
    }
  ],
  "page": 1,
  "pageSize": 20,
  "total": 4,
  "appliedFilters": {
    "type": "agent",
    "src": "reddit"
  }
}
```

**字段说明**：

| 字段 | 说明 |
|---|---|
| `items[]` | ArticleListItem[]；同 [daily-today.md](./daily-today.md) 中 `articles[]` 字段集 |
| `page` / `pageSize` | 回显请求的分页参数（实际生效值） |
| `total` | 满足当前筛选条件的总条目数（用于前端分页器） |
| `appliedFilters` | 回显当前应用的筛选条件；未传的参数对应字段为 `null` 或缺省 |

**前端行为约束**：
- 切换 chips 即请求（建议防抖 200–300ms 避免抖动）
- `items: []` 时前端展示「今天的货架是空的」空态

## Error Scenarios

| HTTP | 业务码 | 触发条件 | 前端表现 |
|---|---|---|---|
| 400 | `1002` | `src` 或 `type` 不在 4 枚举值之内（如 `src=wechat`） | 筛选 chips 区提示，不发起新请求 |
| 422 | `1005` | `page < 1` 或 `pageSize < 1` 或 `pageSize > 50` | 表单级提示 |
| 429 | `1006` | 触发读限流（120/min/IP） | Toast「操作太频繁，稍后再试」 |
| 503 | `9002` | 采集/摘要管线繁忙 | 全局错误态 + 重试按钮 |

## Performance Budget

- P95 ≤ 300 ms（含筛选 + 分页）

## Example (curl)

```bash
curl -s "https://{host}/api/v1/articles?src=reddit&type=agent&page=1&pageSize=20"
```
