/* 设置面板：偏好读写 + 企微推送配置（webhook 增删/测试/状态/重推）的唯一归属。
对 main.js 的 interface 是 7 个事件处理函数；imPush 状态为本模块私有。
保存生效后刷新列表，依赖 actions.js 的 refetchByFilters（单向）。
*/

import { state } from "./state.js";
import { esc, toast } from "./ui.js";
import { promptForToken } from "./auth.js";
import {
  fetchSettings, saveSettings, resetSettingsApi,
  imPushStatusApi, imPushRepushApi, imPushTestApi
} from "./api.js";
import { refetchByFilters } from "./actions.js";

var MAX_WEBHOOKS = 5;
var TEST_RESET_MS = 3500;
/* 前后端校验镜像:与 backend/app/models/settings.py 的 WECOM_WEBHOOK_MASKED_RE /
 * WECOM_WEBHOOK_URL_RE 保持一致,改规则需两处同步。 */
var MASKED_URL_RE = /^https:\/\/qyapi\.weixin\.qq\.com\/cgi-bin\/webhook\/send\?key=\*{4}[0-9A-Za-z-]{0,4}$/;
var FULL_URL_RE = /^https:\/\/qyapi\.weixin\.qq\.com\/cgi-bin\/webhook\/send\?key=[0-9A-Za-z-]{8,64}$/;

/* 模块私有：仅面板内部读写，面板外无消费者。 */
var imPush = { enabled: false, topN: 5, linkBaseUrl: "", webhooks: [] };

/* ═══ 偏好区：toggles 回填与收集 ═══ */

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

/* ═══ 面板编排：打开 / 保存 / 重置 ═══ */

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
  saveSettings(body).then(function (r) {
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

/* ═══ 企微推送：配置回填与收集 ═══ */

function applyImPushToUI(im) {
  if (!im) return;
  imPush = {
    enabled: !!im.enabled,
    topN: im.topN || 5,
    linkBaseUrl: im.linkBaseUrl || "",
    webhooks: (im.webhooks || []).map(function (w) { return { name: w.name || "", url: w.url || "" }; })
  };
  var en = document.getElementById("imPushEnabled");
  if (en) en.checked = imPush.enabled;
  var tn = document.getElementById("imTopN");
  if (tn) tn.value = String(imPush.topN);
  var lb = document.getElementById("imLinkBase");
  if (lb) lb.value = imPush.linkBaseUrl;
  renderWebhookRows();
}

function renderWebhookRows() {
  var list = document.getElementById("imWebhookList");
  if (!list) return;
  list.innerHTML = imPush.webhooks.map(function (w, i) {
    return '<div class="im-hook-row" data-hook-index="' + i + '">' +
      '<input type="text" class="im-hook-name" maxlength="20" placeholder="群名(1-20字)" value="' + esc(w.name) + '" aria-label="webhook 名称">' +
      '<input type="text" class="im-hook-url" placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…" value="' + esc(w.url) + '" aria-label="webhook 地址">' +
      '<button type="button" class="btn btn-ghost im-hook-test" title="先保存配置,再向该群发送测试消息">测试</button>' +
      '<button type="button" class="btn btn-ghost im-hook-del" aria-label="删除 webhook">×</button>' +
      "</div>";
  }).join("");
  var add = document.getElementById("imAddWebhook");
  if (add) add.disabled = imPush.webhooks.length >= MAX_WEBHOOKS;
}

function syncRowsIntoState() {
  var rows = document.querySelectorAll("#imWebhookList .im-hook-row");
  var hooks = [];
  rows.forEach(function (row) {
    hooks.push({
      name: (row.querySelector(".im-hook-name").value || "").trim(),
      url: (row.querySelector(".im-hook-url").value || "").trim()
    });
  });
  imPush.webhooks = hooks;
}

function collectImPushFromUI() {
  var en = document.getElementById("imPushEnabled");
  var tn = document.getElementById("imTopN");
  var lb = document.getElementById("imLinkBase");
  if (en) imPush.enabled = en.checked;
  if (tn) imPush.topN = parseInt(tn.value, 10) || 5;
  // 留空 = 自动使用当前访问地址(内网穿透域名访问时即该域名),手机无法访问时才需显式填写
  if (lb) imPush.linkBaseUrl = (lb.value || "").trim() || window.location.origin;
  syncRowsIntoState();
  return imPush;
}

/* ═══ 企微推送：行级操作 ═══ */

function handleAddWebhook() {
  if (imPush.webhooks.length >= MAX_WEBHOOKS) {
    toast("最多配置 " + MAX_WEBHOOKS + " 个群");
    return;
  }
  syncRowsIntoState();
  imPush.webhooks = imPush.webhooks.concat([{ name: "", url: "" }]);
  renderWebhookRows();
  var rows = document.querySelectorAll("#imWebhookList .im-hook-row");
  var last = rows[rows.length - 1];
  if (last) last.querySelector(".im-hook-name").focus();
}

function handleDeleteWebhook(row) {
  syncRowsIntoState();
  var idx = parseInt(row.dataset.hookIndex, 10);
  imPush.webhooks = imPush.webhooks.filter(function (_, i) { return i !== idx; });
  renderWebhookRows();
}

function validateImPushLocal() {
  var seen = {};
  for (var i = 0; i < imPush.webhooks.length; i++) {
    var w = imPush.webhooks[i];
    if (!w.name || w.name.length > 20) return "群名需 1-20 个字";
    if (seen[w.name]) return "群名重复:" + w.name;
    seen[w.name] = true;
    if (!(FULL_URL_RE.test(w.url) || MASKED_URL_RE.test(w.url))) {
      return "「" + w.name + "」的 webhook 地址不合法(需企业微信群机器人地址)";
    }
  }
  return "";
}

/* 测试 = 先保存当前面板(保证测到的即生效配置),再按 name 发测试消息。 */
function handleTestWebhook(row) {
  var btn = row.querySelector(".im-hook-test");
  var name = (row.querySelector(".im-hook-name").value || "").trim();
  if (!name) { toast("请先填写群名"); return; }
  collectImPushFromUI(); // 校验前先把 DOM 行收进面板状态,避免读到陈旧列表
  var invalid = validateImPushLocal();
  if (invalid) { toast(invalid); return; }
  if (btn) { btn.disabled = true; btn.textContent = "测试中…"; }
  saveSettings(buildSettingsBody())
    .then(function () { return imPushTestApi(name); })
    .then(function (r) {
      if (btn) {
        btn.textContent = r.ok ? "✓ 成功" : "✗ 失败";
        btn.title = r.ok ? "测试消息已送达" : ("失败:" + (r.errmsg || ("errcode " + r.errcode)));
        setTimeout(function () { if (btn) { btn.textContent = "测试"; btn.disabled = false; } }, TEST_RESET_MS);
      }
      toast(r.ok ? "测试消息已发送到「" + name + "」,请到群里确认" : "测试失败:" + (r.errmsg || ("errcode " + r.errcode)));
      refreshImPushStatus();
    })
    .catch(function (e) {
      if (btn) { btn.textContent = "测试"; btn.disabled = false; }
      if (e.needAuth || e.code === 1003) {
        promptForToken(function () { handleTestWebhook(row); }); // Token 有效后自动重试
        return;
      }
      toast("测试失败:" + e.message);
    });
}

/* ═══ 企微推送：状态区 + 手动重推 ═══ */

function statusLabel(s) {
  if (!s.pushed) return { text: "未推送", cls: "im-push-none" };
  if (s.ok) return { text: "已推送", cls: "im-push-ok" };
  return { text: "推送失败", cls: "im-push-fail" };
}

function renderImPushStatuses(statuses) {
  var el = document.getElementById("imPushStatusList");
  if (!el) return;
  if (!statuses || statuses.length === 0) {
    el.innerHTML = '<p class="im-push-row im-push-none">尚未配置企微 webhook(在上方添加)</p>';
    return;
  }
  el.innerHTML = statuses.map(function (s) {
    var label = statusLabel(s);
    var detail = s.pushed && !s.ok && s.errmsg ? '<small class="im-push-err">' + esc(s.errmsg) + "</small>" : "";
    var time = s.pushedAt ? '<small>' + esc(s.pushedAt.replace("T", " ").replace("Z", "")) + "</small>" : "";
    return '<p class="im-push-row ' + label.cls + '"><strong>' + esc(s.name) + "</strong>" +
      "<span>" + label.text + "</span>" + time + detail + "</p>";
  }).join("");
}

function refreshImPushStatus() {
  var el = document.getElementById("imPushStatusList");
  if (!el) return;
  if (!state.issueId) {
    el.innerHTML = '<p class="im-push-row im-push-none">今日刊尚未生成,无推送状态</p>';
    return;
  }
  imPushStatusApi(state.issueId).then(function (data) {
    renderImPushStatuses((data && data.statuses) || []);
  }).catch(function (e) {
    if (e.needAuth) {
      promptForToken(refreshImPushStatus);
      return;
    }
    el.innerHTML = '<p class="im-push-row im-push-fail">状态加载失败:' + esc(e.message) + "</p>";
  });
}

function handleRepush() {
  var btn = document.getElementById("repushImPush");
  if (!btn || btn.disabled) return;
  if (!state.issueId) { toast("今日刊尚未生成,无法推送"); return; }
  var originalLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = "推送中…";
  imPushRepushApi(state.issueId).then(function (data) {
    var results = (data && data.results) || [];
    var okCount = results.filter(function (r) { return r.ok; }).length;
    toast(okCount === results.length
      ? "已重新推送(" + okCount + "/" + results.length + " 个群成功)"
      : "推送完成:" + okCount + "/" + results.length + " 个群成功,失败详情见状态");
    refreshImPushStatus();
  }).catch(function (e) {
    toast("重推失败:" + e.message);
  }).finally(function () {
    btn.disabled = false;
    btn.textContent = originalLabel;
  });
}

export {
  handleOpenSettings, handleApplySettings, handleResetSettings,
  handleRepush, handleAddWebhook, handleDeleteWebhook, handleTestWebhook
};
