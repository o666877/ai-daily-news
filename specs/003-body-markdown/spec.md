# 002 — 正文 Markdown 化（body: string[] → string）

> Triage: `ready-for-agent`

## Problem Statement

读者在阅读器里阅读条目正文时，正文是纯文本段落的堆砌：关键术语、代码/命令、相关项目链接全部以同权重纯文本呈现，无法扫读。对于 AI 日报的核心场景——"每天 5 分钟跟上 AI"——正文中该被强调的实体名（模型名、项目名）和该被等宽展示的命令/代码与普通叙述文字混在一起，信息密度高但可读性差，读者需要逐字阅读才能提取重点。

## Solution

条目正文（body）从字符串数组改为**单个 markdown 字符串**。生成端（LLM 摘要提示词）主动引导使用精简 markdown 语法子集（粗体强调关键术语、行内代码展示命令/标识符、链接指向相关项目）；API 直接返回 markdown 原文；前端引入本地 vendored 的 marked + DOMPurify，在阅读器内安全渲染为 HTML。存量数据在 Alembic 迁移中无损转换（纯文本天然是合法 markdown）。

## User Stories

1. 作为读者，我想看到正文中的关键术语（模型名、项目名、公司名）以粗体呈现，这样我扫读时能立即抓住这条新闻的主角是谁。
2. 作为读者，我想看到命令行、API 名、代码标识符以等宽行内代码呈现，这样我能一眼区分"这是要敲的东西"和"这是叙述"。
3. 作为读者，我想在正文中直接点击相关项目/文档的链接，这样发现感兴趣的内容时不用先复制名字再去搜索。
4. 作为读者，我想让正文中的列表要点以真正的列表样式渲染，这样多项特性/要点不再挤在一个段落里。
5. 作为读者，我想让正文中的引用以引用块样式呈现，这样原话引用和编辑转述在视觉上有区分。
6. 作为读者，我希望 markdown 渲染失败或正文为空时仍能看到可读的降级文本，这样任何生成异常都不会让我面对空白阅读区。
7. 作为读者，我希望正文中出现的链接在新标签页打开并带 noopener 保护，这样我不会被外部站点劫持当前页。
8. 作为读者，我不希望正文渲染出任何脚本或注入内容，这样阅读行为永远是安全的。
9. 作为 API 消费者，我想拿到 markdown 原文而非预渲染 HTML，这样我可以按自己的方式消费正文（终端、RSS、自建渲染）。
10. 作为系统运维者，我希望存量刊期的正文在升级后无需重新生成即可正常显示，这样升级不产生额外 LLM 成本。
11. 作为系统运维者，我希望 LLM 偶尔回吐旧格式（body 为数组或 null）时管线仍能正常入库，这样单次 LLM 格式抖动不会导致条目丢失或刊期失败。
12. 作为编辑（提示词维护者），我想在提示词中明确约束允许的语法子集并禁止 HTML/标题/表格，这样渲染结果风格可控且攻击面最小。
13. 作为阅读密度偏好"简洁"的用户，我的视图不渲染正文（仅标题+一句话总结+原文链接），这次改造不应改变我的视图行为。
14. 作为阅读密度偏好"标准/详细"的用户，我想在我的详情视图中看到完整 markdown 渲染效果，包括粗体、行内代码和链接。
15. 作为开发者，我想让规则回退路径（LLM 不可用时的 `_rule_fallback_summary`）产出与 LLM 路径相同类型的数据，这样两条路径在下游完全同构。
16. 作为开发者，我想让 API 契约文档与实际返回同步更新，这样前后端和任何消费方对 body 类型没有歧义。

## Implementation Decisions

### 数据模型与迁移

- `ArticleORM.body`：JSON 列（`list[str]`）→ TEXT 列（单个 markdown 字符串）。
- 新增 Alembic 迁移（编号 005），迁移中把存量 `list[str]` 以 `"\n\n"` join 转为 markdown 字符串——纯文本是无格式 markdown，转换零损失。
- 读路径不保留任何"数组还是字符串"的兼容分支（兼容只存在于迁移和 LLM 解析边界两处）。

### LLM 生成端

- 摘要提示词中 body 字段定义改为"单个 markdown 字符串"，并**主动引导**使用：关键术语/项目名用粗体、代码/命令用行内代码、提及相关项目时可附链接、正文 2-4 段。
- 明确约束语法子集：段落、粗体、行内代码、链接、无序列表、引用。**禁止**：标题（`#`）、表格、代码块（```）、任何 HTML。
- LLM 解析边界（`_parse_summary_response`）容错：接受 `string` 或 `array`（数组时 `"\n\n"` join）、`null`/缺失 → 空串。下游链路从此只见 `string`。这是对不可控外部输出的边界校验，不是长期双轨。
- 规则回退摘要路径同步改为产出 md 字符串。

### API 契约

- 破坏式变更：`GET /articles/{id}` 的 `body` 字段从 `string[]` 改为 `string`。不做版本化、不加兼容双字段——本项目唯一消费方是自家前端。
- 契约文档与 OpenAPI 示例同步更新。
- excerpt / lede / summary / quote / points 保持现有纯文本结构，不参与 markdown 化。

### 前端渲染

- 引入本地 vendored 的 `marked.min.js` 与 `DOMPurify.min.js`（无 CDN 依赖、版本锁定、离线可用），随静态资源一起由后端提供。
- 渲染顺序：`marked.parse(md)` → `DOMPurify.sanitize(html)`。
- DOMPurify 白名单收紧到子集对应的标签：`p / strong / em / code / a / ul / ol / li / blockquote / br`；其余（含 `img / h1-h6 / table / script / iframe` 等）一律剥除。
- 渲染后的 `<a>` 统一注入 `target="_blank" rel="noopener noreferrer"`（DOMPurify hook）。
- marked 抛异常或正文为空时降级为转义纯文本展示，绝不让阅读区空白。
- 样式：复用现有 `.article-body` 的 ul/li/blockquote 样式，补充 `code`（等宽、底色）与 `strong` 的样式 token。

### 阅读密度交互

- body 仅出现在 standard / detailed 档的详情字段集里；concise 档不渲染正文——此行为不变。

## Testing Decisions

好测试只断言外部可见行为（HTTP 响应形状、渲染后的 DOM），不断言实现细节。接缝共 3 个后端 + 1 个前端手工验证面，复用既有测试文件与模式：

1. **LLM 解析边界**（既有接缝：`tests/unit/test_llm.py` 直接调 `_parse_summary_response`）：md 字符串透传；旧数组格式被 join 容错；null/缺失 → 空串。仿照该文件中现有的 SummaryResult 解析测试。
2. **HTTP API `/articles/{id}`**（既有接缝，最高验证面：`tests/integration/test_articles_detail.py` 走完整 FastAPI + aiosqlite）：断言 `body` 是 `string` 且非空；契约示例更新后文档测试同步。生成链路（提示词约束→解析→存储→返回）在此接缝隐式覆盖。
3. **Alembic 迁移转换**（新接缝，位于迁移内部）：构造含 `list[str]` body 的最小旧库 fixture → 执行迁移 → 断言 body 列为 join 后的 TEXT 字符串。这是唯一新增接缝，因数据转换逻辑只能在此验证。
4. **前端渲染**（无 JS 测试基建，不新建接缝）：用浏览器（chrome-devtools MCP）真实验证——markdown 元素渲染正确、XSS payload（`<script>`、`onerror` 属性、`javascript:` 链接）被 DOMPurify 剥除、链接带 `_blank + noopener`、空 body 降级展示。

## Out of Scope

- excerpt / lede / summary / quote / points 的富文本化。
- 标题（`#`）、表格、代码块（```）、图片等更重语法的支持（若未来开放，需同步扩 DOMPurify 白名单与样式）。
- API 版本化或 body 双字段兼容输出。
- 分享卡片内容格式（不消费 body 字段，本次不受影响）。
- 前端 JS 单元测试基建搭建。
- readingMinutes 计算、详情渲染竞态等既有 P2 遗留。

## Further Notes

- 迁移编号顺延为 005（001-004 已占用）。
- 测试基线现状：374 通过 / 5 个既有环境性失败（web collector 网络类），与本 spec 无关，不阻塞。
- conftest 与多处以 `body=["..."]` 构造 fixture 的测试需同步改为字符串，属机械性改动。
- vendored 库文件体积约 50KB（marked ~40KB + DOMPurify ~20KB min），对单文件前端的加载影响可忽略。
