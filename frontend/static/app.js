/**
 * AI Daily News - Single-page app logic.
 * Vanilla JS + Alpine.js + htmx.
 *
 * State machine: loading | ready | not_generated | generating | empty_filter | error
 */

const API_BASE = "/api/v1";
const META_CACHE_KEY = "aidaily_meta";

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

    async init() {
      await this.loadMeta();
      await this.loadToday();
    },

    // ---- Meta (T050) ----
    async loadMeta() {
      // Try session cache first
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

    // ---- Polling (T051) ----
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

    // ---- Filtering (preview for US2 chips) ----
    filteredArticles() {
      return this.articles.filter((a) => {
        if (this.activeType && a.type !== this.activeType) return false;
        if (this.activeSource && a.src !== this.activeSource) return false;
        return true;
      });
    },

    toggleType(key) {
      this.activeType = this.activeType === key ? null : key;
    },
    toggleSource(key) {
      this.activeSource = this.activeSource === key ? null : key;
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

    // ---- Error handling ----
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
      setTimeout(() => { t.style.display = "none"; }, 3000);
    },
    retryLast() {
      if (!this.lastRequest) {
        this.loadToday();
        return;
      }
      if (this.lastRequest.type === "today") {
        this.loadToday();
      } else if (this.lastRequest.type === "detail" && this.lastRequest.id) {
        this.selectArticle({ id: this.lastRequest.id });
      }
    },
  };
}

window.dailyApp = dailyApp;
