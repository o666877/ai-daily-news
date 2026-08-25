/* 企微推送状态 + 手动重推(specs/006 ticket 04)。设置面板内的按期操作。 */

import { state } from "./state.js";
import { esc, toast } from "./ui.js";
import { imPushStatusApi, imPushRepushApi } from "./api.js";

function statusLabel(s) {
  if (!s.pushed) return { text: "未推送", cls: "im-push-none" };
  if (s.ok) return { text: "已推送", cls: "im-push-ok" };
  return { text: "推送失败", cls: "im-push-fail" };
}

function renderImPushStatuses(statuses) {
  var el = document.getElementById("imPushStatusList");
  if (!el) return;
  if (!statuses || statuses.length === 0) {
    el.innerHTML = '<p class="im-push-row im-push-none">尚未配置企微 webhook(见部署文档 SETUP.md)</p>';
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
      // actions.js 引用了本模块,反向 import 会成环;动态加载打破循环
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

export { refreshImPushStatus, handleRepush };
