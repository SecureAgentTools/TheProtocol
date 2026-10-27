"""D6-814 (agentvault2-d6, 2026-10-23): a card the fail-closed ingest refuses says which fields failed, never the card's
content, and the refusal is counted per peer and first failing field.

Measured on production: ASIA (FEDERATION_INGEST_FAIL_CLOSED=true) refused EU's SYBIL card every 30 s from 2026-09-28 to
2026-10-23 (agentvault2-56 found it closing D6-445): its provider.url was "". The log line was str(ValidationError)[:200],
which holds the first error with its input_value (the card itself) and was cut before the field that failed, so the
mirror stood still for 25 days and nothing said why. Red on the code before D6-814: the line carries the card's text and
no provider.url, schema_refusal_fields and the counter do not exist.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import os
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://t:t@localhost:5432/t")
os.environ.setdefault("API_KEY_SECRET", "test-only-secret-value-0123456789abcdef")

HOME = "spiffe://eu.theprotocol.cloud/registry/eu"
DID = "did:theprotocol:eu.theprotocol.cloud:3b0e8a52-0d0e-4c43-9f0e-7d2b9c1a5e11"
CONTENT = "the-cards-own-text-7c1e"   # stands for what a peer's card carries; it must never reach the log


def _card(*, provider_url="", complete=False):
    """SYBIL's shape: a provider whose url is "". Incomplete, it also lacks two required fields that pydantic reports
    FIRST, the way the 200-character cut lost the field that mattered."""
    cd = {"name": "SYBIL", "description": CONTENT, "url": "https://agent.example.test/a2a", "version": "1.0",
          "protocolVersion": "0.3.0", "provider": {"name": "TheProtocol", "url": provider_url},
          "capabilities": {}, "skills": [], "defaultInputModes": ["text"], "defaultOutputModes": ["text"],
          "federation_metadata": {"origin_registry_name": "EU", "first_synced_from": HOME}}
    if complete:
        cd.update({"humanReadableId": "probe/sybil", "agentVersion": "1.0"})
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


def _upsert(cd):
    from agentvault_registry.crud import crud_peer_registry as crud
    stored = SimpleNamespace(card_data=copy.deepcopy(cd), name="SYBIL", description="stored", is_active=True,
                             updated_at=datetime(2026, 9, 28, 10, 0, 0), developer_id=None, agent_did=DID, unlisted=False)
    incoming = {"id": str(uuid.uuid4()), "name": "SYBIL", "description": "probe", "is_active": True,
                "updated_at": "2026-10-23T18:00:00+00:00", "card_data": copy.deepcopy(cd)}
    db = _Session(stored)
    res = asyncio.run(crud.upsert_agent_cards_from_peer(db=db, peer_svid=HOME, agent_card=incoming,
                                                        peer_trust_domain="eu.theprotocol.cloud", from_origin=False))
    return res, db


@pytest.fixture(autouse=True)
def _fail_closed(monkeypatch):
    monkeypatch.setenv("FEDERATION_INGEST_FAIL_CLOSED", "true")
    monkeypatch.setenv("LISTING_PROPAGATION_MODE", "off")


def _counted(field):
    from agentvault_registry.crud import crud_peer_registry as crud
    c = crud.FEDERATION_CARD_INGEST_REFUSED_TOTAL
    assert c is not None, "the refusal counter is missing"
    return c.labels(peer=HOME, field=field)._value.get()


def test_the_cards_really_fail_the_schema():
    """Controls: without these the tests below could pass through the ordinary path and prove nothing."""
    from agentvault import AgentCard
    for cd in (_card(), _card(complete=True)):
        with pytest.raises(Exception):
            AgentCard.model_validate(cd)


class _Grab(logging.Handler):
    """On the module's own logger: the app's logging config does not propagate it to pytest's caplog."""

    def __init__(self):
        super().__init__(logging.WARNING)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def test_the_line_names_every_failing_field_and_never_the_card():
    from agentvault_registry.crud import crud_peer_registry as crud
    grab = _Grab()
    crud.logger.addHandler(grab)
    try:
        res, db = _upsert(_card())
    finally:
        crud.logger.removeHandler(grab)
    assert res == "skipped" and db.commits == 0, "the refused content must not land"
    lines = [ln for ln in grab.lines if "quarantining federated agent card" in ln]
    assert len(lines) == 1, lines
    line = lines[0]
    for want in ("humanReadableId (missing)", "agentVersion (missing)", "provider.url (url_parsing)", "3 error(s)"):
        assert want in line, f"the refusal line does not name {want!r}: {line[:300]}"
    assert CONTENT not in line and "input_value" not in line, "the refusal line carries the peer's card content"


def test_the_refusal_is_counted_per_peer_and_first_failing_field():
    before = _counted("provider.url")
    _upsert(_card(complete=True))
    assert _counted("provider.url") == before + 1


def test_a_copy_neither_newer_nor_from_home_is_counted_and_named_once(monkeypatch):
    """D6-814's second half: ASIA skipped four newer copies of EU's cards ("0 updated, N skipped") and nothing named the
    gate. A copy the timestamp gate turns away is counted as not_newer and named in the log, once per card and worker."""
    monkeypatch.setenv("FEDERATION_INGEST_FAIL_CLOSED", "false")   # this case is about the clock gate, not the schema
    from agentvault_registry.crud import crud_peer_registry as crud
    cd = _card(provider_url="https://theprotocol.cloud", complete=True)
    stored = SimpleNamespace(card_data=copy.deepcopy(cd), name="SYBIL", description="probe", is_active=True,
                             updated_at=datetime(2026, 10, 23, 19, 30, 0, tzinfo=timezone.utc),   # timestamptz: read aware
                             developer_id=None, agent_did=DID, unlisted=False)
    incoming = {"id": str(uuid.uuid4()), "name": "SYBIL", "description": "probe", "is_active": True,
                "updated_at": "2026-10-23T19:10:00+00:00", "card_data": copy.deepcopy(cd)}
    c = crud.FEDERATION_CARD_INGEST_SKIPPED_TOTAL
    assert c is not None, "the skip counter is missing"
    before = c.labels(peer=HOME, reason="not_newer")._value.get()
    grab = _Grab()
    grab.setLevel(logging.INFO)
    crud.logger.addHandler(grab)
    old_level = crud.logger.level
    crud.logger.setLevel(logging.INFO)
    try:
        for _ in range(2):
            res = asyncio.run(crud.upsert_agent_cards_from_peer(db=_Session(stored), peer_svid=HOME, agent_card=incoming,
                                                                peer_trust_domain="eu.theprotocol.cloud", from_origin=False))
            assert res == "skipped"
    finally:
        crud.logger.removeHandler(grab)
        crud.logger.setLevel(old_level)
    assert c.labels(peer=HOME, reason="not_newer")._value.get() == before + 2
    named = [ln for ln in grab.lines if incoming["id"] in ln]
    assert len(named) == 1, named
    assert "not_newer" in named[0] and "2026-10-23T19:10:00" in named[0] and "from the card's home False" in named[0]


def test_the_field_shapes():
    from agentvault import AgentCard
    from agentvault_registry.crud.crud_peer_registry import schema_refusal_fields
    base = _card(provider_url="https://theprotocol.cloud", complete=True)
    with pytest.raises(Exception) as root:            # no auth declared: the card's root validator refuses it
        AgentCard.model_validate(base)
    assert [f[0] for f in schema_refusal_fields(root.value)] == ["(card)"]
    with pytest.raises(Exception) as listed:           # a skill without its name: the index reads *
        AgentCard.model_validate(dict(base, skills=[{"id": "s1"}]))
    assert "skills.*.name" in [f[0] for f in schema_refusal_fields(listed.value)]
    assert schema_refusal_fields(ValueError("boom")) == [("(card)", "ValueError", "")]
