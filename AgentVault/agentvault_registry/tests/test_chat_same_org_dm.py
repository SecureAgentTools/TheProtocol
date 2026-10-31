"""V0650 (c) (2026-10-31, agentvault2-14): direct messages inside one organization skip the Requests lane.

Order gwo_95c24b32469138f362237977. A first direct message between two principals of one live organization (an active
organization_members row for a developer, agents.organization_id for an agent; the organization itself active) opens
with the other side ACTIVE, as a household's does: no stranger budget, no contact policy. Everything else stays: blocks
keep both their answers (the blocker is refused, a blocked sender gets the silent 'left' row), cross-org and org-less
principals still knock. RED on 6c1f036b (V0649): every case but the controls.

The real chat_service.create_conversation, on a fake database that answers each read by a needle in its SQL.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agentvault_registry.services import chat_service as cs

X = "did:theprotocol:eu.theprotocol.cloud:00000000-0000-4000-8000-00000000000x"
Y = "did:theprotocol:eu.theprotocol.cloud:00000000-0000-4000-8000-00000000000y"
Z = "did:theprotocol:eu.theprotocol.cloud:00000000-0000-4000-8000-00000000000z"


class _R:
    def __init__(self, rows):
        self.rows = list(rows)

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return list(self.rows)

    def scalars(self):
        return self

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class _Db:
    """world = {"dev_orgs": {dev: [org]}, "agent_org": {did: org}, "owners": {did: dev}, "active_orgs": {org},
    "blocks": [(blocker_ptype, blocker_id, blocked_ptype, blocked_id)]}"""

    def __init__(self, world):
        self.w = world
        self.added, self.sql = [], []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.sql.append(sql)
        p = dict(params or {})
        if "SELECT 1 FROM developers" in sql:
            return _R([(1,)])
        if "SELECT did, status, creator_developer_id FROM agents" in sql:
            d = p["d"].lower()
            return _R([(d, "active", self.w["owners"].get(d))])
        if "SELECT did, creator_developer_id FROM agents" in sql:
            return _R([(d, self.w["owners"].get(d)) for d in p["d"]])
        if "FROM chat_blocks" in sql:
            return _R([SimpleNamespace(blocker_ptype=a, blocker_id=b, blocked_ptype=c, blocked_id=e)
                       for a, b, c, e in self.w.get("blocks", [])])
        if "FROM conversations" in sql:
            return _R([])
        if "SELECT organization_id FROM organization_members" in sql:
            return _R([(o,) for o in self.w.get("dev_orgs", {}).get(int(p["d"]), [])])
        if "SELECT organization_id FROM agents" in sql:
            org = self.w.get("agent_org", {}).get(p["d"].lower())
            return _R([(org,)] if org else [(None,)])
        if "SELECT id FROM organizations" in sql:
            return _R([(i,) for i in p["ids"] if i in self.w.get("active_orgs", set())][:1])
        return _R([])          # the contact policy read and anything else: nothing declared

    def add(self, obj):
        self.added.append(obj)

    def add_all(self, objs):
        self.added.extend(objs)

    async def flush(self):
        for o in self.added:
            if getattr(o, "id", None) is None and type(o).__name__ == "Conversation":
                o.id = "conv-new"

    async def commit(self):
        return None

    async def rollback(self):
        return None


@pytest.fixture()
def gates(monkeypatch):
    spent = []

    async def _gate(key, limit, window):
        spent.append(key)
        return True
    monkeypatch.setattr(cs, "_rate_gate", _gate)
    return spent


def _dev(i):
    return cs.Actor("developer", developer_id=i, display_name=f"dev{i}")


def _agent(did):
    return cs.Actor("agent", agent_did=did, display_name="agent")


def _open(db, actor, ptype, target):
    conv, created, mine = asyncio.run(cs.create_conversation(db, actor, "dm", ptype, str(target)))
    theirs = [o for o in db.added if type(o).__name__ == "ConversationParticipant" and o.role == "member"]
    return created, mine, theirs[0] if theirs else None


ONE_ORG = {"active_orgs": {"org-1"}}


def test_two_members_of_one_org_open_active_without_the_stranger_gate(gates):
    # BASE: pending, stranger gate spent
    db = _Db({**ONE_ORG, "dev_orgs": {7: ["org-1"], 8: ["org-1"]}})
    created, _mine, theirs = _open(db, _dev(7), "developer", 8)
    assert created and theirs.state == "active"
    assert not [k for k in gates if k.startswith("stranger:")]
    assert not any("SELECT contact_policy" in q for q in db.sql), "a colleague does not meet the contact policy"


@pytest.mark.parametrize("direction", ["agent_to_member", "member_to_agent"])
def test_an_org_agent_and_an_org_member_open_active(gates, direction):
    # BASE: pending
    db = _Db({**ONE_ORG, "dev_orgs": {8: ["org-1"]}, "agent_org": {X.lower(): "org-1"}, "owners": {X.lower(): 9}})
    if direction == "agent_to_member":
        _, _, theirs = _open(db, _agent(X), "developer", 8)
    else:
        _, _, theirs = _open(db, _dev(8), "agent", X)
    assert theirs.state == "active" and not [k for k in gates if k.startswith("stranger:")]


def test_two_agents_of_one_org_with_different_owners_open_active(gates):
    # BASE: pending
    db = _Db({**ONE_ORG, "agent_org": {X.lower(): "org-1", Y.lower(): "org-1"}, "owners": {X.lower(): 9, Y.lower(): 10}})
    _, _, theirs = _open(db, _agent(X), "agent", Y)
    assert theirs.state == "active" and not gates


def test_shared_org_id_reads_the_live_rows_and_never_asks_for_a_remote_key():
    # BASE: AttributeError (no shared_org_id)
    world = {**ONE_ORG, "dev_orgs": {7: ["org-1"], 8: ["org-1"], 5: ["org-2"]}, "agent_org": {X.lower(): "org-1"}}
    db = _Db(world)
    assert asyncio.run(cs.shared_org_id(db, "dev:7", "dev:8")) == "org-1"
    assert asyncio.run(cs.shared_org_id(db, "dev:7", f"agt:{X.lower()}")) == "org-1"
    assert asyncio.run(cs.shared_org_id(db, f"agt:{X.lower()}", f"agt:{X.lower()}")) == "org-1"
    remote = _Db(world)
    assert asyncio.run(cs.shared_org_id(remote, "dev:7", "rem:mira@https://asia.example")) is None
    assert remote.sql == [], "a principal on another registry belongs to no organization here"
    disjoint = _Db(world)
    assert asyncio.run(cs.shared_org_id(disjoint, "dev:7", "dev:5")) is None
    assert not any("FROM organizations" in q for q in disjoint.sql)
    assert any("is_active = true" in q and "organization_members" in q for q in db.sql)
    assert any("is_active = true" in q and "FROM organizations" in q for q in db.sql)


@pytest.mark.parametrize("pair", ["developers", "agents"])
def test_different_orgs_still_knock(gates, pair):
    # control: pending and one stranger gate on both trees
    db = _Db({"active_orgs": {"org-1", "org-2"}, "dev_orgs": {7: ["org-1"], 8: ["org-2"]},
              "agent_org": {X.lower(): "org-1", Z.lower(): "org-2"}, "owners": {X.lower(): 9, Z.lower(): 10}})
    if pair == "developers":
        _, _, theirs = _open(db, _dev(7), "developer", 8)
        assert gates == ["stranger:dev:7"]
    else:
        _, _, theirs = _open(db, _agent(X), "agent", Z)
        assert gates == [f"stranger:agt:{X.lower()}"]
    assert theirs.state == "pending"


def test_no_organization_at_all_still_knocks(gates):
    # control
    db = _Db({})
    _, _, theirs = _open(db, _dev(7), "developer", 8)
    assert theirs.state == "pending" and gates == ["stranger:dev:7"]


def test_a_closed_organization_does_not_make_colleagues(gates):
    # control: both in org-1, but org-1 is no longer active
    db = _Db({"active_orgs": set(), "dev_orgs": {7: ["org-1"], 8: ["org-1"]}})
    _, _, theirs = _open(db, _dev(7), "developer", 8)
    assert theirs.state == "pending" and gates == ["stranger:dev:7"]


def test_a_colleague_who_blocks_you_still_meets_the_silent_void(gates):
    # control: the target blocks the sender: a 'left' row, a normal-looking thread for the sender
    db = _Db({**ONE_ORG, "dev_orgs": {7: ["org-1"], 8: ["org-1"]},
              "blocks": [("developer", "8", "developer", "7")]})
    _, mine, theirs = _open(db, _dev(7), "developer", 8)
    assert theirs.state == "left" and mine.state == "active" and not gates


def test_you_cannot_message_a_colleague_you_blocked(gates):
    # control
    db = _Db({**ONE_ORG, "dev_orgs": {7: ["org-1"], 8: ["org-1"]},
              "blocks": [("developer", "7", "developer", "8")]})
    with pytest.raises(cs.ChatError) as e:
        _open(db, _dev(7), "developer", 8)
    assert e.value.status_code == 403 and "you have blocked" in e.value.detail and not db.added
