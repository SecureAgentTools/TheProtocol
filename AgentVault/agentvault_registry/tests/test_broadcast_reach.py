"""§FESUITE V0595 (his "your recommendations" on the design calls, 2026-10-11): a broadcast's reach is its audience's
developers online at send, read from the presence keys (`presence:ws:<developer id>`, every worker's sockets), for its
developer, its organization's active members or everyone. It stored ws_manager.get_connection_count(), the connections on
the one gunicorn worker that served the POST (an org-scoped broadcast stored the same figure as one to everyone), and
the scheduled path stored none. Redis and the member table are fakes.
"""
import asyncio
from types import SimpleNamespace

from agentvault_registry.routers import admin_broadcast as ab


class _Redis:
    def __init__(self, present):
        self.keys = {f"presence:ws:{i}" for i in present}

    async def exists(self, *keys):
        return sum(1 for k in keys if k in self.keys)

    async def scan_iter(self, match=None, count=None):
        for k in sorted(self.keys) + ["presence:ws:did:theprotocol:agent1"]:   # an agent socket is not a developer
            yield k.encode()


class _Db:
    def __init__(self, member_ids):
        self.member_ids = member_ids

    async def execute(self, stmt):
        ids = self.member_ids
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: ids))


def _reach(monkeypatch, present, audience, exclude=None, members=()):
    async def redis():
        return _Redis(present)
    monkeypatch.setattr(ab.ws_manager, "_get_redis", redis)
    return asyncio.run(ab.live_reach(_Db(list(members)), audience, exclude))


def test_a_developer_audience_is_that_developer_online_or_not(monkeypatch):
    assert _reach(monkeypatch, ["7", "9"], "user_7") == 1
    assert _reach(monkeypatch, ["9"], "user_7") == 0


def test_an_organization_audience_counts_its_members_online(monkeypatch):
    assert _reach(monkeypatch, ["3", "4", "8"], "org_abc", members=[3, 4, 5]) == 2, "member 8 is not in the org"


def test_everyone_counts_every_developer_online_but_the_composer(monkeypatch):
    assert _reach(monkeypatch, ["1", "2", "3"], None) == 3, "an agent's socket is not a developer reached"
    assert _reach(monkeypatch, ["1", "2", "3"], None, exclude="2") == 2


def test_an_unreadable_presence_counts_nothing_never_a_stand_in(monkeypatch):
    async def none():
        return None
    monkeypatch.setattr(ab.ws_manager, "_get_redis", none)
    monkeypatch.setattr(ab.ws_manager, "get_connection_count", lambda: 41)   # the old stand-in must not leak in
    assert asyncio.run(ab.live_reach(_Db([]), None)) == 0
