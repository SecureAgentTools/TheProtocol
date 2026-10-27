"""The FrameFederationEstablished reactor registers the new peer frame as a TEG partner (agentvault2-56, 2026-10-21).

Two frames that federate through the invitation rail never added each other to their TEGs: both sides emit
FrameFederationEstablished and nothing consumed it, so under the partner rule (ledgergate3, enforce) the TEG that
receives a new frame's first leg refused it. The reactor registers the peer through
reactor_helpers.register_peer_partner_on_teg on each side's own event; the revoke names the partner it releases.

What these tests pin (the database session and the helper replaced; the HTTP call to the TEG is the helper's own):
- the approver's and the initiator's events register the ACTIVE peer row the local invitation names;
- another frame's event (marked foreign by the store) and an event whose invitation this database does not hold (a
  cloud operator reading its parent frame's store) register nothing and open no session or read nothing;
- an invitation that names another peer, a peer row that is not ACTIVE, and a payload without an invitation or a peer
  register nothing;
- main.py starts the reactor, and the frame revoke's PeerRegistryDeactivated event names the partner it releases.
RED on 0f831a0f (V0629): the module does not exist, and the revoke emits teg_id None.
"""
from __future__ import annotations

import ast
import pathlib
import types
from typing import List, Optional

import pytest

from agentvault_registry.background_tasks import reactor_base
from agentvault_registry.background_tasks import reactor_frame_federation_established as r_ffe

SRC = pathlib.Path(r_ffe.__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def reset_leader_keys():
    reactor_base._registered_leader_keys.clear()
    r_ffe._instance = r_ffe._approved_instance = None
    yield
    reactor_base._registered_leader_keys.clear()
    r_ffe._instance = r_ffe._approved_instance = None


class _DB:
    """A session holding one invitation and one peer row; records what was read."""

    def __init__(self, invitations=None, peers=None):
        self.invitations = invitations or {}
        self.peers = peers or {}
        self.reads: List[tuple] = []

    async def get(self, model, key):
        self.reads.append((model.__name__, key))
        table = self.invitations if model.__name__ == "FrameInvitation" else self.peers
        return table.get(key)


class _Session:
    def __init__(self, db):
        self.db = db
        self.opened = 0

    def __call__(self):
        self.opened += 1
        return self

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def world(monkeypatch):
    """invitation inv-1 names peer 7 (ACTIVE, 'nt261021x1b'); register_peer_partner_on_teg recorded, not dialed."""
    from agentvault_registry import database

    calls: List[tuple] = []
    answer: dict = {"value": {"status": "added", "total_partners": 3}}

    async def fake_register(db, peer_name: str, *, source_label: str) -> Optional[dict]:
        calls.append((peer_name, source_label))
        return answer["value"]

    db = _DB(invitations={"inv-1": types.SimpleNamespace(id="inv-1", peer_registry_id=7)},
             peers={7: types.SimpleNamespace(id=7, name="nt261021x1b", status="ACTIVE")})
    session = _Session(db)
    monkeypatch.setattr(database, "AsyncSessionLocal", session)
    monkeypatch.setattr(r_ffe, "register_peer_partner_on_teg", fake_register)
    return types.SimpleNamespace(calls=calls, db=db, session=session, answer=answer)


REACTORS = [r_ffe.FrameFederationEstablishedReactor, r_ffe.FrameInvitationApprovedPartnerReactor]


def _event(**over):
    base = {"invitation_id": "inv-1", "peer_registry_id": 7, "side": "approver", "status": "completed",
            "initiator_trust_domain": "nt261021x1b.example.org", "initiator_name": "nt261021x1b"}
    base.update(over)
    return base


@pytest.mark.asyncio
@pytest.mark.parametrize("REACTOR", REACTORS, ids=["established", "approved"])
@pytest.mark.parametrize("side", ["approver", "initiator"])
async def test_each_sides_own_event_registers_the_peer_frame(REACTOR, world, side):
    await REACTOR().handle_event(_event(side=side))
    assert world.calls == [("nt261021x1b", REACTOR.name)]


@pytest.mark.asyncio
@pytest.mark.parametrize("REACTOR", REACTORS, ids=["established", "approved"])
async def test_a_retried_approve_registers_again_idempotently(REACTOR, world):
    world.answer["value"] = {"status": "updated", "total_partners": 3}
    await REACTOR().handle_event(_event(retry=True))
    assert world.calls == [("nt261021x1b", REACTOR.name)]


@pytest.mark.asyncio
@pytest.mark.parametrize("REACTOR", REACTORS, ids=["established", "approved"])
async def test_another_frames_event_registers_nothing_and_reads_nothing(REACTOR, world):
    await REACTOR().handle_event(_event(_foreign_frame_id="asia"))
    assert world.calls == [] and world.session.opened == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("REACTOR", REACTORS, ids=["established", "approved"])
async def test_an_event_this_registry_does_not_hold_registers_nothing(REACTOR, world):
    """A cloud operator reads its parent frame's store: the parent's handshake is not the operator's."""
    await REACTOR().handle_event(_event(invitation_id="inv-of-the-parent"))
    assert world.calls == []
    assert ("PeerRegistry", 7) not in world.db.reads


@pytest.mark.asyncio
@pytest.mark.parametrize("REACTOR", REACTORS, ids=["established", "approved"])
async def test_an_invitation_naming_another_peer_registers_nothing(REACTOR, world):
    await REACTOR().handle_event(_event(peer_registry_id=8))
    assert world.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("REACTOR", REACTORS, ids=["established", "approved"])
async def test_a_peer_row_that_is_not_active_registers_nothing(REACTOR, world):
    world.db.peers[7].status = "INACTIVE"
    await REACTOR().handle_event(_event())
    assert world.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("REACTOR", REACTORS, ids=["established", "approved"])
@pytest.mark.parametrize("missing", ["invitation_id", "peer_registry_id"])
async def test_a_payload_without_an_invitation_or_a_peer_registers_nothing(REACTOR, world, missing):
    await REACTOR().handle_event(_event(**{missing: None}))
    assert world.calls == [] and world.session.opened == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("REACTOR", REACTORS, ids=["established", "approved"])
async def test_a_helper_that_registered_nothing_is_said_not_raised(REACTOR, world, caplog):
    world.answer["value"] = None
    await REACTOR().handle_event(_event())
    assert world.calls == [("nt261021x1b", REACTOR.name)]
    assert any("was not registered" in r.message for r in caplog.records)


def test_the_reactor_listens_to_the_event_the_handshake_emits():
    assert r_ffe.FrameFederationEstablishedReactor.event_type == "FrameFederationEstablished"
    tree = ast.parse((SRC / "routers" / "frame_invitations.py").read_text())
    emitted = {c.args[0].value for c in ast.walk(tree)
               if isinstance(c, ast.Call) and getattr(c.func, "id", None) == "_emit_event"
               and c.args and isinstance(c.args[0], ast.Constant)}
    assert "FrameFederationEstablished" in emitted


def test_main_starts_the_reactor_under_its_own_switch():
    tree = ast.parse((SRC / "main.py").read_text())
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert "agentvault_registry.background_tasks.reactor_frame_federation_established" in modules
    switches = {c.args[0].value for c in ast.walk(tree)
                if isinstance(c, ast.Call) and getattr(c.func, "attr", None) == "getenv"
                and c.args and isinstance(c.args[0], ast.Constant)}
    assert "REACTOR_FRAME_FEDERATION_ESTABLISHED_ENABLED" in switches


def test_the_frame_revoke_names_the_partner_it_releases():
    """revoke_frame_federation's PeerRegistryDeactivated payload carries the partner id
    crud_peer_registry._released_partner_teg_id names (teg-<safe name>, or None when another ACTIVE row names it),
    so the Phase 1 reactor removes what this reactor registered. Before: the literal None."""
    tree = ast.parse((SRC / "routers" / "frame_invitations.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "revoke_frame_federation")
    calls = {getattr(c.func, "id", None) for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "_released_partner_teg_id" in calls
    payloads = [kw.value for c in ast.walk(fn) if isinstance(c, ast.Call)
                for kw in c.keywords if kw.arg == "data" and isinstance(kw.value, ast.Dict)]
    teg_values = [v for d in payloads for k, v in zip(d.keys, d.values)
                  if isinstance(k, ast.Constant) and k.value == "teg_id"]
    assert teg_values and all(isinstance(v, ast.Name) and v.id == "released_teg_id" for v in teg_values)


@pytest.mark.asyncio
async def test_the_approval_payload_the_store_holds_registers_the_peer(world):
    """The payload frame_invitations emits at approve, as nt261021x2's stores hold it (no side, the reviewer's id)."""
    await r_ffe.FrameInvitationApprovedPartnerReactor().handle_event(
        {"invitation_id": "inv-1", "initiator_trust_domain": "nt261021x1b.example.org", "initiator_name": "nt261021x1b",
         "status": "approved", "peer_registry_id": 7, "reviewer_developer_id": 1, "timestamp": "2026-10-21T13:51:46Z"})
    assert world.calls == [("nt261021x1b", "FrameInvitationApproved")]


def test_both_reactors_listen_to_events_the_handshake_emits():
    tree = ast.parse((SRC / "routers" / "frame_invitations.py").read_text())
    emitted = {c.args[0].value for c in ast.walk(tree)
               if isinstance(c, ast.Call) and getattr(c.func, "id", None) == "_emit_event"
               and c.args and isinstance(c.args[0], ast.Constant)}
    assert {r.event_type for r in REACTORS} <= emitted
    assert len({r.leader_key for r in REACTORS}) == 2


@pytest.mark.asyncio
async def test_start_starts_both_reactors(monkeypatch):
    started = []

    async def fake_start(self):
        started.append(self.event_type)

    monkeypatch.setattr(reactor_base.EventStoreReactor, "start", fake_start)
    await r_ffe.start()
    assert started == ["FrameFederationEstablished", "FrameInvitationApproved"]
