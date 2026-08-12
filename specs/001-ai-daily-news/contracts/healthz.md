# Contract: GET /healthz

**接口 #9 · 健康检查** · 认证：否 · 用途：联调与监控（**不展示给终端用户**）

## Request

```http
GET /api/v1/healthz
```

无参数。无请求体。无鉴权。

## Response 200 OK

```json
{
  "status": "ok",
  "version": "1.0.0",
  "pipeline": {
    "collector": "up",
    "summarizer": "up"
  }
}
```

**字段说明**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | string | 整体状态：`ok` / `degraded` / `down` |
| `version` | string | 后端语义化版本（SemVer），如 `1.0.0` |
| `pipeline.collector` | string | 采集子系统健康状态：`up` / `down` |
| `pipeline.summarizer` | string | 摘要子系统健康状态：`up` / `down` |

**状态判定规则**：

| 条件 | `status` |
|---|---|
| `collector` 与 `summarizer` 均 `up` | `ok` |
| 任一 `down` 但另一 `up` | `degraded` |
| 两者均 `down` | `down` |

## Error Scenarios

| HTTP | 业务码 | 触发条件 | 前端表现 |
|---|---|---|---|
| 503 | `9002` | 服务整体不可用（启动失败、关键依赖断开） | 监控告警 |

> 本接口即使 `status = down`，也返回 200 + 业务字段，便于监控拉取；仅在进程无法响应时返回 503。

## Performance Budget

- P95 ≤ 50 ms（极简响应）

## Example (curl)

```bash
curl -s "https://{host}/api/v1/healthz"
```

## Use Cases

- **联调阶段**：前端确认后端已就绪、采集/摘要子系统健康
- **运维监控**：定时拉取作为存活探针
- **部署验证**：发布后立即调用验证版本号正确
- **故障排查**：判断问题是出在 API 层（status=ok 但接口失败）还是管线层（pipeline.down）
