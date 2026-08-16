# Phase 0 Research: 日报个性化（评分体系 + 数量 + 风格）

**Branch**: `002-daily-personalization` | **Date**: 2026-08-13

本文件记录本期 7 个关键决策的研究结论。所有决策基于 001 系统已落地的代码、`.specify/memory/constitution.md` v1.0.0、以及 clarify 阶段已确认的产品约束。

---

## D1: 综合评分维度与权重

**Decision**: 综合分 = `authority × 0.35 + depth × 0.25 + timeliness × 0.20 + expression × 0.20`，各维度 0–100 整数，综合分按加权后四舍五入取整。

**Rationale**:
- 来源权威占大头（35%）—— clarify 已确认三档权威等级是排序的核心信号，可信源应显著高于社区
- 内容深度（25%）次之—— 用户对"信息密度高"的文章有显式偏好（PRD 提及"30 分钟深度阅读"）
- 时效（20%）与表达（20%）平权—— 时效仅用于同分情况下提权新内容，表达力影响阅读体验但不主导
- 加权合成而非 LLM 直接给综合分：保证可解释性（用户能看到每个维度如何贡献），且能在 LLM 失败时规则回退

**Alternatives considered**:
- LLM 直接输出综合分（不分解维度）：被否，可解释性差，用户无法理解排序
- 等权重（25/25/25/25）：被否，会稀释权威等级的差异，社区内容更容易霸榜
- 用户可调权重：被否（v3 范围），本期固定保证 MVP 可测

**实现位置**: `backend/app/pipeline/scorer.py::compose_score(dimensions: dict) → int`

---

## D2: 来源权威等级的规则映射

**Decision**: 按 `sourceName` 字符串匹配映射到三档（每档对应 `authority` 维度基线分）：

| 等级 | authority 基线 | 命中规则（按 sourceName 包含关键字） |
|---|---|---|
| `official_blog` | 90 | `openai.com` / `anthropic.com` / `google.blog` / `deepmind.google` / `huggingface.co` / `research.google` |
| `authoritative_media` | 70 | `technologyreview.com` / `simonwillison.net` / `latent.space` / `stratechery.com` / `mittr` 等 |
| `community` | 50 | 默认值；X (`x.com/@*`) / Reddit (`reddit.com/r/*`) / GitHub (`github.com`) 全归此档 |

**Rationale**:
- 命中规则用 `sourceName` 而非 `src` 字段——`src=web` 同时包含官方博客和权威媒体，必须在 `sourceName` 层细分
- 基线分差距（90/70/50）足够显著：综合分中权威贡献 31.5 / 24.5 / 17.5，确保顶级官方博客能压过社区内容
- 默认 `community`（50）保证未知来源不会得到高分，鼓励扩展时显式登记

**Alternatives considered**:
- 用 LLM 判断（clarify Q1 备选 A）：被否，每篇额外一次 LLM 调用，违反 SC-004
- 用 X followers / GitHub stars（clarify Q1 备选 D）：被否，依赖外部 API，且冷启动不稳定
- 同平台内细分（如 @karpathy vs 普通账号）：被否（v3 范围），本期不做账号级权威

**实现位置**: `backend/app/pipeline/authority.py::classify_authority(source_name: str) → tuple[str, int]`

**配置位置**: 关键字列表硬编码在 authority.py 顶部常量（与 001 的 `CLASSIFY_KEYWORDS` 模式一致）；不在 settings 暴露（避免用户误配）。

---

## D3: 时效性维度计算

**Decision**: `timeliness = max(0, 100 - age_hours × 2)`，其中 `age_hours = (now - published_at).total_seconds() / 3600`。即 50 小时内时效满分线性衰减，超过 50 小时归零。

**Rationale**:
- 日刊场景下，"今日发布" vs "一周前发布"应有显著差异
- 50 小时窗口对应"今昨两天 + 缓冲"——超过 2 天的内容在日刊语境下意义锐减
- 线性衰减简单可测，避免指数衰减的浮点精度问题
- `published_at` 缺失时（部分 X/Reddit 帖子）：`timeliness = 50`（中性默认），不奖不罚

**Alternatives considered**:
- 阶梯衰减（24h/100、48h/80、7d/50、>7d/0）：被否，阶梯边界会产生"23h vs 25h"的不合理跳变
- 指数衰减：被否，过度工程，线性已足够
- 用 `createdAt`（入库时间）替代 `published_at`：被否，会让"刚采集的老内容"虚高

**实现位置**: `backend/app/pipeline/scorer.py::compute_timeliness(published_at: str) → int`

---

## D4: LLM Prompt 扩展（评分 + 去重字段一次产出）

**Decision**: 在 `backend/app/infra/llm.py::SYSTEM_PROMPT` 中追加以下字段到现有 JSON schema：

```
- composite_score (int): 综合评分（保留位，由后端按权重合成；LLM 仅输出维度分，不输出综合分）
- dimension_scores (object): {"authority": int, "depth": int, "timeliness": int, "expression": int}
- topic_id (string): 文章所述事件的简短标识符（如 "gpt5-release"、"anthropic-claude-opus-45"）；同事件跨源相同
- opinion_fingerprint (string): 观点特征的简短语（如 "official-announcement"、"critical-analysis"、"translation-reprint"）；同质化高度相似
```

实际 LLM 输出 `dimension_scores.authority` 会被后端**覆盖**为规则映射值（D2 决策），确保权威等级始终由系统规则决定。LLM 只产出 `depth / timeliness / expression` 三个维度的内容性判断，加上 `topic_id` / `opinion_fingerprint` 两个去重信号。

**Rationale**:
- 单次 LLM 调用产出所有字段，满足 SC-004（不增加 LLM 调用次数）
- `topic_id` 用自由文本而非 hash：LLM 已具备"识别同事件"的能力，自由文本 + 后端规范化（小写 + 去空格）即可聚类
- `opinion_fingerprint` 同理，让 LLM 输出"观点类型"标签，比 hash 简单
- LLM 不输出综合分：保证权重调整不需要重跑 LLM（成本可控）

**Alternatives considered**:
- 独立调用 LLM 做评分：被否，违反 SC-004
- 用 embedding 做 opinion_fingerprint：被否，需要额外模型，本期不做
- 让 LLM 直接给 topic_id 用 hash：被否，LLM 不可靠地输出 hash，自由文本 + 后端归一化更稳

**实现位置**: `backend/app/infra/llm.py::SYSTEM_PROMPT`（追加字段说明）；`SummaryResult` dataclass（追加字段）；`_parse_summary_response`（解析）；`_ensure_chinese` 检查范围扩展到 dimension_scores 不适用（数值不翻译）

---

## D5: 三层全局去重算法

**Decision**: 在 `generator.generate_issue()` 中，summarize 全部候选文章池后、截取 top-N 之前，依次执行三层去重：

```python
def dedup_candidates(items: list[ScoredItem]) -> list[ScoredItem]:
    # Layer 1: URL 主键（同 sourceUrl 仅保留 composite_score 最高）
    items = _dedup_by_url(items)
    # Layer 2: 同事件/主题（同 topic_id 仅保留 composite_score × 跨源出现次数 最高）
    items = _dedup_by_topic(items)
    # Layer 3: 观点同质化（同 opinion_fingerprint 仅保留 composite_score 最高）
    items = _dedup_by_opinion(items)
    return items
```

**Layer 1 (URL)**：以 `_normalize_url(sourceUrl)` 为 key（沿用 001 collector 已有的 normalize 函数），同 key 保留 `composite_score` 最高；同分按 `publishedAt` 新者优先。

**Layer 2 (topic_id)**：以 `topic_id.lower().strip()` 为 key；同 key 计算每条的 `popularity = composite_score × 该 topic 在 items 中出现次数`；保留 `popularity` 最高。空 `topic_id`（LLM 未输出）跳过本层。

**Layer 3 (opinion_fingerprint)**：以 `opinion_fingerprint.lower().strip()` 为 key；同 key 保留 `composite_score` 最高。空 fingerprint 跳过本层。

**Rationale**:
- 顺序：URL → topic → opinion。URL 最严格（绝对相同），topic 中等（同事件不同角度），opinion 最宽松（同观点不同事件）—— 严格在前避免误杀
- Layer 2 用"热度 × 评分"而非纯评分：clarify Q2 已明确"保留传播热度最高"，体现"跨多源报道 = 高价值"的产品判断
- 空 `topic_id` 跳过而非归并为 ""：避免 LLM 偶发漏字段导致误杀
- 全局去重而非按 src 分组：spec FR-007a 明确"全局唯一"

**Alternatives considered**:
- 标题相似度（>85% Jaccard）：被否，澄清 Q2 已选 LLM 输出 topic_id，标题相似度仅作 fallback
- embedding 聚类：被否，过度工程
- 仅 Layer 1（URL 主键）：被否，无法应对"同事件不同 URL"的高频场景

**实现位置**: `backend/app/pipeline/dedup.py::dedup_candidates(items) → items`；三个内部 helper `_dedup_by_url / _dedup_by_topic / _dedup_by_opinion`，每个 ≤ 30 行。

---

## D6: `daily_count` 截取时机与同分处理

**Decision**: 在三层去重后，按 `composite_score DESC, publishedAt DESC` 稳定排序，截取前 `N = settings.daily_count` 条。候选池不足 N 时全取（不补齐、不报错）。

**Rationale**:
- 排序键双维度：评分优先，同分时新内容优先（与 P1 US1 acceptance #3 一致）
- 不补齐：用户配置 50 但只有 30 篇候选，强行凑数会引入低质量内容
- 截取发生在 generator 阶段（生成时持久化 top-N 为 issue.articles），不在阅读期动态截取——保证阅读期响应一致（用户切换筛选不重新截取，与 US2 acceptance #4 一致）

**Alternatives considered**:
- 阅读期动态截取：被否，用户切 src 筛选后看到"被截掉的内容"，体验错乱
- 截取后随机洗牌：被否，破坏评分的排序价值

**实现位置**: `backend/app/pipeline/generator.py::_truncate_top_n(items, n) → items`（在 dedup 之后调用）

---

## D7: `style_mode` 字段白名单实现

**Decision**: 在前端 `frontend/index.html` 定义三个常量函数，控制索引列表行字段与详情页字段：

```javascript
const STYLE_FIELDS = {
  concise: {
    list: ['title', 'sourceName', 'compositeScore'],
    detail: ['title', 'summary', 'sourceUrl']
  },
  standard: {
    list: ['title', 'excerpt', 'type', 'src', 'time', 'readingMinutes', 'compositeScore'],
    detail: ['title', 'excerpt', 'lede', 'body', 'points', 'sourceUrl', 'readingMinutes']
  },
  detailed: {
    list: ['title', 'excerpt', 'type', 'src', 'time', 'readingMinutes', 'compositeScore', 'dimensionScores'],
    detail: ['title', 'excerpt', 'lede', 'body', 'points', 'quote', 'sourceUrl', 'readingMinutes', 'dimensionScores', 'authorityTier']
  }
};

function getFields(styleMode, view) {
  return STYLE_FIELDS[styleMode][view];  // view: 'list' | 'detail'
}
```

**Rationale**:
- 字段白名单是产品决策（spec FR-009 已细化），用常量字典而非动态配置
- 渲染时按 `getFields(currentStyle, currentView).includes(field)` 决定是否渲染——所有现有渲染函数加一层守卫
- 临时切换（阅读器顶部按钮）：仅修改 `state.currentStyle`，不持久化；刷新页面回退到 settings.styleMode（US3 acceptance #5）

**Alternatives considered**:
- 后端按 style_mode 过滤字段返回：被否，违反"前端控制展示"原则，且会让响应缓存复杂化
- 三套独立组件渲染：被否，代码重复 3 倍，违反 DRY
- 用户自定义白名单：被否（v3 范围）

**实现位置**: `frontend/index.html` 顶部常量 + 各渲染函数（`renderList` / `renderReader`）加字段过滤守卫

---

## D8: 数据库迁移与回滚

**Decision**: Alembic migration `003_personalization.py` 包含：
1. 新建 `article_scores` 表（FK 到 articles.id，1:1）
2. `settings` 表新增 `daily_count INT DEFAULT 30 NOT NULL` 与 `style_mode VARCHAR(16) DEFAULT 'standard' NOT NULL` 两列
3. downgrade：drop article_scores；drop settings 两列

**Rationale**:
- 不在 articles 表直接加 score 列：评分字段较多（4 维 + 综合 + authority_tier + topic_id + opinion_fingerprint + score_source），单独表更清晰，且 1:1 关系简单
- settings 加列而非新表：daily_count/style_mode 是 singleton 偏好的简单字段，沿用现有 settings 表
- DEFAULT 值：保证迁移期间现有数据不需要回填

**实现位置**: `backend/migrations/versions/003_personalization.py`

---

## 总结

8 个决策覆盖：评分维度与权重（D1）、权威映射（D2）、时效算法（D3）、LLM prompt 扩展（D4）、去重算法（D5）、截取时机（D6）、字段白名单（D7）、迁移（D8）。所有决策均与 constitution v1.0.0 对齐，无 NEEDS CLARIFICATION 残留。
