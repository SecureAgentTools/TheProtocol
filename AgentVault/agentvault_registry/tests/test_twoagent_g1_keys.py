"""§TWOAGENT G1 step 4b (2026-09-23) — one address is one key, and a remote principal has a name.

Every comparison of a remote key is exact (blocks, participant rows, pair keys, the relay record), and nothing made the
key canonical: `parse_remote_key` kept the host's case and `participant_wire` built agent and dev:N keys by hand. So
`x@https://Peer.example` and `x@https://peer.example` were two principals, and a block typed in one matched nothing
stored in the other (Session A's review of step 3). Separately, `display_names` sent a `rem:` key down the AGENT branch
and named it with nobody, so every cross-registry thread listed a blank counterparty. Measured before the change: every
stored remote key, agent DID, card DID and handle on sbx-alpha, sbx-beta, EU and ASIA is lower-case (0 of each), and
handles are unique regardless of case (the lower(handle) index): the one form names nobody new and needs no migration.

RED on cea1dc56: every test but the controls.
"""
from __future__ import annotations

import types

import pytest

HOST = "https://sandbox-a.test"
HOME = "https://sandbox-b.test"


def test_one_address_is_one_key_whatever_its_case():
    from agentvault_registry.services import chat_federation as fed
    assert fed.remote_key("Alice", "HTTPS://Sandbox-B.Test/") == "alice@https://sandbox-b.test"
    parsed = fed.parse_remote_key("Alice@HTTPS://Sandbox-B.Test")
    assert parsed == ("Alice", "https://sandbox-b.test") and fed.remote_key(*parsed) == "alice@https://sandbox-b.test"


def test_a_block_typed_in_another_case_names_the_stored_participant():
    from agentvault_registry.routers import chat as chat_router
    req = chat_router.BlockBody(ptype="remote", remote_key="Did:TheProtocol:Knocker@HTTPS://Sandbox-A.Test")
    assert chat_router._block_key(req) == "rem:did:theprotocol:knocker@https://sandbox-a.test"


async def test_the_host_names_its_residents_in_the_one_form(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "HTTPS://Sandbox-A.Test/")
    from agentvault_registry.services import chat_federation as fed
    rows = [types.SimpleNamespace(ptype="agent", agent_did="did:theprotocol:p", developer_id=None, state="active"),
            types.SimpleNamespace(ptype="developer", agent_did=None, developer_id=7, state="active"),
            types.SimpleNamespace(ptype="remote", remote_key="did:theprotocol:w@https://sandbox-b.test", state="active")]

    class _R:
        def __init__(self, v):
            self.v = v

        def scalars(self):
            return self

        def all(self):
            return self.v

        def first(self):
            return self.v

    class _Db:
        n = 0

        async def execute(self, stmt, params=None):
            self.n += 1
            return _R(rows if self.n == 1 else None)      # developer 7 has no handle
    out = await fed.participant_wire(_Db(), types.SimpleNamespace(id="c1"))
    assert [p["key"] for p in out] == ["did:theprotocol:p@https://sandbox-a.test", "dev:7@https://sandbox-a.test",
                                       "did:theprotocol:w@https://sandbox-b.test"]


def test_a_delivery_recognises_its_own_residents_whatever_the_case_of_the_address():
    from agentvault_registry.services import chat_federation as fed
    parts = [{"key": "did:theprotocol:w@HTTPS://Sandbox-B.Test"}, {"key": "did:theprotocol:p@https://sandbox-a.test"}]
    assert fed._local_keys_from(parts, "https://sandbox-b.test") == ["did:theprotocol:w"]
    assert fed._local_keys_from(parts, "HTTPS://SANDBOX-B.TEST/") == ["did:theprotocol:w"]


async def test_opening_a_thread_to_this_registry_in_another_case_is_refused_by_name(monkeypatch):
    monkeypatch.setenv("CHAT_FEDERATION_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_BASE_URL", HOST)
    from agentvault_registry.routers import chat as chat_router
    from agentvault_registry.services import chat_federation as fed
    from agentvault_registry.services import chat_service as cs

    async def _not_reached(db, base):
        raise cs.ChatError(418, "treated our own address as a peer")
    monkeypatch.setattr(fed, "assert_peer_allowed", _not_reached)
    req = chat_router.ConversationCreate(kind="dm", target=chat_router.TargetSpec(
        ptype="developer", remote_key="someone@HTTPS://SANDBOX-A.TEST"))
    with pytest.raises(cs.ChatError) as e:
        await chat_router._create_federated(None, cs.Actor("agent", agent_did="did:theprotocol:k", display_name="K"), req)
    assert e.value.status_code == 422 and "THIS registry" in e.value.detail


class _NameDb:
    def __init__(self, cards):
        self.cards, self.sql = cards, []

    async def execute(self, stmt, params=None):
        self.sql.append((" ".join(str(stmt).split()), params))

        class _All:
            def __init__(self, v):
                self.v = v

            def all(self):
                return self.v
        return _All([c for c in self.cards if c[0].lower() in [d.lower() for d in (params or {}).get("d", [])]])


async def test_a_remote_counterparty_is_named_by_its_mirrored_card_or_by_its_address():
    from agentvault_registry.services import chat_service as cs
    db = _NameDb([("did:theprotocol:w", "B Proof Worker")])
    names = await cs.display_names(db, ["rem:did:theprotocol:w@https://sandbox-b.test", "rem:alice@https://sandbox-b.test"])
    assert names["rem:did:theprotocol:w@https://sandbox-b.test"] == "B Proof Worker"
    assert names["rem:alice@https://sandbox-b.test"] == "alice@https://sandbox-b.test"


async def test_control_a_local_agent_is_still_named_by_its_card():
    from agentvault_registry.services import chat_service as cs
    db = _NameDb([("did:theprotocol:local", "Local Agent")])
    names = await cs.display_names(db, ["agt:did:theprotocol:local"])
    assert names["agt:did:theprotocol:local"] == "Local Agent"
