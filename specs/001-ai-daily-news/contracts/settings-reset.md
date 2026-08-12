# Contract: POST /settings/reset

**接口 #7 · 恢复默认偏好** · 认证：**是** · 用途：一键回到全开 + 08:00 推送

## Request

```http
POST /api/v1/settings/reset
Authorization: Bearer <token>
```

**Headers**：

| Header | 必填 | 说明 |
|---|---|---|
| `Authorization` | 是 | `Bearer <token>` |
| `X-Request-Id` | 否 | 客户端透传 |

无请求体。无参数。

## Response 200 OK

返回重置后的默认 Settings（与 `GET /settings` 首次访问返回值一致）：

```json
{
  "sources": { "x": true, "github": true, "reddit": true, "web": true },
  "types": { "agent": true, "self_improve": true, "open_source": true, "tools": true },
  "dailyPush": { "enabled": true, "time": "08:00" },
  "updatedAt": "2026-08-12T11:05:00+08:00"
}
```

**默认值表**：

| 字段 | 默认值 |
|---|---|
| `sources.x` / `github` / `reddit` / `web` | `true`（全开） |
| `types.agent` / `self_improve` / `open_source` / `tools` | `true`（全开） |
| `dailyPush.enabled` | `true` |
| `dailyPush.time` | `"08:00"` |

**响应头**：

| Header | 说明 |
|---|---|
| `X-Effective-At` | 重置后生效刊期（与 `PUT /settings` 一致） |
| `X-Request-Id` | 透传 |

**生效语义**：
- 行为等价于：用默认值调用一次 `PUT /settings`
- 下一期刊期生效；当期不回溯
- 异步同步给采集调度器
- 幂等：连续多次调用结果一致

**前端行为**：
- 调用后回填返回的默认值到设置面板 UI
- 提示「已恢复默认偏好，明天的日报将按新口味调配」

## Error Scenarios

| HTTP | 业务码 | 触发条件 | 前端表现 |
|---|---|---|---|
| 401 | `1003` | 缺 Authorization 或 token 失效 | 跳登录 |
| 429 | `1006` | 触发写限流（30/min/user） | Toast |
| 500 | `9001` | 服务内部错误 | 全局错误态 + 重试 |

## Performance Budget

- P95 ≤ 300 ms

## Example (curl)

```bash
curl -s -X POST "https://{host}/api/v1/settings/reset" \
  -H "Authorization: Bearer $AIDAILY_TOKEN" \
  -D -
```
