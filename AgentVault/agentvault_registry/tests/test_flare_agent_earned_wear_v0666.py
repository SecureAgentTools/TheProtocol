"""V0666 the Flare view reworked (order gwo_558042610799088faf1a5e4c): an agent wears an EARNED ring or badge its developer unlocked.

Until now the agent routes refused every earned key (400: "Unknown encirclement variant", "Unknown corner variant") and the developer's own earned ring
shipped on every agent the developer owned. Now an agent wears an earned ring or badge only when (1) the developer owns the agent, (2) the developer holds
the unlock row (the contributor track's evaluator is still the only writer of that table; these routes only read it), (3) the agent does not already wear
a BOUGHT ring or corner (one ring and one corner per agent: the person takes the bought one off first, and is told so). An earned item is worn by one agent
at a time, as the bought variants are single-occupancy across the fleet; the developer's own wear is a separate slot. The agent's sidecar ships what the
agent wears and nothing of the developer's. Measured through the real fiat router over real (SQLite) rows; every case fails on the V0665 tip (2b561aa2c),
where the routes answer 400 for an earned key, except the ones marked control.
"""
from __future__ import annotations

import asyncio
import datetime
from types import SimpleNamespace as NS

import httpx
import pytest
from fastapi import FastAPI

from agentvault_registry import models
from agentvault_registry.database import get_db
from agentvault_registry.routers import fiat_onramp as fo
from tests._sqlite_db import sqlite_db

ME, OTHER = 6, 9
A1, A2, A3 = "did:theprotocol:eu.test:a1", "did:theprotocol:eu.test:a2", "did:theprotocol:eu.test:a3"
STRANGER = "did:theprotocol:eu.test:stranger"
NOW = datetime.datetime(2026, 11, 15, 12, 0, tzinfo=datetime.timezone.utc)


def run(coro):
    return asyncio.run(coro)


TOUCHED = []


@pytest.fixture(autouse=True)
def _card_touch(monkeypatch):
    """The card touch is a Postgres statement (JSON path, NOW()): here it only records which agents' cards a change moved."""
    from agentvault_registry.services import enforcement_propagation as ep

    async def touch(db, did):
        TOUCHED.append(did)
        return 1
    TOUCHED.clear()
    monkeypatch.setattr(ep, "touch_native_card_no_commit", touch)


def make(unlocks=(), other_unlocks=(), bears_enc=(), bears_corner=()):
    """An app over real rows: developer ME with three agents, developer OTHER with one; the unlock rows named."""
    db = sqlite_db(models.Developer, models.Agent, models.CosmeticUnlock)
    s = db.sync
    for i in (ME, OTHER):
        s.add(models.Developer(id=i, name=f"dev{i}", email=f"d{i}@example.test", hashed_password="x"))
    s.flush()
    for did, dev in ((A1, ME), (A2, ME), (A3, ME), (STRANGER, OTHER)):
        s.add(models.Agent(did=did, client_id=f"c-{did[-3:]}", hashed_client_secret="x", creator_developer_id=dev, status="active",
                           bears_encirclement_flare=did in bears_enc, bears_corner_flare=did in bears_corner))
    for dev, rows in ((ME, unlocks), (OTHER, other_unlocks)):
        for kind, key in rows:
            s.add(models.CosmeticUnlock(developer_id=dev, kind=kind, item_key=key, tier=1, unlocked_at=NOW, source="test"))
    s.commit()
    app = FastAPI()
    app.include_router(fo.router)

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    me = {"dev": db.sync.get(models.Developer, ME)}
    app.dependency_overrides[fo.get_current_developer_unified] = lambda: me["dev"]
    return app, db, me


def call(app, method, path, **kw):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            return await c.request(method, path, **kw)
    return run(go())


def agent(db, did):
    db.sync.expire_all()
    return db.sync.query(models.Agent).filter(models.Agent.did == did).one()


def ring(app, did, variant):
    return call(app, "PATCH", f"/api/v1/fiat/flare/agent/{did}/variant", json={"variant": variant})


def badge(app, did, variant):
    return call(app, "PATCH", f"/api/v1/fiat/flare/agent/{did}/corner-variant", json={"variant": variant})


# --- the ring ---------------------------------------------------------------------------------------------------------------

def test_an_owner_wears_an_unlocked_earned_ring_on_an_agent():
    app, db, _ = make(unlocks=[("encirclement", "ember")])
    r = ring(app, A1, "ember")
    assert r.status_code == 200, r.text
    assert agent(db, A1).flare_encirclement_variant == "ember"
    assert r.json()["flare_encirclement_variant"] == "ember"


def test_a_ring_the_developer_has_not_unlocked_is_refused_with_the_sentence_that_unlocks_it():
    app, db, _ = make(unlocks=[("encirclement", "lantern")])
    r = ring(app, A1, "ember")
    assert r.status_code == 403 and "Cast three ballots" in r.text
    assert agent(db, A1).flare_encirclement_variant is None


def test_another_developers_unlock_does_not_count():
    app, db, _ = make(other_unlocks=[("encirclement", "ember")])
    r = ring(app, A1, "ember")
    assert r.status_code == 403
    assert agent(db, A1).flare_encirclement_variant is None


def test_a_strangers_agent_cannot_be_given_a_ring_even_with_the_unlock():
    app, db, _ = make(unlocks=[("encirclement", "ember")])
    r = ring(app, STRANGER, "ember")
    assert r.status_code == 403 and "do not own" in r.text
    assert agent(db, STRANGER).flare_encirclement_variant is None


def test_the_change_touches_the_agents_card_so_peers_pull_it():
    app, _, _ = make(unlocks=[("encirclement", "ember"), ("corner", "initiate")])
    ring(app, A1, "ember")
    badge(app, A2, "initiate")
    assert A1 in TOUCHED and A2 in TOUCHED


def test_a_missing_agent_is_a_404():
    app, _, _ = make(unlocks=[("encirclement", "ember")])
    assert ring(app, "did:theprotocol:eu.test:nobody", "ember").status_code == 404


def test_an_agent_that_wears_a_bought_ring_is_told_to_take_it_off_first():
    app, db, _ = make(unlocks=[("encirclement", "ember")], bears_enc=(A1,))
    r = ring(app, A1, "ember")
    assert r.status_code == 409 and "bought ring" in r.text
    assert agent(db, A1).flare_encirclement_variant is None


def test_an_earned_ring_is_worn_by_one_agent_at_a_time_and_moves():
    app, db, _ = make(unlocks=[("encirclement", "ember")])
    assert ring(app, A1, "ember").status_code == 200
    assert ring(app, A2, "ember").status_code == 200
    assert agent(db, A1).flare_encirclement_variant is None and agent(db, A2).flare_encirclement_variant == "ember"


def test_clearing_takes_the_earned_ring_off_without_any_bought_flare():
    app, db, _ = make(unlocks=[("encirclement", "ember")])
    ring(app, A1, "ember")
    r = ring(app, A1, "__clear__")
    assert r.status_code == 200 and agent(db, A1).flare_encirclement_variant is None


def test_control_a_bought_variant_still_needs_the_bought_ring():
    app, db, _ = make(unlocks=[("encirclement", "ember")])
    r = ring(app, A1, "sauron")                                       # the old rule: no encirclement slot on this agent
    assert r.status_code == 400 and "doesn't bear an encirclement slot" in r.text
    assert agent(db, A1).flare_encirclement_variant is None


def test_control_an_unknown_key_is_still_a_400():
    app, _, _ = make(unlocks=[("encirclement", "ember")])
    assert ring(app, A1, "nonsense").status_code == 400


def test_a_badge_key_is_not_a_ring():
    app, db, _ = make(unlocks=[("corner", "initiate")])
    assert ring(app, A1, "initiate").status_code == 400
    assert agent(db, A1).flare_encirclement_variant is None


# --- the badge --------------------------------------------------------------------------------------------------------------

def test_a_non_admin_owner_wears_an_unlocked_earned_badge_on_an_agent():
    app, db, _ = make(unlocks=[("corner", "initiate")])
    r = badge(app, A1, "initiate")
    assert r.status_code == 200, r.text
    assert agent(db, A1).flare_corner_variant == "initiate"


def test_a_badge_not_unlocked_is_refused_and_another_developers_unlock_does_not_count():
    app, db, _ = make(unlocks=[("corner", "architect-prime")], other_unlocks=[("corner", "initiate")])
    r = badge(app, A1, "initiate")
    assert r.status_code == 403 and "Propose your first change" in r.text
    assert agent(db, A1).flare_corner_variant is None


def test_a_strangers_agent_cannot_be_given_a_badge():
    app, db, _ = make(unlocks=[("corner", "initiate")])
    r = badge(app, STRANGER, "initiate")
    assert r.status_code == 403
    assert agent(db, STRANGER).flare_corner_variant is None


def test_an_agent_that_bears_a_bought_corner_is_told_to_take_it_off_first():
    app, db, _ = make(unlocks=[("corner", "initiate")], bears_corner=(A1,))
    r = badge(app, A1, "initiate")
    assert r.status_code == 409 and "bought corner" in r.text
    assert agent(db, A1).flare_corner_variant is None


def test_an_earned_badge_is_worn_by_one_agent_at_a_time_and_moves():
    app, db, _ = make(unlocks=[("corner", "initiate")])
    badge(app, A1, "initiate")
    badge(app, A2, "initiate")
    assert agent(db, A1).flare_corner_variant is None and agent(db, A2).flare_corner_variant == "initiate"


def test_a_non_admin_takes_an_earned_badge_off_but_the_old_badges_stay_admin_only():
    app, db, _ = make(unlocks=[("corner", "initiate")])
    badge(app, A1, "initiate")
    assert badge(app, A1, "__clear__").status_code == 200 and agent(db, A1).flare_corner_variant is None
    r = badge(app, A1, "rocket")                                      # control: the old admin gate
    assert r.status_code == 403 and "admin-only" in r.text
    assert badge(app, A1, "__clear__").status_code == 403             # control: clearing nothing earned is the old admin act


def test_a_missing_agent_for_a_badge_is_a_403_for_a_non_admin_so_existence_is_not_told():
    app, _, _ = make(unlocks=[("corner", "initiate")])
    assert badge(app, "did:theprotocol:eu.test:nobody", "initiate").status_code == 403


# --- a bought flare on an agent that wears an earned item ---------------------------------------------------------------------

def equip(app, slot, did):
    return call(app, "POST", f"/api/v1/fiat/flare/equip/{slot}/{did}")


def test_a_bought_corner_is_refused_on_an_agent_that_wears_an_earned_badge():
    app, db, me = make(unlocks=[("corner", "initiate")])
    me["dev"].flare_tier, me["dev"].selected_corner_flare = "founder", "founder"
    db.sync.commit()
    assert badge(app, A1, "initiate").status_code == 200
    r = equip(app, "corner", A1)
    assert r.status_code == 409 and "Take it off first" in r.text
    a = agent(db, A1)
    assert a.flare_corner_variant == "initiate" and not a.bears_corner_flare


def test_a_bought_ring_is_refused_on_an_agent_that_wears_an_earned_ring():
    app, db, me = make(unlocks=[("encirclement", "ember")])
    me["dev"].flare_tier, me["dev"].selected_encirclement_flare = "shadow_chancellor", "shadow_chancellor"
    db.sync.commit()
    assert ring(app, A1, "ember").status_code == 200
    r = equip(app, "encirclement", A1)
    assert r.status_code == 409 and "Take it off first" in r.text
    a = agent(db, A1)
    assert a.flare_encirclement_variant == "ember" and not a.bears_encirclement_flare


def test_control_a_bought_corner_still_goes_on_a_free_agent():
    app, db, me = make()
    me["dev"].flare_tier, me["dev"].selected_corner_flare = "founder", "founder"
    db.sync.commit()
    r = equip(app, "corner", A2)
    assert r.status_code == 200, r.text
    assert agent(db, A2).bears_corner_flare


# --- one copy, one bearer: the developer and the agents -----------------------------------------------------------------------

def dev_row(db):
    db.sync.expire_all()
    return db.sync.get(models.Developer, ME)


def select(app, **body):
    return call(app, "PATCH", "/api/v1/fiat/flare/selection", json=body)


@pytest.fixture()
def _status(monkeypatch):
    async def payload(dev, db=None):
        return fo.FlareStatusResponse(flare_encirclement_variant=dev.flare_encirclement_variant)
    monkeypatch.setattr(fo, "_flare_status_payload", payload)


def test_an_agent_taking_the_ring_the_developer_wears_takes_it_off_the_developer(_status):
    app, db, me = make(unlocks=[("encirclement", "ember")])
    assert select(app, variant="ember").status_code == 200
    assert dev_row(db).flare_encirclement_variant == "ember"
    assert ring(app, A1, "ember").status_code == 200
    assert agent(db, A1).flare_encirclement_variant == "ember" and dev_row(db).flare_encirclement_variant is None


def test_the_developer_taking_the_ring_an_agent_wears_takes_it_off_the_agent(_status):
    app, db, me = make(unlocks=[("encirclement", "ember")])
    ring(app, A1, "ember")
    assert select(app, variant="ember").status_code == 200
    assert dev_row(db).flare_encirclement_variant == "ember" and agent(db, A1).flare_encirclement_variant is None


def test_the_same_for_a_badge(_status):
    app, db, me = make(unlocks=[("corner", "initiate")])
    assert select(app, corner_variant="initiate").status_code == 200
    assert dev_row(db).flare_corner_variant == "initiate"
    assert badge(app, A1, "initiate").status_code == 200
    assert dev_row(db).flare_corner_variant is None and agent(db, A1).flare_corner_variant == "initiate"
    assert select(app, corner_variant="initiate").status_code == 200
    assert agent(db, A1).flare_corner_variant is None and dev_row(db).flare_corner_variant == "initiate"


def test_another_ring_on_the_developer_leaves_the_agents_ring_alone(_status):
    app, db, me = make(unlocks=[("encirclement", "ember"), ("encirclement", "lantern")])
    ring(app, A1, "ember")
    assert select(app, variant="lantern").status_code == 200
    assert agent(db, A1).flare_encirclement_variant == "ember" and dev_row(db).flare_encirclement_variant == "lantern"


# --- what a peer is shown ---------------------------------------------------------------------------------------------------

def _dev(**kw):
    base = dict(flare_tier=None, flare_encirclement_variant=None, flare_corner_variant=None, flare_encirclement_overlay=None, selected_corner_flare=None,
                selected_encirclement_flare=None, flare_id=None, flare_display_name=None, flare_tagline=None, flare_logo_url=None, flare_link_url=None,
                flare_cause=None, flare_accent_color=None, flare_granted_at=None)
    base.update(kw)
    return NS(**base)


def _agent(**kw):
    base = dict(flare_tier=None, bears_corner_flare=False, bears_encirclement_flare=False, flare_encirclement_variant=None, flare_encirclement_overlay=None,
                flare_corner_variant=None)
    base.update(kw)
    return NS(**base)


def test_an_agent_ships_the_earned_ring_and_badge_it_wears_and_nothing_of_the_developers():
    from agentvault_registry.routers.federation_sync import _build_flare_sidecar
    dev = _dev(flare_encirclement_variant="ember", flare_corner_variant="initiate")           # the developer wears both on their own avatar
    wearing = _agent(flare_encirclement_variant="abyss", flare_corner_variant="lantern-key")
    side = run(_build_flare_sidecar(wearing, dev, "spiffe://x"))
    assert side and side["encirclement_variant"] == "abyss" and side["corner_variant"] == "lantern-key"
    sibling = _agent()
    assert run(_build_flare_sidecar(sibling, dev, "spiffe://x")) is None                       # an agent given nothing shows nothing of the developer's


def test_an_earned_ring_alone_is_enough_for_a_sidecar_with_no_flare_tier_anywhere():
    from agentvault_registry.routers.federation_sync import _build_flare_sidecar
    side = run(_build_flare_sidecar(_agent(flare_encirclement_variant="ember"), _dev(), "spiffe://x"))
    assert side and side["encirclement_variant"] == "ember" and side["tier"] is None


def test_control_an_old_variant_on_an_agent_with_no_tier_still_exports_nothing():
    from agentvault_registry.routers.federation_sync import _build_flare_sidecar
    assert run(_build_flare_sidecar(_agent(flare_encirclement_variant="sauron"), _dev(), "spiffe://x")) is None


def test_a_bought_bearer_does_not_inherit_the_developers_earned_ring_or_badge():
    # the developer wears an EARNED ring and badge on their own avatar; an agent that bears a BOUGHT ring or corner must not show them (the variant column is shared)
    from agentvault_registry.routers.federation_sync import _build_flare_sidecar
    dev = _dev(flare_tier="shadow_chancellor", flare_encirclement_variant="ember", flare_corner_variant="initiate", selected_encirclement_flare="shadow_chancellor",
               selected_corner_flare="founder")
    bearer = _agent(bears_encirclement_flare=True, bears_corner_flare=True)
    side = run(_build_flare_sidecar(bearer, dev, "spiffe://x"))
    assert side["encirclement_variant"] is None and side["corner_variant"] is None
    assert side["bears_encirclement_flare"] and side["bears_corner_flare"]


def test_control_a_bought_bearer_still_inherits_the_developers_bought_variant():
    from agentvault_registry.routers.federation_sync import _build_flare_sidecar
    dev = _dev(flare_tier="shadow_chancellor", flare_encirclement_variant="goth", flare_corner_variant="rocket", selected_encirclement_flare="shadow_chancellor",
               selected_corner_flare="founder")
    side = run(_build_flare_sidecar(_agent(bears_encirclement_flare=True, bears_corner_flare=True), dev, "spiffe://x"))
    assert side["encirclement_variant"] == "goth" and side["corner_variant"] == "rocket"


def test_the_agents_list_does_not_hand_a_bought_corner_bearer_the_developers_earned_badge():
    import inspect
    from agentvault_registry.routers import developers
    src = inspect.getsource(developers)
    chunk = src.split("dev_corner_variant_fallback = getattr", 1)[1][:600]
    assert "EARNED_CORNERS" in chunk and "dev_corner_variant_fallback = None" in chunk


def test_a_sovereign_agent_never_inherits_the_developers_earned_items():
    from agentvault_registry.routers.federation_sync import _build_flare_sidecar
    dev = _dev(flare_encirclement_variant="ember", flare_corner_variant="initiate")
    side = run(_build_flare_sidecar(_agent(flare_tier="sovereign", flare_encirclement_variant="aurora"), dev, "spiffe://x"))
    assert side["encirclement_variant"] == "aurora" and side["corner_variant"] is None


# --- the one writer ---------------------------------------------------------------------------------------------------------

def test_the_wear_routes_read_the_unlock_table_and_never_write_it():
    import inspect
    src = inspect.getsource(fo)
    body = src.split("async def update_agent_flare_variant", 1)[1].split("# §28 (2026-05-13) — Per-agent overlay PATCH", 1)[0]
    body += src.split("async def set_agent_corner_variant", 1)[1].split("# Public stats", 1)[0]
    assert "require_unlocked" in body
    assert "CosmeticUnlock" not in body and "cosmetic_unlocks" not in body and "contributor_track.Tracker" not in body
