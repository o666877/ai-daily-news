/* API 层：token 管理 + 各端点封装。401 统一转 code 1003 needAuth 错误。 */

import { state, typeToBackend } from "./state.js";

var API_BASE = "/api/v1";
var TOKEN_KEY = "AIDAILY_TOKEN";

function getToken() { try { return localStorage.getItem(TOKEN_KEY) || ""; } catch (e) { return ""; } }
function setToken(t) { try { localStorage.setItem(TOKEN_KEY, t); } catch (e) {} }
function clearToken() { try { localStorage.removeItem(TOKEN_KEY); } catch (e) {} }

function authHeaders(extra) {
  var h = Object.assign({}, extra || {});
  var t = getToken();
  if (t) h["Authorization"] = "Bearer " + t;
  return h;
}

function _errFromResponse(r, fallbackCode) {
  return r.json().catch(function () { return { code: r.status, message: r.statusText }; }).then(function (e) {
    throw Object.assign(new Error(e.message || ("HTTP " + r.status)), { code: e.code || fallbackCode });
  });
}

function api(path, opts) {
  opts = opts || {};
  return fetch(API_BASE + path, Object.assign({}, opts, { headers: authHeaders(opts.headers) }))
    .then(function (r) {
      if (r.status === 401) {
        clearToken();
        return r.json().catch(function () { return { code: 1003, message: "未认证" }; }).then(function (e) {
          throw Object.assign(new Error(e.message || "未认证"), { code: 1003, needAuth: true });
        });
      }
      if (!r.ok) return _errFromResponse(r, r.status);
      if (r.status === 204) return null;
      return r.json();
    });
}

function fetchToday() { return api("/daily/today"); }

function fetchArticles(params) {
  var qs = new URLSearchParams();
  if (state.issueId) qs.set("issueId", state.issueId);
  if (params && params.type && params.type !== "all") qs.set("type", typeToBackend(params.type));
  if (params && params.src && params.src !== "all") qs.set("src", params.src);
  qs.set("pageSize", "50");
  return api("/articles?" + qs.toString());
}

function fetchArticle(id) { return api("/articles/" + encodeURIComponent(id)); }
function fetchSettings() { return api("/settings"); }

function saveSettings(body) {
  return fetch(API_BASE + "/settings", {
    method: "PUT",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body)
  }).then(function (r) {
    if (r.status === 401) { clearToken(); throw Object.assign(new Error("未认证"), { code: 1003, needAuth: true }); }
    if (!r.ok) {
      return r.json().catch(function () { return { code: r.status, message: r.statusText }; }).then(function (e) {
        throw Object.assign(new Error(e.message || ("HTTP " + r.status)), { code: e.code || r.status });
      });
    }
    return r.json().then(function (b) { return { body: b, effectiveAt: r.headers.get("X-Effective-At") }; });
  });
}

function resetSettingsApi() {
  return fetch(API_BASE + "/settings/reset", { method: "POST", headers: authHeaders() })
    .then(function (r) {
      if (r.status === 401) { clearToken(); throw Object.assign(new Error("未认证"), { code: 1003, needAuth: true }); }
      if (!r.ok) throw Object.assign(new Error("HTTP " + r.status), { code: r.status });
      return r.json();
    });
}

function shareArticleApi(articleId) {
  return fetch(API_BASE + "/share", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ articleId: articleId })
  }).then(function (r) {
    if (r.status === 401) { clearToken(); throw Object.assign(new Error("未认证"), { code: 1003, needAuth: true }); }
    if (!r.ok) {
      return r.json().catch(function () { return { code: r.status, message: r.statusText }; }).then(function (e) {
        throw Object.assign(new Error(e.message || ("HTTP " + r.status)), { code: e.code || r.status });
      });
    }
    return r.json();
  });
}

export {
  fetchToday, fetchArticles, fetchArticle, fetchSettings, saveSettings,
  resetSettingsApi, shareArticleApi, getToken, setToken, clearToken
};
