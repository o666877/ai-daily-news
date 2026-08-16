# Security Checklist: 002 日报个性化

**Purpose**: Validate security posture for 002 personalization extension.
**Created**: 2026-08-13
**Feature**: 002-daily-personalization

## Mandatory Checks

- [x] No hardcoded secrets (API keys, passwords, tokens) — all via env vars
- [x] All user inputs validated — `dailyCount` and `styleMode` use Pydantic Literal
- [x] SQL injection prevention — all queries use SQLAlchemy ORM with parameterized queries
- [x] XSS prevention — frontend uses existing `esc()` helper for dynamic content
- [x] CSRF protection enabled — PUT /settings requires Bearer token (existing 001 mechanism)
- [x] Authentication/authorization verified — settings endpoints already gated by Bearer
- [x] Rate limiting on all endpoints — inherited from 001 (120/min read, 30/min write)
- [x] Error messages don't leak sensitive data — `{code, message, requestId}` envelope

## Feature-Specific Checks

- [x] New `article_scores` table has FK CASCADE — no orphan rows
- [x] New `daily_count` / `style_mode` columns validated by Pydantic Literal — invalid values rejected with 1005
- [x] New Score response object uses null-safe serialization (legacy rows without score handled)
- [x] Composite score is computed from rule-based authority + LLM-suggested dims — no client-side manipulation
- [x] Dedup layer is server-side only (no client API) — no spoofing risk
- [x] `state.currentStyle` (temporary switch) is in-memory only — not persisted to localStorage (spec compliance + no stale client state)

## Notes

- All settings endpoints inherited from 001 require Bearer auth — unchanged.
- Article detail endpoint is read-anonymous — score object is public info, no PII leak.
- Score source field (`llm` / `rule_fallback`) is debugging info; no security implication.
