"""§TWOAGENT (2026-09-23, on the way) — who may read an agent's grants, and what a suspended developer's grant conveys.

(a) `GET /agents/{did}/delegations` answered ANY developer about ANY agent: who delegated what to it, and until when.
    Its sibling `GET /agents/{did}/capabilities` was already owner-or-admin, the FE client documents both as
    "(owner/admin)", and the only FE callers (PocketApprovals, AgentAccessPanel) read the caller's own agents.
(b) A `dev:` principal's grant outlived that developer's suspension (and deletion) until its own expiry, while the
    liability clamp (PART 15) already treats a suspended human as conveying nothing on the next request.

RED on V0430: the list answers a stranger, and a suspended developer's grant still conveys. The controls (the owner
reads its agent's grants; a live developer's grant conveys; an org grant is untouched) pass on both trees.
"""
from __future__ import annotations

import collections
import types

import pytest
from fastapi import HTTPException

DEL = "did:theprotocol:asia.test:delegate"


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _Db:
    def __init__(self, handlers):
        self.handlers = handlers

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        for needle, rows in self.handlers:
            if needle in sql:
                return _Result(rows)
        return _Result([])


def _list_db():
    Owner = collections.namedtuple("Owner", ["creator_developer_id"])
    return _Db([("SELECT creator_developer_id FROM agents", [Owner(41)]),
                ("FROM agent_delegation_grants WHERE delegate_agent_did", [])])


async def test_a_stranger_cannot_read_an_agents_grants():
    from agentvault_registry.routers import agent_delegation_api as api
    with pytest.raises(HTTPException) as e:
        await api.list_delegations(DEL, current=types.SimpleNamespace(id=99, is_admin=False), db=_list_db())
    assert e.value.status_code == 403


async def test_control_the_owner_and_an_admin_can():
    from agentvault_registry.routers import agent_delegation_api as api
    assert (await api.list_delegations(DEL, current=types.SimpleNamespace(id=41, is_admin=False),
                                       db=_list_db()))["agent_did"] == DEL
    assert (await api.list_delegations(DEL, current=types.SimpleNamespace(id=1, is_admin=True),
                                       db=_list_db()))["agent_did"] == DEL


def _grant_db(ptype, pref, dev_row=None, org_linked=True):
    # D6-270: a dev: grant conveys only onto an agent that developer created, so the double now answers that read
    # too (the delegate is dev 41's own agent; tests/test_sec2_delegation_principals.py covers a stranger's agent).
    return _Db([("FROM agent_delegation_grants", [(["teg.transfer"], ptype, pref)]),
                ("FROM developers WHERE id", [dev_row] if dev_row else []),
                ("AND creator_developer_id = :dev", [(1,)]),
                ("FROM agents a JOIN organizations", [(1,)] if org_linked else [])])


async def _conveys(db, pref):
    from agentvault_registry.agent_authz import resolve_delegated_permissions
    return await resolve_delegated_permissions(db, DEL, pref)


async def test_a_suspended_developers_grant_conveys_nothing(monkeypatch):
    monkeypatch.setenv("AGENT_DELEGATION_MODE", "enforce")
    assert await _conveys(_grant_db("dev", "dev:41", (True, None, None)), "dev:41") == set()
    assert await _conveys(_grant_db("dev", "dev:41", (False, None, "pending_deletion")), "dev:41") == set()


async def test_control_a_live_developers_grant_conveys(monkeypatch):
    monkeypatch.setenv("AGENT_DELEGATION_MODE", "enforce")
    assert await _conveys(_grant_db("dev", "dev:41", (False, None, None)), "dev:41") == {"teg.transfer"}


async def test_control_an_org_grant_is_untouched(monkeypatch):
    monkeypatch.setenv("AGENT_DELEGATION_MODE", "enforce")
    assert await _conveys(_grant_db("org", "org:acme"), "org:acme") == {"teg.transfer"}
