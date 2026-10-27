"""D6-816 (2026-10-24) — a home's erasure reaches the mirror we hold of its card, and nothing else does.

Found by agentvault2-aa's capture of sbx-beta's hourly read (2544 refusals of sbx-alpha cards, 1362 of them erasure
tombstones), diagnosed by agentvault2-d6: a home that deletes an account redacts that developer's cards
(routers/account_deletion.py, step 5: card_data to the DID, the capabilities and `anonymized: true`, inactive) and keeps
exporting them. On a frame with FEDERATION_INGEST_FAIL_CLOSED the tombstone failed the AgentCard schema, and
§QUARANTINEDENY could not apply its deactivation because the tombstone names no origin (is_origin_copy() is False): the
mirror kept serving the deleted account's card, ACTIVE and whole.

The rule under test: the redaction lands on a MIRROR we hold when the presenter is that mirror's own home (the origin we
stored, or the caller's from_origin); never on a native card, never from another peer, never as an insert; a tombstone is
never counted as a schema refusal; an ACTIVE card that merely says anonymized still meets the schema. The last test runs
the V0636 path (the D6-816 branch bypassed) and shows the defect.
"""
from __future__ import annotations

import asyncio
import copy
import os
import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://t:t@localhost:5432/t")
os.environ.setdefault("API_KEY_SECRET", "test-only-secret-value-0123456789abcdef")

DID = "did:theprotocol:eu.theprotocol.cloud:8fc4b88b-1f15-4c5a-b293-00d9e6a05ca3"
HOME = "spiffe://eu.theprotocol.cloud/registry/eu"
RELAY = "spiffe://asia.theprotocol.cloud/registry/asia"
WRITTEN = datetime(2026, 9, 12, 14, 32, 17)
FED = {"origin_registry_name": "EU", "source_registry": "spiffe://eu.theprotocol.cloud/service/registry",
       "first_synced_from": HOME}


def _mirror_cd():
    return {"name": "Jane's Booking Agent", "description": "books for Jane Example", "url": "https://agent.example.test/a2a",
            "version": "1.0", "capabilities": {"streaming": False}, "skills": [], "federation_metadata": dict(FED)}


def _native_cd():
    # the shape of sbx-beta's 49 native cards whose ids sbx-alpha's tombstones carried: origin name only, no mirror source
    cd = _mirror_cd()
    cd["federation_metadata"] = {"origin_registry_name": "EU"}
    return cd


def _tombstone(card_id, *, is_active=False):
    return {"id": card_id, "name": f"deleted-card-{card_id}", "description": None, "is_active": is_active,
            "updated_at": "2026-10-24T09:01:03.000000+00:00",
            "card_data": {"did": DID, "capabilities": {"streaming": False}, "anonymized": True}}


class _Result:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row

    def fetchall(self):
        return []


class _Session:
    """Answers every read with the row it holds; has no add(), so an insert would raise."""

    def __init__(self, existing):
        self.existing, self.commits = existing, 0

    async def execute(self, stmt, params=None):
        return _Result(self.existing)

    async def commit(self):
        self.commits += 1

    async def get(self, model, key):
        return None


class _Counter:
    def __init__(self):
        self.incs = []

    def labels(self, **kw):
        outer = self

        class _L:
            def inc(self, n=1):
                outer.incs.append(kw)
        return _L()


def _existing(cd, *, is_active=True):
    return SimpleNamespace(card_data=copy.deepcopy(cd), name=cd.get("name"), description=cd.get("description"),
                           is_active=is_active, updated_at=WRITTEN, developer_id=None, agent_did=DID, unlisted=False)


@pytest.fixture(autouse=True)
def _fail_closed(monkeypatch):
    monkeypatch.setenv("FEDERATION_INGEST_FAIL_CLOSED", "true")
    monkeypatch.setenv("LISTING_PROPAGATION_MODE", "off")


def _upsert(existing, incoming, *, presenter_td="eu.theprotocol.cloud", peer=HOME, from_origin=False):
    from agentvault_registry.crud import crud_peer_registry as crud
    db = _Session(existing)
    res = asyncio.run(crud.upsert_agent_cards_from_peer(
        db=db, peer_svid=peer, agent_card=incoming, peer_trust_domain=presenter_td, from_origin=from_origin))
    return res, db


def test_the_tombstone_really_fails_the_schema():
    """Control: without this the tests below could pass through the ordinary path and prove nothing."""
    from agentvault import AgentCard
    with pytest.raises(Exception):
        AgentCard.model_validate(_tombstone(str(uuid.uuid4()))["card_data"])


def test_the_homes_erasure_lands_on_its_mirror():
    cid = str(uuid.uuid4())
    existing = _existing(_mirror_cd())
    res, db = _upsert(existing, _tombstone(cid))
    assert res == "updated" and db.commits == 1
    assert existing.is_active is False, "the home erased the card and our mirror still serves it"
    assert existing.card_data == {"did": DID, "capabilities": {"streaming": False}, "anonymized": True,
                                  "federation_metadata": FED}, "the mirror kept the deleted account's content"
    assert existing.name == f"deleted-card-{cid}" and existing.description is None


def test_the_callers_from_origin_counts_too():
    existing = _existing(_mirror_cd())
    res, _ = _upsert(existing, _tombstone(str(uuid.uuid4())), presenter_td=None, from_origin=True)
    assert res == "updated" and existing.is_active is False
    assert existing.card_data.get("anonymized") is True, "§QUARANTINEDENY alone deactivated it and kept the content"


def test_another_peer_cannot_erase_a_mirror():
    """Control: only the mirror's own home speaks for it; the tombstone's word about itself proves nothing."""
    existing = _existing(_mirror_cd())
    res, db = _upsert(existing, _tombstone(str(uuid.uuid4())), presenter_td="asia.theprotocol.cloud", peer=RELAY)
    assert res == "skipped" and db.commits == 0
    assert existing.is_active is True and existing.card_data == _mirror_cd()


def test_a_native_card_is_never_erased_by_a_peer():
    """Control: sbx-beta's 49 — its own cards, whose ids a peer's imported-then-deleted copies carried."""
    existing = _existing(_native_cd())
    res, db = _upsert(existing, _tombstone(str(uuid.uuid4())))
    assert res == "skipped" and db.commits == 0
    assert existing.is_active is True and existing.card_data == _native_cd()


def test_a_tombstone_for_a_card_we_never_held_inserts_nothing():
    res, db = _upsert(None, _tombstone(str(uuid.uuid4())))
    assert res == "skipped" and db.commits == 0


def test_an_erasure_repeats_harmlessly():
    """Every hourly read repeats the tombstone: the second one writes nothing."""
    existing = _existing(_mirror_cd())
    _upsert(existing, _tombstone(str(uuid.uuid4())))
    res, db = _upsert(existing, _tombstone(str(uuid.uuid4())))
    assert res == "skipped" and db.commits == 0


def test_a_tombstone_is_not_counted_as_a_schema_refusal(monkeypatch):
    """A tombstone is an answer, not a malformed card: D6-814's refusal counter (and its day-long alert) never sees it."""
    from agentvault_registry.crud import crud_peer_registry as crud
    refused = _Counter()
    monkeypatch.setattr(crud, "FEDERATION_CARD_INGEST_REFUSED_TOTAL", refused)
    _upsert(_existing(_mirror_cd()), _tombstone(str(uuid.uuid4())), presenter_td="asia.theprotocol.cloud", peer=RELAY)
    _upsert(_existing(_mirror_cd()), _tombstone(str(uuid.uuid4())))
    assert refused.incs == []


def test_an_active_card_that_says_anonymized_still_meets_the_schema(monkeypatch):
    """Control: only an INACTIVE redaction is a tombstone; an active card claiming it is content, refused as before."""
    from agentvault_registry.crud import crud_peer_registry as crud
    refused = _Counter()
    monkeypatch.setattr(crud, "FEDERATION_CARD_INGEST_REFUSED_TOTAL", refused)
    existing = _existing(_mirror_cd())
    res, db = _upsert(existing, _tombstone(str(uuid.uuid4()), is_active=True))
    assert res == "skipped" and db.commits == 0 and existing.card_data == _mirror_cd()
    assert len(refused.incs) == 1


def test_without_fail_closed_a_relay_still_cannot_erase(monkeypatch):
    """With the gate unset (the operators) the tombstone used to overwrite whatever row it named, from any presenter."""
    monkeypatch.setenv("FEDERATION_INGEST_FAIL_CLOSED", "")
    existing = _existing(_mirror_cd())
    res, db = _upsert(existing, _tombstone(str(uuid.uuid4())), presenter_td="asia.theprotocol.cloud", peer=RELAY)
    assert res == "skipped" and db.commits == 0 and existing.is_active is True


def test_the_v0636_path_kept_the_mirror_active(monkeypatch):
    """The defect, shown on the old path (the D6-816 branch bypassed): the fail-closed gate refuses the home's tombstone
    and the mirror stays active and whole."""
    from agentvault_registry.crud import crud_peer_registry as crud
    monkeypatch.setattr(crud, "is_erasure_tombstone", lambda card: False)
    existing = _existing(_mirror_cd())
    res, db = _upsert(existing, _tombstone(str(uuid.uuid4())))
    assert res == "skipped" and existing.is_active is True and existing.card_data == _mirror_cd()
