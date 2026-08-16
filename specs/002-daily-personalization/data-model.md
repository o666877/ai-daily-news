# Phase 1 Data Model: 日报个性化（评分体系 + 数量 + 风格）

**Branch**: `002-daily-personalization` | **Date**: 2026-08-13

本文档定义本期扩展的实体与字段。继承 001 系统的现有表（articles / daily_issues / settings / share_cards），仅描述本期**新增或修改**的部分。

---

## 1. 新增表：`article_scores`

每篇文章的评分快照（综合分 + 4 维子分 + 权威等级 + 去重信号）。与 `articles` 1:1 关联。

### Schema

| 列名 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `article_id` | VARCHAR(64) | PK, FK → articles.id ON DELETE CASCADE | 关联文章 |
| `composite_score` | INTEGER | NOT NULL, CHECK (0 ≤ value ≤ 100) | 综合评分（按 D1 权重合成） |
| `dim_authority` | INTEGER | NOT NULL, CHECK (0 ≤ value ≤ 100) | 来源权威性子分（D2 规则映射基线） |
| `dim_depth` | INTEGER | NOT NULL, CHECK (0 ≤ value ≤ 100) | 内容深度子分（LLM 判断） |
| `dim_timeliness` | INTEGER | NOT NULL, CHECK (0 ≤ value ≤ 100) | 时效性子分（D3 时间衰减） |
| `dim_expression` | INTEGER | NOT NULL, CHECK (0 ≤ value ≤ 100) | 表达力子分（LLM 判断） |
| `authority_tier` | VARCHAR(32) | NOT NULL, CHECK in ('official_blog','authoritative_media','community') | 来源权威等级（D2 三档） |
| `topic_id` | VARCHAR(128) | NULL | 文章所述事件标识（LLM 输出，已 normalize 小写去空格） |
| `opinion_fingerprint` | VARCHAR(128) | NULL | 观点特征标签（LLM 输出，已 normalize） |
| `score_source` | VARCHAR(16) | NOT NULL, DEFAULT 'llm', CHECK in ('llm','rule_fallback') | 评分来源（LLM 成功 / 规则回退） |
| `computed_at` | DATETIME | NOT NULL | 评分计算时间戳（UTC） |

### 索引

| 名 | 列 | 用途 |
|---|---|---|
| `ix_article_scores_composite_score` | `composite_score DESC` | generator 截取 top-N 加速 |
| `ix_article_scores_topic_id` | `topic_id` | dedup Layer 2 聚合 |
| `ix_article_scores_opinion_fingerprint` | `opinion_fingerprint` | dedup Layer 3 聚合 |

### 关系

- `ArticleScoreORM.article_id` → `articles.id` (1:1)
- 删除 article 自动级联删除 score（ON DELETE CASCADE）

### ORM

`backend/app/models/article_score.py::ArticleScoreORM`

---

## 2. 扩展 `articles` 表（响应层，不修改表结构）

`articles` 表本身**不加列**——所有评分字段通过 `article_scores` 关联表读取。但 `ArticleORM` 模型添加一个 `score` relationship 方便查询：

```python
class ArticleORM(Base):
    # ... existing fields unchanged ...
    score: Mapped["ArticleScoreORM | None"] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )
```

**为何不直接加列**：评分字段较多（11 个），单独表更清晰；且避免 001 系统的 articles 表 schema 变化（保持向后兼容）。

---

## 3. 扩展 `settings` 表

新增 2 列：

| 列名 | 类型 | 约束 | 默认值 | 说明 |
|---|---|---|---|---|
| `daily_count` | INTEGER | NOT NULL, CHECK in (10, 20, 30, 40, 50) | 30 | 每日条目数量上限 |
| `style_mode` | VARCHAR(16) | NOT NULL, CHECK in ('concise', 'standard', 'detailed') | 'standard' | 阅读风格档位 |

### ORM 扩展

`backend/app/models/settings.py::SettingsORM` 新增 2 列。

### Pydantic 模型扩展

`SettingsOut`、`SettingsIn` 新增字段（camelCase 通过 CamelModel 自动转换）：

```python
class SettingsOut(CamelModel):
    # existing fields...
    dailyCount: int = Field(ge=10, le=50)  # 实际约束：Literal[10,20,30,40,50]
    styleMode: Literal['concise', 'standard', 'detailed']

class SettingsIn(CamelModel):
    # existing fields...
    dailyCount: Literal[10, 20, 30, 40, 50]
    styleMode: Literal['concise', 'standard', 'detailed']
```

### 校验规则

- `dailyCount` 必须是 `{10, 20, 30, 40, 50}` 之一；非整数或越界 → `1005` 错误（沿用现有 settings 校验错误码）
- `styleMode` 必须是 `{concise, standard, detailed}` 之一；其他 → `1005`
- 全量覆盖语义保持（与 001 一致）：缺失字段视为校验失败，不部分更新

---

## 4. 实体关系图

```
┌──────────────┐       1:1       ┌──────────────────┐
│   articles   │─────────────────│  article_scores  │
│──────────────│                 │──────────────────│
│ id (PK)      │                 │ article_id (PK,  │
│ issue_id     │                 │   FK)            │
│ type         │                 │ composite_score  │
│ src          │                 │ dim_authority    │
│ title        │                 │ dim_depth        │
│ excerpt      │                 │ dim_timeliness   │
│ lede         │                 │ dim_expression   │
│ summary      │                 │ authority_tier   │
│ body         │                 │ topic_id         │
│ quote        │                 │ opinion_fp       │
│ points       │                 │ score_source     │
│ time         │                 │ computed_at      │
│ source_url   │                 └──────────────────┘
│ source_name  │
│ reading_min  │     ┌──────────────┐
│ published_at │     │   settings   │
└──────────────┘     │──────────────│
      ↑               │ id (PK, =1)  │
      │               │ sources JSON │
      N:1             │ types JSON   │
                     │ daily_push   │
┌──────────────┐     │ daily_count  │ ← 新增
│ daily_issues │     │ style_mode   │ ← 新增
│──────────────│     │ updated_at   │
│ id (PK)      │     └──────────────┘
│ date         │
│ edition      │
│ status       │
│ generated_at │
│ filters_appl │
└──────────────┘
```

---

## 5. 数据生命周期

| 阶段 | 写入 | 读取 | 删除 |
|---|---|---|---|
| summarizer 完成单篇 | 写 `article_scores` 一行（含 dim_*/topic_id/opinion_fp） | — | — |
| LLM 失败回退 | 写 `article_scores` 一行（`score_source='rule_fallback'`，dim_* 由 scorer 计算） | — | — |
| generator 去重 + 截取 | — | 读全部候选 + scores，做去重和 top-N | — |
| 用户阅读详情 | — | 读 article + score（JOIN） | — |
| 删除当日 issue（重生成场景） | — | — | 级联删除 articles → 级联删除 article_scores |
| 用户修改 daily_count/style_mode | UPDATE settings 两列 | — | — |

---

## 6. 校验规则汇总

| 字段 | 校验规则 | 失败错误码 |
|---|---|---|
| `composite_score` | 0 ≤ int ≤ 100 | DB CHECK（理论不会失败） |
| `dim_*` (4 个) | 0 ≤ int ≤ 100 | DB CHECK |
| `authority_tier` | ∈ {official_blog, authoritative_media, community} | DB CHECK |
| `topic_id` | str ≤ 128 chars（LLM 输出后 normalize） | 后端 silently truncate |
| `opinion_fingerprint` | str ≤ 128 chars | 后端 silently truncate |
| `score_source` | ∈ {llm, rule_fallback} | DB CHECK |
| `daily_count` | ∈ {10, 20, 30, 40, 50} | 1005 (settings PUT) |
| `style_mode` | ∈ {concise, standard, detailed} | 1005 (settings PUT) |

---

## 7. 迁移脚本

`backend/migrations/versions/003_personalization.py`：

**Upgrade**:
1. CREATE TABLE article_scores（含所有列 + 索引 + CHECK 约束）
2. ALTER TABLE settings ADD COLUMN daily_count ...
3. ALTER TABLE settings ADD COLUMN style_mode ...

**Downgrade**:
1. DROP TABLE article_scores
2. ALTER TABLE settings DROP COLUMN daily_count
3. ALTER TABLE settings DROP COLUMN style_mode

**Data backfill**: 无需——新列有 DEFAULT，新表为空，现有 articles 在迁移后没有 score（直到下次重生成刊期时填充）。

---

## 8. 与 001 系统的兼容性

- `articles` 表 schema 不变（向后兼容 001 所有查询）
- `settings` 表新增列有 DEFAULT（现有读操作仍工作；现有写操作需扩展）
- `daily_issues` 表不变
- 新增表 `article_scores` 是纯增量
- 所有 001 的 9 个 REST 接口 URL 不变；002 仅扩展部分响应字段（详见 contracts/）
