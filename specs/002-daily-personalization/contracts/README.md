# Contracts: 002 日报个性化

本目录描述 002 feature 扩展后的 5 个接口契约。继承 001 系统全部接口（9 个），仅扩展响应字段；URL、认证、错误码体系不变。

## 与 001 系统的差异

| 接口 | 001 | 002 扩展 |
|---|---|---|
| GET /daily/today | 7 字段/条目 | 每条目新增 `compositeScore` |
| GET /articles | 7 字段/条目 | 每条目新增 `compositeScore`；列表已按 `compositeScore DESC` 排序 |
| GET /articles/{id} | 详情字段 | 新增 `dimensionScores` / `authorityTier` / `scoreSource` / `topicId` |
| GET /settings | sources/types/dailyPush | 新增 `dailyCount` / `styleMode` |
| PUT /settings | sources/types/dailyPush | 新增 `dailyCount` / `styleMode`（Literal 校验） |
| POST /settings/reset | — | 行为不变，新增字段也重置为默认值 |
| GET /meta | — | 不变 |
| POST /share | — | 不变 |
| GET /healthz | — | 不变 |

## 阅读约定

- 所有响应字段使用 **camelCase**（前端约定）
- 错误响应统一 `{code, message, requestId}`（沿用 001 业务码 1001-9002）
- 时间字段 ISO 8601 / Asia/Shanghai（+08:00）
- 评分为整数 0–100；缺失时返回 `null`（极少情况，仅迁移后未重新生成的旧 articles）

## 详细契约

- [daily-today.md](./daily-today.md)
- [articles-list.md](./articles-list.md)
- [articles-detail.md](./articles-detail.md)
- [settings-get.md](./settings-get.md)
- [settings-put.md](./settings-put.md)
