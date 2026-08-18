/* 渲染层：列表 + 阅读器。纯 DOM 输出，事件绑定统一在 main.js 委托。 */

import {
  SOURCES, TYPE_NAMES, state, FIELDS, typeFromBackend
} from "./state.js";
import { esc, toast, ICONS } from "./ui.js";
import { renderMarkdown } from "./markdown.js";

function renderList() {
  var el = document.getElementById("articleList");
  el.innerHTML = "";
  var fields = FIELDS.list;
  state.articles.forEach(function (a) {
    var src = SOURCES[a.src] || { short: a.src, icon: "globe", name: a.src };
    var typeKey = typeFromBackend(a.type);
    var typeName = TYPE_NAMES[typeKey] || a.type;
    var item = document.createElement("button");
    item.type = "button";
    item.className = "article-item";
    item.setAttribute("role", "option");
    item.setAttribute("aria-selected", String(a.id === state.selectedId));
    item.setAttribute("data-id", a.id);
    var html = '';
    if (fields.indexOf('title') >= 0) {
      var must = a.mustRead ? '<span class="must-read" title="本期编辑推荐 Top 3">必读</span>' : '';
      html += '<h3 class="article-item-title">' + must + esc(a.title) + '</h3>';
    }
    var metaParts = [];
    if (fields.indexOf('src') >= 0) {
      metaParts.push('<span class="src-name">' + (ICONS[src.icon] || "") + esc(src.short) + '</span>');
    } else if (fields.indexOf('sourceName') >= 0 && a.sourceName) {
      metaParts.push('<span class="src-name">' + esc(a.sourceName) + '</span>');
    }
    if (fields.indexOf('type') >= 0) {
      metaParts.push('<span class="tag" data-type="' + esc(typeKey) + '">' + esc(typeName) + '</span>');
    }
    if (fields.indexOf('time') >= 0 && a.time) {
      metaParts.push('<span class="time">' + esc(a.time) + '</span>');
    }
    if (metaParts.length) {
      html += '<div class="article-item-meta">' + metaParts.join("") + '</div>';
    }
    if (fields.indexOf('excerpt') >= 0) {
      html += '<p class="item-excerpt">' + esc(a.excerpt || "") + '</p>';
    }
    item.innerHTML = html;
    el.appendChild(item);
  });
  document.getElementById("countBadge").textContent = state.articles.length + " 条";
  document.getElementById("readerCount").textContent = state.articles.length;
  el.setAttribute("aria-busy", "false");
}

function renderEmpty() {
  var el = document.getElementById("articleList");
  el.innerHTML =
    '<div class="reader-empty">' +
      '<svg class="empty-mark" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
        '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>' +
        '<path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>' +
      '</svg>' +
      '<h3>今天的货架是空的</h3>' +
      '<p>这个筛选组合下暂时没有条目。要么换个类型看看，要么去设置里把信息源都打开——情报员们也想上班。</p>' +
    '</div>';
  el.setAttribute("aria-busy", "false");
  document.getElementById("countBadge").textContent = "0 条";
  document.getElementById("readerCount").textContent = 0;
}

function renderReaderEmpty() {
  document.getElementById("readerKicker").textContent = "AI 日报 · 阅读器";
  document.getElementById("readerBody").innerHTML =
    '<div class="reader-empty">' +
      '<svg class="empty-mark" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
        '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/><path d="M8 11h6M11 8v6"/>' +
      '</svg>' +
      '<h3>从左边选一条情报开始读</h3>' +
      '<p>点列表里的任意标题，这里就会展开全文。设置面板可以调整信息源与类型偏好。</p>' +
    '</div>';
}

function renderReaderLoading() {
  document.getElementById("readerKicker").textContent = "AI 日报 · 阅读器";
  document.getElementById("readerBody").innerHTML =
    '<div class="reader-empty"><p style="color:var(--ink-muted)">加载中…</p></div>';
}

function renderReader(a) {
  var body = document.getElementById("readerBody");
  var kicker = document.getElementById("readerKicker");
  if (!a) { renderReaderEmpty(); return; }
  var fields = FIELDS.detail;
  var src = SOURCES[a.src] || { short: a.src, icon: "globe", name: a.src };
  var typeKey = typeFromBackend(a.type);
  var typeName = TYPE_NAMES[typeKey] || a.type;
  kicker.textContent = "AI 日报 · " + typeName;
  var bodyHtml = (fields.indexOf('body') >= 0) ? renderMarkdown(a.body) : "";
  var pointsHtml = (fields.indexOf('points') >= 0 && a.points && a.points.length)
    ? (a.points.map(function (p) { return "<li>" + esc(p) + "</li>"; }).join("")) : "";
  var quoteHtml = (fields.indexOf('quote') >= 0 && a.quote)
    ? '<blockquote>' + esc(a.quote) + '</blockquote>' : "";
  var summaryHtml = (fields.indexOf('summary') >= 0 && a.summary)
    ? '<div class="summary-box"><strong>一句话总结：</strong>' + esc(a.summary) + '</div>' : "";
  var ledeHtml = (fields.indexOf('lede') >= 0 && a.lede)
    ? '<p class="lede">' + esc(a.lede) + '</p>' : "";
  var readingLabel = (fields.indexOf('readingMinutes') >= 0 && a.readingMinutes)
    ? " · 阅读原文预计 " + a.readingMinutes + " 分钟" : "";
  var footSource = a.sourceName ? ("via " + a.sourceName + readingLabel) : (src.name + readingLabel);
  var html =
    '<article class="article-head">' +
      '<p class="eyebrow">' + esc(typeName) + " · " + esc(src.short) + '</p>' +
      (fields.indexOf('title') >= 0 ? '<h1>' + esc(a.title) + '</h1>' : '') +
      '<div class="article-byline">' +
        '<span class="src-chip">' + (ICONS[src.icon] || "") + esc(src.name) + '</span>' +
        '<span>今天 ' + esc(a.time || "") + ' 收录</span>' +
        '<span class="tag" data-type="' + esc(typeKey) + '">' + esc(typeName) + '</span>' +
      '</div>' +
      (fields.indexOf('excerpt') >= 0 && a.excerpt ? '<p class="item-excerpt">' + esc(a.excerpt) + '</p>' : '') +
    '</article>' +
    '<div class="article-body">' +
      ledeHtml + summaryHtml + bodyHtml + quoteHtml +
      (pointsHtml ? '<ul>' + pointsHtml + '</ul>' : "") +
    '</div>' +
    '<div class="article-actions">' +
      '<a class="btn btn-primary" id="readOriginal" target="_blank" rel="noopener noreferrer" href="' + esc(a.sourceUrl || "#") + '">' +
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><path d="M15 3h6v6"/><path d="M10 14 21 3"/></svg>' +
        '阅读原文' +
      '</a>' +
      '<button class="btn btn-ghost" id="shareBtn" data-article-id="' + esc(a.id) + '">' +
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m8.6 13.5 6.8 4M15.4 6.5l-6.8 4"/></svg>' +
        '分享这条' +
      '</button>' +
    '</div>' +
    '<div class="article-foot">' +
      '<span>' + esc(footSource) + '</span>' +
      '<span><code>' + esc(String(a.id || "").toUpperCase()) + '</code></span>' +
    '</div>';
  body.innerHTML = html;
}

export {
  renderList, renderEmpty, renderReaderEmpty, renderReaderLoading, renderReader
};
