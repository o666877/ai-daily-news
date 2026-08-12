# Contract: GET /meta

**接口 #4 · 信息源/类型元数据** · 认证：否 · 用途：筛选 chips + 设置面板开关列表的数据源

## Request

```http
GET /api/v1/meta
```

无参数。无请求体。

## Response 200 OK

```json
{
  "sources": [
    {
      "key": "x",
      "name": "X (Twitter)",
      "short": "X",
      "icon": "x",
      "description": "前沿哨兵，偶尔发疯但信息最快"
    },
    {
      "key": "github",
      "name": "GitHub",
      "short": "GitHub",
      "icon": "github",
      "description": "仓库动态、新项目、趋势榜单"
    },
    {
      "key": "reddit",
      "name": "Reddit",
      "short": "Reddit",
      "icon": "reddit",
      "description": "社区热帖与高赞讨论，一手开发者情报"
    },
    {
      "key": "web",
      "name": "全网聚合",
      "short": "全网",
      "icon": "globe",
      "description": "搜索引擎 + RSS 兜底，不放过漏网之鱼"
    }
  ],
  "types": [
    { "key": "agent", "name": "Agent / 智能体", "shortName": "Agent" },
    { "key": "self_improve", "name": "持续学习 / 自我进化", "shortName": "持续学习" },
    { "key": "open_source", "name": "开源项目", "shortName": "开源" },
    { "key": "tools", "name": "工具与效率", "shortName": "工具效率" }
  ]
}
```

**字段说明**：

| 字段 | 说明 |
|---|---|
| `sources[].key` | SourceKey 枚举值 |
| `sources[].name` | 展示名（含品牌全称） |
| `sources[].short` | 短名（chips 与徽标使用） |
| `sources[].icon` | 前端图标 key（`x` / `github` / `reddit` / `globe`） |
| `sources[].description` | 一句话描述（设置面板 tooltip） |
| `types[].key` | TypeKey 枚举值 |
| `types[].name` | 展示名 |
| `types[].shortName` | 短名（chips 使用） |

**关键约束**：
- **前端不硬编码** sources[] / types[] 列表
- 后端未来新增信息源/类型 → 前端无需发版即可自动展示
- 顺序由后端决定，前端按返回顺序渲染

## Error Scenarios

| HTTP | 业务码 | 触发条件 | 前端表现 |
|---|---|---|---|
| 500 | `9001` | 服务内部错误 | 全局错误态 |
| 429 | `1006` | 触发读限流 | Toast |

> 本接口理论上几乎不会失败（数据为静态枚举）；后端 500 时前端可降级使用上次缓存。

## Performance Budget

- P95 ≤ 200 ms（静态数据可缓存）
- 建议前端缓存至 sessionStorage，生命周期内不重复请求

## Example (curl)

```bash
curl -s "https://{host}/api/v1/meta"
```
