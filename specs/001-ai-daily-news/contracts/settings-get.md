# Contract: GET /settings

**接口 #5 · 获取用户偏好** · 认证：**是** · 用途：设置面板回填

## Request

```http
GET /api/v1/settings
Authorization: Bearer <token>
```

**Headers**：

| Header | 必填 | 说明 |
|---|---|---|
| `Authorization` | 是 | `Bearer <token>`；缺省或无效 → 业务码 `1003` |
| `X-Request-Id` | 否 | 客户端透传，响应同值返回 |

无参数。无请求体。

## Response 200 OK

Settings 对象（详见 [data-model.md](../data-model.md#5-settings用户偏好)）：

```json
{
  "sources": { "x": true, "github": true, "reddit": true, "web": true },
  "types": { "agent": true, "self_improve": true, "open_source": true, "tools": true },
  "dailyPush": { "enabled": true, "time": "08:00" },
  "updatedAt": "2026-08-12T10:30:00+08:00"
}
```

**字段说明**：

| 字段 | 说明 |
|---|---|
| `sources` | 4 源开关 map；键齐全（`x` / `github` / `reddit` / `web`） |
| `types` | 4 类型开关 map；键齐全（`agent` / `self_improve` / `open_source` / `tools`） |
| `dailyPush.enabled` | 每日推送总开关 |
| `dailyPush.time` | 推送时间 `HH:mm` 24 小时制 |
| `updatedAt` | 最后修改时间；前端用于展示「上次保存于」 |

**首次访问行为**：
- 用户从未保存过偏好时，返回默认 Settings（全开 + 08:00 推送，`updatedAt` 为系统初始化时间）
- 与 `POST /settings/reset` 返回的默认值一致

## Error Scenarios

| HTTP | 业务码 | 触发条件 | 前端表现 |
|---|---|---|---|
| 401 | `1003` | 缺 `Authorization` 头或 token 失效 | 跳登录 / 提示重新认证 |
| 429 | `1006` | 触发写限流（30/min/user） | Toast |
| 500 | `9001` | 服务内部错误 | 全局错误态 + 重试 |

> **限流归类**：本接口虽为 GET，但因返回私人数据需鉴权，**计入写限流配额**（30/min/user）。详见接口文档 §2。

## Performance Budget

- P95 ≤ 200 ms

## Example (curl)

```bash
curl -s "https://{host}/api/v1/settings" \
  -H "Authorization: Bearer $AIDAILY_TOKEN"
```
