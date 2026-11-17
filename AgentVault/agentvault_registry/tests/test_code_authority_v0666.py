"""V0666 (order gwo_e086b25f868da7ec9fce9fd2): governed code names ONE governing registry.

CODE_CHANGES_GOVERNING_REGISTRY names the registry that governs code; it is compared with THIS registry's own name as its signed card states it. Where this registry is that one:
everything as before. Unset, or another registry: the rail is read-only, every write refuses with 403 and one sentence ("Code changes are governed on <name>; open them there",
with that registry's console link from the network manifest), reads still answer.

  1. the authority itself: self / other / unset, the sentence, the link, the case-insensitive match against the card's name (never a container label);
  2. a census of the router's MUTATING routes: every one of them, driven through the REAL production store (DbStore, so the gate that guards production is the one under test),
     refuses with the sentence on a registry that does not govern; the census finds a route added WITHOUT the gate (a control adds one);
  3. reads still answer on such a registry, including the record whose ballot would have synced;
  4. every write of the production store and every flow step refuses first (nothing is touched: the db is None);
  5. a code_change governance proposal is neither voted on nor tallied there (and the public create route still refuses the type);
  6. the governing registry is unchanged: the flow's existing behaviour (the other test files) is the control, and here every gated step answers through.
"""
from __future__ import annotations

import asyncio
import inspect as _inspect

import httpx
import pytest

from agentvault_registry.services import code_authority as ca
from agentvault_registry.services import code_changes as cc
from tests.test_code_changes_flow_v0663 import FakeStore
from tests.test_code_changes_routes_v0663 import BODY, _Agent, _Dev, _call

SENTENCE_START = "Code changes are governed on "
MANIFEST = '[{"name": "eu", "console": "https://eu.theprotocol.cloud"}, {"name": "sbx-alpha", "console": "https://sandbox-alpha.example"}]'


@pytest.fixture
def other_registry(monkeypatch):
    """A registry named 'asia' while EU governs code."""
    monkeypatch.setattr(ca, "own_name", lambda: "asia")
    monkeypatch.setenv(ca.ENV, "eu")
    monkeypatch.setenv("FRESH_NETWORK_JSON", MANIFEST)


@pytest.fixture
def governing_registry(monkeypatch):
    monkeypatch.setattr(ca, "own_name", lambda: "EU")          # the match is not case-sensitive: the card's spelling is what is read
    monkeypatch.setenv(ca.ENV, "eu")


# --- 1. the authority ----------------------------------------------------------------------------------------------------------------------------------------------------------

def test_the_governing_registry_is_the_one_whose_card_name_the_env_names(governing_registry):
    a = ca.authority()
    assert a["self"] is True and a["governing"] == "eu" and a["sentence"] is None and ca.is_governing()


def test_another_registry_gets_the_sentence_with_the_governing_registrys_console(other_registry):
    a = ca.authority()
    assert a["self"] is False and a["sentence"] == "Code changes are governed on eu; open them there: https://eu.theprotocol.cloud"
    assert not ca.is_governing()


def test_unset_is_read_only_and_names_eu_without_ever_governing(monkeypatch):
    monkeypatch.setattr(ca, "own_name", lambda: "eu")
    monkeypatch.delenv(ca.ENV, raising=False)
    monkeypatch.setenv("FRESH_NETWORK_JSON", MANIFEST)
    a = ca.authority()
    assert a["self"] is False and a["governing"] is None and a["sentence"].startswith(SENTENCE_START + "EU; open them there")
    with pytest.raises(cc.CodeChangeRefusal) as e:
        ca.require_governing()
    assert e.value.status == 403 and e.value.code == "code_change_not_governed_here"


def test_the_match_reads_the_cards_name_not_a_container_label(monkeypatch):
    """federation_name() prefers REGISTRY_FEDERATION_NAME over the container label REGISTRY_NAME (a cloud operator's label is 'cloud-op-x', its card says 'x')."""
    from agentvault_registry.services import registry_card_builder as rcb
    monkeypatch.setenv("REGISTRY_FEDERATION_NAME", "sbx-alpha")
    monkeypatch.setattr(rcb.settings, "REGISTRY_NAME", "cloud-op-sbxalphaop", raising=False)
    monkeypatch.setenv(ca.ENV, "sbx-alpha")
    assert ca.own_name() == "sbx-alpha" and ca.is_governing()
    monkeypatch.setenv(ca.ENV, "cloud-op-sbxalphaop")
    assert not ca.is_governing(), "a container label never makes a registry the governing one"


def test_no_manifest_link_means_the_sentence_without_one(monkeypatch):
    monkeypatch.setattr(ca, "own_name", lambda: "asia")
    monkeypatch.setenv(ca.ENV, "eu")
    monkeypatch.delenv("FRESH_NETWORK_JSON", raising=False)
    assert ca.authority()["sentence"] == "Code changes are governed on eu; open them there."


# --- 2. the census of the router's mutating routes --------------------------------------------------------------------------------------------------------------------------

def _app(monkeypatch, store_factory):
    from fastapi import FastAPI
    from agentvault_registry import database
    from agentvault_registry.routers import code_changes as route
    from agentvault_registry.routers.utils import get_current_agent
    from agentvault_registry import security
    from agentvault_registry.security import get_current_developer

    monkeypatch.setattr(cc, "store_for", store_factory)
    app = FastAPI()
    app.include_router(route.router)

    async def get_db():
        yield None
    app.dependency_overrides[database.get_db] = get_db
    app.dependency_overrides[get_current_agent] = lambda: _Agent()
    app.dependency_overrides[security.get_current_agent] = lambda: _Agent()      # require_agent_permission(...) reads the agent through this one
    app.dependency_overrides[security.verify_agent_token] = lambda: {}              # and the token claims through this one
    app.dependency_overrides[get_current_developer] = lambda: _Dev(7)
    app.dependency_overrides[route._ADMIN] = lambda: _Dev(99)
    return app, route


def _mutating(router):
    """The router's own routes (a FastAPI app wraps an included router, so the app's list does not show them)."""
    return [r for r in router.routes if getattr(r, "methods", None) and (r.methods & {"POST", "PUT", "PATCH", "DELETE"})
            and r.path.startswith(("/api/v1/code-changes", "/api/v1/admin/code-changes"))]


FULL_BODY = {**BODY, "vote": True, "verdict": "approve", "commit": "a" * 40, "findings": "", "into": "main", "reason": "", "signed": None}


def _ungated(app, router):
    """The mutating routes that do NOT answer the governing refusal on a registry that does not govern."""
    bad = []
    for r in _mutating(router):
        path = r.path.replace("{cid}", "cc_1")
        for m in sorted(r.methods & {"POST", "PUT", "PATCH", "DELETE"}):
            resp = _call(app, m, path, FULL_BODY)
            ok = resp.status_code == 403 and resp.json().get("code") == "code_change_not_governed_here" and resp.json().get("detail", "").startswith(SENTENCE_START)
            if not ok:
                bad.append((m, r.path, resp.status_code))
    return bad


def test_every_mutating_route_of_the_rail_refuses_on_a_registry_that_does_not_govern(monkeypatch, other_registry):
    monkeypatch.setenv("CODE_DISTRIBUTIONS_ENABLED", "true")          # the line routes answer 404 while their own switch is off: the census must reach them
    app, route = _app(monkeypatch, lambda db, agent=None: cc.DbStore(db, agent))
    muts = _mutating(route.router)
    assert len(muts) >= 13, f"the census found only {len(muts)} mutating routes: it reads the router, so a smaller number means the router changed"
    assert {r.path for r in muts} >= {"/api/v1/code-changes/{cid}/code-distribution-vote", "/api/v1/code-changes/{cid}/code-distribution-veto",
                                      "/api/v1/code-changes/{cid}/code-distribution-go"}, "the organization lines' steps are part of the rail"
    assert _ungated(app, route.router) == []


def _dist_app(monkeypatch):
    from fastapi import FastAPI
    from agentvault_registry import database
    from agentvault_registry.routers import code_distributions as route
    from agentvault_registry.security import get_current_developer

    monkeypatch.setattr(cc, "store_for", lambda db, agent=None: cc.DbStore(db, agent))
    app = FastAPI()
    app.include_router(route.router)

    async def get_db():
        yield None
    app.dependency_overrides[database.get_db] = get_db
    app.dependency_overrides[get_current_developer] = lambda: _Dev(7)
    app.dependency_overrides[route._ADMIN] = lambda: _Dev(99)
    return app, route


DIST_BODY = {"organization_id": "o", "slug": "line-a", "title": "t", "base_release": "V0666", "open_paths": ["a"], "reason": "r"}


def test_every_mutating_route_of_the_organization_lines_refuses_on_a_registry_that_does_not_govern(monkeypatch, other_registry):
    """The release lines (code distributions) are part of the code-change rail: written on the governing registry only."""
    monkeypatch.setenv("CODE_DISTRIBUTIONS_ENABLED", "true")
    app, route = _dist_app(monkeypatch)
    muts = [r for r in route.router.routes if getattr(r, "methods", None) and (r.methods & {"POST", "PUT", "PATCH", "DELETE"})]
    assert {(m, r.path) for r in muts for m in r.methods & {"POST", "PATCH"}} >= {
        ("POST", "/api/v1/code-distributions"), ("PATCH", "/api/v1/code-distributions/{slug}"),
        ("POST", "/api/v1/admin/code-distributions/{slug}/pause"), ("POST", "/api/v1/admin/code-distributions/{slug}/resume")}
    bad = []
    for r in muts:
        for m in sorted(r.methods & {"POST", "PUT", "PATCH", "DELETE"}):
            resp = _call(app, m, r.path.replace("{slug}", "line-a"), DIST_BODY)
            if not (resp.status_code == 403 and resp.json().get("code") == "code_change_not_governed_here"):
                bad.append((m, r.path, resp.status_code))
    assert bad == []


def test_with_their_switch_off_the_organization_lines_answer_not_found_and_write_nothing(monkeypatch, other_registry):
    monkeypatch.delenv("CODE_DISTRIBUTIONS_ENABLED", raising=False)
    app, route = _dist_app(monkeypatch)
    assert _call(app, "POST", "/api/v1/code-distributions", DIST_BODY).status_code == 404


def test_the_census_finds_a_route_added_without_the_gate(monkeypatch, other_registry):
    app, route = _app(monkeypatch, lambda db, agent=None: cc.DbStore(db, agent))

    @route.router.post("/api/v1/code-changes/{cid}/rogue")
    async def rogue(cid: str):                          # a new write route that forgot the gate
        return {"ok": True}
    try:
        app2, route2 = _app(monkeypatch, lambda db, agent=None: cc.DbStore(db, agent))
        assert ("POST", "/api/v1/code-changes/{cid}/rogue", 200) in _ungated(app2, route2.router)
    finally:
        route.router.routes[:] = [r for r in route.router.routes if getattr(r, "path", "") != "/api/v1/code-changes/{cid}/rogue"]


def test_the_refusal_is_the_one_sentence_with_the_link(monkeypatch, other_registry):
    app, _ = _app(monkeypatch, lambda db, agent=None: cc.DbStore(db, agent))
    r = _call(app, "POST", "/api/v1/code-changes", BODY)
    assert r.status_code == 403 and r.json() == {"code": "code_change_not_governed_here",
                                                  "detail": "Code changes are governed on eu; open them there: https://eu.theprotocol.cloud"}


# --- 3. reads still answer ------------------------------------------------------------------------------------------------------------------------------------------------------

def test_reads_still_answer_on_a_registry_that_does_not_govern(monkeypatch, other_registry):
    store = FakeStore()
    app, _ = _app(monkeypatch, lambda db, agent=None: store)
    assert _call(app, "GET", "/api/v1/code-changes").status_code == 200
    a = _call(app, "GET", "/api/v1/code-changes-authority")
    assert a.status_code == 200 and a.json()["self"] is False and a.json()["sentence"].startswith(SENTENCE_START)


def test_the_authority_route_is_not_swallowed_by_the_record_route(monkeypatch, governing_registry):
    store = FakeStore()
    app, _ = _app(monkeypatch, lambda db, agent=None: store)
    r = _call(app, "GET", "/api/v1/code-changes-authority")
    assert r.status_code == 200 and r.json()["self"] is True and r.json()["sentence"] is None


def test_a_record_whose_ballot_would_sync_is_still_shown_as_it_stands(monkeypatch, other_registry):
    """The view syncs a balloting record from its proposal: on a registry that does not govern that write refuses, and the read must not fail with it."""
    class Gated(FakeStore):
        def check_governing(self):
            ca.require_governing()

        async def update(self, cid, **fields):
            self.check_governing()
            return await super().update(cid, **fields)
    store = Gated()
    store.rows["cc_1"] = {"id": "cc_1", "state": "balloting", "proposal_id": 5, "sensitive": False, "order_id": None, "commit": "a" * 40, "merged": None, "passed_at": None}
    store.proposals[5] = {"status": "PASSED", "tallied_at": None, "end_timestamp": None}
    flow = cc.CodeChangeFlow(store)
    out = asyncio.run(flow._synced("cc_1"))
    assert out["state"] == "balloting", "the record is shown as it stands; nothing was written"


# --- 4. every write of the production store and every flow step refuses first ------------------------------------------------------------------------------------------------

STORE_WRITES = [("post_bounty_order", ({}, ), {"title": "t", "spec": "s", "bounty": 1.0, "currency": "ECU"}), ("settle_order", ("o",), {"actor": "x"}),
                ("return_order", ("o",), {"actor": "x", "reason": "r"}), ("void_proposal", (1,), {}), ("insert", ({},), {}), ("update", ("c",), {}),
                ("add_review", ({},), {}), ("create_proposal", (), {"title": "t", "description": "d", "diff": {}, "quorum": 1.0, "pass_percent": 1.0, "ends": None}),
                ("_announce", ("c",), {}), ("add_distribution_vote", ({},), {}), ("insert_distribution", ({},), {}), ("update_distribution", ("d",), {})]


@pytest.mark.parametrize("name,args,kw", STORE_WRITES)
def test_every_write_of_the_production_store_refuses_first(other_registry, name, args, kw):
    store = cc.DbStore(None)                       # no database: a write that got past the gate would fail on None, not with the sentence
    with pytest.raises(cc.CodeChangeRefusal) as e:
        asyncio.run(getattr(store, name)(*args, **kw))
    assert e.value.code == "code_change_not_governed_here" and e.value.sentence.startswith(SENTENCE_START)


def test_the_store_write_census_covers_every_mutating_method_of_dbstore():
    """A new write method on DbStore must be added to the gate list: this lists the methods that look like writes by name and by their use of the session."""
    src = _inspect.getsource(cc.DbStore)
    writes = {n for n, f in _inspect.getmembers(cc.DbStore, _inspect.isfunction)
              if n != "check_governing" and ("self.db.add(" in _inspect.getsource(f) or "self.db.commit(" in _inspect.getsource(f) or "self.db.execute(" in _inspect.getsource(f)
                                              and ("INSERT" in _inspect.getsource(f) or "UPDATE" in _inspect.getsource(f) or "DELETE" in _inspect.getsource(f)))}
    gated = {n for n, _a, _k in STORE_WRITES}
    assert writes <= gated | {"_track"}, f"DbStore writes without the gate: {sorted(writes - gated)}"
    assert "check_governing" in src


FLOW_STEPS = [("propose", ({"did": "d", "developer_id": 1}, {})), ("record_acceptance", ({}, "c", {})), ("review", ({}, "c", {})), ("open_ballot", ({}, "c")),
              ("veto", ({}, "c", {})), ("withdraw", ({}, "c", {})), ("go", ({}, "c")), ("record_merge", ({}, "c", {})),
              ("line_vote", ({}, "c", {})), ("line_owner_veto", ({}, "c", {})), ("line_owner_go", ({}, "c")),
              ("propose_upstream", ({}, "c"))]            # V0667 D4


@pytest.mark.parametrize("name,args", FLOW_STEPS)
def test_every_flow_step_refuses_before_it_reads_anything(other_registry, name, args):
    class Gated(FakeStore):
        def check_governing(self):
            ca.require_governing()
    flow = cc.CodeChangeFlow(Gated())
    with pytest.raises(cc.CodeChangeRefusal) as e:
        asyncio.run(getattr(flow, name)(*args))
    assert e.value.code == "code_change_not_governed_here"


def test_the_flow_census_covers_every_public_step():
    steps = {n for n, f in _inspect.getmembers(cc.CodeChangeFlow, _inspect.iscoroutinefunction)
             if not n.startswith("_") and n not in ("view", "close_money")}
    assert steps == {n for n, _ in FLOW_STEPS}, f"a flow step without a gate test: {sorted(steps ^ {n for n, _ in FLOW_STEPS})}"
    for n, _ in FLOW_STEPS:
        assert "self._governing()" in _inspect.getsource(getattr(cc.CodeChangeFlow, n)), f"{n} does not call the gate first"


def test_the_governing_registry_passes_every_gated_step_through(governing_registry):
    class Gated(FakeStore):
        def check_governing(self):
            ca.require_governing()
    flow = cc.CodeChangeFlow(Gated())
    with pytest.raises(cc.CodeChangeRefusal) as e:                  # a refusal from the step's OWN rules (no such record), never the governing one
        asyncio.run(flow.go({"admin": True, "developer_id": 1}, "missing"))
    assert e.value.code != "code_change_not_governed_here"


# --- 5. governance ---------------------------------------------------------------------------------------------------------------------------------------------------------------

class _Row:
    def __init__(self, t):
        self.proposal_type = t


class _Db:
    def __init__(self, t):
        self.t = t

    async def get(self, model, pid):
        return None if self.t is None else _Row(self.t)


def test_a_code_change_proposal_is_neither_voted_on_nor_tallied_on_a_registry_that_does_not_govern(other_registry):
    from agentvault_registry.routers.governance import _code_change_not_governed_here as gate
    r = asyncio.run(gate(_Db("code_change"), 5))
    assert r is not None and r.status_code == 403 and b"code_change_not_governed_here" in r.body and SENTENCE_START.encode() in r.body
    assert asyncio.run(gate(_Db("policy"), 5)) is None and asyncio.run(gate(_Db(None), 5)) is None, "other proposals and unknown ids are untouched"


def test_the_governing_registry_votes_and_tallies_a_code_change_proposal(governing_registry):
    from agentvault_registry.routers.governance import _code_change_not_governed_here as gate
    assert asyncio.run(gate(_Db("code_change"), 5)) is None


def test_the_vote_and_the_tally_call_the_gate_before_anything_else():
    src = _inspect.getsource(__import__("agentvault_registry.routers.governance", fromlist=["x"]))
    for fn in ("cast_vote", "tally_proposal_votes"):
        body = src[src.index(f"async def {fn}("):]
        body = body[:body.index("\n@router.")] if "\n@router." in body else body
        i_gate, i_first = body.find("_code_change_not_governed_here(db, proposal_id)"), body.find("crud_governance.")
        assert 0 < i_gate < (i_first if i_first > 0 else 10 ** 9), f"{fn}: the gate must run first"


def test_the_public_create_route_still_refuses_the_code_change_type():
    src = _inspect.getsource(__import__("agentvault_registry.routers.governance", fromlist=["x"]).create_proposal)
    assert "code_change" in src or "proposal_type" in src


# --- 7. the link comes from the governing registry's OWN card (its peer row's cached card), the manifest is the fallback ----------------------------------------------------------

class _CardDb:
    """A session whose one query answers the cached registry card of the governing registry's peer row."""

    def __init__(self, card):
        self.card = card
        self.asked = 0

    async def execute(self, stmt):
        self.asked += 1

        class R:
            def __init__(s, v):
                s.v = v

            def scalar_one_or_none(s):
                return s.v
        return R(self.card)


@pytest.fixture(autouse=True)
def _forget_peer_links():
    ca._PEER_LINKS.clear()
    yield
    ca._PEER_LINKS.clear()


def test_the_link_is_the_governing_registrys_card_public_url_before_the_manifest(other_registry):
    db = _CardDb({"identity": {"registry_name": "eu", "public_url": "https://eu.theprotocol.cloud/"}})
    assert asyncio.run(ca.warm_peer_link(db, "eu")) == "https://eu.theprotocol.cloud/"
    assert ca.authority()["sentence"] == "Code changes are governed on eu; open them there: https://eu.theprotocol.cloud/"
    assert asyncio.run(ca.warm_peer_link(db, "eu")) == "https://eu.theprotocol.cloud/" and db.asked == 1, "remembered for five minutes: one query"


def test_a_card_without_a_public_url_leaves_the_manifest_to_answer(other_registry):
    asyncio.run(ca.warm_peer_link(_CardDb({"identity": {"registry_name": "eu"}}), "eu"))
    assert ca.authority()["sentence"].endswith("https://eu.theprotocol.cloud")        # the manifest's console, no trailing slash


def test_a_peer_row_that_cannot_be_read_never_fails_the_refusal(other_registry):
    class Broken:
        async def execute(self, stmt):
            raise RuntimeError("db down")
    assert asyncio.run(ca.warm_peer_link(Broken(), "eu")) is None
    assert ca.authority()["sentence"].startswith(SENTENCE_START)


def test_the_store_refusal_carries_the_link_read_from_the_card(other_registry):
    db = _CardDb({"identity": {"public_url": "https://eu.theprotocol.cloud/"}})
    with pytest.raises(cc.CodeChangeRefusal) as e:
        asyncio.run(cc.DbStore(db).check_governing())
    assert e.value.sentence.endswith("https://eu.theprotocol.cloud/") and db.asked == 1


def test_the_self_name_is_exactly_what_the_signed_card_publishes(monkeypatch):
    """The lead's check: federation_name() IS the card's identity.registry_name (the builder publishes the same call), so the match compares the card's own word."""
    from agentvault_registry.services import registry_card_builder as rcb
    src = _inspect.getsource(rcb)
    assert '"registry_name": _federation_name,' in src and "_federation_name = federation_name()" in src
    monkeypatch.setenv("REGISTRY_FEDERATION_NAME", "sbx-beta")
    assert ca.own_name() == rcb.federation_name() == "sbx-beta"


def test_the_money_sweep_does_nothing_and_logs_nothing_on_a_registry_that_does_not_govern(other_registry, monkeypatch, caplog):
    from agentvault_registry.background_tasks import guild_order_reaper as r

    def boom(*a, **k):
        raise AssertionError("the sweep opened a session on a registry that does not govern code")
    monkeypatch.setattr(r, "AsyncSessionLocal", boom)
    import logging
    with caplog.at_level(logging.WARNING):
        assert asyncio.run(r.close_code_changes()) == 0
    assert [x for x in caplog.records if "code-change sweep" in x.getMessage()] == []


@pytest.mark.parametrize("card,env,governs", [("EU", "eu", True), ("eu", "EU", True), ("ASIA", "EU", False), ("Sandbox Alpha", "Sandbox Alpha", True),
                                              ("Sandbox Alpha", "sandbox alpha", True), ("Sandbox Alpha", "sbx-alpha", False), ("Sandbox Beta", "Sandbox Alpha", False)])
def test_the_match_is_case_insensitive_on_the_cards_exact_word(monkeypatch, card, env, governs):
    """The live cards say 'EU', 'ASIA', 'Sandbox Alpha': the env line carries the card's value (a stack label like sbx-alpha is not the card's word and does not govern)."""
    monkeypatch.setattr(ca, "own_name", lambda: card)
    monkeypatch.setenv(ca.ENV, env)
    assert ca.is_governing() is governs
