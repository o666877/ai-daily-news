# Contract: GET /articles/{id} (v2 扩展)

**接口 #3 · 文章详情** · 认证：否 · 用途：右侧阅读器渲染

> 本契约在 [001 系统契约](../../001-ai-daily-news/contracts/articles-detail.md) 基础上扩展：新增评分相关 5 个字段。

## Request

```http
GET /api/v1/articles/20260813-0001
```

## Response 200 OK

```json
{
  "id": "20260813-0001",
  "issueId": "20260813",
  "type": "agent",
  "src": "web",
  "title": "OpenAI 发布 GPT-5：多模态推理大幅提升",
  "excerpt": "一句话要点摘要",
  "lede": "导语段落，60-120 汉字，概括新闻核心…",
  "summary": "单句一句话总结，≤80 汉字",
  "body": "**段落 1** 关键术语加粗。\n\n段落 2 提到 `pip install x`，详见 [文档](https://example.com/docs)。",
  "quote": "值得保留的引用（中文翻译）",
  "points": ["要点 1", "要点 2", "要点 3"],
  "time": "09:12",
  "sourceUrl": "https://openai.com/blog/gpt-5",
  "sourceName": "OpenAI Blog",
  "readingMinutes": 6,
  "publishedAt": "2026-08-13T01:12:00+00:00",
  "score": {
    "compositeScore": 92,
    "dimensionScores": {
      "authority": 90,
      "depth": 95,
      "timeliness": 100,
      "expression": 80
    },
    "authorityTier": "official_blog",
    "scoreSource": "llm",
    "topicId": "gpt5-release",
    "opinionFingerprint": "official-announcement"
  }
}
```

### body 字段格式变更（specs/003）

`body` 已从 `string[]`（段落数组）改为 **单个 markdown 字符串**（段落间空行分隔）。
允许语法子集：段落、`**粗体**`、`` `行内代码` ``、`[链接](url)`、无序列表、`>` 引用。
禁止：标题、表格、代码块、HTML。前端以 marked + DOMPurify 白名单渲染。

### Score 对象字段（**新增**）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `compositeScore` | int | 是 | 综合评分 0–100 |
| `dimensionScores` | object | 是 | 4 维子分：`{authority, depth, timeliness, expression}`，每维度 0–100 |
| `authorityTier` | string | 是 | 来源权威等级：`official_blog` / `authoritative_media` / `community` |
| `scoreSource` | string | 是 | 评分来源：`llm`（LLM 评分成功）/ `rule_fallback`（LLM 失败后规则回退） |
| `topicId` | string \| null | 否 | 文章所述事件 ID（用于跨源去重；空表示 LLM 未输出） |
| `opinionFingerprint` | string \| null | 否 | 观点特征标签（用于同质化去重） |

### 字段白名单渲染（前端控制，不修改后端）

前端按当前 `style_mode` 决定渲染哪些字段：

| 字段 | concise | standard | detailed |
|---|---|---|---|
| title | ✓ | ✓ | ✓ |
| summary | ✓ | ✓ | ✓ |
| sourceUrl | ✓ | ✓ | ✓ |
| excerpt | — | ✓ | ✓ |
| lede | — | ✓ | ✓ |
| body | — | ✓ | ✓ |
| points | — | ✓ | ✓ |
| readingMinutes | — | ✓ | ✓ |
| quote | — | — | ✓ |
| score.dimensionScores | — | — | ✓ |
| score.authorityTier | — | — | ✓ |

后端始终返回全字段；前端按 style_mode 过滤显示。

## Response 404 — 2001

```json
{"code": 2001, "message": "文章不存在", "requestId": "req_abc"}
```

## Error Scenarios

| HTTP | 业务码 | 触发 | 前端 |
|---|---|---|---|
| 404 | 2001 | 文章 id 不存在 | 阅读器显示"找不到这篇文章" |
| 429 | 1006 | 触发读限流 | Toast |

## Performance Budget

- P95 ≤ 200 ms

## Example

```bash
curl -s "http://127.0.0.1:8000/api/v1/articles/20260813-0001" | jq '.score'
```
