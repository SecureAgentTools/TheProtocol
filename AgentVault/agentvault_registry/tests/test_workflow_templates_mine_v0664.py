"""V0664 (order gwo_ef4d9981fcbba89cb8e5378b, for C4's My templates, session-watch room seq 3984): an owner lists its own
templates. GET /api/v1/workflow-templates listed public ones only; a draft or an unlisted template was reachable only by its
id, and nothing read the buyers.

GET /api/v1/workflow-templates/mine (services/workflow_templates.Library.mine), read-only:
  who        an agent token: the acting agent's templates; a developer token: those of every agent the developer created;
             no token: 401 signed_in; another agent sees none of them
  what       each template's listing (visibility, pricing, fork share, the counts the public listing has), its versions
             (number, published or draft, the time, content hash, changelog) and its buyers: the number of done purchases
             and each buyer's agent DID and the time (no other data about a buyer; a purchase still pending is no buyer)
Over the library's in-memory store, and the store's own SQL on SQLite. Red on f96c63088: there is no such read.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import text

from agentvault_registry.services import workflow_templates as wt
from tests.test_workflow_templates_kit_v0664 import kit
from tests.test_workflow_templates_library_v0664 import (BUYER, OTHER, OWNER, FakeStore, agent, developer, lib, make,
                                                         refused, run)


def _three(s):
    draft = make(s, visibility="private", slug="draft", publish=False)
    unlisted = make(s, visibility="unlisted", slug="unlisted")
    public = make(s, slug="public", pricing="purchase", price="5")
    run(lib(s).add_version(agent(OWNER), public, {"files": kit(**{"README.md": "# v2\n"}), "changelog": "more words"}))
    return draft, unlisted, public


def test_the_owner_sees_drafts_unlisted_and_public_with_versions_and_buyers():
    s = FakeStore()
    draft, unlisted, public = _three(s)
    run(lib(s).purchase(agent(BUYER), public))
    items = {i["id"]: i for i in run(lib(s).mine(agent(OWNER)))["items"]}
    assert set(items) == {draft, unlisted, public}
    assert items[draft]["visibility"] == "private" and items[draft]["versions"][0]["published"] is False
    v = items[public]["versions"]
    assert [(x["version"], x["published"]) for x in v] == [(1, True), (2, False)] and v[1]["changelog"] == "more words"
    assert all(len(x["content_hash"]) == 64 for x in v)
    assert items[public]["pricing_model"] == "purchase" and items[public]["fork_share_bps"] == 2000
    assert set(items[public]["counts"]) == set(wt.COUNT_KEYS)
    b = items[public]["buyers"]
    assert b["count"] == 1 and [set(x) for x in b["list"]] == [{"agent_did", "at"}] and b["list"][0]["agent_did"] == BUYER
    assert items[draft]["buyers"] == {"count": 0, "list": []}


def test_another_agent_sees_none_of_them_and_nobody_signed_in_is_refused():
    s = FakeStore()
    _three(s)
    assert run(lib(s).mine(agent(OTHER)))["items"] == []
    refused(lib(s).mine(None), 401, "signed_in")


def test_a_developer_token_sees_its_agents_templates():
    s = FakeStore()
    draft, unlisted, public = _three(s)
    assert {i["id"] for i in run(lib(s).mine(developer(1)))["items"]} == {draft, unlisted, public}   # dev 1 owns OWNER
    assert run(lib(s).mine(developer(3)))["items"] == []


def test_a_purchase_still_pending_is_no_buyer():
    s = FakeStore()
    public = make(s, slug="public", pricing="purchase", price="5")
    s.fail_payout_once = True
    try:
        run(lib(s).purchase(agent(BUYER), public))
    except RuntimeError:
        pass
    assert run(lib(s).mine(agent(OWNER)))["items"][0]["buyers"] == {"count": 0, "list": []}


def test_the_stores_reads_on_the_database():
    from tests.test_workflow_templates_dbstore_v0664 import T0, store as db_store
    s, db = db_store()
    c = db.conn
    for col in ("owner_agent_did TEXT", "updated_at TIMESTAMP"):
        c.execute(text(f"ALTER TABLE workflow_templates ADD COLUMN {col}"))
    c.execute(text("UPDATE workflow_templates SET owner_agent_did = 'did:a:one' WHERE id = 'wtpl_a'"))
    c.execute(text("INSERT INTO workflow_templates (id, owner_agent_did) VALUES ('wtpl_b', 'did:a:two'), "
                   "('wtpl_c', 'did:a:three')"))
    c.commit()
    assert [t["id"] for t in run(s.templates_of_agent("did:a:one"))] == ["wtpl_a"]
    assert sorted(t["id"] for t in run(s.templates_of_developer(7))) == ["wtpl_a", "wtpl_b"]   # dev 7 made one and two
    row = {"template_id": "wtpl_a", "buyer_did": "did:a:three", "price": Decimal("10"), "share": Decimal("0"),
           "currency": "ECU", "author_did": "did:a:one", "parent_did": None, "at": T0}
    run(s.insert_pending_purchase(row))
    run(s.insert_pending_purchase({**row, "buyer_did": "did:a:two"}))
    run(s.finish_purchase(run(s.purchase_row("wtpl_a", "did:a:three")), T0))
    assert [b["buyer_did"] for b in run(s.buyers("wtpl_a"))] == ["did:a:three"], "the pending one is no buyer"
