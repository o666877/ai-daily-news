# Contract: POST /share

**接口 #8 · 生成分享卡片** · 认证：**是** · 用途：「分享这条」生成可复制/可打开的卡片链接

## Request

```http
POST /api/v1/share
Authorization: Bearer <token>
Content-Type: application/json

{ "articleId": "20260812-0003" }
```

**Headers**：

| Header | 必填 | 说明 |
|---|---|---|
| `Authorization` | 是 | `Bearer <token>` |
| `Content-Type` | 是 | `application/json` |
| `X-Request-Id` | 否 | 客户端透传 |

**Body 字段**：

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `articleId` | string | 是 | Article.id；缺省 → 业务码 `1001`；不存在 → 业务码 `2001` |

## Response 200 OK

```json
{
  "shareId": "shr_9f2c4a71",
  "cardUrl": "https://{host}/share/shr_9f2c4a71",
  "articleTitle": "…"
}
```

**字段说明**（详见 [data-model.md](../data-model.md#6-sharecard分享卡片)）：

| 字段 | 说明 |
|---|---|
| `shareId` | 卡片 ID，格式 `shr_<8 hex>`；全局唯一 |
| `cardUrl` | 卡片页面 URL；前端用于「打开」或「复制链接」 |
| `articleTitle` | 来自 Article.title 的快照；用于分享前预览，避免后续 Article 修改影响展示 |

**前端行为**：
- 收到响应后展示卡片预览（标题 + cardUrl）
- 提供「复制链接」按钮（前端 `navigator.clipboard.writeText(cardUrl)`）
- 提供「打开」按钮（前端 `window.open(cardUrl, '_blank')`）

**生命周期约束**：
- 卡片在 v1.x 不主动过期（v2 可加 TTL 配置）
- 同一 `articleId` 多次生成会产生多个 `shareId`（不去重，便于统计）

## Error Scenarios

| HTTP | 业务码 | 触发条件 | 前端表现 |
|---|---|---|---|
| 400 | `1001` | 缺 `articleId` 字段 | 表单级提示「请指定文章」 |
| 401 | `1003` | 缺 Authorization 或 token 失效 | 跳登录 |
| 404 | `2001` | `articleId` 不存在或已删除 | Toast「文章不存在」 |
| 429 | `1006` | 触发写限流（30/min/user） | Toast |
| 500 | `9001` | 服务内部错误 | 全局错误态 + 重试 |

## Performance Budget

- P95 ≤ 300 ms

## Example (curl)

```bash
curl -s -X POST "https://{host}/api/v1/share" \
  -H "Authorization: Bearer $AIDAILY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"articleId": "20260812-0003"}'
```
