"""V0662, item 18 (order gwo_c422fc98269eb0ec7a87c2f0; sessionlogs2026/PLAN_2026-11-13_TESTS_MONITORING_DOCS.md): the
card-ingest alert that fires on correct behaviour.

The fail-closed ingest counted two different events in one counter: a card it REFUSED (schema-invalid content from a
peer, nothing applied) and a card whose content it WITHHELD while the card's own home stated a denial
(§QUARANTINEDENY: suspended, revoked or deactivated at its home; the denial lands on our copy, the content does not).
The second is the gate working, and a withdrawn card stays invalid for good, so every hourly read counted a
"refusal" and FederationCardIngestRefusedForADay (keyed on that counter) fired for ever on correct behaviour.
Now a withheld card counts in federation_card_ingest_withheld_total (peer, first failing field), apart: the refusal
counter, and so the alert, counts refusals only. A denial already applied (the same suspension read again) is still
withheld, never a refusal. A relay cannot deny through the quarantine (§QUARANTINEDENY), so its card is a refusal.
Red on 95f3477c7: there is no withheld counter, and a home's suspended card counts as a refusal.
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
DID = "did:theprotocol:eu.theprotocol.cloud:5d0c2e8e-6f4c-4c37-9a4b-6c2f0e8a1b33"
HOME = "spiffe://eu.theprotocol.cloud/registry/eu-withheld-test"   # a peer of its own: counter values stay per test


def _card(*, suspended=False):
    """No protocolVersion: the canonical AgentCard schema refuses it, the shape of the five September cards."""
    cd = {"name": "Withdrawn Agent", "description": "probe", "url": "https://agent.example.test/a2a", "version": "1.0",
          "capabilities": {}, "skills": [],
          "federation_metadata": {"origin_registry_name": "EU", "source_registry": "spiffe://eu.theprotocol.cloud/service/registry",
                                  "first_synced_from": HOME}}
    if suspended:
        cd["extensions"] = [{"uri": ENF, "required": False, "description": "Enforcement state stamped by the home",
                             "params": {"version": 1, "status": "suspended", "since": "2026-09-17T07:00:17Z", "registry": "EU"}}]
    return cd


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


def _upsert(stored_cd, incoming_cd, *, is_active=True, stored_active=True, from_origin=True):
    from agentvault_registry.crud import crud_peer_registry as crud
    existing = SimpleNamespace(card_data=copy.deepcopy(stored_cd), name="Withdrawn Agent", description="probe",
                               is_active=stored_active, updated_at=datetime(2026, 9, 12, 14, 0, 0), developer_id=None,
                               agent_did=DID, unlisted=False)
    incoming = {"id": str(uuid.uuid4()), "name": "Withdrawn Agent", "description": "probe", "is_active": is_active,
                "updated_at": "2026-09-17T07:00:17+00:00", "card_data": copy.deepcopy(incoming_cd)}
    return asyncio.run(crud.upsert_agent_cards_from_peer(db=_Session(existing), peer_svid=HOME, agent_card=incoming,
                                                          peer_trust_domain="eu.theprotocol.cloud", from_origin=from_origin))


def _counts():
    from agentvault_registry.crud import crud_peer_registry as crud
    refused = crud.FEDERATION_CARD_INGEST_REFUSED_TOTAL
    withheld = getattr(crud, "FEDERATION_CARD_INGEST_WITHHELD_TOTAL", None)
    assert withheld is not None, "no counter for a withheld card"
    return (refused.labels(peer=HOME, field="protocolVersion")._value.get(),
            withheld.labels(peer=HOME, field="protocolVersion")._value.get())


@pytest.fixture(autouse=True)
def _fail_closed(monkeypatch):
    monkeypatch.setenv("FEDERATION_INGEST_FAIL_CLOSED", "true")
    monkeypatch.setenv("LISTING_PROPAGATION_MODE", "off")


def test_the_card_really_fails_the_schema():
    from agentvault import AgentCard
    with pytest.raises(Exception):
        AgentCard.model_validate(_card(suspended=True))


def test_a_homes_suspended_card_is_withheld_not_refused():
    r0, w0 = _counts()
    _upsert(_card(), _card(suspended=True))
    assert _counts() == (r0, w0 + 1)


def test_the_same_suspension_read_again_is_still_withheld():
    # the five September cards: the denial landed long ago, the home keeps exporting them, every read counted
    r0, w0 = _counts()
    _upsert(_card(suspended=True), _card(suspended=True))
    _upsert(_card(suspended=True), _card(suspended=True))
    assert _counts() == (r0, w0 + 2)


def test_a_homes_deactivated_card_is_withheld():
    r0, w0 = _counts()
    _upsert(_card(), _card(), is_active=False)
    assert _counts() == (r0, w0 + 1)


def test_an_invalid_card_with_no_denial_is_a_refusal():
    r0, w0 = _counts()
    _upsert(_card(), _card())
    assert _counts() == (r0 + 1, w0)


def test_a_relay_cannot_turn_a_refusal_into_a_withheld_card():
    r0, w0 = _counts()
    _upsert(_card(), _card(suspended=True), from_origin=False)
    assert _counts() == (r0 + 1, w0)
