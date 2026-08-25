/* 鉴权提示：Bearer Token 的录入与即时校验。设置面板与分享动作共用。 */

import { toast } from "./ui.js";
import { fetchSettings, getToken, setToken, clearToken } from "./api.js";

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

export { promptForToken };
