"""§TWOAGENT #10 (2026-09-23): the index records a native card's bond and enforcement from the extensions its home states.

Measured on the live EU/ASIA index before this change: every native card read as unbonded, because the registries served
stored card_data on the single-card read and derived nothing (fixed registry-side in V0437). The same read showed a second
defect here: the enforcement flag was taken from `is_enforced` / `enforced`, fields the enforcement block has never carried
(it states `status`), so an enforced agent could only ever index as not enforced.

The bond tests are CONTROLS (they pass before and after this change: the reader was right, the registry was silent); the
enforcement test is the one that changes direction.

It imports `directory.ingest`, which imports the registry's readers (the Directory runs on the registry image), so it runs
in the directory image; the registry-less reader-gate CI job names it and does not collect it (tests/conftest.py).
"""
REQUIRES_REGISTRY = True

import asyncio
import json

import directory.ingest as ing

BOND = "https://theprotocol.cloud/extensions/v1/reputation-bond"
ENF = "https://theprotocol.cloud/extensions/v1/enforcement"


class FakeStore:
    def __init__(self):
        self.rows = {}

    def get_registry(self, name):
        return {"cards_cursor": None}

    def agent_epoch(self, cid):
        return None

    def upsert_agent(self, **kw):
        self.rows[kw["id"]] = kw

    def sweep_source(self, kind, name, seen):
        return 0

    def set_registry_field(self, name, **kw):
        pass

    def count_for_source(self, kind, name):
        return len(self.rows)


def _index(card_data):
    """One native card through the real walk: the list page, then the single-card read the index trusts."""
    async def fake_fetch(client, url, **kw):
        if "/agent-cards/?" in url:
            return {"applied_filters": {"natives_only": True},
                    "items": [{"id": "c1", "updated_at": "2026-09-23T00:00:00", "agent_did": "did:x:1"}]}, None
        return {"card_data": card_data, "updated_at": "2026-09-23T00:00:00", "is_active": True, "name": "c1",
                "agent_did": "did:x:1"}, None

    store = FakeStore()
    orig = ing.fetch_json
    ing.fetch_json = fake_fetch
    try:
        reg = {"base": "http://x", "name": "SRC", "trust_domain": "td", "verified": True}
        asyncio.run(ing.pull_cards(None, store, reg, full=True))
    finally:
        ing.fetch_json = orig
    row = store.rows["c1"]
    return json.loads(row["bond_json"]), json.loads(row["enforcement_json"])


def _ext(uri, **params):
    return {"uri": uri, "required": False, "params": {"version": 1, **params}}


def test_an_enforced_card_is_indexed_as_enforced():
    _, enf = _index({"name": "c1", "extensions": [_ext(ENF, status="suspended", since=None, registry="EU")]})
    assert enf == {"is_enforced": True, "status": "suspended"}, enf


def test_a_card_without_the_block_is_not_enforced():
    """CONTROL: no block, no enforcement (the default the old reader always fell to)."""
    _, enf = _index({"name": "c1"})
    assert enf == {"is_enforced": False, "status": None}, enf


def test_a_status_that_is_not_enforced_does_not_read_as_enforced():
    """CONTROL: the flag follows the status, not the block's presence."""
    _, enf = _index({"name": "c1", "extensions": [_ext(ENF, status="active")]})
    assert enf["is_enforced"] is False and enf["status"] == "active", enf


def test_a_bonded_card_is_indexed_as_bonded():
    """CONTROL (passes on the old reader too): the bond was read correctly whenever a home stated it."""
    bond, _ = _index({"name": "c1", "extensions": [_ext(BOND, status="locked", amount="250", currency="ECU")]})
    assert bond["is_bonded"] is True and bond["status"] == "locked" and bond["currency"] == "ECU", bond


def test_an_unbonded_card_is_not_bonded():
    bond, _ = _index({"name": "c1", "extensions": []})
    assert bond == {"status": "none", "is_bonded": False, "amount": None, "currency": None}, bond


def test_the_extract_version_moved_past_the_silent_reads():
    """The registries only started stating these on the read with V0437; an index that kept version 2 would never
    re-read a card whose updated_at did not move, and every bonded native card would stay unbonded here."""
    assert ing.EXTRACT_VERSION >= 3
