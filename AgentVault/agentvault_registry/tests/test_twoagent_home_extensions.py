"""§TWOAGENT #10 (2026-09-23) — a native card's bond, enforcement and listing are stated by its home at every read, and
never stored from owner content.

Measured on the live index before this change: the federated Directory, which indexes the single-card read
(`GET /api/v1/agent-cards/{id}`), recorded every native card on EU and ASIA as unbonded, whatever the registry held,
because that read served stored card_data and derived nothing (the card-export and the federation export derive all
three). And nothing kept the three out of stored card_data: an owner could PUT a `locked` bond block its registry never
granted, and an SDK agent republishing the card-export would have it copied back by the pull-sync. Census before the
change: 0 native cards store any of the three on EU (70), ASIA (29), sbx-alpha (6,887) or sbx-beta (836), so the strip
changes no stored card today.

RED on 7241c198 (V0436), measured: 16 of 18 fail (the module most of them import does not exist; the create and update
paths persist an owner's bond block; the pull-sync merge keeps an echoed one; the router states nothing). The two that
pass on both trees are the controls that can: a real change in the extensions still drifts, and the census can fail.
"""
from __future__ import annotations

import ast
import copy
import os
import pathlib

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@localhost:5432/ci")
os.environ.setdefault("API_KEY_SECRET", "ci-dummy-secret-0123456789abcdef")

BOND = "https://theprotocol.cloud/extensions/v1/reputation-bond"
ENF = "https://theprotocol.cloud/extensions/v1/enforcement"
LST = "https://theprotocol.cloud/extensions/v1/listing"
PAY = "https://theprotocol.cloud/extensions/v1/auth/a2a-payment"
OWN = "https://owner.example/extensions/v1/house-style"

DID = "did:theprotocol:eu.theprotocol.cloud:5b0c3a1e-0000-4000-8000-000000000010"


def _ext(uri, **params):
    return {"uri": uri, "required": False, "params": {"version": 1, **params}}


def _uris(card):
    return [e.get("uri") for e in (card.get("extensions") or [])]


def _card(**over):
    card = {
        "protocolVersion": "1.0", "humanReadableId": "twoagent-test/scrivener", "agentVersion": "1.0.0",
        "name": "Scrivener", "description": "Writes things down for a fee.",
        "provider": {"name": "Brussels"}, "capabilities": {"a2aVersion": "1.0", "streaming": False},
        "supportedInterfaces": [{"url": "https://scrivener.example/a2a", "protocolBinding": "JSONRPC"}],
        "securitySchemes": {}, "security": [],
    }
    card.update(over)
    return card


# ── the strip ────────────────────────────────────────────────────────────────

def test_strip_drops_the_three_and_keeps_the_rest_in_order():
    from agentvault_registry.services.home_extensions import strip_home_extensions
    card = {"name": "x", "extensions": [_ext(PAY, base_rate=1), _ext(BOND, status="locked"), _ext(OWN),
                                        _ext(ENF, status="active"), _ext(LST, unlisted=False)]}
    out = strip_home_extensions(card)
    assert _uris(out) == [PAY, OWN]
    assert _uris(card) == [PAY, BOND, OWN, ENF, LST], "the input is never mutated"


def test_control_a_card_with_nothing_to_strip_is_the_same_object():
    """Persisted byte for byte as it came: an unaffected card is not even copied."""
    from agentvault_registry.services.home_extensions import strip_home_extensions
    card = {"name": "x", "extensions": [_ext(PAY, base_rate=1)]}
    assert strip_home_extensions(card) is card
    bare = {"name": "x"}
    assert strip_home_extensions(bare) is bare
    assert strip_home_extensions(None) is None
    odd = {"name": "x", "extensions": "not a list"}
    assert strip_home_extensions(odd) is odd


def test_control_the_capabilities_extensions_are_not_the_home_extensions():
    """The track-record pointer lives in capabilities.extensions and is out of scope; nothing there is touched."""
    from agentvault_registry.services.home_extensions import strip_home_extensions
    card = {"capabilities": {"extensions": [_ext(BOND, status="locked")]}}
    assert strip_home_extensions(card) is card


# ── the writes ───────────────────────────────────────────────────────────────

class _Session:
    """Enough of an AsyncSession for create/update: nothing is read (the reads the CRUD does are best-effort)."""
    def __init__(self):
        self.added = []

    def add(self, o):
        self.added.append(o)

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def refresh(self, o):
        pass

    async def get(self, *a, **k):
        return None

    async def execute(self, *a, **k):
        raise RuntimeError("no database in this test")


async def test_create_does_not_store_an_owner_written_bond():
    from agentvault_registry import schemas
    from agentvault_registry.crud.agent_card import create_agent_card
    card = _card(extensions=[_ext(PAY, base_rate=2, currency="ECU", pricing_model="per_call"),
                             _ext(BOND, status="locked", amount=250, currency="ECU")])
    row = await create_agent_card(_Session(), 1, schemas.AgentCardCreate(card_data=card))
    assert _uris(row.card_data) == [PAY], row.card_data.get("extensions")


async def test_update_does_not_store_an_echoed_read():
    """The console's edit form sends back what the read showed; from V0437 the read states the bond."""
    from agentvault_registry import models, schemas
    from agentvault_registry.crud.agent_card import update_agent_card
    row = models.AgentCard(developer_id=1, card_data=_card(extensions=[_ext(PAY, base_rate=2)]),
                           name="Scrivener", description="d", is_active=True)
    echoed = _card(description="Writes things down, carefully.",
                   extensions=[_ext(PAY, base_rate=2), _ext(BOND, status="matured", amount=250),
                               _ext(ENF, status="suspended"), _ext(LST, unlisted=True)])
    out = await update_agent_card(_Session(), row, schemas.AgentCardUpdate(card_data=echoed))
    assert _uris(out.card_data) == [PAY]
    assert out.card_data["description"] == "Writes things down, carefully.", "the owner's real edit still lands"


def test_the_pullsync_merge_drops_an_echoed_bond_and_calls_it_no_drift():
    from agentvault_registry.background_tasks import agent_card_pullsync as ps
    stored = {"name": "x", "extensions": [_ext(PAY, base_rate=2)]}
    fresh = {"name": "x", "extensions": [_ext(PAY, base_rate=2), _ext(BOND, status="locked", amount=250)]}
    merged, drifted = ps._merge_pulled_card(stored, fresh)
    assert _uris(merged) == [PAY]
    assert drifted == [], drifted


def test_control_a_real_change_in_the_extensions_still_drifts():
    """Passes on both trees: the strip must not swallow the agent's own change."""
    from agentvault_registry.background_tasks import agent_card_pullsync as ps
    stored = {"name": "x", "extensions": [_ext(PAY, base_rate=2)]}
    fresh = {"name": "x", "extensions": [_ext(PAY, base_rate=3), _ext(BOND, status="locked")]}
    merged, drifted = ps._merge_pulled_card(stored, fresh)
    assert "extensions" in drifted
    assert [e for e in merged["extensions"] if e["uri"] == PAY][0]["params"]["base_rate"] == 3


# ── the reads ────────────────────────────────────────────────────────────────

@pytest.fixture
def states(monkeypatch):
    """The three `card_state(s)` readers, replaced; `calls` counts every read so a test can prove who was asked."""
    from agentvault_registry.services import enforcement_propagation as ep
    from agentvault_registry.services import listing_propagation as lp
    from agentvault_registry.services import reputation_bond as rb
    st = {"bond": {}, "enf": {}, "lst": {}, "calls": [], "boom": False}

    def one(kind):
        async def f(db, did):
            st["calls"].append((kind, did))
            if st["boom"]:
                raise RuntimeError("the state table is unreadable")
            return st[kind].get(did)
        return f

    def many(kind):
        async def f(db, dids, **kw):
            st["calls"].append((kind, tuple(dids)))
            if st["boom"]:
                raise RuntimeError("the state table is unreadable")
            return {d: st[kind][d] for d in dids if d in st[kind]}
        return f

    monkeypatch.setattr(rb, "card_state", one("bond"))
    monkeypatch.setattr(ep, "card_state", one("enf"))
    monkeypatch.setattr(lp, "card_state", one("lst"))
    monkeypatch.setattr(rb, "card_states", many("bond"))
    monkeypatch.setattr(ep, "card_states", many("enf"))
    monkeypatch.setattr(lp, "card_states", many("lst"))
    monkeypatch.setattr(rb, "registry_display_name", lambda: "EU")
    return st


def _bond(status="locked"):
    return {"bond": {"status": status, "amount": "250", "currency": "ECU", "locked_at": "2026-09-23T10:00:00+00:00",
                     "registry": "EU"}}


async def test_a_native_read_states_the_bond_this_registry_holds(states):
    from agentvault_registry.services.home_extensions import derive_for_read
    states["bond"][DID] = _bond()
    out = await derive_for_read(None, {"name": "x", "extensions": [_ext(PAY, base_rate=2)]}, DID)
    bond = [e for e in out["extensions"] if e["uri"] == BOND]
    assert len(bond) == 1 and bond[0]["params"]["status"] == "locked" and bond[0]["params"]["currency"] == "ECU"
    assert _uris(out)[0] == PAY


async def test_a_native_read_drops_a_bond_this_registry_does_not_hold(states):
    """The owner-written block from before V0437 (or from any path this change missed) is never served."""
    from agentvault_registry.services.home_extensions import derive_for_read
    stored = {"name": "x", "extensions": [_ext(BOND, status="locked", amount=250)]}
    kept = copy.deepcopy(stored)
    out = await derive_for_read(None, stored, DID)
    assert _uris(out) == []
    assert stored == kept, "the ORM attribute is never mutated by a read"


async def test_a_native_read_states_enforcement_and_listing(states):
    from agentvault_registry.services.home_extensions import derive_for_read
    states["enf"][DID] = {"status": "suspended", "since": "2026-09-23T11:00:00+00:00", "registry": "EU"}
    states["lst"][DID] = {"unlisted": True, "since": "2026-09-23T11:00:00+00:00", "registry": "EU"}
    out = await derive_for_read(None, {"name": "x"}, DID)
    by = {e["uri"]: e["params"] for e in out["extensions"]}
    assert by[ENF]["status"] == "suspended" and by[LST]["unlisted"] is True and BOND not in by


async def test_control_a_mirror_keeps_its_homes_copy_and_nobody_is_asked(states):
    from agentvault_registry.services.home_extensions import derive_for_read
    mirror = {"name": "x", "federation_metadata": {"source_registry": "ASIA"},
              "extensions": [_ext(BOND, status="locked", registry="ASIA")]}
    assert await derive_for_read(None, mirror, DID) is mirror
    assert states["calls"] == []


async def test_a_native_card_without_a_did_states_nothing(states):
    from agentvault_registry.services.home_extensions import derive_for_read
    out = await derive_for_read(None, {"name": "x", "extensions": [_ext(BOND, status="locked")]}, None)
    assert _uris(out) == [] and states["calls"] == []


async def test_an_unreadable_state_serves_the_card_without_the_three(states):
    from agentvault_registry.services.home_extensions import derive_for_read
    states["boom"] = True
    out = await derive_for_read(None, {"name": "x", "extensions": [_ext(PAY), _ext(BOND, status="locked")]}, DID)
    assert _uris(out) == [PAY]


async def test_the_list_twin_asks_once_per_extension_for_the_page(states):
    from agentvault_registry.services.home_extensions import derive_for_read_batch
    d2 = DID[:-2] + "11"
    states["bond"][DID] = _bond("matured")
    mirror = {"name": "m", "federation_metadata": {"source_registry": "ASIA"}, "extensions": [_ext(BOND, status="locked")]}
    items = [{"card_data": {"name": "a"}},
             {"card_data": {"name": "b", "extensions": [_ext(BOND, status="locked")]}},
             {"card_data": mirror},
             {"card_data": {"name": "c", "extensions": [_ext(BOND, status="locked")]}}]
    await derive_for_read_batch(None, items, [DID, d2, DID[:-2] + "12", None])
    assert [e["params"]["status"] for e in items[0]["card_data"]["extensions"]] == ["matured"]
    assert _uris(items[1]["card_data"]) == [], "an owner-written bond on a native card is dropped"
    assert items[2]["card_data"] is mirror
    assert _uris(items[3]["card_data"]) == []
    kinds = [k for k, _ in states["calls"]]
    assert sorted(kinds) == ["bond", "enf", "lst"], states["calls"]
    assert all(dids == tuple(sorted([DID, d2])) for _, dids in states["calls"]), states["calls"]


async def test_the_list_twin_serves_the_page_without_the_three_when_a_state_is_unreadable(states):
    from agentvault_registry.services.home_extensions import derive_for_read_batch
    states["boom"] = True
    items = [{"card_data": {"name": "a", "extensions": [_ext(PAY), _ext(BOND, status="locked")]}}]
    await derive_for_read_batch(None, items, [DID])
    assert _uris(items[0]["card_data"]) == [PAY]


async def test_the_listing_batch_is_the_single_reads_predicate(monkeypatch):
    """One query for both: the newest active NATIVE card per DID decides, and a listed card has no block."""
    from agentvault_registry.services import listing_propagation as lp
    seen = {}

    class _Res:
        def fetchall(self):
            return [(DID, True, None), (DID[:-2] + "11", False, None)]

    class _DB:
        async def execute(self, stmt, params):
            seen["sql"], seen["params"] = str(stmt), params
            return _Res()

    out = await lp.card_states(_DB(), [DID, DID[:-2] + "11", None])
    assert list(out) == [DID] and out[DID]["unlisted"] is True
    assert seen["params"] == {"dids": [DID, DID[:-2] + "11"]}
    sql = " ".join(seen["sql"].split())
    for part in ("DISTINCT ON (agent_did)", "is_active = TRUE", "federation_metadata,source_registry}') IS NULL",
                 "ORDER BY agent_did, updated_at DESC"):
        assert part in sql, (part, sql)
    assert (await lp.card_state(_DB(), DID))["unlisted"] is True


# ── the census: every read site in the card router states them ──────────────

ROUTER = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "routers" / "agent_cards.py"


def _unstated(source: str):
    """Functions that build a card read (or batch-inject flare into served card_data) without stating the three."""
    out = []
    for fn in ast.walk(ast.parse(source)):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        called = {n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        if "_build_agent_card_read_dict" in called and "_state_home_extensions" not in called:
            out.append(fn.name)
        if "_inject_flare_into_card_data_batch" in called and "_state_home_extensions_batch" not in called:
            out.append(fn.name)
    return out


def test_every_card_read_in_the_router_states_the_home_extensions():
    src = ROUTER.read_text()
    assert src.count("_build_agent_card_read_dict(") >= 6, "the census found fewer read sites than the router has"
    assert _unstated(src) == []


def test_control_the_census_can_fail():
    src = "async def r(db, c):\n    d = _build_agent_card_read_dict(c)\n    return d\n"
    assert _unstated(src) == ["r"]
    src2 = "async def l(db, items, cards):\n    await _inject_flare_into_card_data_batch(db, items, cards)\n"
    assert _unstated(src2) == ["l"]
