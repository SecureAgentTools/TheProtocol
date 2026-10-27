"""§TWOAGENT G1 household seat (V0436, his decision 2026-09-23): an owner reads and posts in its agent's cross-registry
thread, as locally, and is never a silent reader.

Locally the household rule seats a developer in any thread its ACTIVE agent holds, silently, on first touch. Across
registries that seat was impossible: the owner's home could seat it on the mirror, but the host had never heard of it
and refused every relay (403 "not a participant"). Now:
  * on a MIRROR the home asks the host first (`/federation/chat/state`, state `join`, `household_of` = the agent's key)
    and seats nobody unless the host recorded it (502);
  * the host seats the owner only when the caller is the home of BOTH the owner and the ACTIVE agent participant (it
    vouches for its own residents), the owner is a developer, and the join is idempotent; it writes one VISIBLE system
    row, committed with its delivery rows, skipped for anyone who blocks the owner's address;
  * the host's own owner joining a federated thread gets the same visible row; a purely local thread is unchanged;
  * the join row's client_ref is recorded like a relay, so it comes home as the owner's own row;
  * a counterparty on a peer registry carries its address (`remote_key`), which a client needs to block it.

RED on da9f2211: every test but the control. Since V0437 a federated household join needs the reader's consent
(`announce_ok`, test_twoagent_household_consent.py); these tests exercise the join itself, so they give it.
"""
from __future__ import annotations

import types

import pytest

HOST = "https://sandbox-a.test"
HOME = "https://sandbox-b.test"
AGENT = "did:theprotocol:sandbox-b.test:worker"
OWNER = "ownerhandle"


class _R:
    def __init__(self, v=None):
        self.v = v

    def scalars(self):
        return self

    def first(self):
        return self.v

    def all(self):
        return self.v if isinstance(self.v, list) else []


def _host(monkeypatch, agent_state="active", joiner_row=None, caller_ok=(True, True)):
    from agentvault_registry.services import chat_federation as fed
    from agentvault_registry.services import chat_service as cs
    conv = types.SimpleNamespace(id="host-conv-1", kind="dm", host_registry=None)
    agent = types.SimpleNamespace(ptype="remote", remote_key=f"{AGENT}@{HOME}", state=agent_state)
    seen: dict = {"posted": []}

    class _Db:
        def __init__(self):
            self.n, self.added = 0, []

        async def execute(self, stmt, params=None):
            self.n += 1
            return _R({1: conv, 2: agent, 3: joiner_row}.get(self.n))

        def add(self, o):
            self.added.append(o)

        async def flush(self):
            return None

    calls = iter(caller_ok)

    async def _caller(db, peer, reg):
        return next(calls, False)

    async def _post(db, conv_, row, joiner_pkey, display, agent_pkey, **kw):
        seen["posted"].append((row.remote_key, row.state, joiner_pkey, display, agent_pkey, kw.get("client_ref")))
        return types.SimpleNamespace(seq=11)
    monkeypatch.setattr(fed, "caller_is", _caller)
    monkeypatch.setattr(fed, "post_household_join", _post, raising=False)
    return fed, cs, _Db(), seen


async def test_the_host_seats_an_owner_its_agents_home_vouches_for_and_shows_the_join(monkeypatch):
    fed, cs, db, seen = _host(monkeypatch)
    out = await fed.apply_remote_state(db, "host-conv-1", f"{OWNER}@{HOME}", "join", "spiffe://sandbox-b.test/r",
                                       household_of=f"{AGENT}@{HOME}", participant_display="Owner O",
                                       client_ref="hjoin-12345678")
    assert out == {"state": "active", "changed": True, "joined": True, "seq": 11}
    assert [(o.ptype, o.remote_key, o.state) for o in db.added] == [("remote", f"{OWNER}@{HOME}", "active")]
    assert seen["posted"] == [(f"{OWNER}@{HOME}", "active", f"rem:{OWNER}@{HOME}", "Owner O", f"rem:{AGENT}@{HOME}",
                               "hjoin-12345678")]


async def test_a_registry_that_is_not_the_agents_home_cannot_seat_anyone(monkeypatch):
    fed, cs, db, seen = _host(monkeypatch, caller_ok=(True, False))
    with pytest.raises(cs.ChatError) as e:
        await fed.apply_remote_state(db, "host-conv-1", f"{OWNER}@{HOME}", "join", "spiffe://stranger.test/r",
                                     household_of=f"{AGENT}@{HOME}")
    assert e.value.status_code == 403 and db.added == [] and seen["posted"] == []


async def test_the_agent_it_joins_through_must_be_an_active_participant(monkeypatch):
    fed, cs, db, seen = _host(monkeypatch, agent_state="pending")
    with pytest.raises(cs.ChatError) as e:
        await fed.apply_remote_state(db, "host-conv-1", f"{OWNER}@{HOME}", "join", "spiffe://sandbox-b.test/r",
                                     household_of=f"{AGENT}@{HOME}")
    assert e.value.status_code == 409 and db.added == []


async def test_an_agent_cannot_take_a_household_seat(monkeypatch):
    fed, cs, db, seen = _host(monkeypatch)
    with pytest.raises(cs.ChatError) as e:
        await fed.apply_remote_state(db, "host-conv-1", f"did:theprotocol:sandbox-b.test:other@{HOME}", "join",
                                     "spiffe://sandbox-b.test/r", household_of=f"{AGENT}@{HOME}")
    assert e.value.status_code == 422 and db.added == []


async def test_a_second_join_changes_nothing_and_shows_nothing(monkeypatch):
    seated = types.SimpleNamespace(ptype="remote", remote_key=f"{OWNER}@{HOME}", state="active")
    fed, cs, db, seen = _host(monkeypatch, joiner_row=seated)
    out = await fed.apply_remote_state(db, "host-conv-1", f"{OWNER}@{HOME}", "join", "spiffe://sandbox-b.test/r",
                                       household_of=f"{AGENT}@{HOME}")
    assert out == {"state": "active", "changed": False, "joined": False} and seen["posted"] == []


async def test_the_visible_join_commits_with_its_deliveries_and_skips_whoever_blocks_the_owner(monkeypatch):
    from agentvault_registry.services import chat_federation as fed
    from agentvault_registry.services import chat_service as cs
    seen: dict = {}

    async def _names(db, keys):
        return {f"rem:{AGENT}@{HOME}": "B Proof Worker"}

    async def _insert(db, conv, row, sender_key, display, kind, body, card, ref, **kw):
        seen["insert"] = (sender_key, kind, body, ref, kw.get("system_row"))
        await kw["before_commit"](types.SimpleNamespace(seq=3))
        return types.SimpleNamespace(seq=3), False

    async def _enqueue(db, conv, m, display):
        seen["queued"] = m.seq
        return 1

    async def _snapshot(db, conv, sender):
        seen["snapshot_sender"] = sender.key
        return []

    async def _fan(*a, **k):
        return None
    monkeypatch.setattr(cs, "display_names", _names)
    monkeypatch.setattr(cs, "insert_remote_message", _insert)
    monkeypatch.setattr(cs, "serialize_message", lambda m: {"seq": m.seq})
    monkeypatch.setattr(fed, "enqueue_delivery", _enqueue)
    monkeypatch.setattr(cs, "recipients_snapshot", _snapshot)
    monkeypatch.setattr(cs, "fan_out_message", _fan)
    conv = types.SimpleNamespace(id="host-conv-1", kind="dm", host_registry=None)
    row = types.SimpleNamespace(ptype="remote", remote_key=f"{OWNER}@{HOME}", state="active")
    await fed.post_household_join(None, conv, row, f"rem:{OWNER}@{HOME}", "Owner O", f"rem:{AGENT}@{HOME}",
                                  client_ref="hjoin-12345678")
    assert seen["insert"] == (f"{OWNER}@{HOME}", "system", "Owner O joined as the owner of B Proof Worker.",
                              "hjoin-12345678", True)
    assert seen["queued"] == 3 and seen["snapshot_sender"] == f"rem:{OWNER}@{HOME}"


def _home(monkeypatch, conv, parts, owner_of, announce_ok=True, fed_on=True):
    if fed_on:
        monkeypatch.setenv("CHAT_FEDERATION_ENABLED", "true")
    else:
        monkeypatch.delenv("CHAT_FEDERATION_ENABLED", raising=False)
    monkeypatch.setenv("PUBLIC_BASE_URL", HOME)
    from agentvault_registry.services import chat_federation as fed
    from agentvault_registry.services import chat_service as cs
    seen: dict = {"announce": [], "posted": []}

    class _Db:
        def __init__(self):
            self.added, self.commits = [], 0

        async def execute(self, stmt, params=None):
            return _R(parts)

        def add(self, o):
            self.added.append(o)

        async def flush(self):
            return None

        async def commit(self):
            self.commits += 1

    async def _none(*a, **k):
        return None

    async def _owners(db, dids):
        return {d: owner_of for d in dids}

    async def _announce(db, conv_, actor, household_of):
        seen["announce"].append((actor.developer_id, household_of))
        return announce_ok

    async def _post(db, conv_, row, joiner_pkey, display, agent_pkey, **kw):
        seen["posted"].append((joiner_pkey, agent_pkey, kw.get("local_actor") is not None))
    monkeypatch.setattr(cs, "_my_row", _none)
    monkeypatch.setattr(cs, "agent_owner_map", _owners)
    monkeypatch.setattr(fed, "announce_household_join", _announce, raising=False)
    monkeypatch.setattr(fed, "post_household_join", _post, raising=False)
    return cs, _Db(), seen


MIRROR = types.SimpleNamespace(id="mirror-1", kind="dm", host_registry=HOST, remote_ref="host-conv-1", org_id=None)


async def test_an_owner_is_seated_on_a_mirror_only_after_the_host_records_the_join(monkeypatch):
    parts = [types.SimpleNamespace(ptype="agent", agent_did=AGENT, developer_id=None, state="active"),
             types.SimpleNamespace(ptype="remote", agent_did=None, developer_id=None, state="active")]
    cs, db, seen = _home(monkeypatch, MIRROR, parts, owner_of=7)
    row = await cs.resolve_membership(db, MIRROR, cs.Actor("developer", developer_id=7, display_name="Owner O"),
                                      announce_ok=True)
    assert seen["announce"] == [(7, f"{AGENT}@{HOME}")] and row.developer_id == 7 and len(db.added) == 1
    assert db.commits == 1, "the seat the host recorded must not roll back with a read"


async def test_when_the_host_does_not_record_the_join_nobody_is_seated(monkeypatch):
    parts = [types.SimpleNamespace(ptype="agent", agent_did=AGENT, developer_id=None, state="active")]
    cs, db, seen = _home(monkeypatch, MIRROR, parts, owner_of=7, announce_ok=False)
    with pytest.raises(cs.ChatError) as e:
        await cs.resolve_membership(db, MIRROR, cs.Actor("developer", developer_id=7, display_name="Owner O"),
                                    announce_ok=True)
    assert e.value.status_code == 502 and db.added == []


async def test_an_agent_does_not_household_join_a_mirror(monkeypatch):
    parts = [types.SimpleNamespace(ptype="developer", agent_did=None, developer_id=7, state="active")]
    cs, db, seen = _home(monkeypatch, MIRROR, parts, owner_of=7)
    with pytest.raises(cs.ChatError) as e:
        await cs.resolve_membership(db, MIRROR, cs.Actor("agent", agent_did="did:theprotocol:sandbox-b.test:sib",
                                                         display_name="Sib"))
    assert e.value.status_code == 403 and seen["announce"] == [] and db.added == []


async def test_the_hosts_own_owner_joining_a_federated_thread_is_shown(monkeypatch):
    hosted = types.SimpleNamespace(id="host-conv-1", kind="dm", host_registry=None, org_id=None)
    local_agent = "did:theprotocol:sandbox-a.test:assay"
    parts = [types.SimpleNamespace(ptype="agent", agent_did=local_agent, developer_id=None, state="active"),
             types.SimpleNamespace(ptype="remote", agent_did=None, developer_id=None, state="active")]
    cs, db, seen = _home(monkeypatch, hosted, parts, owner_of=3)
    await cs.resolve_membership(db, hosted, cs.Actor("developer", developer_id=3, display_name="Host Owner"),
                                announce_ok=True)
    assert seen["posted"] == [("dev:3", f"agt:{local_agent}", True)] and seen["announce"] == []


async def test_control_a_local_thread_seats_its_owner_silently_as_before(monkeypatch):
    local = types.SimpleNamespace(id="c-local", kind="dm", host_registry=None, org_id=None)
    parts = [types.SimpleNamespace(ptype="agent", agent_did="did:theprotocol:x", developer_id=None, state="active"),
             types.SimpleNamespace(ptype="agent", agent_did="did:theprotocol:y", developer_id=None, state="active")]
    cs, db, seen = _home(monkeypatch, local, parts, owner_of=3)
    row = await cs.resolve_membership(db, local, cs.Actor("developer", developer_id=3, display_name="Owner"))
    assert row.developer_id == 3 and seen["posted"] == [] and seen["announce"] == [] and db.commits == 0


async def test_the_join_row_is_recorded_like_a_relay_before_it_is_asked_for(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", HOME)
    from agentvault_registry.services import chat_federation as fed
    from agentvault_registry.services import chat_service as cs
    order: list = []

    class _Db:
        async def execute(self, stmt, params=None):
            return _R((OWNER,))

    async def _record(host, ref_conv, client_ref, sender_key):
        order.append(("record", host, ref_conv, client_ref, sender_key))

    async def _announce(host, ref_conv, pkey, state, **join):
        order.append(("announce", state, pkey, join.get("household_of"), join.get("client_ref")))
        return True
    monkeypatch.setattr(fed, "_record_relay", _record)
    monkeypatch.setattr(fed, "announce_state_to_host", _announce)
    ok = await fed.announce_household_join(_Db(), MIRROR, cs.Actor("developer", developer_id=7, display_name="O"),
                                           f"{AGENT}@{HOME}")
    assert ok and [o[0] for o in order] == ["record", "announce"]
    assert order[0][3] == order[1][4] and order[1][1:4] == ("join", f"{OWNER}@{HOME}", f"{AGENT}@{HOME}")


def test_a_remote_counterparty_carries_its_address():
    from agentvault_registry.services import chat_service as cs
    remote = types.SimpleNamespace(ptype="remote", developer_id=None, agent_did=None, remote_key=f"{AGENT}@{HOME}")
    local = types.SimpleNamespace(ptype="agent", developer_id=None, agent_did="did:theprotocol:x", remote_key=None)
    assert cs.counterparty_fields(remote)["remote_key"] == f"{AGENT}@{HOME}"
    assert cs.counterparty_fields(local) == {"ptype": "agent", "developer_id": None, "agent_did": "did:theprotocol:x",
                                             "remote_key": None}
