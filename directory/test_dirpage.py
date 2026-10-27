"""§DIRPAGE — the card walk pages the whole source, and a PARTIAL read never sweeps.

The defect these pin (measured 2026-09-09, the day the legacy frames joined the index):
  * one page of CARD_LIMIT was read and the rest of the source was invisible — Frame-C publishes
    5,502 natives and the index held exactly 5,000, reporting `more=false`;
  * a `full` pass swept whatever it had not seen, while reading only the NEWEST page — so any card
    the incremental cursor had indexed beyond one page would have been marked GONE.

Each test has a control: the sweep MUST happen on a completed walk, and MUST NOT on a truncated one.
"""
import asyncio, json, types, pytest
import directory.ingest as ing


class FakeStore:
    def __init__(self): self.swept = []; self.fields = {}; self.epochs = {}
    def get_registry(self, name): return {"cards_cursor": None}
    def agent_epoch(self, cid): return self.epochs.get(cid)
    def upsert_agent(self, **kw): self.epochs[kw["id"]] = kw.get("updated_at")
    def sweep_source(self, kind, name, seen): self.swept.append((name, len(seen))); return 0
    def set_registry_field(self, name, **kw): self.fields.update(kw)
    def count_for_source(self, kind, name): return len(self.epochs)


def make_client(pages):
    """pages: list of item-lists, served in order for each /agent-cards/? request."""
    calls = {"n": 0}
    async def fake_fetch(client, url, **kw):
        if "/agent-cards/?" in url:
            i = calls["n"]; calls["n"] += 1
            if i >= len(pages): return None, "no more pages"
            p = pages[i]
            if p is None: return None, "boom"          # a mid-walk failure
            return {"applied_filters": {"natives_only": True}, "items": p}, None
        cid = url.rsplit("/", 1)[-1]
        return {"card_data": {}, "updated_at": f"e{cid}", "is_active": True, "name": cid}, None
    return fake_fetch, calls


def card(i, epoch): return {"id": str(i), "updated_at": epoch, "agent_did": f"did:x:{i}"}


def run(pages, full, limit=4, monkeypatch=None):
    store = FakeStore()
    fake_fetch, calls = make_client(pages)
    orig_fetch, orig_limit = ing.fetch_json, ing.CARD_LIMIT
    ing.fetch_json, ing.CARD_LIMIT = fake_fetch, limit
    try:
        reg = {"base": "http://x", "name": "SRC", "trust_domain": "td", "verified": True}
        return asyncio.run(ing.pull_cards(None, store, reg, full=full)), store, calls
    finally:
        ing.fetch_json, ing.CARD_LIMIT = orig_fetch, orig_limit


def test_walk_crosses_page_boundaries_and_completes():
    """4+4+2 = 10 rows over three pages; the old code would have stopped at 4."""
    pages = [[card(i, f"2026-01-0{i}") for i in (1, 2, 3, 4)],
             [card(i, f"2026-01-{i:02d}") for i in (5, 6, 7, 8)],
             [card(i, f"2026-01-{i:02d}") for i in (9, 10)]]
    res, store, calls = run(pages, full=True)
    assert res["pages"] == 3, res
    assert res["listed"] == 10, res
    assert res["complete"] is True
    assert res["more"] is False and res["stalled"] is False


def test_a_completed_full_walk_SWEEPS():
    """CONTROL for the next test: sweeping is the normal, wanted behaviour."""
    res, store, _ = run([[card(1, "2026-01-01"), card(2, "2026-01-02")]], full=True)
    assert res["complete"] is True and res["swept"] is True
    assert store.swept, "a completed full walk must sweep"


def test_a_stalled_walk_DOES_NOT_SWEEP():
    """A same-instant cluster wider than a page: the cursor cannot advance. Say so, and do not sweep
    — sweeping here would mark every row we could not reach as gone."""
    same = [card(i, "2026-01-01T00:00:00") for i in range(1, 5)]     # 4 rows, one instant, limit 4
    res, store, _ = run([same, same], full=True)
    assert res["stalled"] is True and res["more"] is True
    assert res["complete"] is False and res["swept"] is False
    assert store.swept == [], "a stalled walk must never sweep"


def test_a_page_failing_MIDWALK_does_not_sweep():
    pages = [[card(i, f"2026-01-0{i}") for i in (1, 2, 3, 4)], None]
    res, store, _ = run(pages, full=True)
    assert res["complete"] is False and res["swept"] is False
    assert store.swept == [], "a walk that lost a page must never sweep"


def test_first_page_failure_still_reports_unreachable():
    res, store, _ = run([None], full=True)
    assert res["mode"] == "unreachable" and res.get("error")
    assert store.swept == []


# ── the OTHER half: a sweep must be able to give a row back ──────────────────────────────────

def _store(tmp_path):
    from directory.store import Store
    return Store(str(tmp_path / "d.db"))


def _add(st, cid, source="SRC"):
    st.upsert_agent(id=cid, did=f"did:x:{cid}", name=cid, hri=None, description=None, is_active=1,
                    updated_at="2026-01-01", source=source, source_td="td", issuer=None, shape=None,
                    home=source, bond_json="{}", enforcement_json="{}", verified=1, reachable=1,
                    fetched_at=0, card_json="{}")


def test_sweep_retires_what_the_source_stopped_publishing(tmp_path):
    """CONTROL: the retiring half must still work, or the restore below proves nothing."""
    st = _store(tmp_path)
    for i in ("a", "b", "c"): _add(st, i)
    gone = st.sweep_source("agents", "SRC", ["a", "b"])
    assert gone == 1
    assert st.count_for_source("agents", "SRC") == 2


def test_sweep_RESTORES_a_row_the_source_still_publishes(tmp_path):
    """The stuck-forever bug: a truncated pass marked a live row unreachable, and because the
    incremental walk skips unchanged cards it was never re-upserted. Seeing it again must undo it."""
    st = _store(tmp_path)
    for i in ("a", "b", "c"): _add(st, i)
    st.sweep_source("agents", "SRC", ["a"])                 # a partial pass retires b and c
    assert st.count_for_source("agents", "SRC") == 1
    st.sweep_source("agents", "SRC", ["a", "b", "c"])       # a complete pass sees them all again
    assert st.count_for_source("agents", "SRC") == 3, "a seen row must come back"


def test_sweep_handles_a_seen_set_far_past_the_sqlite_param_ceiling(tmp_path):
    """The walk exists so a source may be arbitrarily large; the sweep must not be the new ceiling.
    A `?`-per-id IN(...) would raise 'too many SQL variables' here."""
    st = _store(tmp_path)
    ids = [str(i) for i in range(12000)]
    for i in ids[:50]: _add(st, i)
    st.sweep_source("agents", "SRC", ids)                   # must not raise
    assert st.count_for_source("agents", "SRC") == 50
