"""§TWOAGENT V0441 (2026-09-24) — a cross-registry thread names its people and its host truthfully, on both sides.

Found by the journal-48 screenshots of the first agent-to-agent chat between two production frames (EU hosts it, ASIA
keeps the mirror):
  1. every message a peer's principal wrote rendered as its raw key (`did:…@https://asia…` on EU, `did:…@https://eu…` on
     ASIA): the thread read named only developer and agent senders;
  2. ASIA's header and list row named EU's owner (`dev:12@https://eu…`, seated by the household join) instead of the
     Scrivener: the counterparty was "the first participant not mine" from rows read with no ORDER BY;
  3. ASIA said "Hosted by ASIA — the operator can read this thread" about a thread whose host_registry is EU, and neither
     side said the other registry keeps a copy;
  4. one EU developer was two principals at the mirror: its seat went out as `dev:12@…`, its messages as `12@…`, so a
     block made with the listed address matched none of its messages.

RED on V0440: pick_counterparty / sender_key_of / hosting_summary / local_wire_id / registry_display_names do not exist,
the thread read leaves a remote sender_name empty, and the envelope states a developer by its bare id.
"""
from __future__ import annotations

import datetime
import types

import pytest

from agentvault_registry.services import chat_service as cs

EU, ASIA = "https://eu.theprotocol.test", "https://asia.theprotocol.test"
SCRIVENER = f"did:theprotocol:eu:scrivener@{EU}"
STRAITS = "did:theprotocol:asia:straits"
T0 = datetime.datetime(2026, 9, 23, 19, 9, tzinfo=datetime.timezone.utc)


def _part(pid, ptype, *, dev=None, did=None, remote=None, at=0):
    return types.SimpleNamespace(id=pid, ptype=ptype, developer_id=dev, agent_did=did, remote_key=remote,
                                 state="active", joined_at=T0 + datetime.timedelta(seconds=at))


# ASIA's mirror, as measured: the resident agent and the thread's starter seated by the first delivery, EU's owner
# (a household join) and ASIA's owner seated a minute later.
MIRROR_PARTS = [
    _part("p-a", "agent", did=STRAITS, at=0),
    _part("p-s", "remote", remote=SCRIVENER, at=0),
    _part("p-o", "remote", remote=f"dev:12@{EU}", at=40),
    _part("p-d", "developer", dev=11, at=61),
]
MINE = {cs.principal_key("developer", 11), cs.principal_key("agent", STRAITS)}


@pytest.mark.parametrize("order", [MIRROR_PARTS, list(reversed(MIRROR_PARTS)),
                                   [MIRROR_PARTS[2], MIRROR_PARTS[0], MIRROR_PARTS[3], MIRROR_PARTS[1]]])
def test_a_mirror_names_the_principal_that_started_it_whatever_the_row_order(order):
    p, same = cs.pick_counterparty("dm", order, MINE, cs.principal_key("developer", 11),
                                   created_by=cs.created_by_key("remote", SCRIVENER))
    assert p.remote_key == SCRIVENER and same is False


def test_without_a_record_the_earliest_seated_stranger_is_named_not_the_owner_who_joined_later():
    order = [MIRROR_PARTS[2], MIRROR_PARTS[3], MIRROR_PARTS[0], MIRROR_PARTS[1]]   # the owner's row read first
    p, _ = cs.pick_counterparty("dm", order, MINE, cs.principal_key("developer", 11))
    assert p.remote_key == SCRIVENER


def test_a_local_dm_names_the_other_end_of_its_pair():
    host_parts = [_part("h-o", "remote", remote=f"dev:11@{ASIA}", at=0),       # listed first, seated with the pair
                  _part("h-s", "agent", did="did:theprotocol:eu:scrivener", at=0),
                  _part("h-a", "remote", remote=f"{STRAITS}@{ASIA}", at=0)]
    pair = "dm|" + "|".join(sorted([cs.principal_key("agent", "did:theprotocol:eu:scrivener"),
                                    cs.principal_key("remote", f"{STRAITS}@{ASIA}")]))
    me = cs.principal_key("agent", "did:theprotocol:eu:scrivener")
    p, _ = cs.pick_counterparty("dm", host_parts, {me}, me, pair_key=pair)
    assert p.remote_key == f"{STRAITS}@{ASIA}"


def test_control_both_sides_yours_still_names_the_side_that_is_not_the_caller():
    parts = [_part("x1", "agent", did="did:theprotocol:a:buyer"), _part("x2", "agent", did="did:theprotocol:a:seller")]
    mine = {cs.principal_key("agent", "did:theprotocol:a:buyer"), cs.principal_key("agent", "did:theprotocol:a:seller")}
    p, same = cs.pick_counterparty("agent_service", parts, mine, cs.principal_key("agent", "did:theprotocol:a:buyer"))
    assert p.agent_did == "did:theprotocol:a:seller" and same is True


def test_control_a_room_has_members_never_a_counterparty():
    assert cs.pick_counterparty("org", MIRROR_PARTS, set(), "dev:1") == (None, False)


def test_every_sender_a_person_or_agent_can_be_is_keyed_and_a_system_row_is_not():
    msg = lambda pt, sid: types.SimpleNamespace(sender_ptype=pt, sender_id=sid)   # noqa: E731
    assert cs.sender_key_of(msg("remote", SCRIVENER)) == f"rem:{SCRIVENER}"
    assert cs.sender_key_of(msg("developer", "12")) == "dev:12"
    assert cs.sender_key_of(msg("agent", STRAITS)) == f"agt:{STRAITS}"
    assert cs.sender_key_of(msg("system", "desk")) is None
    assert cs.sender_key_of(msg("developer", "not-a-number")) is None


async def test_the_thread_read_names_a_remote_sender_and_the_thread_it_is_with(monkeypatch):
    conv = types.SimpleNamespace(id="c-m", kind="dm", host_registry=EU, dm_pair_key=None, created_by_ptype="remote",
                                 created_by_id=SCRIVENER, last_seq=2, service_inflight_at=None, retention_hours=None)
    msgs = [types.SimpleNamespace(id="m1", conversation_id="c-m", seq=1, sender_ptype="remote", sender_id=SCRIVENER,
                                  kind="text", body="Hello from EU", card=None, reply_to=None, client_ref="r1",
                                  remote_seq=1, origin_registry=EU, created_at=T0, edited_at=None, deleted_at=None),
            types.SimpleNamespace(id="m2", conversation_id="c-m", seq=2, sender_ptype="agent", sender_id=STRAITS,
                                  kind="text", body="Replying from ASIA", card=None, reply_to=None, client_ref="r2",
                                  remote_seq=None, origin_registry=None, created_at=T0, edited_at=None,
                                  deleted_at=None)]
    order = [MIRROR_PARTS[2], MIRROR_PARTS[0], MIRROR_PARTS[3], MIRROR_PARTS[1]]   # the measured lottery: owner first

    class _R:
        def __init__(self, v):
            self.v = v

        def scalars(self):
            return self

        def all(self):
            return self.v

    class _Db:
        def __init__(self):
            self.n = 0

        async def execute(self, stmt, params=None):
            self.n += 1
            return _R(list(reversed(msgs)) if self.n == 1 else order)

    asked = []

    async def _names(db, keys):
        asked.extend(keys)
        return {f"rem:{SCRIVENER}": "Scrivener of Brussels", f"agt:{STRAITS}": "Straits Assay",
                f"rem:dev:12@{EU}": f"dev:12@{EU}"}

    async def _conv(db, cid):
        return conv

    async def _member(db, c, actor, announce_ok=False):
        return types.SimpleNamespace(state="active", last_read_seq=2, hidden_before_seq=None, can_post=True)

    async def _mine(db, actor):
        return set(MINE)

    async def _hosting(db, c, parts):
        return {"registry": "EU", "copies": ["ASIA"], "here": False, "plaintext": True}
    monkeypatch.setattr(cs, "_get_conversation", _conv)
    monkeypatch.setattr(cs, "resolve_membership", _member)
    monkeypatch.setattr(cs, "household_keys", _mine)
    monkeypatch.setattr(cs, "display_names", _names)
    monkeypatch.setattr(cs, "thread_hosting", _hosting)
    out = await cs.list_messages(_Db(), "c-m", cs.Actor("developer", developer_id=11, display_name="Straits Assay Desk"))
    assert [m["sender_name"] for m in out["messages"]] == ["Scrivener of Brussels", "Straits Assay"]
    assert f"rem:{SCRIVENER}" in asked
    assert out["counterparty"]["remote_key"] == SCRIVENER and out["counterparty"]["name"] == "Scrivener of Brussels"
    assert out["counterparty"]["same_household"] is False
    assert out["hosting"]["registry"] == "EU" and out["hosting"]["copies"] == ["ASIA"]


def test_a_mirror_says_who_hosts_it_and_that_it_keeps_a_copy():
    names = {EU: "EU", ASIA: "ASIA"}
    h = cs.hosting_summary(EU, [EU, EU, ASIA], ASIA, names)
    assert h["registry"] == "EU" and h["copies"] == ["ASIA"] and h["here"] is False and h["plaintext"] is True
    assert h["says"] == "hosted by EU, copied to ASIA — the operator of each can read this thread"


def test_the_host_says_the_other_registry_keeps_a_copy():
    h = cs.hosting_summary(EU, [EU, ASIA, ASIA, EU], EU, {EU: "EU", ASIA: "ASIA"})
    assert h["registry"] == "EU" and h["copies"] == ["ASIA"] and h["here"] is True


def test_control_a_local_thread_is_held_here_alone():
    h = cs.hosting_summary("here", ["here"], "here", {"here": "ASIA"})
    assert h == {"registry": "ASIA", "here": True, "copies": [], "plaintext": True,
                 "says": "hosted by ASIA — the operator can read this thread"}


async def test_a_thread_with_no_peer_is_hosted_here_without_asking_the_federation(monkeypatch):
    monkeypatch.setenv("REGISTRY_FEDERATION_NAME", "ASIA")
    h = await cs.thread_hosting(None, types.SimpleNamespace(host_registry=None), [_part("l1", "developer", dev=3)])
    assert h["registry"] == "ASIA" and h["copies"] == [] and h["here"] is True


async def test_a_mirror_on_this_registry_names_its_host_from_the_peers_signed_card(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", ASIA)
    monkeypatch.setenv("REGISTRY_FEDERATION_NAME", "ASIA")
    from agentvault_registry.services import chat_federation as fed

    class _R:
        def all(self):
            return [("eu", "https://eu.theprotocol.test:8443", {"identity": {"display_name": "EU"}}, True)]

    class _Db:
        async def execute(self, stmt, params=None):
            return _R()
    h = await cs.thread_hosting(_Db(), types.SimpleNamespace(host_registry=EU), MIRROR_PARTS)
    assert h["registry"] == "EU" and h["copies"] == ["ASIA"] and h["here"] is False
    assert (await fed.registry_display_names(_Db(), [EU])) == {EU: "EU"}


async def test_an_unverified_card_is_not_believed_and_an_unknown_registry_is_named_by_its_host():
    from agentvault_registry.services import chat_federation as fed

    class _R:
        def all(self):
            return [("eu", "https://eu.theprotocol.test:8443", {"identity": {"display_name": "Totally EU"}}, False)]

    class _Db:
        async def execute(self, stmt, params=None):
            return _R()
    names = await fed.registry_display_names(_Db(), [EU, "https://third.example"])
    assert names == {EU: "eu", "https://third.example": "third.example"}


class _Rows:
    def __init__(self, v):
        self.v = v

    def scalars(self):
        return self

    def all(self):
        return self.v

    def first(self):
        return self.v


class _WireDb:
    """enqueue_delivery against a thread EU hosts: its own developer 12 and ASIA's agent. Answers by query shape: a
    handle lookup gets the handle row; the participant selects come in enqueue_delivery's order (the remote rows
    first, then every row for participant_wire)."""

    def __init__(self, handle=None):
        self.handle, self.added, self.selects = handle, [], 0
        self.parts = [_part("w1", "developer", dev=12), _part("w2", "remote", remote=f"{STRAITS}@{ASIA}")]

    async def execute(self, stmt, params=None):
        if "handle" in " ".join(str(stmt).split()).lower():
            return _Rows((self.handle,) if self.handle else None)
        self.selects += 1
        return _Rows([p for p in self.parts if p.ptype == "remote"] if self.selects == 1 else self.parts)

    def add(self, row):
        self.added.append(row)


async def test_a_developer_goes_by_its_handle_or_dev_id_on_the_wire():
    from agentvault_registry.services import chat_federation as fed
    assert await fed.local_wire_id(_WireDb(), "developer", 12) == "dev:12"
    assert await fed.local_wire_id(_WireDb(handle="scrivener-eu"), "developer", "12") == "scrivener-eu"
    assert await fed.local_wire_id(_WireDb(), "agent", STRAITS) == STRAITS


@pytest.mark.parametrize("handle", [None, "scrivener-eu"])
async def test_a_host_developers_message_goes_out_under_the_key_its_seat_is_listed_under(monkeypatch, handle):
    monkeypatch.setenv("PUBLIC_BASE_URL", EU)
    from agentvault_registry.services import chat_federation as fed
    db = _WireDb(handle=handle)
    conv = types.SimpleNamespace(id="c-h", kind="dm", title=None, host_registry=None)
    msg = types.SimpleNamespace(id="m-o", seq=4, sender_ptype="developer", sender_id="12", kind="text",
                                body="The Scrivener's owner here", card=None, client_ref="o-1", created_at=T0)
    assert await fed.enqueue_delivery(db, conv, msg, "scrivener-eu") == 1
    payload = db.added[0].payload
    sender = payload["message"]["sender"]
    listed = [p["key"] for p in payload["conversation"]["participants"] if p["key"].endswith("@" + EU)]
    assert fed.remote_key(sender["id"], sender["registry"]) in listed
    assert sender["id"] == (handle or "dev:12")
