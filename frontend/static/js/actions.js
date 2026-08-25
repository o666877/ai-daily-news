/* 动作层：筛选、加载、分享。设置面板见 settings-panel.js，token 提示见 auth.js。 */

import { state, typeFromBackend } from "./state.js";
import { toast } from "./ui.js";
import { fetchArticles, fetchArticle, shareArticleApi, getToken } from "./api.js";
import { promptForToken } from "./auth.js";
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
  refetchByFilters, handleShare
};
