# API Contracts: AI 日报系统

**Base URL**: `https://{host}/api/v1`
**Protocol / Encoding**: HTTPS · JSON · UTF-8
**Time**: ISO 8601, `Asia/Shanghai` (UTC+8)
**Auth**: 读接口匿名可用；写接口需 `Authorization: Bearer <token>`
**Request ID**: 客户端可传 `X-Request-Id` 头，响应同值返回
**Pagination**: `page` 从 1 起；`pageSize` 默认 20，最大 50
**Idempotency**: `PUT /settings` 全量覆盖，重复提交安全
**Rate Limit**: 读 120 次/分钟/IP，写 30 次/分钟/用户

## Endpoints

| # | 方法 | 路径 | 认证 | 契约文档 |
|---|---|---|---|---|
| 1 | GET | `/daily/today` | 否 | [daily-today.md](./daily-today.md) |
| 2 | GET | `/articles` | 否 | [articles-list.md](./articles-list.md) |
| 3 | GET | `/articles/{id}` | 否 | [articles-detail.md](./articles-detail.md) |
| 4 | GET | `/meta` | 否 | [meta.md](./meta.md) |
| 5 | GET | `/settings` | 是 | [settings-get.md](./settings-get.md) |
| 6 | PUT | `/settings` | 是 | [settings-put.md](./settings-put.md) |
| 7 | POST | `/settings/reset` | 是 | [settings-reset.md](./settings-reset.md) |
| 8 | POST | `/share` | 是 | [share.md](./share.md) |
| 9 | GET | `/healthz` | 否 | [healthz.md](./healthz.md) |

## Unified Error Structure

所有 4xx/5xx 响应必含：

```json
{
  "code": <integer>,
  "message": <string>,
  "requestId": <string>
}
```

## Error Code Table

| HTTP | 业务码 | 含义 | 触发示例 |
|---|---|---|---|
| 400 | `1001` | 缺少必填参数 | `POST /share` 缺 `articleId` |
| 400 | `1002` | 枚举值非法（type/src） | `GET /articles?src=wechat` |
| 401 | `1003` | 未认证或 token 失效 | 写接口无 Bearer |
| 403 | `1004` | 无权限 | （本期单用户预留） |
| 404 | `2001` | 文章不存在 | `GET /articles/xxx` |
| 404 | `2002` | 刊期不存在或未生成完成 | 08:00 前访问今日刊 |
| 409 | `2003` | 刊期正在生成中 | `GET /daily/today` 命中 generating |
| 422 | `1005` | 请求体校验失败 | `dailyPush.time = "25:00"` |
| 429 | `1006` | 触发限流 | 超出 120/min/IP 或 30/min/user |
| 500 | `9001` | 服务内部错误 | 未捕获异常 |
| 503 | `9002` | 采集 / 摘要管线繁忙 | 下游依赖不可用 |

> **安全约束**：错误响应**绝不**返回内部栈、SQL、密钥；仅含上述三字段。
