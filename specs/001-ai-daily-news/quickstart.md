# Quickstart: AI 日报系统 端到端验证

**Date**: 2026-08-12
**Phase**: 1 (Design & Contracts)
**Purpose**: 验证本期 v1.x 功能端到端可跑通的最小步骤。本文档为验证指南，**不含完整实现代码**——具体实现细节由 `/speckit-tasks` 阶段产出。

## Prerequisites

### 环境就绪

- 操作系统：Windows 11 / macOS 14+ / Ubuntu 22.04+
- 运行时：Python 3.11.9+（D1 决议）
- 浏览器：Chromium 内核 ≥ 110（用于前端 + Playwright E2E）
- 网络访问：能访问所选 Anthropic 兼容 LLM 服务（官方 API 或 OneAPI/DeepSeek/Moonshot 转发层）
- 信息源凭据：GitHub PAT（可选，无 token 走 trending 兜底）/ Reddit user-agent（必填，免费 OAuth）/ RSS（web 无需凭据）/ RSSHub（X 源，可选）

### 配置项

部署者在启动前需配置（详见 `research.md` D5/D6/D7）：

```bash
# 必填
AIDAILY_LLM_API_KEY=sk-ant-...                # Anthropic 兼容 API 密钥

# LLM 可选（带默认，clarify Q5 决议）
AIDAILY_LLM_BASE_URL=https://api.anthropic.com  # 可改为 OneAPI/DeepSeek/Moonshot 转发层
AIDAILY_LLM_MODEL=claude-haiku-4-5-20251001      # 任何 Anthropic 协议兼容模型

# 鉴权（可选，缺失时启动自动生成并打印 stdout 一次）
AIDAILY_BEARER_TOKEN=<generated-or-preset>      # 写接口鉴权

# 通用可选（带默认）
AIDAILY_DB_PATH=./data/aidaily.db               # SQLite 路径
AIDAILY_HOST=127.0.0.1
AIDAILY_PORT=8000
AIDAILY_DAILY_PUSH_TIME=08:00                   # 用户偏好初始默认，可被 PUT /settings 覆盖
AIDAILY_TZ=Asia/Shanghai

# X 源（clarify Q1 决议：无 X API token，改用 RSSHub）
AIDAILY_X_RSSHUB_BASE_URL=http://localhost:1200 # 自部署 RSSHub；未配置则 X 源静默跳过
AIDAILY_X_ACCOUNTS=karpathy,simonw,swyx,...     # 覆盖默认 20-30 个 AI KOL 清单

# 其他源凭据（按需）
AIDAILY_GITHUB_TOKEN=ghp_...                    # GitHub PAT，缺失则 trending 兜底
AIDAILY_REDDIT_UA=ai-daily/1.0 by your_username # Reddit API 必填
```

> **X 源部署提示**：默认 RSSHub 实例需自部署（`docker run -d -p 1200:1200 diygod/rsshub`）；未配置时 X 源静默跳过，其余 3 源（github/reddit/web）正常出刊。
>
> 缺失 `AIDAILY_BEARER_TOKEN` 时，后端启动时自动生成并打印到 stdout 一次，部署者复制保存。

## Setup Commands

> 具体命令以 `tasks.md` 阶段产出的 README 为准；此处给出最小流程。

```bash
# 0. （可选，仅 X 源需要）自部署 RSSHub
docker run -d --name rsshub -p 1200:1200 diygod/rsshub:latest
# 设置 AIDAILY_X_RSSHUB_BASE_URL=http://localhost:1200

# 1. 安装依赖
cd backend/
pip install -e ".[dev]"

# 2. 初始化数据库（运行 Alembic 迁移）
alembic upgrade head

# 3. 启动后端（含调度器）
#    首次启动会自动触发初始刊期生成（FR-001b），无需等到 08:00
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 4. （可选，dev 调试用）立即重新生成今日刊
#    v1.x 不暴露为 API；通过内部脚本触发
python -m app.pipeline.run_once --date 2026-08-12

# 5. 打开前端
#    方式 A：浏览器访问 http://127.0.0.1:8000/ （后端 serve 前端静态资源）
#    方式 B：开发模式 separate：cd frontend/ && python -m http.server 3000
```

## Validation Scenarios

### VS-1：今日刊首屏（对应 US1）

**前置**：今日刊期已 `ready`（步骤 4 已生成）

```bash
curl -s "http://127.0.0.1:8000/api/v1/daily/today" | jq '.issue.status, .issue.articleCount, (.articles | length)'
```

**期望输出**：
```
"ready"
<number ≥ 1>
<number ≥ 1，等于 articleCount>
```

**前端验证**：
- 浏览器打开 `http://127.0.0.1:8000/`，首屏 ≤ 1.5s 可交互
- 报头展示日期 `2026-08-12`、版次（≥ 1）、状态徽标
- 左侧索引渲染全部条目（id/title/excerpt/type/src/time/readingMinutes 7 字段）
- 数量徽标按 `byType` 与 `bySource` 渲染

### VS-2：双维筛选（对应 US2）

```bash
# Reddit + Agent 组合
curl -s "http://127.0.0.1:8000/api/v1/articles?src=reddit&type=agent" | jq '.items | length, .appliedFilters'
```

**期望**：`items[]` 全部满足 `src=reddit` 且 `type=agent`；`appliedFilters = { type: "agent", src: "reddit" }`

**前端验证**：
- 点击类型 chip『Agent』→ 列表仅显示 agent 类型
- 叠加点击来源 chip『Reddit』→ 列表显示 reddit + agent 组合
- 列表为空时展示「今天的货架是空的」

### VS-3：详情阅读 + 阅读原文（对应 US1）

```bash
ARTICLE_ID=$(curl -s "http://127.0.0.1:8000/api/v1/daily/today" | jq -r '.articles[0].id')
curl -s "http://127.0.0.1:8000/api/v1/articles/$ARTICLE_ID" | jq 'keys'
```

**期望字段集**：`["id","issueId","type","src","title","excerpt","lede","summary","body","quote","points","time","sourceUrl","sourceName","readingMinutes","publishedAt"]`

**前端验证**：
- 点击索引条目 → 右侧切换详情视图
- 「阅读原文」按钮 → 新标签页打开 `sourceUrl`

### VS-4：偏好保存与下一期生效（对应 US3）

```bash
# 1. 保存偏好（关闭 github 源）
curl -s -X PUT "http://127.0.0.1:8000/api/v1/settings" \
  -H "Authorization: Bearer $AIDAILY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "sources": {"x": true, "github": false, "reddit": true, "web": true},
    "types": {"agent": true, "self_improve": true, "open_source": true, "tools": true},
    "dailyPush": {"enabled": true, "time": "08:00"}
  }' \
  -D /tmp/headers.txt > /tmp/body.json
cat /tmp/headers.txt | grep -i x-effective-at
cat /tmp/body.json | jq '.sources.github'    # 期望 false

# 2. 验证持久化
curl -s "http://127.0.0.1:8000/api/v1/settings" \
  -H "Authorization: Bearer $AIDAILY_BEARER_TOKEN" | jq '.sources.github'    # 期望 false

# 3. 触发下一期生成（dev 脚本）
python -m app.pipeline.run_once --date 2026-08-13

# 4. 验证新刊期 filtersApplied 不含 github
curl -s "http://127.0.0.1:8000/api/v1/daily/today" | jq '.issue.filtersApplied.sources'    # 期望 ["x","reddit","web"]
```

**期望**：响应头 `X-Effective-At: 20260813`；下一期刊期 `filtersApplied.sources` 不含 `github`。

### VS-5：恢复默认（对应 US3）

```bash
curl -s -X POST "http://127.0.0.1:8000/api/v1/settings/reset" \
  -H "Authorization: Bearer $AIDAILY_BEARER_TOKEN" | jq '.sources, .types, .dailyPush'
```

**期望**：4 源全 true、4 类型全 true、`dailyPush = { enabled: true, time: "08:00" }`

### VS-6：分享卡片（对应 US4）

```bash
curl -s -X POST "http://127.0.0.1:8000/api/v1/share" \
  -H "Authorization: Bearer $AIDAILY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"articleId\": \"$ARTICLE_ID\"}" | jq '.shareId, .cardUrl, .articleTitle'
```

**期望**：`shareId` 形如 `shr_<8 hex>`；`cardUrl` 可在浏览器打开；`articleTitle` 与原 Article.title 一致。

### VS-7：元数据驱动（对应 US2 + FR-008）

```bash
curl -s "http://127.0.0.1:8000/api/v1/meta" | jq '.sources | length, .types | length'
```

**期望**：`4` / `4`

**前端验证**：
- 在浏览器 DevTools 中 grep 前端代码：搜索 `'github'` 字面量 → 应仅在图标资源名中出现，不应在筛选/设置列表逻辑中出现
- 修改后端 `/meta` 返回（临时新增一个 source key 如 `mastodon`）→ 前端无需发版即可在 chips 中显示

### VS-8：错误态全覆盖（对应 US5）

```bash
# 1002：非法枚举
curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8000/api/v1/articles?src=wechat"
# 期望：400

# 2001：文章不存在
curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8000/api/v1/articles/nonexistent"
# 期望：404

# 1003：未认证访问写接口
curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8000/api/v1/settings"
# 期望：401

# 1005：校验失败
curl -s -o /dev/null -w "%{http_code}\n" -X PUT "http://127.0.0.1:8000/api/v1/settings" \
  -H "Authorization: Bearer $AIDAILY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"sources": {}, "types": {}, "dailyPush": {"enabled": true, "time": "25:00"}}'
# 期望：422
```

### VS-9：健康检查（对应 FR-025）

```bash
curl -s "http://127.0.0.1:8000/api/v1/healthz" | jq '.'
```

**期望**：`status: "ok"`、`version` 与部署版本一致、`pipeline.collector` 与 `pipeline.summarizer` 均 `up`。

### VS-9a：首装自动触发初始刊期（对应 FR-001b）

**前置**：删除 `./data/aidaily.db` 模拟全新部署。

```bash
# 1. 清空数据库
rm ./data/aidaily.db

# 2. 启动后端（首装检测 → 自动后台触发初始生成）
uvicorn app.main:app --host 127.0.0.1 --port 8000 &

# 3. 30 秒内调用今日刊接口（应返回 2002）
curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8000/api/v1/daily/today"
# 期望：404（业务码 2002）

# 4. 等待 5-10 分钟后重试
sleep 600
curl -s "http://127.0.0.1:8000/api/v1/daily/today" | jq '.issue.status'
# 期望："ready"
```

**期望**：首装后无需等到 08:00，约 5-10 分钟内首期生成完成。

### VS-9b：单源失败容错（对应 FR-007a）

**前置**：配置一个不可达的 RSSHub 端点。

```bash
# 设置错误的 RSSHub 端点
export AIDAILY_X_RSSHUB_BASE_URL=http://192.0.2.1:1200   # TEST-NET-1 永不可达

# 触发一次刊期生成
python -m app.pipeline.run_once --date 2026-08-12

# 验证刊期状态 ready（X 源跳过，其他源继续）
curl -s "http://127.0.0.1:8000/api/v1/daily/today" | jq '.issue.status, .summary.bySource'
# 期望：status="ready"；bySource.x=0；bySource.github/reddit/web 有数据

# 验证结构化日志记录失败源
grep "source=x.*failed" logs/aidaily.log | tail -5
# 期望：可见 X 源采集失败日志（不影响整体刊期）
```

### VS-10：E2E 主路径（Playwright）

```bash
cd backend/tests/e2e/
pytest test_happy_path.py -v
```

**测试覆盖的主路径**：
1. 打开首页 → 验证报头与索引可见
2. 点击类型 chip → 验证列表筛选生效
3. 点击第一条 → 验证详情视图渲染完整字段
4. 点击「阅读原文」→ 验证新标签页 URL = `sourceUrl`
5. 打开设置面板 → 关闭 github 源 → 保存 → 验证响应头 `X-Effective-At` 存在
6. 重新打开设置面板 → 验证回填正确
7. 点击「恢复默认」→ 验证全开 + 08:00
8. 在详情点击「分享这条」→ 验证返回 `cardUrl`

## References

- 接口契约：[contracts/](./contracts/)
- 数据模型：[data-model.md](./data-model.md)
- 技术决策：[research.md](./research.md)
- 实现规范：[spec.md](./spec.md)
- 联调自测清单（接口文档 §9）：见 `ai日报-后端集成接口文档.md`

## Performance Validation

完成上述 VS-1 ~ VS-10 后，运行性能基准（对应 Constitution IV）：

```bash
# P95 测试（需 locust 或 k6）
cd backend/tests/performance/
pytest test_perf_budgets.py --baseline

# 期望：
# - GET /daily/today      P95 ≤ 500 ms
# - GET /articles         P95 ≤ 300 ms
# - GET /articles/{id}    P95 ≤ 200 ms
# - 首屏可交互             ≤ 1.5 s
```

性能基准必须在 CI 中可重复运行，回归即阻断合并（详见 Constitution IV）。
