"""D6-112: resync registers the PEER's event store, never this frame's own.

On the frame that joined, the invitation linked to the approver's peer row is its own outbound one, whose
initiator_event_store_url is this frame's own store; resync took it as the peer's and registered this frame's store
as the peer's. Only an invitation the peer sent (initiator_trust_domain = the peer's) names the peer's store; without
one resync takes the convention and says so (event_store_url_source).
"""
import asyncio
import types

from agentvault_registry.routers import frame_invitations as fi

PEER_TD = "asia.example.org"
OWN_STORE = "https://eu.example.org:8461"
PEER_STORE = "https://asia.example.org:8471"


class _Result:
    def __init__(self, v):
        self.v = v

    def scalar_one_or_none(self):
        return self.v

    def scalars(self):
        return self

    def first(self):
        return self.v


class _Db:
    """Answers the peer lookup, then the invitation lookup with the invitations that match its WHERE."""

    def __init__(self, peer, invitations):
        self.peer, self.invitations, self.statements = peer, invitations, []

    async def execute(self, stmt):
        self.statements.append(stmt)
        if len(self.statements) == 1:
            return _Result(self.peer)
        where = str(stmt.whereclause.compile(compile_kwargs={"literal_binds": True}))
        hits = [i for i in self.invitations
                if f"frame_invitations.peer_registry_id = {i.peer_registry_id}" in where
                and ("initiator_trust_domain" not in where or f"'{i.initiator_trust_domain}'" in where)]
        return _Result(hits[0] if hits else None)


def _run(monkeypatch, invitations):
    registered = []

    async def _cross(**kw):
        registered.append(kw)
        return types.SimpleNamespace(ok=True, detail=None)

    async def _op(**kw):
        return types.SimpleNamespace(ok=True, detail=None)
    monkeypatch.setattr(fi.frame_data_plane_sync, "register_cross_frame_peer", _cross)
    monkeypatch.setattr(fi.frame_data_plane_sync, "register_federation_operator", _op)
    peer = types.SimpleNamespace(id=5, peer_type="frame", trust_domain=PEER_TD, name="ASIA")
    out = asyncio.run(fi.resync_frame_eventstore(peer_id=5, db=_Db(peer, invitations),
                                                 current_admin=types.SimpleNamespace(email="admin@example.org")))
    return out, registered


def _inv(initiator_td, store):
    return types.SimpleNamespace(peer_registry_id=5, initiator_trust_domain=initiator_td, initiator_event_store_url=store)


def test_the_joining_frame_never_registers_its_own_store(monkeypatch):
    out, registered = _run(monkeypatch, [_inv("eu.example.org", OWN_STORE)])
    assert registered[0]["event_store_url"] != OWN_STORE
    assert out["event_store_url_source"] == "convention"


def test_the_approver_takes_the_store_the_peer_named(monkeypatch):
    out, registered = _run(monkeypatch, [_inv(PEER_TD, PEER_STORE)])
    assert registered[0]["event_store_url"] == PEER_STORE
    assert out["event_store_url_source"] == "invitation"
