"""The attestation replay guard, and the profile that shows what an agent proved.

agentvault2-61's live finding on V0611 (sbx-beta): a proof submitted again
answered 200 "verified" with an id nothing stored. The route read
`earlier.id` after `db.rollback()`; the rollback expires every row the
session loaded, so the read loaded it outside the async driver
(MissingGreenlet), the handler around persistence swallowed that, and the
route answered as if the proof were new. The session below expires its row
on rollback the same way, so these tests fail on that code.

The same run found the MCP getAgentProfile without `recent_attestations`:
the profile moved to /agents/by-did (§pass70), which never carried them.
"""
from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.exc import MissingGreenlet

from agentvault_registry.core import zkp_verifier as Z
from agentvault_registry.routers import attestations as route

AGENT = "did:theprotocol:replay-guard-test"
CIRCUIT = "fairMarkupPolicy/v2.0.0"
LABEL = "quote-1"
EARLIER_ID = "7fcd1ec0-0000-4000-8000-000000000001"


class _Bind:
    dialect = SimpleNamespace(name="sqlite")  # advisory_lock is a no-op off PostgreSQL


class _Session:
    """An AsyncSession where it matters here: a rollback expires what it loaded."""

    def __init__(self) -> None:
        self.rolled_back = False

    def get_bind(self):
        return _Bind()

    async def rollback(self) -> None:
        self.rolled_back = True


class _Row:
    """A loaded attestation: its id is gone once the session rolls back."""

    def __init__(self, session: _Session) -> None:
        self._session = session

    @property
    def id(self) -> str:
        if self._session.rolled_back:
            raise MissingGreenlet("greenlet_spawn has not been called; can't call await_() here.")
        return EARLIER_ID


def _submission():
    return route.AttestationSubmission(
        circuit_id=CIRCUIT,
        proof_data={"proof_bytes": base64.b64encode(b"proof bytes").decode()},
        public_inputs={"reference_label": LABEL},
    )


@pytest.fixture
def wired(monkeypatch):
    """A verified v2 proof, Phase 1 on, and spies on everything a grant would touch."""
    calls = {"reputation": 0, "events": 0, "rows": 0}

    async def verified(**_):
        return SimpleNamespace(verified=True, reason="ok", circuit_id=CIRCUIT,
                               public_values={"context": Z.derive_reference(AGENT, LABEL)})

    async def reputation(*_a, **_k):
        calls["reputation"] += 1
        return 1.0

    async def event(*_a, **_k):
        calls["events"] += 1

    async def none(*_a, **_k):
        return None

    async def zero(*_a, **_k):
        return 0

    async def create(*_a, **_k):
        calls["rows"] += 1
        return SimpleNamespace(id="row-created")

    monkeypatch.setattr(route, "ZKP_PHASE_1_ENABLED", True)
    monkeypatch.setattr(route, "ZKP_PHASE_3_ENABLED", False)
    monkeypatch.setattr(route, "ZKP_PHASE_5_ENABLED", False)
    monkeypatch.setattr(route, "verify_proof_detailed", verified)
    monkeypatch.setattr(route, "record_attestation_success", reputation)
    monkeypatch.setattr(route, "_emit_attestation_submitted_event", event)
    monkeypatch.setattr(route.crud_attestation, "find_verified_by_proof_hash", none)
    monkeypatch.setattr(route.crud_attestation, "find_verified_by_reference", none)
    monkeypatch.setattr(route.crud_attestation, "count_verified_on_day", zero)
    monkeypatch.setattr(route.crud_attestation, "create_attestation", create)
    return monkeypatch, calls


def _submit(session: _Session):
    async def go():
        return await route.submit_attestation(_submission(), current_agent=SimpleNamespace(did=AGENT), db=session)
    return asyncio.run(go())


def test_the_session_double_fails_like_the_live_one():
    session = _Session()
    row = _Row(session)
    assert row.id == EARLIER_ID
    asyncio.run(session.rollback())
    with pytest.raises(MissingGreenlet):
        row.id


@pytest.mark.parametrize("lookup", ["find_verified_by_proof_hash", "find_verified_by_reference"])
def test_a_proof_attested_before_answers_409_naming_the_first(wired, lookup):
    monkeypatch, calls = wired
    session = _Session()

    async def earlier(*_a, **_k):
        return _Row(session)

    monkeypatch.setattr(route.crud_attestation, lookup, earlier)
    with pytest.raises(HTTPException) as caught:
        _submit(session)
    assert caught.value.status_code == 409
    assert EARLIER_ID in caught.value.detail
    assert session.rolled_back, "the rollback releases the advisory locks"
    assert calls == {"reputation": 0, "events": 0, "rows": 0}


def test_a_verified_proof_that_cannot_be_recorded_is_not_answered_verified(wired):
    monkeypatch, calls = wired
    session = _Session()

    async def broken(*_a, **_k):
        raise RuntimeError("the database went away")

    monkeypatch.setattr(route.crud_attestation, "create_attestation", broken)
    with pytest.raises(HTTPException) as caught:
        _submit(session)
    assert caught.value.status_code == 503
    assert "nothing was granted" in caught.value.detail
    assert calls == {"reputation": 0, "events": 0, "rows": 0}


def test_control_a_new_proof_is_recorded_and_answered_verified(wired):
    _, calls = wired
    out = _submit(_Session())
    assert out.status == "verified" and out.attestation_id == "row-created"
    assert calls["rows"] == 1 and calls["reputation"] == 1


def _profile(monkeypatch, listing: httpx.Response):
    from agentvault_registry.mcp import tools_discovery as td

    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append((request.url.path, dict(request.url.params)))
        if request.url.path.endswith("/attestations"):
            return listing
        return httpx.Response(200, json={"did": AGENT, "name": "Replay guard"})

    real = httpx.AsyncClient
    monkeypatch.setattr(td.httpx, "AsyncClient", lambda *a, **k: real(*a, transport=httpx.MockTransport(handler), **k))
    return asyncio.run(td.get_agent_profile(AGENT)), asked


def test_the_profile_carries_the_latest_verified_attestations(monkeypatch):
    item = {"id": "a1", "agent_did": AGENT, "circuit_id": CIRCUIT, "verified": True, "proof_hash": "f0",
            "public_inputs": {}, "submitted_at": "2026-10-13T16:00:00Z", "verified_at": "2026-10-13T16:00:01Z"}
    out, asked = _profile(monkeypatch, httpx.Response(200, json={"items": [item], "count": 1, "limit": 5, "offset": 0}))
    assert out["name"] == "Replay guard"
    assert out["recent_attestations"] == [
        {"id": "a1", "circuit_id": CIRCUIT, "verified_at": "2026-10-13T16:00:01Z", "expires_at": None},
    ]
    assert asked[1][1] == {"verified": "true", "limit": "50"}


def _listed(ident: str, **extra):
    return {"id": ident, "agent_did": AGENT, "circuit_id": CIRCUIT, "verified": True, "proof_hash": ident,
            "public_inputs": {}, "submitted_at": "2026-10-13T16:00:00Z", "verified_at": "2026-10-13T16:00:01Z", **extra}


def test_a_revoked_or_expired_attestation_is_left_out_of_the_profile(monkeypatch):
    items = [
        _listed("revoked", revoked_at="2026-10-13T17:00:00Z", expires_at="2099-01-01T00:00:00Z"),
        _listed("expired", expires_at="2026-01-01T00:00:00Z"),
        _listed("held", expires_at="2099-01-01T00:00:00Z"),
    ]
    out, _ = _profile(monkeypatch, httpx.Response(200, json={"items": items, "count": 3, "limit": 50, "offset": 0}))
    assert [a["id"] for a in out["recent_attestations"]] == ["held"]


def test_the_profile_keeps_the_five_newest_that_hold(monkeypatch):
    items = [_listed(f"a{i}", expires_at="2099-01-01T00:00:00Z") for i in range(7)]
    out, _ = _profile(monkeypatch, httpx.Response(200, json={"items": items, "count": 7, "limit": 50, "offset": 0}))
    assert [a["id"] for a in out["recent_attestations"]] == ["a0", "a1", "a2", "a3", "a4"]


def test_control_an_unreadable_listing_is_null_not_empty(monkeypatch):
    out, _ = _profile(monkeypatch, httpx.Response(500, json={"detail": "boom"}))
    assert out["recent_attestations"] is None
