# 领域词汇表（CONTEXT.md）

AI 日报系统的领域语言。架构讨论与命名以此为准。

## 刊期（Issue）

一次日报生成周期的聚合根。ID 为日期 `YYYYMMDD`。状态机：`generating → ready | failed`。
每日一期，重生成 = 删除刊期及全部条目后重新装配。

## 条目（Article）

刊期内的一条资讯，ID 为 `{issue_id}-{index:04d}`，index 是生成期的展示序号。
四种类型（agent / self_improve / open_source / tools）、四种来源（x / github / reddit / web）。

## 必读（mustRead）

刊期的编辑推荐 Top-N（N=3，`generator.MUST_READ_TOP_N`）。生成期由持久化序号判定并
写入 `articles.is_must_read` 列——这是唯一事实源，读路径一律读列，任何一方都不得从
ID 后缀或列表位置重算（历史上有过后缀解析实现，已于 006 迁移时废除）。

## 条目装配器（article assembly）

`app/services/article_assembly.py`——ORM 行到 API 模型（列表项/详情+score 子对象）的
唯一转换点。字段名与 camelCase 键名重映射只存在于这里；新增字段只改装配器与契约文档。

## 候选（Candidate）与准入（Admission）

采集-摘要后的条目进入排序前称候选；综合分低于 `ADMISSION_FLOOR`（45）的候选被拒收。
通过者经三层去重（URL → 主题 → 观点）与类型多样性配额截断，成为刊期条目。

## 摘要器（Summarizer）

`app.pipeline.summarizer.summarize_item`——摘要策略+机制的归属模块（重试、预算、评分
增强、规则回退）。LLMClient（`app/infra/llm.py`）是纯传输 adapter：提示词、解析与
中文校验在其内，但不做策略决策。

## 评分（Score）

条目的 5 维评分（authority/depth/engagement/timeliness/expression，0-100）加综合分，
1:1 存于 `article_scores`。engagement 对 GitHub star 做 log10 压缩，无信号源取中性 50。
