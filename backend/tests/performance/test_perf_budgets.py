"""Performance budget tests (Constitution IV).

Validates P95 latency budgets for the three read endpoints that dominate the
happy-path UX. Tagged with `@pytest.mark.perf` so they can be skipped in fast
CI lanes (`pytest -m "not perf"`).

Budgets (per `contracts/*.md`):
    GET /daily/today      P95 ≤ 500 ms   (12-article fixture)
    GET /articles         P95 ≤ 300 ms   (filter + paginate)
    GET /articles/{id}    P95 ≤ 200 ms

Approach:
    Uses `pytest-asyncio` + `httpx.ASGITransport` against the real FastAPI app
    with an in-memory SQLite seeded with 12 articles. Each test issues N=50
    requests, records wall-clock latency, asserts the 95th percentile is within
    budget. No `pytest-benchmark` machinery needed — these are latency probes,
    not microbenchmarks.

Note:
    Local runs on developer machines may be noisier; treat thresholds as
    "regression guardrails" — a 50% overshoot fails reliably, a 5% wobble
    typically passes. CI runners (ubuntu-latest) are more stable.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra import db as db_module
from app.infra.db import init_db
from app.models.article import ArticleORM
from app.models.daily_issue import DailyIssueORM

# ---------------------------------------------------------------------------
# Marker registration (so `-m perf` works without warnings).
# ---------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "perf: performance budget test (Constitution IV)")


# ---------------------------------------------------------------------------
# Seeded fixture: 12 articles across all 4 sources × all 4 types.
# ---------------------------------------------------------------------------


_PERF_SOURCES = ["x", "github", "reddit", "web"]
_PERF_TYPES = ["agent", "self_improve", "open_source", "tools"]


def _make_article(idx: int, src: str, type_: str, issue_id: str) -> ArticleORM:
    """Construct a deterministic ArticleORM for the perf fixture."""
    return ArticleORM(
        id=f"{issue_id}-{idx:04d}",
        issue_id=issue_id,
        type=type_,
        src=src,
        title=f"Article {idx} - {src}/{type_}",
        excerpt=f"Excerpt for article {idx}.",
        lede=f"Lede paragraph for article {idx}.",
        summary=f"One-line summary for {idx}.",
        body=f"Body paragraph 1 of {idx}.\n\nBody paragraph 2 of {idx}.",
        quote="Quote snippet" if idx % 2 == 0 else None,
        points=[f"Point 1 of {idx}", f"Point 2 of {idx}", f"Point 3 of {idx}"],
        time=f"{8 + (idx % 12):02d}:{(idx * 7) % 60:02d}",
        source_url=f"https://example.com/{src}/{idx}",
        source_name=f"{src}.example.com",
        reading_minutes=2 + (idx % 8),
        published_at=datetime(2026, 8, 12, 8, 0, tzinfo=UTC).isoformat(),
    )


@pytest_asyncio.fixture
async def perf_client(monkeypatch, tmp_path) -> AsyncIterator[AsyncClient]:
    """A client against an in-memory SQLite seeded with 12 articles."""
    # Isolated settings.
    monkeypatch.setenv("AIDAILY_DB_PATH", ":memory:")
    monkeypatch.setenv("AIDAILY_LLM_API_KEY", "test-key")
    monkeypatch.setenv("AIDAILY_LLM_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("AIDAILY_LLM_MODEL", "claude-test")
    monkeypatch.setenv("AIDAILY_BEARER_TOKEN", "test-bearer-token")
    monkeypatch.setenv("AIDAILY_TZ", "UTC")
    monkeypatch.setenv("AIDAILY_DAILY_PUSH_TIME", "08:00")
    from app.config import reset_settings_cache

    reset_settings_cache()
    db_module._engine = None
    db_module._session_factory = None

    # Build engine + tables.
    engine = db_module.make_engine(":memory:")
    await init_db(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    db_module._engine = engine
    db_module._session_factory = factory

    # Seed 12 articles (4 src × 3 type to vary distribution).
    issue_id = datetime.now(UTC).strftime("%Y%m%d")
    async with factory() as session:
        session.add(
            DailyIssueORM(
                id=issue_id,
                date=issue_id,
                edition=1,
                status="ready",
                generated_at=datetime.now(UTC),
                filters_applied={
                    "sources": _PERF_SOURCES,
                    "types": _PERF_TYPES,
                },
            )
        )
        await session.commit()
        for idx in range(1, 13):
            src = _PERF_SOURCES[idx % 4]
            type_ = _PERF_TYPES[idx % 4]
            session.add(_make_article(idx, src, type_, issue_id))
        await session.commit()

    # Build app with session override pointing at our factory.
    from app.main import create_app

    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    from app.infra.db import get_session as real_get_session

    app.dependency_overrides[real_get_session] = _override_session

    class _NoopLifespan:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *args):
            return None

    app.router.lifespan_context = lambda _app: _NoopLifespan()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://perf") as ac:
        yield ac

    await engine.dispose()
    reset_settings_cache()
    db_module._engine = None
    db_module._session_factory = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _percentile(samples: list[float], pct: float) -> float:
    """Compute the pct-th percentile (0-100) from a list of ms samples."""
    if not samples:
        return float("inf")
    sorted_samples = sorted(samples)
    k = max(0, min(len(sorted_samples) - 1, int(round((pct / 100.0) * (len(sorted_samples) - 1)))))
    return sorted_samples[k]


async def _measure_latency_ms(coro_factory, n: int = 50) -> list[float]:
    """Issue n requests, return latencies in ms."""
    samples: list[float] = []
    for _ in range(n):
        start = time.perf_counter()
        await coro_factory()
        samples.append((time.perf_counter() - start) * 1000.0)
    return samples


# ---------------------------------------------------------------------------
# Budget tests
# ---------------------------------------------------------------------------


@pytest.mark.perf
async def test_daily_today_p95_under_500ms(perf_client: AsyncClient) -> None:
    """GET /daily/today P95 ≤ 500ms (12-article fixture)."""
    samples = await _measure_latency_ms(
        lambda: perf_client.get("/api/v1/daily/today"),
        n=50,
    )
    p95 = _percentile(samples, 95)
    assert p95 <= 500.0, (
        f"P95 latency budget breach: /daily/today P95={p95:.1f}ms > 500ms. "
        f"Samples: n={len(samples)}, median={_percentile(samples, 50):.1f}ms."
    )


@pytest.mark.perf
async def test_articles_filter_p95_under_300ms(perf_client: AsyncClient) -> None:
    """GET /articles?type=agent&src=reddit P95 ≤ 300ms."""
    samples = await _measure_latency_ms(
        lambda: perf_client.get("/api/v1/articles?type=agent&src=reddit"),
        n=50,
    )
    p95 = _percentile(samples, 95)
    assert p95 <= 300.0, (
        f"P95 latency budget breach: /articles?type=agent&src=reddit P95={p95:.1f}ms > 300ms."
    )


@pytest.mark.perf
async def test_article_detail_p95_under_200ms(perf_client: AsyncClient) -> None:
    """GET /articles/{id} P95 ≤ 200ms."""
    # First fetch the list to learn a valid id.
    resp = await perf_client.get("/api/v1/articles")
    assert resp.status_code == 200
    items = resp.json().get("items", [])
    assert items, "fixture must seed at least one article for detail probe"
    article_id = items[0]["id"]

    samples = await _measure_latency_ms(
        lambda: perf_client.get(f"/api/v1/articles/{article_id}"),
        n=50,
    )
    p95 = _percentile(samples, 95)
    assert p95 <= 200.0, (
        f"P95 latency budget breach: /articles/{article_id} P95={p95:.1f}ms > 200ms."
    )


# ---------------------------------------------------------------------------
# Smoke test (always run, no budget check) — confirms endpoints wire up.
# ---------------------------------------------------------------------------


async def test_perf_endpoints_respond(perf_client: AsyncClient) -> None:
    """Smoke check: all three perf target endpoints return 200 (no perf gate)."""
    r1 = await perf_client.get("/api/v1/daily/today")
    assert r1.status_code == 200, r1.text

    r2 = await perf_client.get("/api/v1/articles?type=agent&src=reddit")
    assert r2.status_code == 200, r2.text

    items = r2.json().get("items", [])
    if items:
        r3 = await perf_client.get(f"/api/v1/articles/{items[0]['id']}")
        assert r3.status_code == 200, r3.text


# Avoid unused-import warning for asyncio (referenced indirectly via fixtures).
_ = asyncio
