"""V0657 (b), item 6 (session-code, 2026-11-06): the Directory indexes the organizations each registry lists and the
organization mark on each native card, and answers both in GraphQL.

- a complete read upserts and sweeps (an organization its registry no longer lists is marked, never deleted, and left
  out of the answer); a registry before V0657 (404) or a failed read keeps what is held;
- a native card's org mark is kept with the agent (EXTRACT_VERSION 4 re-reads every card once, so a mark the read
  gained is seen);
- `organizations` and `agents { org }` answer it, with the home rebuilt from the registry's public URL.

It imports `directory.ingest`, which imports the registry's readers, so it runs in the directory image (REQUIRES_REGISTRY).
RED on origin/master (ca7020bf): no organizations are read, stored or answered.
"""
REQUIRES_REGISTRY = True

import asyncio
import json

import directory.ingest as ing
from directory.schema import schema
from directory.store import Store

BASE = "https://eu.theprotocol.cloud"
ORG = "https://theprotocol.cloud/extensions/v1/org"


def _store(tmp_path):
    s = Store(str(tmp_path / "d.db"))
    s.upsert_registry(name="EU", trust_domain="eu.td", tier="frame", public_url=BASE, did_namespace=None, verified=1,
                      reason=None, reachable=1, card_epoch=None, location=None, latitude=None, longitude=None,
                      parent_name=None, federation_status=None, hop=0, last_sync_at=0, last_error=None, agents_indexed=0,
                      card_json=None, currency="ECU")
    return s


def _pull(store, answer):
    async def fake_fetch(client, url, **kw):
        return answer
    orig = ing.fetch_json
    ing.fetch_json = fake_fetch
    try:
        return asyncio.run(ing.pull_organizations(None, store, {"base": BASE, "name": "EU"}))
    finally:
        ing.fetch_json = orig


def _gql(store, q):
    out = schema.execute_sync(q, context_value={"store": store})
    assert not out.errors, out.errors
    return out.data


def test_listed_organizations_are_indexed_swept_and_answered(tmp_path):
    store = _store(tmp_path)
    doc = {"organizations": [
        {"id": "org-1", "slug": "sessions", "name": "Sessions", "logo": "https://x/y?v=abc", "member_count": 3},
        {"id": "org-2", "slug": "labs", "name": "Labs"}], "total": 2}
    out = _pull(store, (doc, None))
    assert out["held"] == 2 and out["gone"] == 0
    data = _gql(store, "{ organizations { total edges { id slug name logo page source home { name origin console } } } }")
    edges = {e["id"]: e for e in data["organizations"]["edges"]}
    assert data["organizations"]["total"] == 2
    assert edges["org-1"]["logo"] == f"{BASE}/api/v1/organizations/org-1/logo?v=abc"
    assert edges["org-1"]["home"] == {"name": "EU", "origin": BASE, "console": f"{BASE}/ui"}
    out = _pull(store, ({"organizations": [doc["organizations"][0]], "total": 1}, None))   # org-2 no longer listed
    assert out["gone"] == 1
    assert [e["id"] for e in _gql(store, "{ organizations { edges { id } } }")["organizations"]["edges"]] == ["org-1"]


def test_a_registry_before_v0657_or_a_failed_read_keeps_what_is_held(tmp_path):
    store = _store(tmp_path)
    _pull(store, ({"organizations": [{"id": "org-1", "name": "Sessions"}], "total": 1}, None))
    for answer in ((None, "http 404"), (None, "http 502")):
        out = _pull(store, answer)
        assert out["held"] == 1
    assert _pull(store, (None, "http 404"))["supported"] is False
    assert _gql(store, "{ organizations { total } }")["organizations"]["total"] == 1


def test_a_native_cards_org_mark_is_kept_with_the_agent_and_answered(tmp_path):
    assert ing.EXTRACT_VERSION >= 4, "a field the read gained is seen only when every card is read again"
    store = _store(tmp_path)
    cd = {"name": "c1", "extensions": [{"uri": ORG, "params": {"id": "org-1", "slug": "sessions", "name": "Sessions",
                                                                "logo": "https://elsewhere.example/l.png?v=1"}}]}

    async def fake_fetch(client, url, **kw):
        if "/agent-cards/?" in url:
            return {"applied_filters": {"natives_only": True},
                    "items": [{"id": "c1", "updated_at": "2026-11-06T00:00:00", "agent_did": "did:x:1"}]}, None
        return {"card_data": cd, "updated_at": "2026-11-06T00:00:00", "is_active": True, "name": "c1",
                "agent_did": "did:x:1"}, None
    orig = ing.fetch_json
    ing.fetch_json = fake_fetch
    try:
        asyncio.run(ing.pull_cards(None, store, {"base": BASE, "name": "EU", "trust_domain": "eu.td", "verified": True},
                                   full=True))
    finally:
        ing.fetch_json = orig
    data = _gql(store, '{ agent(did: "did:x:1") { name org { id name logo page home { origin } } } }')
    assert data["agent"]["org"] == {"id": "org-1", "name": "Sessions",
                                    "logo": f"{BASE}/api/v1/organizations/org-1/logo?v=1",
                                    "page": f"{BASE}/ui/#/firms?org=sessions", "home": {"origin": BASE}}
