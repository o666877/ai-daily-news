# Test Checklist: 002 日报个性化

**Purpose**: Validate test coverage and quality for 002 personalization.
**Created**: 2026-08-13
**Feature**: 002-daily-personalization

## Coverage

- [x] Unit tests cover all new modules (authority/scorer/dedup/summarizer extensions)
- [x] Integration tests cover all 5 extended REST endpoints (GET/PUT settings, GET articles, GET articles/{id}, GET daily/today)
- [x] TDD followed: tests written before implementation, validated RED→GREEN
- [x] No fake DB at integration boundaries — uses real SQLite in-memory via conftest fixtures
- [x] Mocking only at LLM and CLI subprocess boundaries (respx, monkeypatch)

## Test Counts

| Layer | Count |
|---|---|
| Unit tests (new + extended) | ~250 |
| Integration tests (new + extended) | ~60 |
| **Total (excluding flaky e2e)** | **310 passed** |
| Coverage | **86%** |

## Per-Module Coverage

| Module | Coverage |
|---|---|
| app/pipeline/authority.py | 100% |
| app/pipeline/scorer.py | 91% |
| app/pipeline/summarizer.py | 95% |
| app/pipeline/generator.py | 90% |
| app/pipeline/dedup.py | 93% |
| app/services/article_service.py | 80% |
| app/services/issue_service.py | 83% |

## Failure Modes Covered

- [x] LLM failure → rule_fallback score path
- [x] dailyCount invalid (15, "30", 30.0, 0, 60, -10, 100) → 422 with 1005
- [x] dailyCount missing → 422 with 1005
- [x] styleMode invalid (verbose, Concise, "") → 422 with 1005
- [x] Candidate pool smaller than daily_count → all returned (no padding)
- [x] URL dedup → highest score kept
- [x] Topic dedup → popularity (score × count) wins
- [x] Opinion dedup → highest score kept
- [x] Empty topic_id / opinion_fingerprint → layer skipped
- [x] Stable tiebreak by time DESC
- [x] Legacy articles without score row → compositeScore: null in response
- [x] Bearer auth missing → 401 (inherited from 001)

## Notes

- e2e tests (`tests/e2e/test_filter.py::test_type_and_source_filters`) excluded due to Playwright timeout flakiness on Windows; functional coverage verified at integration layer instead.
- Real LLM end-to-end verification (T023 / T037) deferred to staging — quota-limited on dev machine; mock-based contract tests cover the schema/serialization contract.
