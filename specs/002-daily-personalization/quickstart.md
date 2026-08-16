# Quickstart: 日报个性化（评分体系 + 数量 + 风格）

**Branch**: `002-daily-personalization` | **Date**: 2026-08-13

本文件描述端到端验证本期 3 个 user stories 的可执行场景。**不含完整代码**——具体实现细节见 tasks.md（后续 /speckit-tasks 生成）。

---

## 前置条件

继承 001 系统的全部前置条件：

1. **后端运行**：`http://127.0.0.1:8000`（uvicorn 单进程）
2. **Bearer token**：保存到 `$AIDAILY_TOKEN` 环境变量
3. **DB 已迁移**：执行 `alembic upgrade head`，应新增 `article_scores` 表 + `settings` 两列
4. **至少一期已生成**：当日有 ready 状态的 daily_issue

新增前置（002 特有）：

5. **LLM 可达**：评分字段需要 LLM 在 summarizer 阶段产出，确保 `AIDAILY_LLM_BASE_URL` + `AIDAILY_LLM_API_KEY` 配置正确

---

## 验证场景 1: P1 — 综合评分可见可解释

**目标**：每篇文章都有综合分 + 4 维子分；用户能从详情页理解排序依据。

### 步骤

```bash
# 1. 查询今日刊，确认每条目有 compositeScore
curl -s "http://127.0.0.1:8000/api/v1/daily/today" \
  | jq '.articles[0:3] | map({id, title: .title[0:30], compositeScore})'

# 期望：3 条文章 compositeScore 在 50-100 区间，按降序排列

# 2. 查询详情，确认 dimensionScores + authorityTier
curl -s "http://127.0.0.1:8000/api/v1/articles/$(curl -s http://127.0.0.1:8000/api/v1/daily/today | jq -r '.articles[0].id')" \
  | jq '.score'

# 期望：返回对象含
# - compositeScore: 整数
# - dimensionScores: {authority, depth, timeliness, expression} 四个整数
# - authorityTier: official_blog / authoritative_media / community 之一
# - scoreSource: llm 或 rule_fallback
# - topicId / opinionFingerprint: 字符串或 null
```

### 通过判据

- ✅ 每条目 `compositeScore` ∈ [0, 100]
- ✅ 详情 `dimensionScores` 4 个子分齐全
- ✅ 官方博客来源（如 OpenAI Blog）的 `authorityTier = 'official_blog'`、`dimensionScores.authority ≥ 90`
- ✅ 社区来源（如 X / Reddit）的 `authorityTier = 'community'`、`dimensionScores.authority ≈ 50`
- ✅ 列表 articles 数组按 `compositeScore DESC` 排序

---

## 验证场景 2: P2 — `daily_count` 截取生效

**目标**：修改 `dailyCount` 后，下一期刊按 top-N 截取。

### 步骤

```bash
# 1. 当前刊期条目数
curl -s "http://127.0.0.1:8000/api/v1/daily/today" | jq '.issue.articleCount'
# 期望：30（默认值）

# 2. 修改 dailyCount 为 10
curl -s -X PUT "http://127.0.0.1:8000/api/v1/settings" \
  -H "Authorization: Bearer $AIDAILY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "sources": {"x": true, "github": true, "reddit": true, "web": true},
    "types": {"agent": true, "self_improve": true, "open_source": true, "tools": true},
    "dailyPush": {"enabled": true, "time": "08:00"},
    "dailyCount": 10,
    "styleMode": "standard"
  }' \
  -D -  # 验证 X-Effective-At 头
# 期望：HTTP 200；X-Effective-At: 明日日期；响应中 dailyCount=10

# 3. 模拟下一期生成（直接调 python，绕过调度）
python -c "
import asyncio
from app.pipeline.generator import generate_issue
from datetime import datetime, timedelta
# 用明日日期触发下一期
tomorrow = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=1)
r = asyncio.run(generate_issue(date=tomorrow))
print(f'issue={r.id} count={r.article_count}')
"
# 期望：articleCount=10（按综合分 top-10 截取）

# 4. 校验 top-10 是评分最高的 10 条
curl -s "http://127.0.0.1:8000/api/v1/daily/today" | jq '[.articles[].compositeScore] | sort | reverse | .[0:10]'
# 期望：与上一条命令返回的 10 条 article 的 compositeScore 列表一致
```

### 通过判据

- ✅ PUT settings 返回 200，`X-Effective-At` 为明日
- ✅ 明日刊期 `articleCount = 10`
- ✅ 这 10 条的 `compositeScore` 是当期候选池的 top-10
- ✅ 当日已发行刊期未被重生成

---

## 验证场景 3: P3 — 三档 `style_mode` 字段白名单

**目标**：切换 style_mode 后，索引列表与详情页字段同步变化。

### 步骤（浏览器手动）

1. 打开 `http://127.0.0.1:8000/`，确认今日刊加载完成
2. 打开设置面板，切换 `styleMode = concise`，保存
3. 刷新页面，**观察索引列表**：
   - 每行只显示：标题、来源、综合评分
   - 隐藏：摘要、收录时间、阅读分钟、类型
4. 点击任意条目，**观察详情页**：
   - 只显示：标题、一句话总结、原文链接
   - 隐藏：导语、正文、引用、要点、子分数
5. 切换 `styleMode = detailed`，刷新
6. **观察索引列表**：行末出现子分数徽标（如 `权90 深85 时70 表80`）
7. **观察详情页**：底部出现各维度子分数可视化 + 引用块

### 自动化验证（可选 e2e）

```bash
# 通过 Playwright（继承 001 e2e 框架）
pytest backend/tests/e2e/test_style_mode.py -v
# 期望：3 个测试通过（concise / standard / detailed 各一）
```

### 通过判据

- ✅ `concise` 档列表只显示 3 字段（标题/来源/评分）
- ✅ `concise` 档详情只显示 3 字段（标题/总结/链接）
- ✅ `detailed` 档列表多 4 个子分数徽标
- ✅ `detailed` 档详情多引用块 + 子分数可视化
- ✅ `styleMode` 临时切换（阅读器顶部按钮）不持久化（刷新后回到 settings 默认）

---

## 验证场景 4: 三层去重生效（Edge Case）

**目标**：当候选池中存在 URL 相同 / 同事件 / 同观点的文章时，去重后只保留最高分。

### 步骤

```bash
# 1. 在测试 fixture 中注入 3 篇"同事件"文章（不同 URL，LLM 输出相同 topic_id）
# 详见 backend/tests/unit/test_dedup.py::test_dedup_same_topic_keeps_highest

# 2. 跑单测
pytest backend/tests/unit/test_dedup.py -v

# 期望：
# - test_dedup_by_url: 同 URL 仅留最高分
# - test_dedup_by_topic: 同 topic_id 仅留"评分 × 出现次数"最高
# - test_dedup_by_opinion: 同 opinion_fingerprint 仅留最高分
# - test_dedup_layered: 三层依次应用
```

### 通过判据

- ✅ 三层去重单测全部通过
- ✅ 实际刊期中无 URL 重复条目
- ✅ 同一 GitHub repo 同时被 X 转发 + Web 报道时，只保留评分最高一条

---

## 故障回退验证

**目标**：LLM 失败时，规则评分回退，刊期不阻断。

### 步骤

```bash
# 1. 临时配置无效 LLM 端点
export AIDAILY_LLM_BASE_URL=http://127.0.0.1:9999  # 不存在的端点

# 2. 删除明日刊期并重生
python -c "
import asyncio
from app.pipeline.generator import generate_issue
from datetime import datetime, timedelta
tomorrow = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=1)
r = asyncio.run(generate_issue(date=tomorrow))
print(f'status={r.status}')
"
# 期望：status='ready'（不阻断）

# 3. 查看一篇详情
curl -s "http://127.0.0.1:8000/api/v1/articles/<id>" | jq '.score.scoreSource'
# 期望："rule_fallback"
```

### 通过判据

- ✅ LLM 全部失败时刊期状态仍为 `ready`（FR-007a 容错）
- ✅ 所有文章 `scoreSource = 'rule_fallback'`
- ✅ `dimensionScores.authority` 仍按规则映射正确（D2 不依赖 LLM）
- ✅ `dimensionScores.timeliness` 仍按时间衰减正确（D3 不依赖 LLM）
- ✅ `dimensionScores.depth` 与 `expression` 取默认中位数（如 50）

---

## 性能预算验证

```bash
# 切换 styleMode 重渲染延迟（前端，浏览器 Performance API）
# 期望：≤ 500 ms (SC-003)

# 评分字段引入的 LLM token 成本
python -c "
import asyncio
from app.infra.llm import LLMClient
# 旧 prompt vs 新 prompt token 数对比
# 期望：新 prompt token ≤ 旧 × 1.3 (SC-004)
"
```

---

## 完整回归（继承 001）

```bash
cd backend && python -m pytest tests/unit/ tests/integration/ -q
# 期望：191 + N 个新测试全部通过（N = 本期新增测试数）
```
