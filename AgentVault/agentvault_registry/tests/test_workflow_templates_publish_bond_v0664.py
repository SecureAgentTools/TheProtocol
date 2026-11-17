"""V0664 (order gwo_2dc9f93f2096cf1da1708a26, found by session-tester, room seq 3952; decided by session-lead, seq 3957):
publishing a migration template passes the reputation bond gate, not legacy-full.

M4's create and fork routes required contract.template.publish, which no role carries and no owner can grant, so no
agent of a new developer could put up a template. Now:
  drafts     any agent creates a template, adds versions and forks one it may read: private drafts, no gate
  publish    what others can see, and what costs money, passes services/reputation_bond.gate(db, did,
             site="template_publish"): a template created or patched to public, unlisted or org; a version published
             while the template is visible; a price set or raised (create purchase-priced, patch to purchase, a higher
             price). off passes, shadow counts and passes, enforce refuses with the gate's own sentence, nothing written
  not asked  a private draft, its versions, a fork, a lower price or a free template, a purchase, an instantiate
The route keeps the M4 answer shape: {code: bond_required, detail: the gate's sentence}, 403.
Red on v0664/cut 64ab5a54e: the routes require contract.template.publish and the library never asks the bond.
"""
from __future__ import annotations

import asyncio
import pathlib

import pytest
from fastapi import HTTPException

from agentvault_registry.services import reputation_bond as rb
from agentvault_registry.services import workflow_templates as wt
from tests.test_workflow_templates_kit_v0664 import kit
from tests.test_workflow_templates_library_v0664 import (BUYER, OTHER, OWNER, FakeStore, agent, lib, make, refused,
                                                         run)

SRC = pathlib.Path(wt.__file__).resolve().parents[1]
FRESH = "did:a:fresh-agent-of-a-new-developer"


def _enforce(s, *bonded):
    s.bond_mode, s.bonded = "enforce", set(bonded)


def test_the_site_is_one_of_the_bond_gates_sites():
    assert "template_publish" in rb.GATE_SITES
    out, why = run(rb.decide(None, FRESH, site="template_publish", mode="off"))
    assert out["decision"] == "skipped" and why is None


def test_a_fresh_agent_drafts_versions_and_forks_privately_without_a_bond():
    s = FakeStore()
    public = make(s, by=OWNER, slug="public-one")                         # someone else's public template, to fork
    s.bond_asks.clear()
    _enforce(s)                                                            # enforce, and nobody holds a bond
    tid = run(lib(s).create(agent(FRESH), {"slug": "draft", "title": "Draft", "files": kit()}))["template_id"]
    run(lib(s).add_version(agent(FRESH), tid, {"files": kit(**{"README.md": "# v2\n"})}))
    run(lib(s).publish(agent(FRESH), tid, 1))                              # a private template's version: nobody sees it
    assert run(lib(s).fork(agent(FRESH), public, {"slug": "my-fork"}))["template_id"].startswith("wtpl_")
    assert s.bond_asks == [], "no step of a private draft asks the bond"


@pytest.mark.parametrize("visibility", ["public", "unlisted", "org"])
def test_in_enforce_a_visible_template_needs_a_bond_and_nothing_is_written_without_one(visibility):
    s = FakeStore()
    _enforce(s)
    e = refused(lib(s).create(agent(FRESH), {"slug": "shown", "title": "Shown", "visibility": visibility,
                                             "files": kit()}), 403, "bond_required")
    assert "template_publish" in e.sentence and not s.templates and not s.versions
    s.bonded.add(FRESH)
    assert run(lib(s).create(agent(FRESH), {"slug": "shown", "title": "Shown", "visibility": visibility,
                                            "files": kit()}))["template_id"]


def test_in_enforce_making_a_draft_visible_and_publishing_while_visible_need_a_bond():
    s = FakeStore()
    _enforce(s)
    tid = run(lib(s).create(agent(FRESH), {"slug": "later", "title": "Later", "files": kit()}))["template_id"]
    refused(lib(s).patch(agent(FRESH), tid, {"visibility": "public"}), 403, "bond_required")
    assert s.templates[tid]["visibility"] == "private"
    s.bonded.add(FRESH)
    run(lib(s).patch(agent(FRESH), tid, {"visibility": "public"}))
    run(lib(s).add_version(agent(FRESH), tid, {"files": kit(**{"README.md": "# v2\n"})}))
    s.bonded.clear()                                                       # the bond released since
    refused(lib(s).publish(agent(FRESH), tid, 2), 403, "bond_required")
    assert s.versions and all(v["published_at"] is None for v in s.versions.values() if v["version"] == 2)


def test_in_enforce_setting_or_raising_a_price_needs_a_bond_and_lowering_it_does_not():
    s = FakeStore()
    _enforce(s)
    refused(lib(s).create(agent(FRESH), {"slug": "paid", "title": "Paid", "pricing_model": "purchase", "price": "5",
                                         "files": kit()}), 403, "bond_required")
    tid = run(lib(s).create(agent(FRESH), {"slug": "free", "title": "Free", "files": kit()}))["template_id"]
    refused(lib(s).patch(agent(FRESH), tid, {"pricing_model": "purchase", "price": "5"}), 403, "bond_required")
    s.bonded.add(FRESH)
    run(lib(s).patch(agent(FRESH), tid, {"pricing_model": "purchase", "price": "5"}))
    s.bonded.clear()
    refused(lib(s).patch(agent(FRESH), tid, {"price": "8"}), 403, "bond_required")
    asks = len(s.bond_asks)
    run(lib(s).patch(agent(FRESH), tid, {"price": "3"}))
    run(lib(s).patch(agent(FRESH), tid, {"pricing_model": "free"}))
    run(lib(s).patch(agent(FRESH), tid, {"title": "Free again"}))
    assert len(s.bond_asks) == asks, "a lower price, a free template and a title change ask nothing"


def test_shadow_asks_and_lets_through_and_off_asks_nothing():
    s = FakeStore()
    s.bond_mode = "shadow"                                                 # the FakeStore counts a shadow ask, never refuses
    tid = run(lib(s).create(agent(FRESH), {"slug": "shadowed", "title": "S", "visibility": "public",
                                           "files": kit()}))["template_id"]
    run(lib(s).publish(agent(FRESH), tid, 1))
    assert s.bond_asks == [FRESH, FRESH]
    s2 = FakeStore()
    tid2 = run(lib(s2).create(agent(FRESH), {"slug": "open", "title": "O", "visibility": "public", "files": kit()}))
    assert tid2["template_id"] and s2.bond_asks == [FRESH], "off: the store's gate answers skipped (DbStore below)"


def test_a_buyer_and_an_instantiator_need_no_bond():
    s = FakeStore()
    paid, free = make(s, pricing="purchase", price="5"), make(s, slug="free-one")
    _enforce(s)                                                            # and the buyer and the instantiator hold no bond
    asks = len(s.bond_asks)
    run(lib(s).purchase(agent(BUYER), paid))
    run(lib(s).instantiate(agent(OTHER), free, {"total_budget": "10"}))
    assert s.bond_asks[asks:] == [], "a purchase and an instantiate ask nothing"


def test_the_store_asks_the_gate_at_its_site_and_returns_its_sentence_as_the_library_refusal(monkeypatch):
    seen = []

    async def gate(db, did, *, site, mode=None, policy=None):
        seen.append((did, site))
        if did == "did:a:unbonded":
            raise HTTPException(403, detail="did:a:unbonded holds no reputation bond. Publishing here (template_publish) "
                                            "requires a bond of 250 ECU: deposit it at POST /api/v1/reputation-bond/deposit")
        return {"decision": "allow"}
    monkeypatch.setattr(rb, "gate", gate)
    store = wt.DbStore(db=None)
    run(store.bond_gate("did:a:bonded"))
    with pytest.raises(wt.LibraryRefusal) as e:
        run(store.bond_gate("did:a:unbonded"))
    assert (e.value.status, e.value.code) == (403, "bond_required") and "deposit" in e.value.sentence
    assert seen == [("did:a:bonded", "template_publish"), ("did:a:unbonded", "template_publish")]


def test_the_mcp_tools_follow_the_routes():
    src = (SRC / "mcp" / "tools_workflow_templates.py").read_text()
    assert "contract.template.publish" not in src
    assert "/versions/{int(version)}/publish" in src, "publish goes through the route that asks the gate"
    assert "reputation bond" in src, "the publish tool's description names the bond"


def test_the_docs_list_the_new_site():
    docs = (SRC / "static" / "new_registry_frontend" / "src" / "assets" / "docs" / "oracle" / "03_staking.md").read_text()
    assert '"template_publish"' in docs
