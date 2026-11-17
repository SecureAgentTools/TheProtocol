"""V0664 (order gwo_2dc9f93f2096cf1da1708a26, session-lead room seq 4002): a suspended author publishes nothing, sets no
price, and sells nothing; what is already theirs or already bought stays readable.

  the gate   template_publish joins services/enforcement_propagation's sites: wherever the bond gate is asked (a template
             made visible or priced, a version published while visible, a price set or raised), the suspension gate is
             asked first; enforce refuses a suspended or revoked agent with the enforcement sentence (403 enforced)
  the list   a suspended author's templates leave the public list (as discovery hides an enforced agent: under enforce)
  a sale     a new purchase of a suspended author's template is refused with the enforcement sentence; a purchase
             recorded before the suspension finishes as recorded (the escrow is never left holding a deposit)
  reads      the owner reads its own templates and files; a buyer reads what it bought
Both ways: every refusal has its control, the same act by an author in good standing, and shadow and off pass.
Red on 1402ee756: the suspension gate is never asked.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from agentvault_registry.services import enforcement_propagation as ep
from agentvault_registry.services import workflow_templates as wt
from tests.test_workflow_templates_kit_v0664 import kit
from tests.test_workflow_templates_library_v0664 import BUYER, OWNER, FakeStore, agent, lib, make, refused, run

SUSPENDED = "did:a:suspended-author"


def _suspended(s, mode="enforce"):
    s.enf_mode, s.enforced = mode, {SUSPENDED}


def test_the_site_is_one_of_the_suspension_gates_sites():
    assert "template_publish" in ep.GATE_SITES
    out, why = run(ep.decide(None, SUSPENDED, site="template_publish", mode="off"))
    assert out["decision"] == "skipped" and why is None


@pytest.mark.parametrize("act", ["create visible", "create priced", "patch visible", "patch price", "publish visible"])
def test_a_suspended_author_publishes_nothing_and_sets_no_price_and_a_good_one_does(act):
    for who, ok in ((SUSPENDED, False), (OWNER, True)):
        s = FakeStore()
        draft = run(lib(s).create(agent(who), {"slug": "dd", "title": "D", "files": kit()}))["template_id"]
        if act == "publish visible":
            s.templates[draft]["visibility"] = "public"
        _suspended(s)
        call = {"create visible": lambda: lib(s).create(agent(who), {"slug": "vv", "title": "V", "visibility": "public",
                                                                      "files": kit()}),
                "create priced": lambda: lib(s).create(agent(who), {"slug": "pp", "title": "P", "pricing_model": "purchase",
                                                                     "price": "5", "files": kit()}),
                "patch visible": lambda: lib(s).patch(agent(who), draft, {"visibility": "unlisted"}),
                "patch price": lambda: lib(s).patch(agent(who), draft, {"pricing_model": "purchase", "price": "5"}),
                "publish visible": lambda: lib(s).publish(agent(who), draft, 1)}[act]
        if ok:
            run(call())
        else:
            e = refused(call(), 403, "enforced")
            assert "template_publish" in e.sentence and "suspended" in e.sentence
            assert s.bond_asks.count(who) == 0, "the suspension gate answers before the bond is asked"


def test_shadow_and_off_let_a_suspended_author_through():
    for mode in ("shadow", "off"):
        s = FakeStore()
        _suspended(s, mode)
        assert run(lib(s).create(agent(SUSPENDED), {"slug": "xx", "title": "X", "visibility": "public", "files": kit()}))


def test_a_suspended_authors_templates_leave_the_public_list_and_return_after():
    s = FakeStore()
    mine, theirs = make(s, by=SUSPENDED, slug="sus"), make(s, by=OWNER, slug="good")
    _suspended(s)
    assert [t["id"] for t in run(lib(s).list({}))["items"]] == [theirs]
    s.enforced = set()
    assert sorted(t["id"] for t in run(lib(s).list({}))["items"]) == sorted([mine, theirs])


def test_a_new_purchase_from_a_suspended_author_is_refused_and_one_from_a_good_author_passes():
    s = FakeStore()
    sus, good = make(s, by=SUSPENDED, slug="sus", pricing="purchase", price="5"), make(s, by=OWNER, slug="good",
                                                                                         pricing="purchase", price="5")
    _suspended(s)
    e = refused(lib(s).purchase(agent(BUYER), sus), 403, "enforced")
    assert "suspended" in e.sentence and s.legs == [] and run(s.purchase_row(sus, BUYER)) is None
    assert run(lib(s).purchase(agent(BUYER), good))["ok"] is True


def test_a_purchase_recorded_before_the_suspension_finishes_as_recorded():
    s = FakeStore()
    sus = make(s, by=SUSPENDED, slug="sus", pricing="purchase", price="5")
    s.fail_payout_once = True
    with pytest.raises(RuntimeError):
        run(lib(s).purchase(agent(BUYER), sus))                  # the deposit took 5, the payout did not run
    _suspended(s)
    run(lib(s).purchase(agent(BUYER), sus))
    took, paid = s.taken_and_paid(f"wtpl:{sus}:")
    assert took == paid, "the escrow is never left holding the buyer's deposit"


def test_the_owner_and_a_buyer_still_read_what_is_theirs():
    s = FakeStore()
    sus = make(s, by=SUSPENDED, slug="sus", pricing="purchase", price="5")
    run(lib(s).purchase(agent(BUYER), sus))
    _suspended(s)
    for actor in (agent(SUSPENDED), agent(BUYER)):
        assert run(lib(s).detail(actor, sus))["id"] == sus
        assert run(lib(s).version(actor, sus, 1))["files"]["migration.yaml"]


def test_the_store_asks_the_suspension_gate_at_its_site_and_returns_its_sentence(monkeypatch):
    seen = []

    async def gate(db, did, *, site, mode=None):
        seen.append((did, site))
        if did == SUSPENDED:
            raise HTTPException(403, detail=f"Agent {did} is suspended by EU; {site} is refused while the enforcement "
                                            "stands (ENFORCEMENT_PROPAGATION_MODE=enforce).")
        return {"decision": "allow"}
    monkeypatch.setattr(ep, "gate", gate)
    store = wt.DbStore(db=None)
    run(store.enforcement_gate("did:a:good"))
    with pytest.raises(wt.LibraryRefusal) as e:
        run(store.enforcement_gate(SUSPENDED))
    assert (e.value.status, e.value.code) == (403, "enforced") and "suspended" in e.value.sentence
    assert seen == [("did:a:good", "template_publish"), (SUSPENDED, "template_publish")]


def test_the_database_list_leaves_out_a_suspended_authors_templates_under_enforce(monkeypatch):
    from sqlalchemy import text
    from tests.test_workflow_templates_dbstore_v0664 import store as db_store
    s, db = db_store()
    c = db.conn
    for col in ("visibility TEXT DEFAULT 'public'", "owner_agent_did TEXT", "created_at TIMESTAMP"):
        c.execute(text(f"ALTER TABLE workflow_templates ADD COLUMN {col}"))
    c.execute(text("ALTER TABLE agents ADD COLUMN status TEXT DEFAULT 'active'"))
    c.execute(text("UPDATE workflow_templates SET owner_agent_did = 'did:a:one' WHERE id = 'wtpl_a'"))
    c.execute(text("INSERT INTO workflow_templates (id, owner_agent_did) VALUES ('wtpl_b', 'did:a:two')"))
    c.execute(text("UPDATE agents SET status = 'suspended' WHERE did = 'did:a:two'"))
    c.commit()
    monkeypatch.setattr(ep, "propagation_mode", lambda: "enforce")
    assert [r["id"] for r in run(s.list_public({}))] == ["wtpl_a"]
    monkeypatch.setattr(ep, "propagation_mode", lambda: "shadow")
    assert sorted(r["id"] for r in run(s.list_public({}))) == ["wtpl_a", "wtpl_b"]
