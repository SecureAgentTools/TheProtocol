"""V0664 (order gwo_874694de65551c5c1488641c, his four approved suggestions): a sender sees when the cross-frame relay limit holds a
message back.

The limit is the HOST's (fed.FED_RL: relay_thread, relay_peer, relay_agent_thread): a resident's relay-send past it answered 429 with
no word of how long, and the resident passed the refusal on as a sentence with no number. The console cannot say "sends in about N s"
without one, so the number now travels where the client already looks for it (a 429's Retry-After header, read as retryAfterS):
the host takes it from the limit's own counter (the seconds left of the window), the resident passes it through, and the chat error
answer carries it as the header. No new route.
"""
from __future__ import annotations

import types

import pytest
from fastapi import HTTPException

HOST = "https://sandbox-a.test"
HOME = "https://sandbox-b.test"
PEER = "spiffe://sandbox-b.test/service/registry"


class _Resp:
    def __init__(self, code, body, headers=None):
        self.status_code, self._body, self.text, self.headers = code, body, str(body), dict(headers or {})

    def json(self):
        return self._body


def _wire_http(monkeypatch, outcome):
    class _Client:
        def __init__(self, **cfg):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def aclose(self):
            return None

        async def post(self, url, headers=None, json=None):
            return outcome

    async def _peer(db, url):
        return "https://peer-internal-mtls:8443"
    from agentvault_registry.routers import guild
    import httpx
    monkeypatch.setattr(guild, "_resolve_peer_url", _peer)
    monkeypatch.setattr(guild, "_fed_client_config", lambda t: ({"timeout": 15.0, "cert": ("svid.pem", "svid.key")}, {"X-Federation-Secret": "s"}))
    monkeypatch.setattr(httpx, "AsyncClient", _Client)


@pytest.fixture(autouse=True)
def _no_pooled_fake():
    """peer_client pools one client per peer; a fake of this file must not stay in it for the next file's test (it is closed there)."""
    from agentvault_registry.services import chat_federation as fed
    fed._POOL.clear()
    yield
    fed._POOL.clear()


class _FakeRedis:
    def __init__(self, ttl):
        self._ttl = ttl
        self.asked = []

    async def ttl(self, key):
        self.asked.append(key)
        return self._ttl


# ── the limit's own wait ──────────────────────────────────────────────────────────────────────────────────────────
async def test_the_wait_is_the_seconds_left_of_the_limits_own_window(monkeypatch):
    from agentvault_registry.background_tasks import leader
    from agentvault_registry.services import chat_federation as fed

    async def _get_redis():
        return fake
    monkeypatch.setattr(leader, "get_redis", _get_redis)
    fake = _FakeRedis(17)
    assert await fed.fed_rate_wait("relay_thread", "c-1") == 17
    assert fake.asked == ["chat:rl:fed:relay_thread:c-1"]                     # the key fed_rate_ok counts under
    fake._ttl = -1                                                           # no expiry set (or no key): the window itself, the bound
    assert await fed.fed_rate_wait("relay_thread", "c-1") == fed.FED_RL["relay_thread"][1]
    fake._ttl = 500
    assert await fed.fed_rate_wait("relay_thread", "c-1") == fed.FED_RL["relay_thread"][1]   # never longer than the window


async def test_without_redis_the_wait_is_the_window(monkeypatch):
    from agentvault_registry.background_tasks import leader
    from agentvault_registry.services import chat_federation as fed

    async def _none():
        return None
    monkeypatch.setattr(leader, "get_redis", _none)
    assert await fed.fed_rate_wait("relay_peer", HOME) == fed.FED_RL["relay_peer"][1]


# ── the host says it ──────────────────────────────────────────────────────────────────────────────────────────────
async def test_the_hosts_429_carries_how_long_to_wait(monkeypatch):
    from agentvault_registry.routers import chat_federation as route
    from agentvault_registry.services import chat_federation as fed
    monkeypatch.setattr(fed, "federation_enabled", lambda: True)

    async def _peer_ok(db, base):
        return base
    monkeypatch.setattr(fed, "assert_peer_allowed", _peer_ok)

    async def _gate(kind, *parts):
        return kind != "relay_thread"                                         # the per-thread cap is the one that is spent

    async def _wait(kind, *parts):
        return {"relay_thread": 17, "relay_peer": 3}[kind]
    monkeypatch.setattr(fed, "fed_rate_ok", _gate)
    monkeypatch.setattr(fed, "fed_rate_wait", _wait)
    req = route.RelaySend(conversation_ref="c-1", sender_key=f"bob@{HOME}", client_ref="ref-12345678", body="hi")
    with pytest.raises(HTTPException) as e:
        await route.relay_send(req, peer=PEER, db=None)
    assert e.value.status_code == 429
    assert e.value.headers == {"Retry-After": "17"}                          # the cap that was spent, not another


async def test_the_longest_spent_cap_sets_the_wait(monkeypatch):
    from agentvault_registry.routers import chat_federation as route
    from agentvault_registry.services import chat_federation as fed
    monkeypatch.setattr(fed, "federation_enabled", lambda: True)

    async def _peer_ok(db, base):
        return base
    monkeypatch.setattr(fed, "assert_peer_allowed", _peer_ok)

    async def _gate(kind, *parts):
        return False                                                         # every cap spent

    async def _wait(kind, *parts):
        return {"relay_thread": 17, "relay_peer": 44, "relay_agent_thread": 9}[kind]
    monkeypatch.setattr(fed, "fed_rate_ok", _gate)
    monkeypatch.setattr(fed, "fed_rate_wait", _wait)
    req = route.RelaySend(conversation_ref="c-1", sender_key=f"did:theprotocol:x:1@{HOME}", client_ref="ref-12345678", body="hi")
    with pytest.raises(HTTPException) as e:
        await route.relay_send(req, peer=PEER, db=None)
    assert e.value.headers == {"Retry-After": "44"}                          # waiting less would only be refused again


# ── the resident passes it on ─────────────────────────────────────────────────────────────────────────────────────
async def test_the_resident_passes_the_hosts_wait_on_and_still_says_nothing_was_sent(monkeypatch):
    from agentvault_registry.services import chat_federation as fed
    from agentvault_registry.services import chat_service as cs
    _wire_http(monkeypatch, _Resp(429, {"detail": "this thread's cross-registry message rate is capped; slow down"}, {"retry-after": "17"}))
    conv = types.SimpleNamespace(id="mirror-1", host_registry=HOST, remote_ref="c-1")
    with pytest.raises(cs.ChatError) as e:
        await fed.relay_to_host(None, conv, f"bob@{HOME}", "Bob", "text", "x", None, "ref-12345678")
    assert e.value.status_code == 429 and e.value.retry_after_s == 17
    assert "NOT sent" in e.value.detail and "capped" in e.value.detail


async def test_a_429_without_a_wait_says_so_by_none_not_by_a_guess(monkeypatch):
    from agentvault_registry.services import chat_federation as fed
    from agentvault_registry.services import chat_service as cs
    _wire_http(monkeypatch, _Resp(429, {"detail": "slow down"}))
    conv = types.SimpleNamespace(id="mirror-1", host_registry=HOST, remote_ref="c-1")
    with pytest.raises(cs.ChatError) as e:
        await fed.relay_to_host(None, conv, f"bob@{HOME}", "Bob", "text", "x", None, "ref-12345678")
    assert e.value.status_code == 429 and e.value.retry_after_s is None      # an older host: the console falls back, the server invents nothing


async def test_another_refusal_carries_no_wait(monkeypatch):
    from agentvault_registry.services import chat_federation as fed
    from agentvault_registry.services import chat_service as cs
    _wire_http(monkeypatch, _Resp(403, {"detail": "no"}, {"retry-after": "9"}))
    conv = types.SimpleNamespace(id="mirror-1", host_registry=HOST, remote_ref="c-1")
    with pytest.raises(cs.ChatError) as e:
        await fed.relay_to_host(None, conv, f"bob@{HOME}", "Bob", "text", "x", None, "ref-12345678")
    assert e.value.status_code == 403 and e.value.retry_after_s is None      # only a limit has a wait


def test_a_chat_error_has_no_wait_unless_one_is_given():
    from agentvault_registry.services import chat_service as cs
    assert cs.ChatError(409, "x").retry_after_s is None
    assert cs.ChatError(429, "x", retry_after_s=5).retry_after_s == 5


# ── the answer carries it ─────────────────────────────────────────────────────────────────────────────────────────
async def test_the_chat_error_answer_carries_the_wait_as_retry_after():
    from agentvault_registry.routers import chat as R
    from agentvault_registry.services import chat_service as cs

    @R.chat_errors
    async def held():
        raise cs.ChatError(429, "held", retry_after_s=17)

    @R.chat_errors
    async def plain():
        raise cs.ChatError(409, "no")
    with pytest.raises(HTTPException) as e:
        await held()
    assert e.value.status_code == 429 and e.value.headers == {"Retry-After": "17"}
    with pytest.raises(HTTPException) as e:
        await plain()
    assert not e.value.headers                                               # nothing else changes
