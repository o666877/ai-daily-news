# Contract: PUT /settings

**接口 #6 · 保存用户偏好（全量覆盖）** · 认证：**是** · 用途：保存偏好；下一期刊期生效

## Request

```http
PUT /api/v1/settings
Authorization: Bearer <token>
Content-Type: application/json

{
  "sources": { "x": true, "github": false, "reddit": true, "web": true },
  "types": { "agent": true, "self_improve": true, "open_source": false, "tools": true },
  "dailyPush": { "enabled": true, "time": "08:00" }
}
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
| `sources` | object | 是 | 4 键齐全（`x` / `github` / `reddit` / `web`）；值均为 boolean；缺键 → `1005` |
| `types` | object | 是 | 4 键齐全（`agent` / `self_improve` / `open_source` / `tools`）；值均为 boolean；缺键 → `1005` |
| `dailyPush.enabled` | boolean | 是 | — |
| `dailyPush.time` | string | 是 | `HH:mm` 24 小时制（`00:00` – `23:59`）；非法 → `1005` |

> **全量覆盖语义**：所有字段必须提交；缺省字段不会被解释为「不修改」。`updatedAt` 由后端写入，前端不传。

## Response 200 OK

```http
HTTP/1.1 200 OK
X-Effective-At: 20260813
Content-Type: application/json

{
  "sources": { "x": true, "github": false, "reddit": true, "web": true },
  "types": { "agent": true, "self_improve": true, "open_source": false, "tools": true },
  "dailyPush": { "enabled": true, "time": "08:00" },
  "updatedAt": "2026-08-12T11:00:00+08:00"
}
```

**响应头**：

| Header | 说明 |
|---|---|
| `X-Effective-At` | 生效刊期，格式 `YYYYMMDD`（如 `20260813` 表示明日刊期生效） |
| `X-Request-Id` | 与请求头同值（若客户端传了） |

**生效语义**：
- **下一期刊期生成立即生效**（不重算当期）
- 前端 UI 提示语：「明天的日报将按新口味调配」
- 异步同步给采集调度器
- **幂等**：重复提交相同 body 不产生副作用

## Error Scenarios

| HTTP | 业务码 | 触发条件 | 前端表现 |
|---|---|---|---|
| 401 | `1003` | 缺 Authorization 或 token 失效 | 跳登录 |
| 422 | `1005` | body 校验失败：缺键、值非 boolean、`dailyPush.time` 非 `HH:mm`、`time = "25:00"` 等 | 表单级提示，注明字段 |
| 429 | `1006` | 触发写限流（30/min/user） | Toast |
| 500 | `9001` | 服务内部错误 | 全局错误态 + 重试 |

## Performance Budget

- P95 ≤ 300 ms（不含异步同步给采集调度器）

## Example (curl)

```bash
curl -s -X PUT "https://{host}/api/v1/settings" \
  -H "Authorization: Bearer $AIDAILY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "sources": {"x": true, "github": false, "reddit": true, "web": true},
    "types": {"agent": true, "self_improve": true, "open_source": false, "tools": true},
    "dailyPush": {"enabled": true, "time": "08:00"}
  }' \
  -D -  # 显示响应头以验证 X-Effective-At
```
