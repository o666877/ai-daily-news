/* 全局状态与领域常量（specs/004 cand 4：自 index.html 内联 script 拆出）。 */

var TYPE_TO_BACKEND = { "self-improve": "self_improve", "open-source": "open_source" };
var TYPE_FROM_BACKEND = { "self_improve": "self-improve", "open_source": "open-source" };

var SOURCES = {
  x:      { name: "X (Twitter)",  short: "X",      icon: "x" },
  github: { name: "GitHub",       short: "GitHub", icon: "github" },
  reddit: { name: "Reddit",       short: "Reddit", icon: "reddit" },
  web:    { name: "全网聚合",      short: "全网",    icon: "globe" }
};
var TYPE_NAMES = {
  "agent": "Agent / 智能体",
  "self-improve": "持续学习 / 自我进化",
  "open-source": "开源项目",
  "tools": "工具与效率",
  "commentary": "观点时评"
};

/* 各视图渲染的字段（固定 standard 档，阅读密度档位已下线）。 */
var FIELDS = {
  list: ['title', 'excerpt', 'type', 'src', 'time'],
  detail: ['title', 'excerpt', 'lede', 'body', 'points', 'sourceUrl', 'readingMinutes']
};

var state = {
  filters: { type: "all", src: "all" },
  toggles: { x: true, github: true, reddit: true, web: true,
              agent: true, "self-improve": true, "open-source": true, tools: true, commentary: true, dailyPush: true },
  selectedId: null,
  currentIssue: null,
  articles: [],
  byId: {},
  issueId: null,
  dailyCount: 15,
  pushTime: "08:00",
  imPush: { enabled: false, topN: 5, linkBaseUrl: "", webhooks: [] }
};

function typeToBackend(k) { return TYPE_TO_BACKEND[k] || k; }
function typeFromBackend(k) { return TYPE_FROM_BACKEND[k] || k; }

export {
  SOURCES, TYPE_NAMES, state, FIELDS,
  typeToBackend, typeFromBackend
};
