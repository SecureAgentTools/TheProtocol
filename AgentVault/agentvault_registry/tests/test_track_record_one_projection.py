"""§MARKSURFACES (2026-09-10) — ONE projection, and its keys are a contract with the FE.

Why this test exists, and why it is about NAMES rather than numbers:

`services/api/trackRecord.ts::compactFromSummary` carries a warning in its own docstring
about this exact class — *"an earlier cut spelled one name in one place and the other
elsewhere, and the globe silently rendered no earned mark at all"* (`jobs_verified` vs
`jobs`). Nothing threw. The ring simply did not appear.

Until today the compact row was built INLINE inside `/agent-cards/discover`, so that was
the only endpoint that could show a mark. It is now `compact_track_record`, read by the
discover feed, `/developers/me/agents`, `/agents/by-did` and the reputation rankings — one
fact, one name, four surfaces. A key renamed here now breaks a test instead of quietly
emptying four rings.
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@localhost:5432/ci")
os.environ.setdefault("API_KEY_SECRET", "ci-dummy-secret-0123456789abcdef")

from agentvault_registry.services.track_record import compact_track_record  # noqa: E402

# The exact field names `earnedMarks()` and the discovery chips read.
# services/api/trackRecord.ts: TrackRecordCompact
FE_COMPACT_KEYS = {
    "jobs", "stars", "five_star", "on_time_met", "on_time_of", "traveled",
    "cross_registry", "disputes", "open_disputes", "lost_disputes", "last_verified_at",
}


def _summary(**over):
    s = {
        "jobs_verified": 250, "local_jobs": 250, "traveled_jobs": 0,
        "avg_stars": 4.58, "five_star": 156,
        "on_time": {"met": 240, "of": 250},
        "disputes": {"total": 0, "lost": 0, "open": 0},
        "volume": [{"currency": "ECU", "total": "8.0000000000", "jobs": 250}],
        "cross_registry_jobs": 0, "distinct_hosts": 0,
        "distinct_posters": 3, "repeat_poster_jobs": 247,
        "first_verified_at": "2026-09-07T10:24:00+00:00",
        "last_verified_at": "2026-09-09T23:44:04+00:00",
    }
    s.update(over)
    return s


def test_the_projection_carries_exactly_the_keys_the_frontend_reads():
    out = compact_track_record(_summary())
    assert set(out) == FE_COMPACT_KEYS, (
        f"missing={FE_COMPACT_KEYS - set(out)} unexpected={set(out) - FE_COMPACT_KEYS}"
    )


def test_the_ladder_reads_the_right_number():
    """`earnedMarks()` keys the tier off `jobs`, which is jobs_verified — local plus
    traveled. Sovereign is 250. This is the number a reader sees on the medallion."""
    out = compact_track_record(_summary())
    assert out["jobs"] == 250
    out2 = compact_track_record(_summary(jobs_verified=4, local_jobs=4))
    assert out2["jobs"] == 4


def test_disputes_are_carried_open_and_lost_separately():
    """The mark renders an OPEN dispute differently from a LOST one, and hides neither.
    A single `disputes` total cannot drive that, which is why three fields travel."""
    out = compact_track_record(_summary(disputes={"total": 3, "lost": 1, "open": 2}))
    assert (out["disputes"], out["open_disputes"], out["lost_disputes"]) == (3, 2, 1)


def test_a_missing_open_count_does_not_raise():
    """CONTROL. `track_record_summaries` always writes `open`, but an older row or a peer's
    payload may not. A `.get()` default here is the difference between a degraded mark and
    a 500 on a public discovery rail."""
    out = compact_track_record(_summary(disputes={"total": 1, "lost": 1}))
    assert out["open_disputes"] == 0


def test_null_stars_stay_null():
    """CONTROL. An unrated record has no average, and 0.0 would be a claim that it was
    rated badly. Null must survive the projection."""
    out = compact_track_record(_summary(avg_stars=None))
    assert out["stars"] is None


# ── §MARKSURFACES-2 (2026-09-10, same night) — the sibling return path ──────────────
def test_the_by_did_endpoint_enriches_every_return_path():
    """`GET /agents/by-did/{did}` has THREE returns: the local-agent one and two federated ones
    for a card this registry mirrors but holds no `agents` row for. The first cut of this batch
    widened only the local one.

    Measured on frame-c minutes after the V0302 roll: its most-verified worker (8 settled orders,
    5.0 stars) is a MIRROR from op-doha, so it took a federated path and answered
    `track_record: null` — while `/agents/{did}/track-record` served the same DID's 8 jobs happily
    and the rankings feed on the same node carried the mark. §FANOUTFIX inside one function.

    This is a SOURCE assertion on purpose: the three returns are in different branches of a
    handler that needs a database, an Agent row and a mirrored card to exercise, and what actually
    went wrong was a branch nobody widened. Counting the enriched returns is the question that
    would have failed."""
    import ast, pathlib
    src = pathlib.Path(__file__).resolve().parents[1] / "src/agentvault_registry/routers/agent_discovery.py"
    tree = ast.parse(src.read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "get_agent_by_did")
    returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return) and n.value is not None]
    enriched = [
        r for r in returns
        if any(isinstance(c, ast.Call) and getattr(c.func, "id", None) == "_attach_track_record"
               for c in ast.walk(r))
    ]
    assert len(returns) >= 3, f"expected at least 3 value returns, found {len(returns)}"
    assert len(enriched) == len(returns), (
        f"{len(returns) - len(enriched)} of {len(returns)} return paths ship no track record — "
        "a mirrored agent that did verified work in THIS registry's guild book still has a record here"
    )
