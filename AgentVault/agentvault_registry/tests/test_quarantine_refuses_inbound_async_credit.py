"""D6-801's rest (2026-10-17): no inbound async credit from a peer this registry holds in quarantine.

The async cross-frame rail credits the receiver here when the sender frame's CrossFrameTransferInitiated arrives
(background_tasks/reactor_cross_frame_initiated.py). It never asked the compliance state, so a peer this registry held
in quarantine still had its transfers booked here. The event names only its sender's trust domain (`source_frame`), so
the reactor now asks, before it credits, whether a registry of that trust domain is quarantined, soft quarantined or
blacklisted here (one read per trust domain within a short time), and:

  * refuses it: nothing is credited, no Settled is sent (the sender's saga refunds its sender at its timeout), and the
    transfer is recorded REFUSED (an inbound row with status 'refused', and a warning naming the registry);
  * never credits a refused transfer later, even once the quarantine is lifted (its sender may be refunded by then);
  * credits nothing when the compliance state cannot be read (the handler raises; the event is handled again);
  * and the Refunded reactor reverses only a row that was credited, never a refused one.

These are background reactors with no route: each test hands the reactor the event as the foreign-events bridge
delivers it. Doubles: the registry database (agents, inbound rows, the compliance read), the TEG (a recorder of the
credit and reverse calls) and the event emitter (a recorder).
RED on 453cc8b8: every test but the two controls (the base credits whatever arrives, and reverses any row it finds).
"""
from __future__ import annotations

import asyncio
import contextlib
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from agentvault_registry.background_tasks import reactor_base
from agentvault_registry.background_tasks import reactor_cross_frame_initiated as initiated
from agentvault_registry.background_tasks import reactor_cross_frame_refunded as refunded

HERE_TD, PEER_TD, OTHER_TD = "asia.example.invalid", "eu.example.invalid", "orbit.example.invalid"
RECEIVER, SENDER = "did:theprotocol:asia:receiver-1", "did:theprotocol:eu:sender-1"
TID = "7a9d3f5e-0000-4c1e-9a7b-3d2f1e0c5b4a"
EVENT = {"transfer_id": TID, "sender_did": SENDER, "receiver_did": RECEIVER, "source_frame": PEER_TD,
         "target_frame": HERE_TD, "amount": "5.000000", "memo": "m"}


class _Res:
    def __init__(self, one=None, rows=()):
        self._one, self._rows = one, list(rows)

    def scalar_one_or_none(self):
        return self._one

    def all(self):
        return list(self._rows)


class _Db:
    """This registry's database: its agents, its inbound rows, and the compliance read (rows of (name, trust domain,
    peer type, state)) that answers or fails."""

    def __init__(self, store):
        self.s = store

    async def execute(self, stmt, *a, **k):
        sql = str(stmt)
        if "federated_registry_compliance" in sql:
            self.s.compliance_reads += 1
            if self.s.compliance_fails:
                raise RuntimeError("database unreachable")
            return _Res(rows=self.s.quarantined)
        if sql.startswith("INSERT INTO cross_frame_transfers_inbound"):
            p = stmt.compile(dialect=postgresql.dialect()).params
            self.s.inbound.setdefault(p["id"], SimpleNamespace(**p))
            return _Res()
        if sql.startswith("UPDATE cross_frame_transfers_inbound"):
            p = stmt.compile(dialect=postgresql.dialect()).params
            row = self.s.inbound.get(p["id_1"])
            if row is not None and row.status == p["status_1"]:
                row.status = p["status"]
            return _Res()
        if "FROM cross_frame_transfers_inbound" in sql:
            return _Res(one=next(iter(self.s.inbound.values()), None))
        if "FROM agents" in sql:
            return _Res(one=SimpleNamespace(did=RECEIVER) if self.s.receiver_local else None)
        raise AssertionError(f"unexpected statement: {sql[:120]}")

    async def get(self, model, key):
        assert model.__name__ == "CrossFrameTransferInbound"
        return self.s.inbound.get(key)

    async def commit(self):
        pass


class _Teg:
    def __init__(self, store):
        self.s = store

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        self.s.teg.append((url.rsplit("/", 1)[-1], dict(json or {})))
        return SimpleNamespace(status_code=200, text="", json=lambda: {"status": "ok"})


class _Emitter:
    def __init__(self, store):
        self.s = store

    async def emit(self, *, event_type, **k):
        self.s.emitter_calls.append(event_type)


@pytest.fixture
def store(monkeypatch):
    s = SimpleNamespace(quarantined=[], compliance_fails=False, compliance_reads=0, inbound={}, teg=[],
                        emitter_calls=[], receiver_local=True)

    @contextlib.asynccontextmanager
    async def _ctx():
        yield _Db(s)
    for mod in (initiated, refunded):
        monkeypatch.setattr(mod, "get_db_context", _ctx)
        monkeypatch.setattr(mod, "get_httpx_verify", lambda: False)
        monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **k: _Teg(s))
    monkeypatch.setattr(initiated, "get_event_emitter", lambda: _Emitter(s))
    from agentvault_registry import event_emitter
    monkeypatch.setattr(event_emitter, "get_event_emitter", lambda: _Emitter(s))
    monkeypatch.setattr(reactor_base, "_registered_leader_keys", set())
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", HERE_TD)
    return s


def _credit(event=EVENT, reactor=None):
    """One delivery of the event, to `reactor` or to a fresh reactor (a fresh one reads the compliance state anew)."""
    if reactor is None:
        reactor_base._registered_leader_keys.clear()   # one leader key per process: the test makes one reactor at a time
        reactor = initiated.CrossFrameInitiatedReactor()
    asyncio.run(reactor.handle_event(dict(event)))
    return reactor


# ── the inbound credit ─────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("state", ["quarantined", "soft_quarantined", "blacklisted"])
def test_a_credit_from_a_quarantined_trust_domain_is_refused_and_recorded(store, state):
    store.quarantined = [("Lisbon", PEER_TD, "cloud_operator", state)]
    _credit()
    assert store.teg == [], "a credit from a quarantined peer reached the TEG"
    assert store.emitter_calls == [], "a refused credit sent Settled"
    row = store.inbound[TID]
    assert (row.status, row.source_frame, Decimal(str(row.amount))) == ("refused", PEER_TD, Decimal("5"))


def test_a_refused_transfer_is_never_credited_later(store):
    store.quarantined = [("EU", PEER_TD, "frame", "quarantined")]
    _credit()
    store.quarantined = []          # the quarantine is lifted; the event is delivered again (to a reactor that reads anew)
    _credit()
    assert store.compliance_reads == 1, "the second delivery was decided by the compliance state, not the refusal"
    assert store.teg == [] and store.emitter_calls == []
    assert store.inbound[TID].status == "refused"


def test_an_unreadable_compliance_state_credits_nothing(store):
    store.compliance_fails = True
    with pytest.raises(Exception):
        _credit()
    assert store.teg == [] and store.inbound == {} and store.emitter_calls == []


def test_one_trust_domains_verdict_is_reused_within_its_time(store):
    r = _credit()
    _credit(dict(EVENT, transfer_id="7a9d3f5e-1111-4c1e-9a7b-3d2f1e0c5b4a"), reactor=r)
    assert store.compliance_reads == 1, store.compliance_reads
    assert [e for e, _ in store.teg] == ["credit-async", "credit-async"]


def test_control_a_credit_from_a_trust_domain_in_good_standing_is_booked(store):
    store.quarantined = [("Orbit", OTHER_TD, "frame", "quarantined")]   # another trust domain is quarantined
    _credit()
    (endpoint, body), = store.teg
    assert endpoint == "credit-async" and body["receiver_did"] == RECEIVER and body["transfer_id"] == TID
    assert store.inbound[TID].status == "credited"
    assert store.emitter_calls == ["CrossFrameTransferSettled"]


# ── the reverse after the sender's refund ──────────────────────────────────────────────────────────────────────────

REFUNDED = {"transfer_id": TID, "target_frame": HERE_TD, "sender_did": SENDER}


def _reverse(store):
    reactor_base._registered_leader_keys.clear()
    asyncio.run(refunded.CrossFrameRefundedReactor().handle_event(dict(REFUNDED)))


def test_the_refunded_reactor_reverses_nothing_it_refused(store):
    store.inbound[TID] = SimpleNamespace(id=TID, status="refused", receiver_did=RECEIVER, amount=Decimal("5"),
                                         source_frame=PEER_TD)
    _reverse(store)
    assert store.teg == [], "a transfer that was never credited was reversed"
    assert store.inbound[TID].status == "refused" and store.emitter_calls == []


def test_control_the_refunded_reactor_reverses_a_credited_row(store):
    store.inbound[TID] = SimpleNamespace(id=TID, status="credited", receiver_did=RECEIVER, amount=Decimal("5"),
                                         source_frame=PEER_TD)
    _reverse(store)
    assert [e for e, _ in store.teg] == ["reverse-async"]
    assert store.inbound[TID].status == "reversed"
    assert store.emitter_calls == ["CrossFrameTransferReversed"]
