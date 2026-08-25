# 005 — 跨期去重 + commentary 观点类型

Triage: ready-for-agent
Date: 2026-08-18
Status: approved

## Problem Statement

两个内容质量问题，均有近两期（20260817/20260818）实证：

1. **跨期重复**：读者连刷多期看到同一条资讯。LeCun-Anthropic 争论连刷两天。根因：三层去重（URL→主题→观点）只作用于当期候选内部，而采集窗口 72h 让昨天的热帖今天仍是"新鲜"候选，跨期无任何拦截。
2. **类型兜底污染 tools 桶**：近两期 tools 桶 8 条中 6 条是观点帖/课程/长文（LeCun 观点 ×3、Karpathy 课程、上下文工程等）。根因双层：摘要提示词明示"不确定优先选 tools"（llm.py SYSTEM_PROMPT），关键词规则硬兜底也是 TOOLS（collector.py classify_type）。tools 成为杂物抽屉，类型筛选与多样性配额失去语义。

## Solution

1. 生成期装配前增加**跨期排除层**：查询最近 3 期已刊登条目的归一化 URL 与规范化 topic_id，硬性丢弃命中候选，再进当期三层去重。
2. 新增第五类型 **commentary（观点时评）** 并让它兼任兜底类：观点/评论/争议/纯新闻/行业事件/不确定项归 commentary；tools 回归纯工具（工具/教程/实践/资源）。规则侧硬兜底改为来源感知（GITHUB→open_source，X/REDDIT/WEB→commentary），tools 不再是任何路径的兜底。

## User Stories

1. 作为日报读者，我不想在连续几期里看到同一条资讯，这样每天的刊期都值得打开。
2. 作为日报读者，我想用「观点时评」筛选器只看 KOL 观点与行业评论，这样能快速把握舆论动向。
3. 作为日报读者，我想在「工具与效率」筛选器里只看到工具/教程/实践内容，这样筛选结果符合标签语义。
4. 作为日报读者，我想让观点帖不再挤占 tools 的类型多样性配额，这样真正的工具条目不被截断出局。
5. 作为日报读者，我想让 GitHub 仓库条目默认正确归类为开源项目，这样即使关键词没命中也不会错标。
6. 作为设置过类型开关的老用户，我想升级后自动看到新增的「观点时评」内容，这样不会误以为条目丢失。
7. 作为运营者，我想在日志里看到跨期排除的计数，这样能验证去重层在工作而非静默失效。
8. 作为运营者，我想让同一热点的换 URL 报道（博客原文 vs HN 讨论）也被跨期拦截，这样换链接刷屏无效。
9. 作为运营者，我想让重生成流程不受跨期排除影响，这样修正性重生成行为不变。

## Implementation Decisions

### Part 1 — 跨期去重

- **匹配键**：归一化 source_url（复用 `_normalize_url`）+ 规范化 topic_id（复用 `_norm_key` / `_canonicalize_topics`，精确相等才排除；跨期不做模糊匹配）。opinion_fingerprint 不参与跨期（其语义是当期内同观点合并，跨期会误杀后续进展）。
- **回看窗口**：最近 3 期（issue_id 日期序）。与 72h 采集窗口数学对齐：一条帖子从进入采集窗口到滑出最多跨 3 期，任何一期刊登过即排除后续各期；第 4 期起它已不在采集结果中，自然闭环，无多余误杀。
- **排除策略**：硬性丢弃，无分数豁免。分数跨期不可比（不同候选池），豁免机制会沦为随机放行。日报语义是"今天的新信息"。
- **三层分工**：
  - `issue_repository` 新增 `recent_published_keys(session, issues=3)` → 返回已刊登的 URL 集合与 topic_id 集合（JOIN articles 与 article_scores，两者均已索引，零 schema 变更）。
  - `dedup.py` 新增纯函数 `exclude_published(candidates, published)` → 命中即剔，日志记录排除计数。
  - `generator._select_for_issue` 在当期三层去重**之前**调用（先排除减少后续层工作量；顺序对结果无影响）。
- **重生成安全**：重生成 = 先删本期再装配，本期行已不存在于回看查询结果中，不会自锁（依赖既有删除语义，无新增逻辑）。

### Part 2 — commentary 类型

- **枚举**：`TypeKey` 增加 `COMMENTARY = "commentary"`。articles.type 为字符串列，零迁移。
- **语义边界**：
  - commentary = 观点 / 评论 / 争议 / 人物言论 / 行业讨论 / 纯新闻 / 行业事件 / 安全研究 / 不确定项（**兜底类**）。
  - tools = 工具 / 教程 / 实用资源 / 技术实践，**不再是任何兜底路径的产物**，只能由关键词或 LLM 显式给出。
  - agent / self_improve / open_source 语义不变。
- **提示词改写**（llm.py SYSTEM_PROMPT 的 type 判定段）："若不确定优先选 tools" 改为"若不确定优先选 commentary"；原"LeCun 评论归 tools"反例改归 commentary；tools 条目描述收紧为纯工具/教程/实践。
- **规则兜底来源感知**（collector.py classify_type）：关键词表照旧前置命中；未命中时按 `sourceKey` 兜底——GITHUB→open_source，X/REDDIT/WEB→commentary。`suggestedType` 由此产生，`effective_type` 的 rule 路径随动，最后一道硬兜底（suggestedType 为 None 时）同步改为 commentary。
- **设置缺键合并**（generator 设置读取处）：存量设置 JSON 的 types/sources 字典缺新键时读出补 True（新类型默认开），否则 commentary 候选会被类型过滤全数丢弃（generator._filter_by_settings 的 allow-list 语义）。
- **前端**：标签「观点时评」，chips 排末位（agent / self-improve / open-source / tools / commentary 顺序不变四类位置）；state.js 键名映射、actions.js toggles、chips 渲染同步。
- **兼容**：历史已入库条目不回填重分类（成本高收益低，筛选只影响阅读过滤不影响正确性）。
- **配额**：truncate_diverse 的 max_share 通用逻辑无需改动，第五类自动参与。

## Testing Decisions

好测试只测外部行为（公开函数的输入输出），不测内部实现细节。网络与 DB 全 mock。

- `exclude_published`（新接缝，纯函数）：命中 URL 剔除 / 命中 topic_id（含前缀合并等价）剔除 / 未命中保留 / published 集合为空时全通过 / 排除计数日志。先例：tests/unit/test_dedup.py 既有三层测试风格。
- `recent_published_keys`：repository 层测试，mock session 或走测试 DB fixture，验证 3 期窗口边界（第 4 期不查）与 JOIN 取键。先例：issue_repository 既有测试。
- `classify_type`：关键词命中优先级不变；GITHUB 未命中→open_source；X/REDDIT/WEB 未命中→commentary；无任何路径产出 tools 兜底。先例：test_collector.py classify 测试。
- `effective_type`：llm_type 有效优先；llm_type 无效时走来源感知 suggestedType；全缺失时兜底 commentary。
- 设置缺键合并：存量 dict 无 commentary 键 → 读出含 commentary=True。
- 提示词与前端 chips 无自动化测试（与仓库现状一致），验收靠真机重生成观察类型分布。

## Out of Scope

- opinion_fingerprint 参与跨期去重（观察 topic_id 层效果后再议）。
- 历史条目类型回填重分类。
- 跨期"重大进展"逃生门（分数豁免）。
- 第六类及类型更名/合并。
- LLM topic_id 跨天稳定性专项治理（跨期 topic 匹配已按"宁可漏杀"设计）。

## Further Notes

- 决策链留档：commentary 兼任兜底（候选 A"只收观点、tools 继续兜底"被否，理由：杂物抽屉平移是伪解）；来源感知规则兜底；3 期回看与 72h 窗口对齐。
- tools 桶污染实证样本（20260817/18）：LeCun 驳 Anthropic ×3、Karpathy GPT 课程、上下文工程实战、OpenAI 产品负责人访谈——6/8 非工具内容。
- 跨期重复实证：LeCun-Anthropic 争论 20260817 与 20260818 连续两期出现。
- 老设置自锁风险来源：_filter_by_settings 在 allow-list ≠ 全枚举时逐条过滤，缺键即全杀该类型候选——任何未来新增类型都要走缺键合并路径。
