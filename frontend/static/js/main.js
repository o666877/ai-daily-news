/* 入口：事件绑定 + 启动流程。 */

import { state } from "./state.js";
import { esc, toast } from "./ui.js";
import { fetchToday } from "./api.js";
import {
  renderList, renderEmpty, renderReaderEmpty
} from "./render.js";
import {
  refetchByFilters, applyToggles, selectFirstIfNone,
  loadArticleIntoReader, handleOpenSettings, handleApplySettings,
  handleResetSettings, handleShare
} from "./actions.js";

/* ═══ 事件绑定 ═══ */
document.querySelectorAll("#typeFilters .chip").forEach(function (c) {
  c.addEventListener("click", function () { state.filters.type = c.dataset.filter; refetchByFilters(); });
});
document.querySelectorAll("#srcFilters .chip").forEach(function (c) {
  c.addEventListener("click", function () { state.filters.src = c.dataset.src; refetchByFilters(); });
});
document.getElementById("articleList").addEventListener("click", function (e) {
  var btn = e.target.closest(".article-item");
  if (!btn) return;
  state.selectedId = btn.dataset.id;
  renderList();
  loadArticleIntoReader(state.selectedId);
  if (window.innerWidth < 860) {
    document.body.classList.add("reading");
    document.getElementById("reader").focus({ preventScroll: false });
  }
});
document.getElementById("backBtn").addEventListener("click", function () {
  document.body.classList.remove("reading");
  window.scrollTo({ top: 0, behavior: "auto" });
  document.querySelector(".index-col").focus({ preventScroll: false });
});

/* 阅读器内按钮：事件委托（renderReader 不再自行绑定）。
 * readOriginal 无原文时 href="#"，拦截并提示；shareBtn 携带 data-article-id。 */
document.getElementById("readerBody").addEventListener("click", function (e) {
  var share = e.target.closest("#shareBtn");
  if (share && share.dataset.articleId) { handleShare(share.dataset.articleId); return; }
  var orig = e.target.closest("#readOriginal");
  if (orig && orig.getAttribute("href") === "#") {
    e.preventDefault();
    toast("这篇文章没有原文链接");
  }
});

document.getElementById("openSettings").addEventListener("click", handleOpenSettings);
document.getElementById("closeSettings").addEventListener("click", function () { document.getElementById("settingsDialog").close(); });
document.getElementById("settingsDialog").addEventListener("click", function (e) { if (e.target === this) this.close(); });
document.querySelectorAll("[data-src-toggle]").forEach(function (inp) {
  inp.addEventListener("change", function () { state.toggles[inp.dataset.srcToggle] = inp.checked; refetchByFilters(); });
});
document.querySelectorAll("[data-type-toggle]").forEach(function (inp) {
  inp.addEventListener("change", function () { state.toggles[inp.dataset.typeToggle] = inp.checked; refetchByFilters(); });
});
document.querySelector("[data-toggle='dailyPush']").addEventListener("change", function (e) {
  state.toggles.dailyPush = e.target.checked;
  toast(e.target.checked ? "每日推送已开启 · 明天生效" : "每日推送已关闭 · 明天生效");
});
document.getElementById("resetSettings").addEventListener("click", handleResetSettings);
document.getElementById("applySettings").addEventListener("click", handleApplySettings);

/* ═══ 日期 ═══ */
(function () {
  var now = new Date();
  var week = ["日","一","二","三","四","五","六"];
  document.getElementById("dateStamp").innerHTML =
    "<strong>" + (now.getMonth() + 1) + " 月 " + now.getDate() + " 日 · 周" + week[now.getDay()] + "</strong>" +
    "<span>今日刊 · 自动生成</span>";
})();

/* ═══ 启动 ═══ */
function startToday(attempt) {
  attempt = attempt || 0;
  var delays = [5000, 8000, 13000, 20000, 30000];
  var listEl = document.getElementById("articleList");
  fetchToday().then(function (data) {
    state.currentIssue = data.issue;
    state.issueId = data.issue ? data.issue.id : null;
    var items = data.articles || [];
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
  }).catch(function (e) {
    if (e.code === 2003) {
      listEl.innerHTML =
        '<div class="skeleton-list">' +
          Array.from({length: 6}, function () { return '<div class="sk-item"><div class="sk-line w70"></div><div class="sk-line w40"></div><div class="sk-line w90"></div></div>'; }).join("") +
        '</div>';
      listEl.setAttribute("aria-busy", "true");
      var sec = Math.round(delays[Math.min(attempt, delays.length - 1)] / 1000);
      toast("今日刊生成中 · " + sec + "s 后重试");
      setTimeout(function () { startToday(attempt + 1); }, delays[Math.min(attempt, delays.length - 1)]);
    } else if (e.code === 2002) {
      toast("今日刊尚未生成 · 等调度（通常 08:00）");
      listEl.innerHTML = '<div class="reader-empty"><p>今日刊尚未生成。</p></div>';
      listEl.setAttribute("aria-busy", "false");
      renderReaderEmpty();
    } else {
      listEl.innerHTML = '<div class="reader-empty"><p>加载失败：' + esc(e.message) + "</p></div>";
      listEl.setAttribute("aria-busy", "false");
    }
  });
}

document.addEventListener("DOMContentLoaded", function () {
  startToday(0);
});
