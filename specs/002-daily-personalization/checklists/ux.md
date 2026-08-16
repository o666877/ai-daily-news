# US3 阅读密度档位 — 手动验证清单

> 对应任务：T039, T042-T050
> 实现位置：`frontend/index.html`（inline `<style>` + inline `<script>`）
> 验证方式：浏览器手动操作（e2e 框架在 Windows 当前环境不稳定，依宪章改为手动脚本）

## 前置准备

1. 启动后端：`cd backend && uvicorn app.main:app --reload`
2. 浏览器打开 `http://127.0.0.1:8000/`
3. 顶部右上角点设置图标 → 若弹 Token 框，填入 `.env` 中的 `AIDAILY_BEARER_TOKEN`

## 场景 1 — 默认 standard 模式（T046, T042）

- [ ] 列表项显示字段：`title`、`excerpt`、`type tag`、`src-name`、`time`、`readingMinutes`
- [ ] 详情视图显示：`title`、`excerpt`、`lede`、`body`、`points`、底部 `阅读原文` + `分享这条` 按钮
- [ ] 阅读器顶栏右侧 3 个档位按钮「简 / 标 / 详」中「标」高亮（深底白字）

## 场景 2 — 切换到 concise（设置面板）

- [ ] 打开设置 → 「阅读密度」选「简洁」→ 保存
- [ ] Toast 显示「已保存 · 生效刊期：...」
- [ ] 列表项只剩：`title`、`src-name`（sourceName）、`compositeScore` 徽章（若后端有数据）
- [ ] 列表项仍可点击，hover 出现 `--accent` 边框
- [ ] 点击列表项 → 详情只剩：`title` + `summary`（一句话总结）+ `阅读原文` 按钮
- [ ] 「返回索引」、列表项点击、详情底部按钮均保留可交互

## 场景 3 — 切换到 detailed（设置面板）

- [ ] 打开设置 → 选「详细」→ 保存
- [ ] 列表项末尾出现 4 个子维度徽章：`权90 深85 时70 表80`（颜色：橙 / 绿 / 黄 / 灰），及综合分
- [ ] 详情底部多出 `score-block`：4 个维度徽章 + `权威等级 A` 徽章
- [ ] 详情全部字段（含 `quote`）均渲染

## 场景 4 — 阅读器顶栏临时切换（T047，不持久化）

- [ ] 在详情视图点「简」→ 详情立即变为 `title + summary + 阅读原文`，列表同步精简
- [ ] 点「详」→ 详情恢复完整 + 显示子维度徽章
- [ ] 「标」→ 回到 standard
- [ ] 刷新页面（F5）→ `state.currentStyle` 重置为 `null`，渲染回到上次保存的 `styleMode`

## 场景 5 — 持久化校验

- [ ] 设置面板选「简洁」→ 保存 → F5 刷新
- [ ] 刷新后列表自动呈现 concise 字段集（说明 GET /settings 返回 styleMode 并被 state 应用）
- [ ] 顶栏档位按钮 active 状态对应「简」

## 场景 6 — 缺失字段的优雅降级

- [ ] 后端当前 `/articles` 不返回 `compositeScore / dimensionScores / authorityTier`
- [ ] 因此 detailed 模式列表/详情应：徽章不渲染（renderScoreBadges 收到 undefined 返回空串），其余字段正常
- [ ] 控制台无报错（`Cannot read property of undefined` 等）

## 场景 7 — 无障碍 / 键盘

- [ ] 顶栏档位按钮 `role="group"` + `aria-label`
- [ ] 当前激活按钮 `aria-pressed="true"`
- [ ] 单选框 `<input type="radio" name="styleMode">` 可用 Tab + 方向键操作

## 已知限制（非本 PR 范围）

- 后端 `/articles` 与 `/articles/{id}` 尚未 join `article_scores` 表，因此 `compositeScore / dimensionScores / authorityTier` 当前从后端拿不到。前端已做 null-safe 处理；待评分端点接入后无需前端改动即可显示徽章。
- Playwright e2e 跳过，待 Windows 环境修复后补 `tests/e2e/style_mode.spec.ts`。
