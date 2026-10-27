"""§QUARANTINEDENY (2026-09-29) — a quarantined update still lands its HOME's deny-only facts on the mirror we hold.

Measured on production: EU suspended 'Test Agent v3' on 2026-09-17. Its card (created 09-12, no `protocolVersion`)
fails today's AgentCard schema, so ASIA (FEDERATION_INGEST_FAIL_CLOSED=true) quarantined every update, 8 EU cards per
repair walk, and kept serving its 09-12 copy ACTIVE and unenforced for twelve days, while the four operators (the gate
unset) took the suspension at once. The quarantine refuses untrusted CONTENT; it must not keep a withdrawn agent usable.

The rule under test: from the card's own home, onto a mirror we already hold, a suspension/revocation and a
deactivation land; a lift, a reactivation, a relay's word and any content do not. Red on the code before
§QUARANTINEDENY except the named controls.
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

ENF = "https://theprotocol.cloud/extensions/v1/enforcement"
DID = "did:theprotocol:eu.theprotocol.cloud:8fc4b88b-1f15-4c5a-b293-00d9e6a05ca3"
HOME = "spiffe://eu.theprotocol.cloud/registry/eu"
WRITTEN = datetime(2026, 9, 12, 14, 32, 17)        # ASIA's copy, naive UTC as the column holds it


def _card(*, suspended=False, description="probe", mirror=True, ext_params=None):
    """The shape of the real card: no protocolVersion, so the canonical AgentCard schema refuses it."""
    cd = {"name": "Test Agent v3", "description": description, "url": "https://agent.example.test/a2a",
          "version": "1.0", "capabilities": {}, "skills": []}
    if mirror:
        cd["federation_metadata"] = {"origin_registry_name": "EU",
                                     "source_registry": "spiffe://eu.theprotocol.cloud/service/registry",
                                     "first_synced_from": HOME}
    if suspended:
        cd["extensions"] = [{"uri": ENF, "required": False, "description": "Enforcement state stamped by the home",
                             "params": ext_params or {"version": 1, "status": "suspended",
                                                      "since": "2026-09-17T07:00:17Z", "registry": "EU"}}]
    return cd


def _ext(cd):
    for e in (cd or {}).get("extensions") or []:
        if isinstance(e, dict) and e.get("uri") == ENF:
            return e
    return None


class _Result:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row

    def fetchall(self):
        return []


class _Session:
    def __init__(self, existing):
        self.existing, self.commits = existing, 0

    async def execute(self, stmt, params=None):
        return _Result(self.existing)

    async def commit(self):
        self.commits += 1

    async def get(self, model, key):
        return None


def _existing(cd, *, is_active=True):
    return SimpleNamespace(card_data=copy.deepcopy(cd), name="Test Agent v3", description=cd.get("description"),
                           is_active=is_active, updated_at=WRITTEN, developer_id=None, agent_did=DID, unlisted=False)


def _incoming(cd, *, is_active=True):
    return {"id": str(uuid.uuid4()), "name": "Test Agent v3", "description": cd.get("description"),
            "is_active": is_active, "updated_at": "2026-09-17T07:00:17.044322+00:00", "card_data": copy.deepcopy(cd)}


@pytest.fixture(autouse=True)
def _fail_closed(monkeypatch):
    monkeypatch.setenv("FEDERATION_INGEST_FAIL_CLOSED", "true")
    monkeypatch.setenv("LISTING_PROPAGATION_MODE", "off")


def _upsert(existing, incoming, *, from_origin=True):
    from agentvault_registry.crud import crud_peer_registry as crud
    db = _Session(existing)
    res = asyncio.run(crud.upsert_agent_cards_from_peer(
        db=db, peer_svid=HOME, agent_card=incoming, peer_trust_domain="eu.theprotocol.cloud", from_origin=from_origin))
    return res, db


def test_the_card_really_fails_the_schema():
    """Control: without this the tests below could pass through the ordinary path and prove nothing."""
    from agentvault import AgentCard
    with pytest.raises(Exception):
        AgentCard.model_validate(_card(suspended=True))


def test_the_homes_suspension_lands_despite_the_quarantine():
    existing = _existing(_card())
    res, db = _upsert(existing, _incoming(_card(suspended=True, description="new text from the home")))
    assert (_ext(existing.card_data) or {}).get("params", {}).get("status") == "suspended", \
        "the home suspended the agent and our mirror still serves it unenforced"
    assert existing.card_data["description"] == "probe", "the quarantined CONTENT came in with the denial"
    assert res == "updated" and db.commits == 1


def test_the_homes_deactivation_lands_despite_the_quarantine():
    existing = _existing(_card())
    res, _ = _upsert(existing, _incoming(_card(), is_active=False))
    assert existing.is_active is False and res == "updated"


def test_the_stored_block_is_ours_not_the_peers():
    junk = {"version": 1, "status": "suspended", "since": "2026-09-17", "registry": "EU" * 200, "evil": "<script>"}
    existing = _existing(_card())
    _upsert(existing, _incoming(_card(suspended=True, ext_params=junk)))
    params = (_ext(existing.card_data) or {}).get("params") or {}
    assert set(params) == {"version", "status", "since", "registry"} and len(params["registry"]) <= 120


def test_a_lift_still_needs_a_valid_card():
    """Control: deny-only. A reinstatement that fails the schema leaves the suspension in place."""
    existing = _existing(_card(suspended=True))
    res, db = _upsert(existing, _incoming(_card(suspended=False)))
    assert (_ext(existing.card_data) or {}).get("params", {}).get("status") == "suspended"
    assert res == "skipped" and db.commits == 0


def test_a_reactivation_still_needs_a_valid_card():
    """Control: deny-only in the other field too."""
    existing = _existing(_card(), is_active=False)
    res, _ = _upsert(existing, _incoming(_card(), is_active=True))
    assert existing.is_active is False and res == "skipped"


def test_a_relay_cannot_deny_through_the_quarantine():
    """Control: only the card's home speaks for it."""
    existing = _existing(_card())
    res, db = _upsert(existing, _incoming(_card(suspended=True)), from_origin=False)
    assert _ext(existing.card_data) is None and res == "skipped" and db.commits == 0


def test_a_native_card_is_never_touched():
    """Control: OWL24."""
    existing = _existing(_card(mirror=False))
    res, db = _upsert(existing, _incoming(_card(suspended=True)))
    assert _ext(existing.card_data) is None and res == "skipped" and db.commits == 0
