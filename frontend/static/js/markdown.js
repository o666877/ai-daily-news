/* Markdown 渲染管线（specs/003：body 为单个 md 字符串）。
 * marked 输出必须经 DOMPurify 白名单消毒，库缺失时 fail-closed 降级为纯文本。 */

import { esc } from "./ui.js";

var MD_ALLOWED_TAGS = ["p", "br", "strong", "em", "code", "a", "ul", "ol", "li", "blockquote"];
var MD_ALLOWED_ATTR = ["href", "title"];

if (window.DOMPurify) {
  DOMPurify.addHook("afterSanitizeAttributes", function (node) {
    if (node.tagName === "A") {
      node.setAttribute("target", "_blank");
      node.setAttribute("rel", "noopener noreferrer");
    }
  });
}

function renderMarkdown(md) {
  if (!md) return "";
  // Fail-closed: without DOMPurify the raw marked output (which passes
  // inline HTML through) must never reach innerHTML.
  if (!window.DOMPurify || !window.marked) return "<p>" + esc(md) + "</p>";
  try {
    var html = marked.parse(md);
    return DOMPurify.sanitize(html, { ALLOWED_TAGS: MD_ALLOWED_TAGS, ALLOWED_ATTR: MD_ALLOWED_ATTR });
  } catch (e) {
    return "<p>" + esc(md) + "</p>";
  }
}

export { renderMarkdown };
