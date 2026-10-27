"""D6-555 (2026-10-16): the chat rate gates never fail open.

chat_service._rate_gate counted in Redis and answered "allowed" whenever Redis could not count: no Redis configured,
or any Redis error. Every chat limit (60 messages a minute, 20 new stranger threads a day, one ping per thread per ten
minutes and 30 a day, the federated create and relay limits) rode on it, so a Redis outage lifted all of them at once.
Now a gate that cannot count in Redis counts in the worker, with the same limit and window. Each case marked BASE fails
on 7140a4a6.

Through FastAPI on the real ping route (POST /api/v1/chat/conversations/{id}/ping), whose two gates are _rate_gate;
only the database rows, the message write behind the ping and the caller's token are replaced, and Redis is absent,
failing, or a working stand-in.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.background_tasks import leader
from agentvault_registry.database import get_db
from agentvault_registry.errors import register_error_handlers
from agentvault_registry.routers import chat
from agentvault_registry.security import get_current_actor_for_read
from agentvault_registry.services import chat_service as cs


class _Session:
    async def execute(self, stmt, params=None):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: None))   # no row still pending

    async def commit(self):
        pass

    async def rollback(self):
        pass


class _Redis:
    """A working Redis for the shared count (the control)."""

    def __init__(self):
        self.n = {}

    async def incr(self, k):
        self.n[k] = self.n.get(k, 0) + 1
        return self.n[k]

    async def expire(self, k, s):
        return True

    async def decr(self, k):
        self.n[k] = self.n.get(k, 0) - 1
        return self.n[k]


class _BrokenRedis(_Redis):
    async def incr(self, k):
        raise ConnectionError("Redis went away")


@pytest.fixture()
def ping(monkeypatch):
    if hasattr(cs, "_LOCAL_RL"):
        monkeypatch.setattr(cs, "_LOCAL_RL", {})

    async def _conv(db, cid):
        return SimpleNamespace(id=cid, kind="dm", host_registry=None)

    async def _member(db, conv, actor, **k):
        return SimpleNamespace(state="active")

    async def _sent(db, conv, my_row, actor, kind, body, card, client_ref, **k):
        return {"seq": 1, "kind": kind, "body": body}
    monkeypatch.setattr(cs, "_get_conversation", _conv)
    monkeypatch.setattr(cs, "resolve_membership", _member)
    monkeypatch.setattr(chat, "_send_and_fan_out", _sent)

    def run(redis, times=2):
        async def _get_redis():
            return redis
        monkeypatch.setattr(leader, "get_redis", _get_redis)
        app = FastAPI()
        register_error_handlers(app)
        app.include_router(chat.router)
        app.dependency_overrides[get_db] = lambda: _Session()
        app.dependency_overrides[get_current_actor_for_read] = lambda: {
            "kind": "developer", "developer": SimpleNamespace(id=5, name="Knocker", email="k@example.test")}
        c = TestClient(app, raise_server_exceptions=False)
        return [c.post("/api/v1/chat/conversations/conv-1/ping", json={"client_ref": f"ping-ref-{i:04d}"}).status_code
                for i in range(times)]
    return run


def test_a_working_redis_counts_the_pings(ping):
    assert ping(_Redis()) == [201, 429]          # control: one ping per thread per ten minutes


def test_no_redis_still_counts(ping):
    assert ping(None) == [201, 429]              # BASE: [201, 201] (no Redis: every ping allowed)


def test_a_failing_redis_still_counts(ping):
    assert ping(_BrokenRedis()) == [201, 429]    # BASE: [201, 201] (a Redis error: every ping allowed)


async def test_a_refused_action_gives_its_count_back_without_redis(monkeypatch):
    monkeypatch.setattr(cs, "_LOCAL_RL", {})

    async def _none():
        return None
    monkeypatch.setattr(leader, "get_redis", _none)
    assert await cs._rate_gate("msg:dev:9", 1, 60) is True
    await cs._rate_peek_release("msg:dev:9")     # the action it counted was refused after all
    assert await cs._rate_gate("msg:dev:9", 1, 60) is True
    assert await cs._rate_gate("msg:dev:9", 1, 60) is False


def test_the_worker_count_is_bounded_and_refuses_what_it_cannot_count(monkeypatch):
    monkeypatch.setattr(cs, "_LOCAL_RL", {})
    monkeypatch.setattr(cs, "_LOCAL_RL_MAX_KEYS", 2)
    assert cs._local_rate_gate("chat:rl:a", 5, 60) and cs._local_rate_gate("chat:rl:b", 5, 60)
    assert cs._local_rate_gate("chat:rl:c", 5, 60) is False      # no room left: refused, never uncounted
    assert cs._local_rate_gate("chat:rl:a", 5, 60) is True       # a key it holds is still counted
