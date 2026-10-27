"""§TWOAGENT G1 (V0437): a REPLY from a pending row is the accept, and the knocker now hears it.

Only the /accept rail notified. A reply flipped the pending row silently, locally (insert_message) and at a
cross-registry HOST (insert_remote_message), where the resident's home announced the accept only AFTER relaying the
reply, found the row already active and changed nothing. So a knocker whose request was accepted by a reply never heard
`chat.request.accepted`, on either path. Now the flip itself announces, post-commit, exactly once.

RED on 7241c198: the two reply-accept tests (the controls pass on both).
"""
from __future__ import annotations

import asyncio
import types

HOST = "https://sandbox-a.test"
HOME = "https://sandbox-b.test"
KNOCKER = "did:theprotocol:sandbox-a.test:knocker"
TARGET = "did:theprotocol:sandbox-b.test:worker"


class _R:
    def __init__(self, v=None):
        self.v = v

    def scalars(self):
        return self

    def first(self):
        return self.v

    def scalar_one(self):
        return self.v[0]


class _Db:
    def __init__(self, seq):
        self.seq = seq

    async def execute(self, stmt, params=None):
        if "UPDATE conversations" in str(stmt):
            return _R((self.seq,))
        return _R(None)

    def add(self, o):
        return None

    async def flush(self):
        return None

    async def commit(self):
        return None


def _capture(monkeypatch):
    from agentvault_registry.services import chat_service as cs
    heard: list = []

    async def _notify(notice, name):
        heard.append((notice["knocker_id"], notice["accepted_by_ptype"], notice["accepted_by"], name))
        return 1

    async def _names(db, keys):
        return {k: "B Proof Worker" for k in keys}

    async def _open(*a, **k):
        return None
    monkeypatch.setattr(cs, "notify_request_accepted", _notify)
    monkeypatch.setattr(cs, "display_names", _names)
    monkeypatch.setattr(cs, "room_posting_gate", _open)
    return cs, heard


CONV = types.SimpleNamespace(id="host-conv-1", kind="dm", created_by_ptype="agent", created_by_id=KNOCKER)


async def test_a_reply_that_accepts_a_cross_registry_knock_tells_the_knocker(monkeypatch):
    cs, heard = _capture(monkeypatch)
    part = types.SimpleNamespace(ptype="remote", remote_key=f"{TARGET}@{HOME}", state="pending")
    await cs.insert_remote_message(_Db(2), CONV, part, f"{TARGET}@{HOME}", "W", "text", "yes, let us talk", None,
                                   "ref-12345678")
    await asyncio.sleep(0)
    assert part.state == "active"
    assert heard == [(KNOCKER, "remote", f"{TARGET}@{HOME}", "B Proof Worker")]


async def test_a_local_reply_that_accepts_a_knock_tells_the_knocker(monkeypatch):
    cs, heard = _capture(monkeypatch)
    row = types.SimpleNamespace(ptype="agent", agent_did=TARGET, developer_id=None, state="pending", last_read_seq=0)
    await cs.insert_message(_Db(2), CONV, row, cs.Actor("agent", agent_did=TARGET, display_name=TARGET),
                            "text", "yes, let us talk", None, "ref-12345678")
    await asyncio.sleep(0)
    assert row.state == "active" and heard == [(KNOCKER, "agent", TARGET, "B Proof Worker")]


async def test_control_a_message_from_an_active_row_announces_nothing(monkeypatch):
    cs, heard = _capture(monkeypatch)
    part = types.SimpleNamespace(ptype="remote", remote_key=f"{TARGET}@{HOME}", state="active")
    await cs.insert_remote_message(_Db(3), CONV, part, f"{TARGET}@{HOME}", "W", "text", "again", None, "ref-12345679")
    row = types.SimpleNamespace(ptype="agent", agent_did=TARGET, developer_id=None, state="active", last_read_seq=0)
    await cs.insert_message(_Db(4), CONV, row, cs.Actor("agent", agent_did=TARGET, display_name=TARGET),
                            "text", "again", None, "ref-12345680")
    await asyncio.sleep(0)
    assert heard == []


async def test_control_the_homes_late_accept_announce_is_still_a_no_op(monkeypatch):
    from agentvault_registry.services import chat_federation as fed
    cs, heard = _capture(monkeypatch)
    part = types.SimpleNamespace(ptype="remote", remote_key=f"{TARGET}@{HOME}", state="active")

    class _HostDb:
        n = 0

        async def execute(self, stmt, params=None):
            self.n += 1
            return _R(types.SimpleNamespace(id="host-conv-1", kind="dm", host_registry=None) if self.n == 1 else part)

        async def commit(self):
            return None

    async def _yes(*a, **k):
        return True
    monkeypatch.setattr(fed, "caller_is", _yes)
    out = await fed.apply_remote_state(_HostDb(), "host-conv-1", f"{TARGET}@{HOME}", "active", "spiffe://sandbox-b.test/r")
    await asyncio.sleep(0)
    assert out == {"state": "active", "changed": False} and heard == []
