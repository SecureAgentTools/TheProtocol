"""§TWOAGENT G1 step 4 (2026-09-23) — one thread per pair across registries, and a way back into it.

A mirror carries no pair key (its uniqueness is (host, remote_ref)), so the federated create's pair-key lookup never
saw a thread the OTHER registry hosts. Opening a dm to someone who had already written from their registry started a
SECOND thread, hosted on this side (and, to an agent, a second knock), while the first request sat unanswered. And the
host refused a left -> active announce, so a resident who left could never rejoin the old thread. Now:
  * the federated create finds that mirror first and answers it, as a local create answers the pair's thread;
  * a pending row is the accept and a left row a rejoin, announced to the host BEFORE any message (the host refuses a
    message from a participant it holds as left), and if the host cannot hear it nothing changes here;
  * the host accepts a rejoin from the participant's own home, and a rejoin is no accept (no notice).

RED on 4669888f: every test but the controls.
"""
from __future__ import annotations

import types

import pytest

HOST = "https://sandbox-a.test"
HOME = "https://sandbox-b.test"
A_DID = "did:theprotocol:sandbox-a.test:knocker"
B_DID = "did:theprotocol:sandbox-b.test:assay"


class _R:
    def __init__(self, v=None):
        self.v = v

    def scalars(self):
        return self

    def first(self):
        return self.v


class _Db:
    """The pair-key lookup finds nothing; anything the old create path would write is recorded."""

    def __init__(self):
        self.added: list = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        return _R(None)

    def add(self, o):
        self.added.append(o)

    def add_all(self, os_):
        self.added.extend(os_)

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1


def _setup(monkeypatch, my_state, announce_ok=True):
    monkeypatch.setenv("CHAT_FEDERATION_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_BASE_URL", HOME)
    from agentvault_registry.routers import chat as chat_router
    from agentvault_registry.services import chat_federation as fed
    from agentvault_registry.services import chat_service as cs
    mirror = types.SimpleNamespace(id="mirror-1", kind="dm", host_registry=HOST, remote_ref="host-conv-1")
    my_row = types.SimpleNamespace(ptype="agent", agent_did=B_DID, state=my_state)
    calls: dict = {"announce": [], "sent": []}

    async def _allowed(db, base):
        return "sandbox-a"

    async def _blocks(db, a, b):
        return {"a_blocks_b": False, "b_blocks_a": False}

    async def _mirror(db, actor, key):
        return (mirror, my_row) if key == f"{A_DID}@{HOST}" else None

    async def _announce(host, ref, pkey, state):
        calls["announce"].append((host, ref, pkey, state, my_row.state))
        return announce_ok

    async def _handle(db, row):
        return row.agent_did

    async def _yes(*a, **k):
        return True

    async def _send(db, conv, row, actor, kind, body, card, client_ref):
        calls["sent"].append((conv.id, row.state, client_ref))
        return {"relayed": True, "conversation_id": conv.id}
    monkeypatch.setattr(fed, "assert_peer_allowed", _allowed)
    monkeypatch.setattr(fed, "mirror_thread_with", _mirror, raising=False)
    monkeypatch.setattr(fed, "announce_state_to_host", _announce)
    monkeypatch.setattr(fed, "fed_rate_ok", _yes)
    monkeypatch.setattr(cs, "blocks_between", _blocks)
    monkeypatch.setattr(cs, "_participant_handle", _handle)
    monkeypatch.setattr(chat_router, "_send_and_fan_out", _send)
    req = chat_router.ConversationCreate(
        kind="dm", target=chat_router.TargetSpec(ptype="agent", agent_did=A_DID, remote_key=f"{A_DID}@{HOST}"),
        first_message=chat_router.FirstMessage(kind="text", body="back", client_ref="ref-12345678"))
    actor = cs.Actor("agent", agent_did=B_DID, display_name="B")
    return chat_router, cs, req, actor, my_row, calls


async def test_opening_a_dm_to_someone_who_already_wrote_from_their_registry_answers_that_thread(monkeypatch):
    chat_router, cs, req, actor, my_row, calls = _setup(monkeypatch, "pending")
    db = _Db()
    out = await chat_router._create_federated(db, actor, req)
    assert out["conversation_id"] == "mirror-1" and out["created"] is False and out["host"] == HOST
    assert db.added == [], "no second thread, no second knock"
    # the accept reached the host BEFORE the message, and the message went into the same thread
    assert calls["announce"] == [(HOST, "host-conv-1", f"{B_DID}@{HOME}", "active", "active")]
    assert calls["sent"] == [("mirror-1", "active", "ref-12345678")] and my_row.state == "active"


async def test_a_resident_who_left_rejoins_the_same_thread_and_the_host_hears_it_first(monkeypatch):
    chat_router, cs, req, actor, my_row, calls = _setup(monkeypatch, "left")
    out = await chat_router._create_federated(_Db(), actor, req)
    assert out["conversation_id"] == "mirror-1" and out["my_state"] == "active"
    assert [c[3] for c in calls["announce"]] == ["active"] and len(calls["sent"]) == 1


async def test_when_the_host_cannot_hear_the_rejoin_nothing_changes_here(monkeypatch):
    chat_router, cs, req, actor, my_row, calls = _setup(monkeypatch, "left", announce_ok=False)
    with pytest.raises(cs.ChatError) as e:
        await chat_router._create_federated(_Db(), actor, req)
    assert e.value.status_code == 502 and my_row.state == "left" and calls["sent"] == []


async def test_an_active_mirror_is_answered_without_an_announce(monkeypatch):
    chat_router, cs, req, actor, my_row, calls = _setup(monkeypatch, "active")
    out = await chat_router._create_federated(_Db(), actor, req)
    assert out["conversation_id"] == "mirror-1" and calls["announce"] == [] and len(calls["sent"]) == 1


class _HostDb:
    def __init__(self, conv, part):
        self.conv, self.part, self.n, self.commits = conv, part, 0, 0

    async def execute(self, stmt, params=None):
        self.n += 1
        return _R(self.conv if self.n == 1 else self.part)

    async def commit(self):
        self.commits += 1


def _host(monkeypatch, before, caller_ok=True):
    from agentvault_registry.services import chat_federation as fed
    from agentvault_registry.services import chat_service as cs
    conv = types.SimpleNamespace(id="host-conv-1", kind="dm", host_registry=None)
    part = types.SimpleNamespace(ptype="remote", remote_key=f"{B_DID}@{HOME}", state=before)
    notices: list = []

    async def _caller(db, peer, reg):
        return caller_ok
    monkeypatch.setattr(fed, "caller_is", _caller)
    monkeypatch.setattr(cs, "accepted_knock_notice", lambda c, b, a, p: notices.append((b, a)) or None)
    return fed, cs, _HostDb(conv, part), part, notices


async def test_the_host_lets_a_participant_who_left_rejoin_from_its_own_home(monkeypatch):
    fed, cs, db, part, notices = _host(monkeypatch, "left")
    out = await fed.apply_remote_state(db, "host-conv-1", f"{B_DID}@{HOME}", "active",
                                       "spiffe://sandbox-b.test/service/registry")
    assert out == {"state": "active", "changed": True} and part.state == "active"


async def test_control_a_rejoin_from_a_registry_that_is_not_the_participants_home_is_refused(monkeypatch):
    fed, cs, db, part, notices = _host(monkeypatch, "left", caller_ok=False)
    with pytest.raises(cs.ChatError) as e:
        await fed.apply_remote_state(db, "host-conv-1", f"{B_DID}@{HOME}", "active",
                                     "spiffe://stranger.test/service/registry")
    assert e.value.status_code == 403 and part.state == "left"


async def test_the_mirror_lookup_asks_only_for_a_thread_the_other_registry_hosts(monkeypatch):
    from agentvault_registry.services import chat_federation as fed
    from agentvault_registry.services import chat_service as cs
    seen: dict = {}

    class _Q:
        async def execute(self, stmt, params=None):
            seen["sql"], seen["params"] = " ".join(str(stmt).split()), params
            return _R(None)
    got = await fed.mirror_thread_with(_Q(), cs.Actor("agent", agent_did=B_DID, display_name="B"), f"{A_DID}@{HOST}")
    assert got is None
    assert "c.host_registry IS NOT NULL" in seen["sql"] and "c.kind = 'dm'" in seen["sql"]
    assert seen["params"] == {"k": f"{A_DID}@{HOST}", "mt": "agent", "mi": B_DID}
