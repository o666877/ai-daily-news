# Contract: PUT /settings (v2 扩展)

**接口 #5 · 保存用户偏好（全量覆盖）** · 认证：**是**

> 本契约在 [001 系统契约](../../001-ai-daily-news/contracts/settings-put.md) 基础上扩展：请求体新增 `dailyCount` 与 `styleMode`，校验规则与生效语义对齐。

## Request

```http
PUT /api/v1/settings
Authorization: Bearer <token>
Content-Type: application/json

{
  "sources": {"x": true, "github": false, "reddit": true, "web": true},
  "types": {"agent": true, "self_improve": true, "open_source": false, "tools": true},
  "dailyPush": {"enabled": true, "time": "08:00"},
  "dailyCount": 10,
  "styleMode": "concise"
}
```

### Body 字段

| 字段 | 类型 | 必填 | 约束 | 非法 → |
|---|---|---|---|---|
| `sources` | object | 是 | 4 键齐全，boolean | `1005` |
| `types` | object | 是 | 4 键齐全，boolean | `1005` |
| `dailyPush.enabled` | boolean | 是 | — | `1005` |
| `dailyPush.time` | string | 是 | HH:mm 24h | `1005` |
| **`dailyCount`** | int | 是 | **新增**；∈ {10, 20, 30, 40, 50} | `1005` |
| **`styleMode`** | string | 是 | **新增**；∈ {concise, standard, detailed} | `1005` |

> **全量覆盖语义保持**：所有 6 个字段必须提交；缺省字段视为校验失败（不会"不修改"），与 001 体系一致。

## Response 200 OK

```http
HTTP/1.1 200 OK
X-Effective-At: 20260814
Content-Type: application/json

{
  "sources": {"x": true, "github": false, "reddit": true, "web": true},
  "types": {"agent": true, "self_improve": true, "open_source": false, "tools": true},
  "dailyPush": {"enabled": true, "time": "08:00"},
  "dailyCount": 10,
  "styleMode": "concise",
  "updatedAt": "2026-08-13T11:00:00+08:00"
}
```

### 响应头

| Header | 说明 |
|---|---|
| `X-Effective-At` | 生效刊期 YYYYMMDD（明日，对齐 001 语义） |
| `X-Request-Id` | 客户端透传 |

### 生效语义（**新增**）

- `sources` / `types` / `dailyPush` / `dailyCount`：**下一期刊生成立即生效**（不重算当期），与 001 一致
- `styleMode`：**立即生效**（前端读取后即时切换字段白名单，无需等下一期；持久化值用于下次启动默认档）
- 前端 UI 提示语：
  - 修改 `dailyCount` → "已保存，下次 08:00 生效"
  - 修改 `styleMode` → "已保存，立即生效"
- **幂等**：重复提交相同 body 不产生副作用

## Error Scenarios

| HTTP | 业务码 | 触发条件 | 前端表现 |
|---|---|---|---|
| 401 | 1003 | 缺 Authorization 或 token 失效 | 跳登录 |
| 422 | 1005 | body 校验失败：缺键、值类型错、`dailyCount=15` 非 5 档、`styleMode="verbose"` 非三档等 | 表单级提示，注明字段 |
| 429 | 1006 | 触发写限流 30/min/user | Toast |
| 500 | 9001 | 服务内部错误 | 全局错误态 + 重试 |

## 校验细节

- `dailyCount` 必须是 JSON 整数，且 ∈ {10, 20, 30, 40, 50}；其他值（包括字符串 "30"、浮点 30.0、整数 15）→ `1005`
- `styleMode` 必须是 JSON 字符串，且 ∈ {concise, standard, detailed}；其他值（包括大写 "Concise"、空串）→ `1005`
- 字段类型严格（与 001 sources/types 的 StrictBool 一致）

## Performance Budget

- P95 ≤ 300 ms（不含异步同步给采集调度器）

## Example

```bash
curl -s -X PUT "http://127.0.0.1:8000/api/v1/settings" \
  -H "Authorization: Bearer $AIDAILY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "sources": {"x": true, "github": true, "reddit": true, "web": true},
    "types": {"agent": true, "self_improve": true, "open_source": true, "tools": true},
    "dailyPush": {"enabled": true, "time": "08:00"},
    "dailyCount": 10,
    "styleMode": "concise"
  }' \
  -D -  # 验证 X-Effective-At
```
