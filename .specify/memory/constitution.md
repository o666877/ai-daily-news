<!--
Sync Impact Report
==================
- Version change: (uninitialized template) → 1.0.0
  Rationale: First ratification. Placeholders replaced with concrete principles;
  semantic version starts at 1.0.0 per Spec Kit convention for initial adoption.
- Modified principles: N/A (initial adoption; template placeholders resolved)
  - [PRINCIPLE_1_*] → I. Code Quality
  - [PRINCIPLE_2_*] → II. Testing Standards
  - [PRINCIPLE_3_*] → III. User Experience Consistency
  - [PRINCIPLE_4_*] → IV. Performance Requirements
  - [PRINCIPLE_5_*] → removed (user requested exactly four principle areas)
- Added sections:
  - Section 2: Quality Gates (replaces [SECTION_2_*])
  - Section 3: Development Workflow (replaces [SECTION_3_*])
  - Governance section body
- Removed sections: none
- Follow-up TODOs: Replace `my-project` with the real product name once known.
-->

# my-project Constitution

## Core Principles

### I. Code Quality

All production code MUST be readable, well-named, and small in scope.

- Functions MUST stay under 50 lines. Files SHOULD stay under 400 lines and MUST NOT exceed 800 lines without an approved justification in the PR description.
- Nesting MUST NOT exceed four levels; deeper logic MUST be refactored into named helpers.
- Data MUST be treated as immutable: produce new objects rather than mutate in place.
- Hardcoded values (URLs, timeouts, magic numbers, secrets) MUST be promoted to constants or configuration.
- Every system boundary (user input, external API responses, file/network data) MUST be validated with explicit schemas; internal code MAY rely on typed contracts.
- Errors MUST be handled explicitly at every level; user-facing messages MUST be friendly and actionable, server logs MUST contain full context. Silently swallowing errors is forbidden.
- Public APIs MUST use a consistent envelope (`success`, `data`, `error`, optional pagination metadata).

**Rationale**: Uniform quality lowers review friction, prevents regression clusters, and keeps the codebase safe for concurrent change.

### II. Testing Standards

Test-first development is NON-NEGOTIABLE for behavior-bearing code.

- TDD cycle (Red → Green → Refactor) MUST be followed for new logic and bug fixes. Tests are written first, demoed to fail, then made to pass.
- Coverage MUST remain at or above 80% across unit, integration, and end-to-end suites combined.
- Three layers of tests are mandatory:
  - **Unit tests** for functions, utilities, and components.
  - **Integration tests** for API endpoints, repository contracts, and database operations.
  - **E2E tests** for critical user flows; framework chosen per language/platform.
- Tests MUST be isolated and deterministic. Mocks MUST target boundaries only — never fake the database or core domain in integration tests.
- When a test fails, the implementation is fixed (not the test), unless the test itself encodes a wrong expectation.

**Rationale**: Tests are the executable specification of the system. Without them, refactoring is gambling.

### III. User Experience Consistency

The product MUST feel like one product across every surface.

- A single, versioned design system is the only source of truth for tokens (color, typography, spacing, motion), components, and interaction patterns. Reuse MUST come before bespoke styling.
- Visual and interaction consistency MUST hold across responsive breakpoints, themes (light/dark), locales, and accessibility modes.
- Accessibility is part of UX, not optional: WCAG 2.1 AA is the floor. Keyboard navigation, focus management, color contrast, and screen-reader semantics MUST be verified for every user-facing change.
- Copy MUST use one shared voice and glossary; the same action MUST be labeled consistently everywhere.
- Loading, empty, error, and success states MUST be designed and shipped together with the happy path — never deferred.
- Friction MUST be measurable: every new UX flow SHOULD declare its target metric (TTHW, completion rate, error rate) and ship with instrumentation.

**Rationale**: Inconsistency erodes trust faster than bugs do; users learn patterns, not screens.

### IV. Performance Requirements

Performance is a feature and is enforced via budgets and continuous measurement.

- Every user-facing surface MUST declare performance budgets for the metrics that matter to it (e.g., Core Web Vitals: LCP, INP, CLS; backend p50/p95/p99 latency; cold-start time; bundle size).
- Performance MUST NOT regress on critical paths: a regression beyond the documented budget blocks merge until remediated or until the budget is explicitly re-negotiated.
- Optimizations MUST be evidence-driven: profile first, optimize the measured bottleneck, then re-measure. Speculative micro-optimization is forbidden.
- Expensive operations MUST be deferred, paginated, cached, or moved off the critical path; blocking work on user-facing threads MUST be justified.
- Performance budgets, baselines, and benchmarks MUST live alongside the code and be exercised in CI on every change.

**Rationale**: Users perceive speed as correctness. Performance regressions, once baked in, are expensive to reverse.

## Quality Gates

The following gates MUST pass before any change merges:

- Lint and type checks are green on all touched files.
- Unit, integration, and E2E test suites are green; coverage delta does not drop below 80%.
- Performance budgets are unchanged or, if regressed, carry an approved exemption.
- Security checklist passes: no hardcoded secrets; inputs validated; no injection or XSS vectors; authN/authZ verified; rate limiting present; error messages leak no sensitive data.
- Accessibility checklist passes for user-facing changes (keyboard, contrast, ARIA, focus, screen-reader spot-check).
- Public API changes include updated contracts, examples, and migration notes where breaking.

## Development Workflow

- Trunk-based development with short-lived feature branches; pull requests are the unit of review.
- Commits follow Conventional Commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`, `perf:`, `ci:`). Atomic commits — one logical change per commit.
- Every PR description MUST include: summary of changes, test plan, and explicit notes on performance, security, and UX impact.
- Code review MUST evaluate correctness, readability, architecture, security, and performance — not style preferences. Reviewers MAY block on any of these axes.
- A change is shippable only when the Quality Gates pass AND at least one reviewer approves.
- Feature flags MUST be used to decouple deploy from release for risky or incremental work.

## Governance

- This Constitution supersedes ad-hoc practices on `my-project`. Where this document and another guide disagree, this document prevails.
- Amendments MUST be proposed as a PR that:
  1. States the change and its rationale,
  2. Bumps `CONSTITUTION_VERSION` per semantic versioning (MAJOR for principle removals/redefinitions, MINOR for additions/material expansion, PATCH for clarifications),
  3. Updates `LAST_AMENDED_DATE` to the merge date,
  4. Includes a migration plan for any code or docs that the amendment invalidates.
- Every PR MUST self-certify compliance with the four Core Principles and the Quality Gates; reviewers MUST verify that certification.
- Complexity beyond what the task requires MUST be justified in the PR description; premature abstraction is a defect.
- Operational development guidance, conventions, and recipes live in the project's guidance files (e.g., `CLAUDE.md`, `README.md`, and any `.claude/rules/*.md`) — this Constitution governs principles only.

**Version**: 1.0.0 | **Ratified**: 2026-08-09 | **Last Amended**: 2026-08-09
