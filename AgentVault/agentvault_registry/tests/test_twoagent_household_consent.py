"""§TWOAGENT G1 (V0437): an owner is announced to the other side of a cross-registry thread only with consent.

V0436 made the owner's household join VISIBLE, but the first OPEN did it: an owner who merely looked at its agent's
thread was announced to a stranger with no prompt. Now, in a federated thread (a mirror, or one hosted here with a remote
participant), a read, a mark-read or a mute answers 409 `household_join_confirm: …` naming what joining does, and the
read with join=true confirms; a deliberate act (a post, a ping, a card, a service call, an accept) is itself consent.
A purely local household join is unchanged.

RED on 65bfeba9: every test but the control.
"""
from __future__ import annotations

import types

import pytest

HOST = "https://sandbox-a.test"
HOME = "https://sandbox-b.test"
AGENT = "did:theprotocol:sandbox-b.test:worker"


class _R:
    def __init__(self, v=None):
        self.v = v

    def scalars(self):
        return self

    def first(self):
        return self.v

    def all(self):
        return self.v if isinstance(self.v, list) else []


def _setup(monkeypatch, parts):
    monkeypatch.setenv("CHAT_FEDERATION_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_BASE_URL", HOME)
    from agentvault_registry.services import chat_federation as fed
    from agentvault_registry.services import chat_service as cs
    seen: dict = {"announce": 0, "posted": 0}

    class _Db:
        def __init__(self):
            self.added = []

        async def execute(self, stmt, params=None):
            return _R(parts)

        def add(self, o):
            self.added.append(o)

        async def flush(self):
            return None

        async def commit(self):
            return None

    async def _none(*a, **k):
        return None

    async def _owners(db, dids):
        return {d: 7 for d in dids}

    async def _names(db, keys):
        return {k: "B Proof Worker" for k in keys}

    async def _announce(*a, **k):
        seen["announce"] += 1
        return True

    async def _post(*a, **k):
        seen["posted"] += 1
    monkeypatch.setattr(cs, "_my_row", _none)
    monkeypatch.setattr(cs, "agent_owner_map", _owners)
    monkeypatch.setattr(cs, "display_names", _names)
    monkeypatch.setattr(fed, "announce_household_join", _announce)
    monkeypatch.setattr(fed, "post_household_join", _post)
    return cs, _Db(), seen


OWNER = dict(developer_id=7, display_name="Owner O")
MIRROR = types.SimpleNamespace(id="mirror-1", kind="dm", host_registry=HOST, remote_ref="host-conv-1", org_id=None)
AGENT_ROW = types.SimpleNamespace(ptype="agent", agent_did=AGENT, developer_id=None, state="active")
REMOTE_ROW = types.SimpleNamespace(ptype="remote", agent_did=None, developer_id=None, state="active")


async def test_a_read_asks_before_it_announces_an_owner_on_a_mirror(monkeypatch):
    cs, db, seen = _setup(monkeypatch, [AGENT_ROW, REMOTE_ROW])
    with pytest.raises(cs.ChatError) as e:
        await cs.resolve_membership(db, MIRROR, cs.Actor("developer", **OWNER))
    assert e.value.status_code == 409 and e.value.detail.startswith("household_join_confirm:")
    assert "the owner of B Proof Worker" in e.value.detail and "join=true" in e.value.detail
    assert seen == {"announce": 0, "posted": 0} and db.added == []


async def test_the_hosts_own_owner_is_asked_too(monkeypatch):
    hosted = types.SimpleNamespace(id="host-conv-1", kind="dm", host_registry=None, org_id=None)
    cs, db, seen = _setup(monkeypatch, [AGENT_ROW, REMOTE_ROW])
    with pytest.raises(cs.ChatError) as e:
        await cs.resolve_membership(db, hosted, cs.Actor("developer", **OWNER))
    assert e.value.status_code == 409 and seen["posted"] == 0 and db.added == []


async def test_reading_passes_the_readers_consent_through(monkeypatch):
    from agentvault_registry.services import chat_service as cs
    got: list = []

    async def _conv(db, cid):
        return MIRROR

    async def _resolve(db, conv, actor, **kw):
        got.append(kw.get("announce_ok"))
        raise cs.ChatError(418, "stop here")
    monkeypatch.setattr(cs, "_get_conversation", _conv)
    monkeypatch.setattr(cs, "resolve_membership", _resolve)
    for join in (False, True):
        with pytest.raises(cs.ChatError):
            await cs.list_messages(None, "mirror-1", cs.Actor("developer", **OWNER), join=join)
    assert got == [False, True]


async def test_posting_is_itself_consent(monkeypatch):
    from agentvault_registry.routers import chat as chat_router
    from agentvault_registry.services import chat_service as cs
    got: list = []

    async def _conv(db, cid):
        return MIRROR

    async def _resolve(db, conv, actor, **kw):
        got.append(kw.get("announce_ok"))
        raise cs.ChatError(418, "stop here")
    monkeypatch.setattr(cs, "_get_conversation", _conv)
    monkeypatch.setattr(cs, "resolve_membership", _resolve)
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        await chat_router.post_message(
            conversation_id="mirror-1",
            req=chat_router.MessagePost(kind="text", body="hello", client_ref="ref-12345678"),
            actor_dict={"kind": "developer", "developer": types.SimpleNamespace(id=7, name="Owner O")},
            db=None)
    assert got == [True]


async def test_control_a_local_household_join_needs_no_consent(monkeypatch):
    local = types.SimpleNamespace(id="c-local", kind="dm", host_registry=None, org_id=None)
    other = types.SimpleNamespace(ptype="agent", agent_did="did:theprotocol:y", developer_id=None, state="active")
    cs, db, seen = _setup(monkeypatch, [AGENT_ROW, other])
    row = await cs.resolve_membership(db, local, cs.Actor("developer", **OWNER))
    assert row.developer_id == 7 and seen == {"announce": 0, "posted": 0}
