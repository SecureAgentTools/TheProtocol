"""§DIRFEED — the agent-card list is an INDEX FEED: the summary carries the DID and the epoch, the cursor and
the natives filter run SERVER-side, and the response says which of them it actually applied.

Why the echo is load-bearing: FastAPI silently ignores a query parameter the endpoint does not declare, so an
index that simply sends `updated_since` to an older registry gets a 200 with the FULL list and no way to know
its cursor was dropped. `applied_filters` is the only honest signal, and these tests pin it both ways.
"""
import datetime
import inspect
import types

import pytest

from agentvault_registry import schemas
from agentvault_registry.routers import agent_cards as router_mod


# ── the summary ──────────────────────────────────────────────────────────────
def _row(**kw):
    o = types.SimpleNamespace(
        id="6afaba65-e9ca-4995-8ba1-dab963652522", name="probe", description="d", is_active=True,
        origin_registry_name=None, agent_did=None, updated_at=None,
    )
    for k, v in kw.items():
        setattr(o, k, v)
    return o


def test_summary_carries_the_did_and_the_epoch():
    ts = datetime.datetime(2026, 9, 6, 12, 0, 0, tzinfo=datetime.timezone.utc)
    s = schemas.AgentCardSummary.model_validate(
        _row(agent_did="did:theprotocol:eu.theprotocol.cloud:392e1ff0-60a7-4e2a-a0c6-c8078fcfd77c", updated_at=ts)
    )
    assert s.agent_did == "did:theprotocol:eu.theprotocol.cloud:392e1ff0-60a7-4e2a-a0c6-c8078fcfd77c"
    assert s.updated_at == ts


def test_summary_did_is_null_for_an_unlinked_card_not_missing():
    d = schemas.AgentCardSummary.model_validate(_row()).model_dump()
    assert "agent_did" in d and d["agent_did"] is None
    assert "updated_at" in d and d["updated_at"] is None


# ── the wiring: params reach the CRUD, the echo reaches the caller ───────────
class _FakeCrud:
    def __init__(self):
        self.kwargs = None

    async def list_agent_cards(self, **kwargs):
        self.kwargs = kwargs
        return [], 0


@pytest.fixture
def crud(monkeypatch):
    f = _FakeCrud()
    monkeypatch.setattr(router_mod.agent_card, "list_agent_cards", f.list_agent_cards)
    return f


async def _call(**over):
    kw = dict(db=None, current_developer=None, skip=0, limit=100, active_only=True, search=None, tags=None,
              has_tee=None, tee_type=None, owned_only=False, include_federated=False, include_card_data=False,
              bearing_encirclement=False, foreign_only=False, updated_since=None, natives_only=False,
              include_unlisted=False)
    kw.update(over)
    return await router_mod.list_agent_cards(**kw)


@pytest.mark.asyncio
async def test_cursor_and_natives_reach_the_crud_and_are_echoed(crud):
    since = datetime.datetime(2026, 9, 6, 12, 0, 0, tzinfo=datetime.timezone.utc)
    r = await _call(updated_since=since, natives_only=True)
    assert crud.kwargs["updated_since"] == since
    assert crud.kwargs["native_only"] is True
    # §DARKSYNC (2026-09-22): the public feed lists LISTED cards only, and says so (a filter applied is a filter echoed)
    assert crud.kwargs["listed_only"] is True
    assert r.applied_filters == {"updated_since": since.isoformat(), "natives_only": True, "listed_only": True}


@pytest.mark.asyncio
async def test_the_control_no_filters_asked_no_filters_claimed(crud):
    r = await _call()
    assert crud.kwargs["updated_since"] is None
    assert crud.kwargs["native_only"] is False
    assert r.applied_filters is None, "a response must not claim a filter the caller never asked for"


@pytest.mark.asyncio
async def test_natives_only_skips_the_peer_fanout(monkeypatch, crud):
    called = []

    async def _boom(**kwargs):
        called.append(kwargs)
        return {}

    monkeypatch.setattr(router_mod, "query_all_peers", _boom)
    await _call(natives_only=True, include_federated=True)
    assert called == [], "a mirror is not native: asking peers under natives_only contradicts the filter"


@pytest.mark.asyncio
async def test_the_control_the_fanout_still_runs_without_natives_only(monkeypatch, crud):
    called = []

    async def _peers(**kwargs):
        called.append(kwargs)
        return {}

    monkeypatch.setattr(router_mod, "query_all_peers", _peers)
    await _call(include_federated=True)
    assert len(called) == 1, "the control: the federated fan-out is untouched when natives_only is off"


# ── the CRUD's own contract (source-pinned: the filter is inclusive and flips the order) ──
def test_the_cursor_is_inclusive_and_orders_ascending():
    import inspect

    from agentvault_registry.crud import agent_card as crud_mod

    src = inspect.getsource(crud_mod.list_agent_cards)
    assert "models.AgentCard.updated_at >= updated_since" in src, "an exclusive bound drops rows that share an instant"
    assert "updated_at.asc() if updated_since is not None" in src, "a cursor walk must be monotone in the cursor"


def test_list_ordering_is_total_so_pagination_is_a_partition():
    """§DIRFEED-2 — the ORDER BY must carry a unique tiebreak.

    `updated_at` is not unique (95 active cards on the EU rehearsal frame share 68 distinct
    instants), and an ordering that does not TOTALLY order the rows lets the planner arrange the
    equal-keyed ones differently for a different LIMIT/OFFSET — so `skip`-paging returned two rows
    twice and never returned two others, and the two errors cancelled in a count. This pins the
    compiled statement rather than a behaviour a small fixture would never exhibit: a test that
    pages three unique-timestamp rows passes with or without the fix.
    """
    import re
    from agentvault_registry.crud import agent_card as crud

    src = inspect.getsource(crud.list_agent_cards)
    order = re.search(r"\.order_by\((.*?)\)\s*\n\s*\.offset", src, re.S)
    assert order, "list_agent_cards no longer has an .order_by(...).offset(...) chain"
    clause = order.group(1)
    assert "AgentCard.id" in clause, (
        "the list ordering has no unique tiebreak; skip-paging is not a partition without one"
    )
    # both directions must carry it — the cursor walk needs it as much as the browse
    assert "updated_at.asc()" in clause and "updated_at.desc()" in clause, clause


def test_discover_echoes_what_it_applied():
    """§DISCECHO — the ranked page names its paging and filters.

    FastAPI drops an undeclared query parameter silently, so a caller who guesses gets a 200 and a full
    first page with no signal that nothing was applied. Measured by agentvault2-eb on this route: `?skip=4`
    returns the same four rows as `?skip=0`, forever, because the page parameter is `offset`. The index
    feed answers this with `applied_filters`; discover — the more public of the two, read by the landing
    preview and by /explore without a session — had no echo at all.

    Pinned on the SOURCE for the same reason as the ordering tiebreak: a fixture that passes the right
    parameter names proves nothing about the case this exists for.
    """
    import inspect
    from agentvault_registry.routers import agent_cards as mod

    src = inspect.getsource(mod.discover_agent_cards)
    assert "applied_filters = {" in src, "discover no longer builds an echo"
    for key in ("offset", "limit", "sort", "bonded_only", "include_unbonded"):
        assert f'"{key}"' in src.split("applied_filters = {")[1][:900], f"the echo does not name {key}"
    # BOTH return paths — an empty result must echo too, or a zero teaches the caller nothing
    assert src.count('"applied_filters": applied_filters') == 2, (
        "only one return path echoes; the empty-population branch is exactly where a caller most needs "
        "to know whether their filter ran"
    )
