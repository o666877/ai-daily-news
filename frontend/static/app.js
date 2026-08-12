/**
 * AI Daily News - Single-page app logic.
 * Vanilla JS + Alpine.js + htmx.
 *
 * State machine: loading | ready | not_generated | generating | empty_filter | error
 */

const API_BASE = "/api/v1";
const META_CACHE_KEY = "aidaily_meta";
const FILTER_DEBOUNCE_MS = 250;

// T083: business-code → UI behavior mapping
const CODE_UI_BEHAVIOR = {
  1001: "inline-form",       // missing param
  1002: "chip-inline",       // invalid enum (US2)
  1003: "login-redirect",    // unauthorized
  1004: "forbidden",         // forbidden
  1005: "inline-form",       // validation failed
  1006: "rate-limit-toast",  // rate limit
  2001: "block-empty",       // article not found
  2002: "block-loading",     // issue not generated (keep polling)
  2003: "block-generating",  // issue generating (skeleton + poll)
  9001: "global-error",      // internal error (retry)
  9002: "global-error",      // pipeline busy (retry)
};

// T085: token storage key (per spec)
const TOKEN_STORAGE_KEY = "AIDAILY_TOKEN";

/**
 * T082/T083/T085: unified fetch wrapper.
 * - Non-2xx → parse {code, message, requestId} and dispatch app:error
 * - Returns parsed JSON on success
 * - Stores last request descriptor for retry
 * - Special-cases 1003 → shows login panel; on submit retries with token
 * - Never exposes requestId to user (only console.log for debugging)
 */
async function apiFetch(url, opts = {}) {
  const isWrite = ["POST", "PUT", "DELETE", "PATCH"].includes((opts.method || "GET").toUpperCase());
  const token = localStorage.getItem(TOKEN_STORAGE_KEY) || "";
  const headers = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(opts.headers || {}),
  };

  // Cache the request descriptor for retry (T084)
  if (opts.cache !== false) {
    window.__aidailyLastRequest = { url, opts: { ...opts, headers } };
  }

  let res;
  try {
    res = await fetch(url, { ...opts, headers });
  } catch (e) {
    // Network failure: treat as 9001
    const err = { code: 9001, message: "网络异常", originalRequest: { url, opts }, status: 0 };
    window.dispatchEvent(new CustomEvent("app:error", { detail: err }));
    throw err;
  }

  if (res.ok) {
    // 204 No Content
    if (res.status === 204) return null;
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) {
      return await res.json();
    }
    return await res.text();
  }

  // Non-2xx: extract body
  let body = {};
  try {
    body = await res.json();
  } catch (_e) {
    body = { message: `HTTP ${res.status}` };
  }
  const code = Number(body.code) || 9001;
  const message = body.message || `HTTP ${res.status}`;
  // requestId is for logs only — never user-facing
  if (body.requestId) {
    console.log(`[app] requestId=${body.requestId} code=${code} ${url}`);
  }
  const err = {
    code,
    message,
    status: res.status,
    isWrite,
    originalRequest: { url, opts },
  };
  window.dispatchEvent(new CustomEvent("app:error", { detail: err }));
  const errToThrow = new Error(message);
  errToThrow.code = code;
  errToThrow.status = res.status;
  throw errToThrow;
}

function dailyApp() {
  return {
    state: "loading",
    issue: null,
    summary: null,
    articles: [],
    selectedArticle: null,
    detail: null,
    sources: [],
    types: [],
    errorMessage: "",
    activeType: null,
    activeSource: null,
    lastRequest: null,
    pollAttempts: 0,
    pollTimer: null,
    filterTimer: null,
    filterController: null,
    bearerToken: "",

    // T082/T083: chip-area inline message (1002)
    chipInlineError: "",
    // T083: inline form field error (1001/1005)
    inlineFormError: "",
    // T085: login panel state
    loginOpen: false,
    loginToken: "",
    loginError: "",
    // 1003 pending retry after login
    pendingRetry: null,

    async init() {
      this.bearerToken = localStorage.getItem(TOKEN_STORAGE_KEY) || "";
      window.addEventListener("app:error", (ev) => this.handleAppError(ev.detail));
      await this.loadMeta();
      await this.loadToday();
    },

    // ---- Meta (T050) ----
    async loadMeta() {
      const cached = sessionStorage.getItem(META_CACHE_KEY);
      if (cached) {
        try {
          const parsed = JSON.parse(cached);
          this.sources = parsed.sources || [];
          this.types = parsed.types || [];
          return;
        } catch (_e) { /* fall through */ }
      }
      try {
        const res = await fetch(`${API_BASE}/meta`);
        if (!res.ok) throw new Error(`meta failed: ${res.status}`);
        const data = await res.json();
        this.sources = data.sources || [];
        this.types = data.types || [];
        sessionStorage.setItem(META_CACHE_KEY, JSON.stringify(data));
      } catch (e) {
        this.sources = [];
        this.types = [];
        console.error("meta load failed", e);
      }
    },

    // ---- Today (T048) ----
    async loadToday() {
      this.state = "loading";
      this._showErrorPanel(false);
      this.lastRequest = { type: "today" };
      try {
        const res = await fetch(`${API_BASE}/daily/today`);
        if (res.status === 404) {
          const body = await res.json();
          if (body.code === 2002) {
            this.state = "not_generated";
            return;
          }
          this.state = "error";
          this.errorMessage = body.message || "今日刊不存在";
          return;
        }
        if (res.status === 409) {
          const body = await res.json();
          if (body.code === 2003) {
            this.state = "generating";
            this.startPolling();
            return;
          }
        }
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          this.state = "error";
          this.errorMessage = body.message || `HTTP ${res.status}`;
          return;
        }
        const data = await res.json();
        this.issue = data.issue;
        this.summary = data.summary;
        this.articles = data.articles || [];
        this.state = this.articles.length > 0 ? "ready" : "empty_filter";
        this.pollAttempts = 0;
      } catch (e) {
        this.state = "error";
        this.errorMessage = "网络异常";
        console.error(e);
      }
    },

    startPolling() {
      if (this.pollTimer) clearTimeout(this.pollTimer);
      if (this.pollAttempts >= 30) {
        this.state = "error";
        this.errorMessage = "轮询超时，请稍后再试";
        return;
      }
      const delay = Math.min(15000, 5000 * Math.pow(1.4, this.pollAttempts));
      this.pollTimer = setTimeout(async () => {
        this.pollAttempts++;
        await this.loadToday();
      }, delay);
    },

    // ---- Article detail (T049) ----
    async selectArticle(article) {
      this.selectedArticle = article;
      this.detail = null;
      this.lastRequest = { type: "detail", id: article.id };
      try {
        const res = await fetch(`${API_BASE}/articles/${article.id}`);
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          this.showError(body.message || `HTTP ${res.status}`);
          return;
        }
        this.detail = await res.json();
      } catch (e) {
        this.showError("网络异常");
        console.error(e);
      }
    },

    // ---- Share (T080) ----
    shareModalOpen: false,
    shareCard: null,
    shareBusy: false,
    shareCopyState: "",

    async shareCurrentArticle() {
      // T080: POST /api/v1/share with current articleId, show modal with cardUrl + title.
      if (!this.detail || !this.detail.id) return;
      this.shareBusy = true;
      this.shareCopyState = "";
      try {
        const token = this.bearerToken || localStorage.getItem("aidaily_token") || "";
        const headers = {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        };
        const res = await fetch(`${API_BASE}/share`, {
          method: "POST",
          headers,
          body: JSON.stringify({ articleId: this.detail.id }),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          this.showError(body.message || `分享失败: HTTP ${res.status}`);
          return;
        }
        this.shareCard = await res.json();
        this.shareModalOpen = true;
      } catch (e) {
        this.showError("分享请求失败");
        console.error(e);
      } finally {
        this.shareBusy = false;
      }
    },

    closeShareModal() {
      this.shareModalOpen = false;
      this.shareCopyState = "";
    },

    async copyShareUrl() {
      // T080: navigator.clipboard.writeText(cardUrl).
      if (!this.shareCard || !this.shareCard.cardUrl) return;
      try {
        await navigator.clipboard.writeText(this.shareCard.cardUrl);
        this.shareCopyState = "已复制";
        setTimeout(() => { if (this.shareCopyState === "已复制") this.shareCopyState = ""; }, 2000);
      } catch (e) {
        // Fallback for older browsers / non-secure contexts.
        const ta = document.createElement("textarea");
        ta.value = this.shareCard.cardUrl;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        try {
          document.execCommand("copy");
          this.shareCopyState = "已复制";
          setTimeout(() => { if (this.shareCopyState === "已复制") this.shareCopyState = ""; }, 2000);
        } catch (_e) {
          this.shareCopyState = "复制失败，请手动复制";
        } finally {
          document.body.removeChild(ta);
        }
      }
    },

    openShareInNewTab() {
      // T080: window.open(cardUrl, "_blank").
      if (!this.shareCard || !this.shareCard.cardUrl) return;
      window.open(this.shareCard.cardUrl, "_blank", "noopener,noreferrer");
    },

    // ---- Filtering (US2) ----
    isValidEnum(dimension, key) {
      const list = dimension === "type" ? this.types : this.sources;
      return Array.isArray(list) && list.some((x) => x.key === key);
    },

    scheduleFilteredFetch() {
      if (this.filterTimer) clearTimeout(this.filterTimer);
      this.filterTimer = setTimeout(() => this.fetchFiltered(), FILTER_DEBOUNCE_MS);
    },

    toggleType(key) {
      if (!this.isValidEnum("type", key)) {
        this.showError(`非法类型: ${key}`);
        return;
      }
      this.activeType = this.activeType === key ? null : key;
      this.scheduleFilteredFetch();
    },

    toggleSource(key) {
      if (!this.isValidEnum("source", key)) {
        this.showError(`非法来源: ${key}`);
        return;
      }
      this.activeSource = this.activeSource === key ? null : key;
      this.scheduleFilteredFetch();
    },

    async fetchFiltered() {
      if (this.filterController) this.filterController.abort();
      this.filterController = new AbortController();
      const params = new URLSearchParams();
      if (this.activeType) params.set("type", this.activeType);
      if (this.activeSource) params.set("src", this.activeSource);
      this.lastRequest = { type: "filter", params: params.toString() };
      this.state = "loading";
      try {
        const res = await fetch(`${API_BASE}/articles?${params.toString()}`, {
          signal: this.filterController.signal,
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          this.showError(body.message || `HTTP ${res.status}`);
          return;
        }
        const data = await res.json();
        this.articles = data.items || [];
        this.state = this.articles.length > 0 ? "ready" : "empty_filter";
      } catch (e) {
        if (e.name === "AbortError") return;
        this.showError("网络异常");
        console.error(e);
      }
    },

    isActiveType(key) { return this.activeType === key; },
    isActiveSource(key) { return this.activeSource === key; },

    typeLabel(key) {
      const t = this.types.find((x) => x.key === key);
      return t ? t.shortName : key;
    },
    srcLabel(key) {
      const s = this.sources.find((x) => x.key === key);
      return s ? s.short : key;
    },

    // ---- Status badge helpers ----
    statusBadgeClass() {
      const map = {
        ready: "ready",
        generating: "generating",
        not_generated: "not_generated",
        loading: "generating",
        empty_filter: "ready",
        error: "not_generated",
      };
      return map[this.state] || "not_generated";
    },
    statusBadgeText() {
      const map = {
        ready: "已就绪",
        generating: "生成中",
        not_generated: "未生成",
        loading: "加载中",
        empty_filter: "无匹配",
        error: "异常",
      };
      return map[this.state] || "未生成";
    },

    // ---- Error handling (T082/T083/T084/T085) ----
    showError(msg) {
      this.state = "error";
      this.errorMessage = msg;
      this.showToast(msg);
    },
    showToast(msg) {
      const t = document.querySelector(".toast");
      if (!t) return;
      t.textContent = msg;
      t.style.display = "block";
      t.setAttribute("data-visible", "1");
      clearTimeout(this._toastTimer);
      this._toastTimer = setTimeout(() => {
        t.style.display = "none";
        t.removeAttribute("data-visible");
      }, 3000);
    },

    /**
     * T083: dispatch table for business codes.
     * Called by the apiFetch wrapper's app:error event.
     */
    handleAppError(detail) {
      if (!detail) return;
      const code = Number(detail.code) || 9001;
      const message = detail.message || "服务内部错误";
      const behavior = CODE_UI_BEHAVIOR[code] || "toast";

      // 1003 → login panel (only for write endpoints per spec T085)
      if (behavior === "login-redirect") {
        if (detail.isWrite) {
          this.openLoginPanel(detail.originalRequest);
        } else {
          this.showError(message);
        }
        return;
      }

      switch (behavior) {
        case "inline-form":
          this.inlineFormError = message;
          this.showToast(message);
          break;
        case "chip-inline":
          this.chipInlineError = message;
          this.showToast(message);
          break;
        case "rate-limit-toast":
          this.showToast("操作太频繁，稍后再试");
          break;
        case "block-empty":
          // 2001: content not found — block-level empty state
          this.state = "empty_filter";
          this.errorMessage = "内容不存在";
          break;
        case "block-loading":
          // 2002: not generated — keep showing loading state
          this.state = "not_generated";
          this.errorMessage = "正在翻今天的墙头…";
          break;
        case "block-generating":
          // 2003: generating — skeleton + continue polling
          this.state = "generating";
          this.startPolling();
          break;
        case "global-error":
          // 9001/9002 — show global error panel with retry
          this.state = "error";
          this.errorMessage = "服务开了小差";
          this._showErrorPanel(true);
          break;
        case "forbidden":
          this.state = "error";
          this.errorMessage = message;
          this.showToast(message);
          break;
        default:
          this.showToast(message);
      }
    },

    _showErrorPanel(visible) {
      const panel = document.querySelector(".error-panel");
      if (!panel) return;
      panel.style.display = visible ? "flex" : "none";
    },

    // T084: retry last failed request, preserving filters & settings context.
    retryLast() {
      // Hide error panel first.
      this._showErrorPanel(false);
      // Prefer the cached request descriptor from apiFetch.
      const cached = window.__aidailyLastRequest;
      if (cached) {
        const { url, opts } = cached;
        // Strip any body if it was an AbortController-bound request.
        const safeOpts = { ...opts };
        delete safeOpts.signal;
        this._replayRequest(url, safeOpts);
        return;
      }
      // Fallback to local lastRequest state for back-compat with T048-T049 callers.
      if (!this.lastRequest) {
        this.loadToday();
        return;
      }
      if (this.lastRequest.type === "today") {
        this.loadToday();
      } else if (this.lastRequest.type === "detail" && this.lastRequest.id) {
        this.selectArticle({ id: this.lastRequest.id });
      } else if (this.lastRequest.type === "filter") {
        this.fetchFiltered();
      }
    },

    async _replayRequest(url, opts) {
      // Map back to the high-level handlers so state stays consistent.
      try {
        if (url === `${API_BASE}/daily/today`) {
          await this.loadToday();
        } else if (url.startsWith(`${API_BASE}/articles/`) && (!opts.method || opts.method === "GET")) {
          const id = url.split("/").pop();
          await this.selectArticle({ id });
        } else if (url.startsWith(`${API_BASE}/articles`) && (!opts.method || opts.method === "GET")) {
          await this.fetchFiltered();
        } else {
          // Generic replay for write endpoints (PUT /settings, POST /share, etc.)
          await apiFetch(url, { ...opts, cache: false });
        }
      } catch (e) {
        console.error("retry failed", e);
      }
    },

    // T085: 1003 → login panel → cache token → retry
    openLoginPanel(pendingRequest) {
      this.loginError = "";
      this.loginToken = localStorage.getItem(TOKEN_STORAGE_KEY) || "";
      this.pendingRetry = pendingRequest || null;
      this.loginOpen = true;
    },
    closeLoginPanel() {
      this.loginOpen = false;
      this.pendingRetry = null;
    },
    async submitLogin() {
      const token = (this.loginToken || "").trim();
      if (!token) {
        this.loginError = "请输入令牌";
        return;
      }
      localStorage.setItem(TOKEN_STORAGE_KEY, token);
      this.bearerToken = token;
      this.loginError = "";
      const pending = this.pendingRetry;
      this.closeLoginPanel();
      // Retry the original request with the new token.
      if (pending && pending.url) {
        const safeOpts = { ...(pending.opts || {}) };
        delete safeOpts.signal;
        // Force a fresh fetch (don't re-cache the old descriptor).
        await this._replayRequest(pending.url, safeOpts);
      } else {
        // No specific pending request — re-fetch today.
        await this.loadToday();
      }
    },
  };
}

// ---- Settings panel (T070-T073) ----
function settingsHelpers() {
  return {
    settingsOpen: false,
    settingsSaving: false,
    settingsFormError: "",
    settingsForm: {
      sources: {},
      types: {},
      dailyPush: { enabled: true, time: "08:00" },
    },

    async openSettings() {
      // T070: backfill from /settings using cached token (local user session)
      this.settingsFormError = "";
      this.settingsOpen = true;
      try {
        const token = this.bearerToken || localStorage.getItem("aidaily_token") || "";
        const headers = token ? { Authorization: `Bearer ${token}` } : {};
        const res = await fetch(`${API_BASE}/settings`, { headers });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          this.showError(body.message || `加载偏好失败: HTTP ${res.status}`);
          this.settingsOpen = false;
          return;
        }
        const data = await res.json();
        this.backfillSettingsForm(data);
      } catch (e) {
        this.showError("加载偏好失败");
        this.settingsOpen = false;
        console.error(e);
      }
    },

    closeSettings() {
      this.settingsOpen = false;
      this.settingsFormError = "";
    },

    backfillSettingsForm(data) {
      // Initialize all source/type keys to true (defensive) before merging server response
      const sources = {};
      const types = {};
      for (const s of this.sources) sources[s.key] = true;
      for (const t of this.types) types[t.key] = true;
      Object.assign(sources, data.sources || {});
      Object.assign(types, data.types || {});
      this.settingsForm = {
        sources,
        types,
        dailyPush: {
          enabled: !!(data.dailyPush && data.dailyPush.enabled),
          time: (data.dailyPush && data.dailyPush.time) || "08:00",
        },
      };
    },

    async saveSettings() {
      // T071: PUT full body, read X-Effective-At, show toast
      this.settingsSaving = true;
      this.settingsFormError = "";
      try {
        // T073: client-side HH:mm pattern check
        const re = /^([01]\d|2[0-3]):[0-5]\d$/;
        if (!re.test(this.settingsForm.dailyPush.time)) {
          this.settingsFormError = "dailyPush.time 必须是 HH:mm 24 小时制（00:00 – 23:59）";
          this.settingsSaving = false;
          return;
        }
        const token = this.bearerToken || localStorage.getItem("aidaily_token") || "";
        const headers = {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        };
        const res = await fetch(`${API_BASE}/settings`, {
          method: "PUT",
          headers,
          body: JSON.stringify(this.settingsForm),
        });
        if (res.status === 401) {
          this.showError("未认证或 token 失效");
          this.settingsSaving = false;
          return;
        }
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          if (body.code === 1005) {
            this.settingsFormError = body.message || "请求体校验失败";
          } else {
            this.showError(body.message || `保存失败: HTTP ${res.status}`);
          }
          this.settingsSaving = false;
          return;
        }
        const eff = res.headers.get("X-Effective-At") || res.headers.get("x-effective-at");
        let formatted = eff;
        if (eff && /^\d{8}$/.test(eff)) {
          formatted = `${eff.slice(0, 4)}-${eff.slice(4, 6)}-${eff.slice(6, 8)}`;
        }
        this.showToast(
          formatted
            ? `明天的日报将按新口味调配（生效刊期: ${formatted}）`
            : "明天的日报将按新口味调配"
        );
        this.closeSettings();
      } catch (e) {
        this.showError("保存失败");
        console.error(e);
      } finally {
        this.settingsSaving = false;
      }
    },

    async resetSettings() {
      // T072: POST /settings/reset, backfill, toast
      this.settingsSaving = true;
      this.settingsFormError = "";
      try {
        const token = this.bearerToken || localStorage.getItem("aidaily_token") || "";
        const headers = token ? { Authorization: `Bearer ${token}` } : {};
        const res = await fetch(`${API_BASE}/settings/reset`, {
          method: "POST",
          headers,
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          this.showError(body.message || `恢复默认失败: HTTP ${res.status}`);
          this.settingsSaving = false;
          return;
        }
        const data = await res.json();
        this.backfillSettingsForm(data);
        const effHeader = res.headers.get("X-Effective-At") || res.headers.get("x-effective-at");
        let formatted = effHeader;
        if (effHeader && /^\d{8}$/.test(effHeader)) {
          formatted = `${effHeader.slice(0, 4)}-${effHeader.slice(4, 6)}-${effHeader.slice(6, 8)}`;
        }
        this.showToast(
          formatted ? `已恢复默认（生效刊期: ${formatted}）` : "已恢复默认"
        );
      } catch (e) {
        this.showError("恢复默认失败");
        console.error(e);
      } finally {
        this.settingsSaving = false;
      }
    },
  };
}

const _origDailyApp = dailyApp;
function dailyAppWithSettings() {
  return Object.assign(_origDailyApp(), settingsHelpers({}));
}
window.dailyApp = dailyAppWithSettings;
