/* 企微推送配置 + 状态 + 手动重推(specs/006 ticket 04/05)。设置面板内的按期操作。

与 actions.js 存在静态循环 import:两侧都只在事件回调里调用对方函数
(函数声明提升),模块求值期无调用,ESM 下安全。
*/

import { state } from "./state.js";
import { esc, toast } from "./ui.js";
import { imPushStatusApi, imPushRepushApi, imPushTestApi, saveSettings } from "./api.js";
import { buildSettingsBody, promptForToken } from "./actions.js";

var MAX_WEBHOOKS = 5;
var TEST_RESET_MS = 3500;
/* 前后端校验镜像:与 backend/app/models/settings.py 的 WECOM_WEBHOOK_MASKED_RE /
 * WECOM_WEBHOOK_URL_RE 保持一致,改规则需两处同步。 */
var MASKED_URL_RE = /^https:\/\/qyapi\.weixin\.qq\.com\/cgi-bin\/webhook\/send\?key=\*{4}[0-9A-Za-z-]{0,4}$/;
var FULL_URL_RE = /^https:\/\/qyapi\.weixin\.qq\.com\/cgi-bin\/webhook\/send\?key=[0-9A-Za-z-]{8,64}$/;

/* ═══ 配置区:回填与收集 ═══ */

function applyImPushToUI(im) {
  if (!im) return;
  state.imPush = {
    enabled: !!im.enabled,
    topN: im.topN || 5,
    linkBaseUrl: im.linkBaseUrl || "",
    webhooks: (im.webhooks || []).map(function (w) { return { name: w.name || "", url: w.url || "" }; })
  };
  var en = document.getElementById("imPushEnabled");
  if (en) en.checked = state.imPush.enabled;
  var tn = document.getElementById("imTopN");
  if (tn) tn.value = String(state.imPush.topN);
  var lb = document.getElementById("imLinkBase");
  if (lb) lb.value = state.imPush.linkBaseUrl;
  renderWebhookRows();
}

function renderWebhookRows() {
  var list = document.getElementById("imWebhookList");
  if (!list) return;
  list.innerHTML = state.imPush.webhooks.map(function (w, i) {
    return '<div class="im-hook-row" data-hook-index="' + i + '">' +
      '<input type="text" class="im-hook-name" maxlength="20" placeholder="群名(1-20字)" value="' + esc(w.name) + '" aria-label="webhook 名称">' +
      '<input type="text" class="im-hook-url" placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…" value="' + esc(w.url) + '" aria-label="webhook 地址">' +
      '<button type="button" class="btn btn-ghost im-hook-test" title="先保存配置,再向该群发送测试消息">测试</button>' +
      '<button type="button" class="btn btn-ghost im-hook-del" aria-label="删除 webhook">×</button>' +
      "</div>";
  }).join("");
  var add = document.getElementById("imAddWebhook");
  if (add) add.disabled = state.imPush.webhooks.length >= MAX_WEBHOOKS;
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
  state.imPush.webhooks = hooks;
}

function collectImPushFromUI() {
  var en = document.getElementById("imPushEnabled");
  var tn = document.getElementById("imTopN");
  var lb = document.getElementById("imLinkBase");
  if (en) state.imPush.enabled = en.checked;
  if (tn) state.imPush.topN = parseInt(tn.value, 10) || 5;
  // 留空 = 自动使用当前访问地址(内网穿透域名访问时即该域名),手机无法访问时才需显式填写
  if (lb) state.imPush.linkBaseUrl = (lb.value || "").trim() || window.location.origin;
  syncRowsIntoState();
  return state.imPush;
}

/* ═══ 配置区:行级操作 ═══ */

function handleAddWebhook() {
  if (state.imPush.webhooks.length >= MAX_WEBHOOKS) {
    toast("最多配置 " + MAX_WEBHOOKS + " 个群");
    return;
  }
  syncRowsIntoState();
  state.imPush.webhooks = state.imPush.webhooks.concat([{ name: "", url: "" }]);
  renderWebhookRows();
  var rows = document.querySelectorAll("#imWebhookList .im-hook-row");
  var last = rows[rows.length - 1];
  if (last) last.querySelector(".im-hook-name").focus();
}

function handleDeleteWebhook(row) {
  syncRowsIntoState();
  var idx = parseInt(row.dataset.hookIndex, 10);
  state.imPush.webhooks = state.imPush.webhooks.filter(function (_, i) { return i !== idx; });
  renderWebhookRows();
}

function validateImPushLocal() {
  var seen = {};
  for (var i = 0; i < state.imPush.webhooks.length; i++) {
    var w = state.imPush.webhooks[i];
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
  collectImPushFromUI(); // 校验前先把 DOM 行收进 state,避免读到陈旧列表
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

/* ═══ 状态区 + 重推(ticket 04) ═══ */

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
      import("./actions.js").then(function (m) { m.promptForToken(refreshImPushStatus); });
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
  refreshImPushStatus, handleRepush,
  applyImPushToUI, collectImPushFromUI, validateImPushLocal,
  handleAddWebhook, handleDeleteWebhook, handleTestWebhook
};
