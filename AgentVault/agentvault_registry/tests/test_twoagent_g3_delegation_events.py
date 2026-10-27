"""§TWOAGENT G3 (2026-09-23) — the delegate's owner hears about delegated authority; only the issuer's home can revoke it.

Measured on the EU/ASIA pair (V0430, stage S5): EU's agent delegated to ASIA's agent across registries, then revoked,
and the delegate's owner (me) heard NOTHING either time; the only trace was the delegate home's audit table. The same
is true of a local L3 grant, which a developer can hand to ANY agent. Now `delegation.received` / `delegation.revoked`
go to the delegate's owner, owner-scoped, after the commit, with `scope` local or cross_registry.

Found on the way: `POST /federation/ironkey/delegation-revoke` flipped a credential for ANY federation caller that named
the issuer's registry in the body, and `GET /federation/ironkey/delegations-for-issuer` listed every credential held for
any issuer to any caller: the ids the revoke takes. Now both are bound to the caller's SVID: only the credential's own
issuer home can revoke it or list it; anyone else gets the answer an unknown credential gets.

RED on V0430: no notices, the revoke obeys a stranger, the list answers anyone. The controls (a redelivery tells nobody;
a repeat local revoke tells nobody) pass on both trees.
"""
from __future__ import annotations

import asyncio
import collections
import types

import pytest

ISS = "did:theprotocol:eu.test:issuer"
DEL = "did:theprotocol:asia.test:delegate"
CID = "cred-0001"
EU_SVID = "spiffe://eu.theprotocol.cloud/service/registry"
OTHER_SVID = "spiffe://lantern.theprotocol.cloud/service/registry"


class _Result:
    def __init__(self, rows, rowcount=None):
        self._rows = list(rows)
        self.rowcount = len(self._rows) if rowcount is None else rowcount

    def all(self):
        return list(self._rows)

    def fetchall(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _Db:
    def __init__(self, handlers):
        self.handlers = handlers
        self.sql = []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.sql.append(sql)
        for needle, res in self.handlers:
            if needle in sql:
                return res() if callable(res) else res
        return _Result([], rowcount=0)

    async def commit(self):
        return None

    def wrote(self, needle):
        return any(needle in q for q in self.sql)


@pytest.fixture
def wired(monkeypatch):
    """Owner-scoped dispatch recorded; audit, ledger and peer-name resolution stubbed."""
    got: list = []

    async def _owner(event, data, dids, source_label="endpoint"):
        got.append((event, tuple(dids), data.get("scope")))
        return 1

    async def _broadcast(*a, **k):
        got.append(("BROADCAST",))
        return 1

    async def _audit(*a, **k):
        return None

    class _Emitter:
        async def emit(self, **k):
            return True

        def emit_background(self, **k):
            return None

    async def _resolve(db, value):
        v = str(value or "")
        return "eu" if "eu." in v else ("lantern" if "lantern" in v else None)
    from agentvault_registry.background_tasks import reactor_helpers as rh
    from agentvault_registry.routers import agent_delegation_api as api
    from agentvault_registry import event_emitter
    from agentvault_registry.services import contract_xframe
    monkeypatch.setattr(rh, "dispatch_webhook_for_agents", _owner)
    monkeypatch.setattr(rh, "dispatch_webhook_event", _broadcast)
    monkeypatch.setattr(api, "log_ironkey_action", _audit)
    monkeypatch.setattr(event_emitter, "get_event_emitter", lambda: _Emitter())
    monkeypatch.setattr(contract_xframe, "resolve_peer_name", _resolve)
    monkeypatch.setenv("AGENT_XREG_DELEGATION_ENABLED", "true")
    return got


async def _drain():
    for _ in range(5):
        await asyncio.sleep(0)


def test_the_vocabulary_names_the_events():
    from agentvault_registry.services.webhook_service import WebhookService
    assert {"delegation.received", "delegation.revoked"} <= set(WebhookService.SUPPORTED_EVENTS)


# ─────────────────────────────── cross-registry ───────────────────────────────

def _receive_db(first_delivery=True):
    Grant = collections.namedtuple("Grant", ["id"])
    return _Db([
        ("SELECT 1 FROM agents WHERE did", _Result([(1,)])),
        ("INSERT INTO agent_delegation_credentials", _Result([], rowcount=1 if first_delivery else 0)),
        ("INSERT INTO agent_delegation_grants", _Result([Grant(5)])),
    ])


def _signed_body():
    from agentvault_registry.routers import agent_delegation_api as api
    claim = {"kind": "ironkey.delegation.v1", "credential_id": CID, "issuer_registry": "https://eu.theprotocol.cloud",
             "issuer_did": ISS, "delegate_did": DEL, "permissions": ["teg.transfer"], "caveats": {},
             "expires_at": "2099-01-01T00:00:00+00:00", "signature_pubkey_id": "pk1"}
    return api._FedDelegationIn(credential_id=CID, issuer_registry="https://eu.theprotocol.cloud", issuer_did=ISS,
                                delegate_did=DEL, permissions=["teg.transfer"], credential=claim)


def _trust_the_signature(monkeypatch):
    from agentvault_registry.routers import guild
    from agentvault_registry.services import attestation_signer

    async def _pk(db, host, expect_pubkey_id=None):
        return {"pubkey_id": "pk1", "pubkey_b64": "x"}
    monkeypatch.setattr(guild, "_fetch_peer_pubkey", _pk)
    monkeypatch.setattr(attestation_signer, "verify_bundle_signature", lambda b, issuer_pubkey_b64=None: (True, ""))


async def test_a_received_credential_is_told_to_the_delegates_owner(wired, monkeypatch):
    _trust_the_signature(monkeypatch)
    from agentvault_registry.routers import agent_delegation_api as api
    out = await api.receive_delegation_credential(body=_signed_body(), db=_receive_db(), peer_spiffe_id=EU_SVID)
    await _drain()
    assert out["granted"] is True
    assert wired == [("delegation.received", (DEL,), "cross_registry")], wired


async def test_control_a_redelivery_tells_nobody(wired, monkeypatch):
    _trust_the_signature(monkeypatch)
    from agentvault_registry.routers import agent_delegation_api as api
    out = await api.receive_delegation_credential(body=_signed_body(), db=_receive_db(False), peer_spiffe_id=EU_SVID)
    await _drain()
    assert out["granted"] is False and wired == []


def _revoke_db():
    Row = collections.namedtuple("Row", ["issuer_did", "delegate_did"])
    return _Db([("SELECT issuer_did, delegate_did FROM agent_delegation_credentials", _Result([Row(ISS, DEL)]))])


async def test_only_the_issuers_own_home_can_revoke(wired):
    from agentvault_registry.routers import agent_delegation_api as api
    db = _revoke_db()
    out = await api.revoke_delegation_credential(
        body=api._FedRevokeIn(credential_id=CID, issuer_registry="https://eu.theprotocol.cloud"), db=db,
        peer_spiffe_id=OTHER_SVID)
    await _drain()
    assert out == {"ok": True, "revoked": False, "reason": "unknown_or_already_revoked"}
    assert not db.wrote("UPDATE agent_delegation_credentials SET revoked_at") and wired == []


async def test_the_issuers_revoke_flips_and_tells_the_delegates_owner(wired):
    from agentvault_registry.routers import agent_delegation_api as api
    db = _revoke_db()
    out = await api.revoke_delegation_credential(
        body=api._FedRevokeIn(credential_id=CID, issuer_registry="https://eu.theprotocol.cloud"), db=db,
        peer_spiffe_id=EU_SVID)
    await _drain()
    assert out == {"ok": True, "revoked": True}
    assert db.wrote("UPDATE agent_delegation_credentials SET revoked_at")
    assert wired == [("delegation.revoked", (DEL,), "cross_registry")], wired


async def test_the_lineage_read_shows_a_caller_only_its_own_credentials(wired):
    from agentvault_registry.routers import agent_delegation_api as api
    Row = collections.namedtuple("Row", ["credential_id", "host_registry", "delegate_did", "permissions", "verified",
                                         "cred_revoked", "grant_exp", "grant_revoked"])
    rows = [Row(CID, "https://eu.theprotocol.cloud", DEL, ["teg.transfer"], True, None, None, None),
            Row("cred-lantern", "https://lantern.theprotocol.cloud", DEL, ["gov.vote"], True, None, None, None)]
    db = _Db([("FROM agent_delegation_credentials c", _Result(rows))])
    mine = await api.delegations_for_issuer(issuer_did=ISS, db=db, peer_spiffe_id=EU_SVID)
    assert [d["credential_id"] for d in mine["delegations"]] == [CID]
    nobody = await api.delegations_for_issuer(issuer_did=ISS, db=db, peer_spiffe_id="spiffe://x.test/service/registry")
    assert nobody["delegations"] == []


# ─────────────────────────────── local L3 ───────────────────────────────

async def test_a_local_grant_is_told_to_the_delegates_owner(wired):
    from agentvault_registry.routers import agent_delegation_api as api
    # D6-270: the delegate read now carries its creator (a dev: grant reaches only that developer's own agent).
    Agent = collections.namedtuple("Agent", ["did", "organization_id", "creator_developer_id"])
    db = _Db([("SELECT did, organization_id, creator_developer_id FROM agents", _Result([Agent(DEL, None, 41)]))])
    await api.create_delegation(did=DEL, body=api.DelegationIn(principal_type="dev", principal_ref="dev:41",
                                                             permissions=["teg.transfer"]),
                                current=types.SimpleNamespace(id=41, is_admin=False), db=db)
    await _drain()
    assert wired == [("delegation.received", (DEL,), "local")], wired


def _local_revoke_db(revoked_at):
    Row = collections.namedtuple("Row", ["granted_by_dev_id", "delegate_agent_did", "principal_ref", "revoked_at"])
    return _Db([("FROM agent_delegation_grants WHERE id", _Result([Row(41, DEL, "dev:41", revoked_at)]))])


async def test_a_local_revoke_is_told_once(wired):
    from agentvault_registry.routers import agent_delegation_api as api
    me = types.SimpleNamespace(id=41, is_admin=False)
    await api.revoke_delegation(grant_id=5, current=me, db=_local_revoke_db(None))
    await _drain()
    assert wired == [("delegation.revoked", (DEL,), "local")], wired


async def test_control_a_repeat_local_revoke_tells_nobody(wired):
    from agentvault_registry.routers import agent_delegation_api as api
    me = types.SimpleNamespace(id=41, is_admin=False)
    await api.revoke_delegation(grant_id=5, current=me, db=_local_revoke_db("2026-09-23T10:00:00+00:00"))
    await _drain()
    assert wired == []
