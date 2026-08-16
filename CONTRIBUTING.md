# Contributing to AI Daily News

感谢你考虑为 AI 日报系统贡献代码！这份指南说明本地开发流程、commit 约定与 PR 流程。

---

## 开发环境搭建

### 前置要求

- Python 3.11.9+
- Git 2.30+
- （可选）Docker + Docker Compose：用于端到端联调
- （可选）Node.js 18+：仅前端样式调试需要（前端零构建步骤，vendor JS 已 vendored）

### 步骤

```bash
# 1. Fork → clone 你的 fork
git clone https://github.com/<your-username>/ai-daily-news.git
cd ai-daily-news

# 2. 添加 upstream
git remote add upstream https://github.com/your-org/ai-daily-news.git

# 3. 创建虚拟环境
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 4. 安装开发依赖（含 pytest, ruff, mypy, respx）
cd backend
pip install -e ".[dev]"

# 5. 配置环境变量
cp ../.env.example ../.env
# 编辑 .env，至少填入 AIDAILY_LLM_API_KEY=test-key

# 6. 初始化数据库
alembic upgrade head

# 7. 启动开发服务器（热重载）
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 8. 验证
pytest --cov=app --cov-fail-under=80 --ignore=tests/e2e
ruff check backend/
mypy backend/app
```

### 安装 Playwright（如需运行 E2E）

```bash
pip install pytest-playwright
python -m playwright install chromium
```

---

## Commit 约定

遵循 [Conventional Commits](https://www.conventionalcommits.org/) 规范：

```
<type>: <description>

<optional body>
<optional footer>
```

### Type 一览

| Type | 用途 |
|---|---|
| `feat` | 新功能（用户可见） |
| `fix` | Bug 修复 |
| `refactor` | 不改变行为的重构 |
| `docs` | 文档变更（README、CONTRACTS、注释） |
| `test` | 新增 / 修改测试 |
| `chore` | 构建、依赖、配置等杂项 |
| `perf` | 性能优化 |
| `ci` | CI / CD 配置变更 |
| `build` | 构建系统或外部依赖变更 |
| `revert` | 回滚某次提交 |

### 写作要求

- **祈使句、现在时**：`Add healthz endpoint`（不是 `Added`）
- **首行 ≤ 72 字符**；详情放 body
- **body 解释 "为什么"**，而非 "做了什么"（diff 已经说明了 what）
- **关联 issue**：`Closes #123` / `Refs #456`

### 示例

```
feat: add /daily/today endpoint with summary badges

Returns today's issue (status, edition, filtersApplied), summary
(byType/bySource count maps), and article index (7 fields each).
Frontend reads this on first paint; no separate /articles call needed.

Closes #21
```

```
fix: handle empty AIDAILY_X_RSSHUB_BASE_URL silently

Previously a missing RSSHub URL caused the X collector to throw,
aborting the whole pipeline. Now it returns an empty list, matching
FR-007a partial-failure tolerance. The other 3 sources still run.
```

```
test: add contract tests for GET /settings (401 path)

Covers missing Authorization header (1003) and invalid token (1003).
Uses the standard `client` fixture; no DB seeding needed.
```

---

## PR 流程

### 1. 创建分支

分支命名约定：

```
<type>/<short-description>
```

示例：

- `feat/share-cards`
- `fix/x-collector-empty-url`
- `docs/api-examples`
- `chore/upgrade-fastapi`

### 2. 写测试（Red）

按 Constitution II 强制 TDD：先写测试，确保失败，再实现。

```bash
# 跑单一测试文件
pytest tests/integration/test_share.py -v

# 验证 Red（应该 FAIL）
pytest tests/integration/test_share.py::test_share_returns_shareid -v
```

### 3. 实现（Green → Refactor）

```bash
# 实现 → 测试通过
pytest tests/integration/test_share.py -v

# 重构 → 保持绿
pytest --cov=app --cov-fail-under=80 --ignore=tests/e2e
```

### 4. 提交

```bash
git add backend/app/api/share.py backend/tests/integration/test_share.py
git commit -m "feat: add POST /share endpoint"
```

原子提交：一个 PR 内可以有多个 commit，但每个 commit 应该是一个逻辑变更。

### 5. 推送 + 创建 PR

```bash
git push -u origin feat/share-cards
```

在 GitHub 上创建 PR，目标分支为 `main`。

### 6. PR 描述模板

PR 描述必须包含以下章节（详见 Constitution §Development Workflow）：

```markdown
## Summary

<1-3 句话概述本 PR 做了什么、为什么>

## Changes

- <bullet 列表，每条对应一个 commit 或逻辑变更>

## Test Plan

- [ ] `pytest --cov=app --cov-fail-under=80` 通过
- [ ] `ruff check backend/` 通过
- [ ] `mypy backend/app` 通过
- [ ] 手动验证 <相关 quickstart VS 场景>

## Performance Impact

<说明对性能预算的影响；如无影响，写 "None"。>

## Security Impact

<说明对安全的影响；如新增了认证、修复了注入等>

## UX Impact

<说明对用户体验的影响；如无 UI 变更，写 "None"。>
```

### 7. Code Review 维度

Reviewer 会从五个维度评估（详见 Constitution §Development Workflow）：

1. **正确性**：逻辑对吗？边界条件覆盖了吗？
2. **可读性**：命名、注释、结构清晰吗？
3. **架构**：模块边界、依赖方向合理吗？
4. **安全**：输入校验、鉴权、错误信息泄露吗？
5. **性能**：是否触碰性能预算？

Reviewer 可以基于任一维度 block PR。

### 8. 合并

- PR 必须 ≥ 1 个 reviewer 批准
- 所有 CI 检查（lint/type/coverage/perf）必须绿
- **Squash merge 推荐**：保留原子 commit 历史，主分支整洁

---

## 分支保护建议

仓库管理员建议在 GitHub 设置中对 `main` 分支启用以下保护规则：

```
Settings → Branches → Branch protection rules → main
```

建议规则：

- ✅ Require a pull request before merging
  - Required approvals: ≥ 1
  - Dismiss stale pull request approvals when new commits are pushed
- ✅ Require status checks to pass before merging
  - Require branches to be up to date before merging
  - Status checks: `Lint + Type Check`, `Unit + Integration (coverage ≥ 80%)`, `Performance Budgets (Constitution IV)`
- ✅ Require conversation resolution before merging
- ✅ Do not allow bypassing the above settings
- （可选）Require linear history：与 squash merge 配合使用
- （可选）Require signed commits：高敏感场景

这些规则在 Constitution §Quality Gates 中是隐含的：所有 PR 必须 lint/type/test/coverage 通过，至少 1 reviewer 批准。

---

## 测试覆盖率

- **门槛**：80%（Constitution II）
- **检查**：CI 中 `pytest --cov-fail-under=80`，低于此值 PR 会被阻断
- **三层测试**：unit（函数/工具）+ integration（API + DB）+ e2e（Playwright）

新增功能时：

- **业务逻辑** → 必须有单元测试
- **API 端点** → 必须有集成测试（含 happy path + 错误码路径）
- **关键用户流** → 必须有 E2E 测试
- **Bug 修复** → 先写复现测试（Red），再修复（Green）

详见 [`backend/tests/`](backend/tests/) 与 [`specs/001-ai-daily-news/contracts/`](specs/001-ai-daily-news/contracts/)。

---

## 性能预算

Constitution IV 强制性能预算。变更影响以下接口时，必须运行性能基准：

```bash
pytest tests/performance/ -v -m perf
```

| 接口 | P95 预算 |
|---|---|
| `GET /daily/today` | ≤ 500 ms |
| `GET /articles?type=&src=` | ≤ 300 ms |
| `GET /articles/{id}` | ≤ 200 ms |
| 首屏可交互 | ≤ 1.5 s |

性能回归超出预算的 PR 会被 `perf` CI job 阻断，直到修复或显式重新协商预算。

---

## 安全清单

每次 PR 提交前自查（详见 Constitution §Quality Gates）：

- [ ] 无硬编码 secrets（API keys / tokens / passwords）
- [ ] 所有用户输入有 schema 校验
- [ ] SQL 查询使用参数化（无字符串拼接）
- [ ] 错误响应不泄露内部栈、SQL、env 变量值
- [ ] 写接口有 `require_auth` 依赖
- [ ] 敏感字段在日志中被 redact（如有）
- [ ] 新增依赖来自可信来源且无已知 CVE

发现安全漏洞？请勿公开提 issue，邮件至 `security@your-org.example.com`。

---

## 设计文档 / 决策记录

- 项目宪法：[`.specify/memory/constitution.md`](.specify/memory/constitution.md)
- 设计 spec / contracts：[`specs/001-ai-daily-news/`](specs/001-ai-daily-news/)
- 技术决策（D1-D9）：[`specs/001-ai-daily-news/research.md`](specs/001-ai-daily-news/research.md)
- 路线图：[`ROADMAP.md`](ROADMAP.md)

重大架构决策请通过 ADR (Architecture Decision Record) 记录，放在 `docs/adr/` 下。

---

## 行为准则

参与本项目即代表你同意遵守 [Contributor Covenant 行为准则](https://www.contributor-covenant.org/version/2/1/code_of_conduct/)。请保持尊重、建设性、包容。

---

## 联系方式

- Issue tracker: [GitHub Issues](https://github.com/your-org/ai-daily-news/issues)
- Discussion: [GitHub Discussions](https://github.com/your-org/ai-daily-news/discussions)
- Security: `security@your-org.example.com`

感谢你的贡献！
