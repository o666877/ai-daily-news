# Contract: GET /settings (v2 扩展)

**接口 #4 · 获取用户偏好** · 认证：**是**

> 本契约在 [001 系统契约](../../001-ai-daily-news/contracts/settings-get.md) 基础上扩展：新增 `dailyCount` 与 `styleMode` 字段。

## Request

```http
GET /api/v1/settings
Authorization: Bearer <token>
```

## Response 200 OK

```json
{
  "sources": {"x": true, "github": true, "reddit": true, "web": true},
  "types": {"agent": true, "self_improve": true, "open_source": true, "tools": true},
  "dailyPush": {"enabled": true, "time": "08:00"},
  "dailyCount": 30,
  "styleMode": "standard",
  "updatedAt": "2026-08-13T08:00:00+08:00"
}
```

### Response 字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `sources` | object | 是 | 4 键齐全，boolean |
| `types` | object | 是 | 4 键齐全，boolean |
| `dailyPush.enabled` | boolean | 是 | — |
| `dailyPush.time` | string | 是 | HH:mm 24h |
| **`dailyCount`** | int | 是 | **新增**；当前每日条目上限，∈ {10, 20, 30, 40, 50} |
| **`styleMode`** | string | 是 | **新增**；当前阅读风格档位，∈ {concise, standard, detailed} |
| `updatedAt` | string | 是 | 最后修改时间 ISO 8601 / Asia/Shanghai |

## Error Scenarios

| HTTP | 业务码 | 触发 | 前端 |
|---|---|---|---|
| 401 | 1003 | 缺 Authorization / token 失效 | 跳登录 |
| 429 | 1006 | 读限流 120/min/ip | Toast |
| 500 | 9001 | 服务内部错误 | 全局错误态 |

## Performance Budget

- P95 ≤ 200 ms

## Example

```bash
curl -s -H "Authorization: Bearer $AIDAILY_TOKEN" \
  "http://127.0.0.1:8000/api/v1/settings" | jq '{dailyCount, styleMode}'
```
