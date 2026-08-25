/* 动作层：筛选、加载、设置面板、token、分享。 */

import { state, typeFromBackend } from "./state.js";
import { toast } from "./ui.js";
import {
  refreshImPushStatus, applyImPushToUI, collectImPushFromUI, validateImPushLocal
} from "./im-push.js";
import {
  fetchArticles, fetchArticle, fetchSettings, saveSettings,
  resetSettingsApi, shareArticleApi, getToken, setToken, clearToken
} from "./api.js";
import {
  renderList, renderEmpty, renderReaderEmpty, renderReaderLoading,
  renderReader
} from "./render.js";

/* ═══ 筛选与拉取 ═══ */
function syncChips() {
  document.querySelectorAll("#typeFilters .chip").forEach(function (c) {
    c.setAttribute("aria-pressed", String(c.dataset.filter === state.filters.type));
  });
  document.querySelectorAll("#srcFilters .chip").forEach(function (c) {
    c.setAttribute("aria-pressed", String(c.dataset.src === state.filters.src));
  });
}

function applyToggles(items) {
  return items.filter(function (a) {
    var typeKey = typeFromBackend(a.type);
    if (!state.toggles[a.src] || !state.toggles[typeKey]) return false;
    return true;
  });
}

function selectFirstIfNone(list) {
  if (list.length > 0 && (!state.selectedId || !list.some(function (a) { return a.id === state.selectedId; }))) {
    state.selectedId = list[0].id;
  }
}

function loadArticleIntoReader(id) {
  renderReaderLoading();
  fetchArticle(id).then(renderReader).catch(function (e) { toast("加载详情失败：" + e.message); renderReader(null); });
}

function refetchByFilters() {
  syncChips();
  var listEl = document.getElementById("articleList");
  listEl.setAttribute("aria-busy", "true");
  fetchArticles({ type: state.filters.type, src: state.filters.src })
    .then(function (data) {
      var items = data.items || [];
      // 注意：不在此处设置 a.rank —— 必读徽标由后端 mustRead 字段锚定全刊 Top3，
      // 筛选视图按结果集重新编号会让 56 分的内容也戴上"必读"。
      var filtered = applyToggles(items);
      state.articles = filtered;
      state.byId = {};
      filtered.forEach(function (a) { state.byId[a.id] = a; });
      if (filtered.length === 0) {
        renderEmpty();
        state.selectedId = null;
        renderReaderEmpty();
        return;
      }
      renderList();
      selectFirstIfNone(filtered);
      loadArticleIntoReader(state.selectedId);
    })
    .catch(function (e) {
      listEl.setAttribute("aria-busy", "false");
      listEl.innerHTML = '<div class="reader-empty"><p>加载失败：' + e.message + "</p></div>";
    });
}

/* ═══ 设置面板 ═══ */
function applyTogglesToUI() {
  document.querySelectorAll("[data-src-toggle]").forEach(function (inp) { inp.checked = !!state.toggles[inp.dataset.srcToggle]; });
  document.querySelectorAll("[data-type-toggle]").forEach(function (inp) { inp.checked = !!state.toggles[inp.dataset.typeToggle]; });
  var dp = document.querySelector("[data-toggle='dailyPush']"); if (dp) dp.checked = !!state.toggles.dailyPush;
  var pt = document.getElementById("pushTime");
  if (pt) { pt.value = state.pushTime; pt.disabled = !state.toggles.dailyPush; }
  document.querySelectorAll("[name='dailyCount']").forEach(function (inp) {
    inp.checked = (parseInt(inp.value, 10) === state.dailyCount);
  });
}

function readTogglesFromUI() {
  document.querySelectorAll("[data-src-toggle]").forEach(function (inp) { state.toggles[inp.dataset.srcToggle] = inp.checked; });
  document.querySelectorAll("[data-type-toggle]").forEach(function (inp) { state.toggles[inp.dataset.typeToggle] = inp.checked; });
  var dp = document.querySelector("[data-toggle='dailyPush']"); if (dp) state.toggles.dailyPush = dp.checked;
  var pt = document.getElementById("pushTime");
  state.pushTime = (pt && pt.value) ? pt.value : state.pushTime;
  var dc = document.querySelector("[name='dailyCount']:checked");
  if (dc) state.dailyCount = parseInt(dc.value, 10);
}

function syncTogglesFromSettings(s) {
  state.toggles.x = !!s.sources.x; state.toggles.github = !!s.sources.github; state.toggles.reddit = !!s.sources.reddit; state.toggles.web = !!s.sources.web;
  state.toggles.agent = !!s.types.agent; state.toggles["self-improve"] = !!s.types.self_improve; state.toggles["open-source"] = !!s.types.open_source; state.toggles.tools = !!s.types.tools; state.toggles.commentary = !!s.types.commentary;
  state.toggles.dailyPush = !!s.dailyPush.enabled;
  state.pushTime = (s.dailyPush && s.dailyPush.time) || "08:00";
  state.dailyCount = s.dailyCount || 15;
}

function handleOpenSettings() {
  var d = document.getElementById("settingsDialog");
  d.showModal();
  loadSettingsIntoPanel(d);
  refreshImPushStatus();
}

function loadSettingsIntoPanel(d) {
  fetchSettings().then(function (s) {
    syncTogglesFromSettings(s); applyTogglesToUI();
    applyImPushToUI(s.imPush);
  }).catch(function (e) {
    if (e.code === 1003) {
      d.close();
      promptForToken(function () { d.showModal(); loadSettingsIntoPanel(d); });
    }
    else { toast("加载设置失败：" + e.message); }
  });
}

function buildSettingsBody() {
  readTogglesFromUI();
  return {
    sources: { x: state.toggles.x, github: state.toggles.github, reddit: state.toggles.reddit, web: state.toggles.web },
    types: { agent: state.toggles.agent, self_improve: state.toggles["self-improve"], open_source: state.toggles["open-source"], tools: state.toggles.tools, commentary: state.toggles.commentary },
    dailyPush: { enabled: state.toggles.dailyPush, time: state.pushTime || "08:00" },
    dailyCount: state.dailyCount || 15,
    imPush: collectImPushFromUI()
  };
}

function handleApplySettings() {
  var body = buildSettingsBody(); // 先收集 DOM(含 imPush 行)再校验
  var invalid = validateImPushLocal();
  if (invalid) { toast(invalid); return; }
  saveSettingsBody(body).then(function (r) {
    applyImPushToUI(r.body && r.body.imPush); // 新增 webhook 的完整 URL 回读为脱敏形式
    refreshImPushStatus();
    document.getElementById("settingsDialog").close();
    toast("已保存 · 生效刊期：" + (r.effectiveAt || "下一期"));
    refetchByFilters();
  }).catch(function (e) {
    if (e.code === 1003) {
      toast("需要 Bearer Token 才能保存偏好");
      promptForToken(handleApplySettings); // Token 校验通过后自动重试保存
      return;
    }
    toast("保存失败：" + e.message);
  });
}

function handleResetSettings() {
  resetSettingsApi().then(function (s) {
    syncTogglesFromSettings(s); applyTogglesToUI();
    applyImPushToUI(s.imPush);
    refreshImPushStatus();
    toast("已恢复默认偏好(企微推送配置一并清空)");
    refetchByFilters();
  }).catch(function (e) {
    if (e.code === 1003) { document.getElementById("settingsDialog").close(); promptForToken(); return; }
    toast("重置失败：" + e.message);
  });
}

function promptForToken(onValid) {
  var cur = getToken();
  var t = window.prompt(
    "Bearer Token（默认 Token 见后端启动日志中 [aidaily] Generated bearer token 一行；也可在 .env 设置 AIDAILY_BEARER_TOKEN）",
    cur || ""
  );
  if (t === null) { toast(cur ? "保留原 Token" : "未设置 Token · 写操作仍受限制"); return; }
  t = t.trim();
  if (!t) { clearToken(); toast("已清除 Token · 写操作仍受限制"); return; }
  setToken(t);
  // 立即校验，错误 token 给明确反馈而不是等下一次 401 死循环。
  fetchSettings().then(function () {
    toast("Token 有效");
    if (onValid) onValid();
  }).catch(function (e) {
    if (e.code === 1003) { clearToken(); toast("Token 无效：请核对后端启动日志后重试"); }
    else { toast("已保存 Token（校验接口暂不可达）"); }
  });
}

/* ═══ 分享 ═══ */
function handleShare(articleId) {
  if (!getToken()) { promptForToken(); return; }
  shareArticleApi(articleId).then(function (r) {
    var url = r.cardUrl;
    var copy = window.confirm("已生成卡片：" + r.articleTitle + "\n" + url + "\n\n点击确定复制链接，取消仅查看。");
    if (copy) {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(function () { toast("链接已复制"); }).catch(function () { window.prompt("请手动复制：", url); });
      } else {
        window.prompt("请手动复制：", url);
      }
    }
  }).catch(function (e) {
    if (e.code === 1003) { promptForToken(); return; }
    toast("分享失败：" + e.message);
  });
}

export {
  syncChips, applyToggles, selectFirstIfNone, loadArticleIntoReader,
  refetchByFilters, applyTogglesToUI, handleOpenSettings, handleApplySettings,
  handleResetSettings, promptForToken, handleShare,
  buildSettingsBody
};
