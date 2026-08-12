# Contract: GET /articles/{id}

**接口 #3 · 条目详情** · 认证：否 · 用途：阅读器正文渲染

## Request

```http
GET /api/v1/articles/20260812-0003
```

**Path 参数**：

| 参数 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `id` | string | 是 | Article.id；格式 `{issueId}-{NNNN}`（如 `20260812-0003`） |

## Response 200 OK

完整 Article 对象（详见 [data-model.md](../data-model.md#2-article资讯条目)）：

```json
{
  "id": "20260812-0003",
  "issueId": "20260812",
  "type": "agent",
  "src": "reddit",
  "title": "…",
  "excerpt": "…",
  "lede": "导语：阅读器首段文本…",
  "summary": "一句话总结…",
  "body": [
    "正文第一段…",
    "正文第二段…"
  ],
  "quote": "可选引用块，可为 null",
  "points": [
    "要点 1",
    "要点 2",
    "要点 3"
  ],
  "time": "10:42",
  "sourceUrl": "https://www.reddit.com/r/…",
  "sourceName": "reddit.com",
  "readingMinutes": 5,
  "publishedAt": "2026-08-12T09:30:00+08:00"
}
```

**前端行为约束**：
- 「阅读原文」直接使用 `sourceUrl` 在新浏览器标签页打开（系统不单独提供跳转接口）
- `quote: null` 时不渲染引用块区域
- `body[]` 按数组顺序渲染为段落

## Error Scenarios

| HTTP | 业务码 | 触发条件 | 前端表现 |
|---|---|---|---|
| 404 | `2001` | 文章不存在（id 不匹配或已删除） | 详情视图显示「内容不存在」 |
| 429 | `1006` | 触发读限流 | Toast「操作太频繁，稍后再试」 |
| 500 | `9001` | 服务内部错误 | 全局错误态 + 重试按钮 |

## Performance Budget

- P95 ≤ 200 ms

## Example (curl)

```bash
curl -s "https://{host}/api/v1/articles/20260812-0003"
```
