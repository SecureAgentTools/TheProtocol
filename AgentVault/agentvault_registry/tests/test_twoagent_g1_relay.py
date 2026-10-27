"""§TWOAGENT G1 step 1 (2026-09-23) — the first cross-registry chat round trip: a resident's reply reaches the host.

The G1 survey (scratchpad/twoagent/MAP_G1_chat_federation.md) found federated OurChat one-way:
  * a RESIDENT's post into a mirrored thread was stored in its own mirror only; `relay-send` existed at the host and
    nothing called it, so the other side never saw a reply;
  * the host stamped EVERY sender with its own registry, so a resident's relayed message came back to its home as
    `handle@B@A`, a stranger wearing its own developer's name (a message loop for an agent that answers automatically);
  * the host dialled the peer's PUBLIC 443 form with a licence or the internal secret, which the console vhosts clear
    or refuse, so the delivery leg had no credential that could land.
Now the resident's post goes to the host (`relay_to_host`, nothing stored locally, an honest 502 when the host cannot
take it), the envelope states each sender with ITS registry, the resident maps its own developer back to itself, and
both legs dial through the mTLS federation client every other peer rail uses. Step 1 is developers only.

RED on V0431 (539b49f8): every test but the controls.
"""
from __future__ import annotations

import asyncio
import types

import pytest

HOST = "https://sandbox-a.test"
HOME = "https://sandbox-b.test"


class _Resp:
    def __init__(self, code, body):
        self.status_code, self._body, self.text = code, body, str(body)

    def json(self):
        return self._body


def _wire_http(monkeypatch, outcome):
    seen: dict = {}

    class _Client:
        def __init__(self, **cfg):
            seen["cfg"] = cfg

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            seen.update(url=url, headers=dict(headers or {}), json=json)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    async def _peer(db, url):
        return "https://peer-internal-mtls:8443"
    from agentvault_registry.routers import guild
    import httpx
    monkeypatch.setattr(guild, "_resolve_peer_url", _peer)
    monkeypatch.setattr(guild, "_fed_client_config",
                        lambda t: ({"timeout": 15.0, "cert": ("svid.pem", "svid.key")},
                                   {"X-Federation-Secret": "s", "X-Federation-SPIFFE-ID": "spiffe://x/service/registry"}))
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    return seen


# ─────────────────────────────── the envelope ───────────────────────────────

def test_a_relayed_residents_message_goes_out_with_its_own_registry(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", HOST)
    from agentvault_registry.services import chat_federation as fed
    msg = types.SimpleNamespace(id="m1", seq=3, kind="text", body="hi", card=None, client_ref="c1", created_at=None,
                                sender_ptype="remote", sender_id=f"bob@{HOME}")
    conv = types.SimpleNamespace(id="c-1", kind="dm", title=None)
    env = fed.message_envelope(conv, msg, "Bob", [])
    assert env["message"]["sender"]["id"] == "bob" and env["message"]["sender"]["registry"] == HOME


def test_control_a_local_sender_is_stamped_with_this_registry(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", HOST)
    from agentvault_registry.services import chat_federation as fed
    msg = types.SimpleNamespace(id="m1", seq=3, kind="text", body="hi", card=None, client_ref="c1", created_at=None,
                                sender_ptype="developer", sender_id="42")
    env = fed.message_envelope(types.SimpleNamespace(id="c-1", kind="dm", title=None), msg, "Alice", [])
    assert env["message"]["sender"]["id"] == "42" and env["message"]["sender"]["registry"] == HOST


# ─────────────────────────────── the transport ───────────────────────────────

async def test_the_host_delivers_over_the_federation_mtls_client(monkeypatch):
    from agentvault_registry.services import chat_federation as fed
    seen = _wire_http(monkeypatch, _Resp(200, {"ok": True}))
    row = types.SimpleNamespace(peer_base_url=HOME, payload={"v": 1})
    ok, detail = await fed.deliver_one(row, db=object())
    assert ok, detail
    assert seen["url"] == "https://peer-internal-mtls:8443/api/v1/federation/chat/deliver"
    assert seen["cfg"].get("cert") and "X-Federation-Secret" not in seen["headers"]


# ─────────────────────────────── the resident's send ───────────────────────────────

async def test_relay_to_host_posts_to_the_hosts_relay_send(monkeypatch):
    from agentvault_registry.services import chat_federation as fed
    seen = _wire_http(monkeypatch, _Resp(201, {"seq": 7, "duplicate": False}))
    conv = types.SimpleNamespace(id="mirror-1", host_registry=HOST, remote_ref="c-1")
    out = await fed.relay_to_host(None, conv, f"bob@{HOME}", "Bob", "text", "hello back", None, "ref-12345678")
    assert out["seq"] == 7 and seen["url"].endswith("/api/v1/federation/chat/relay-send")
    assert seen["json"]["conversation_ref"] == "c-1" and seen["json"]["sender_key"] == f"bob@{HOME}"


async def test_a_host_that_cannot_take_it_is_an_honest_502(monkeypatch):
    from agentvault_registry.services import chat_federation as fed
    from agentvault_registry.services import chat_service as cs
    conv = types.SimpleNamespace(id="mirror-1", host_registry=HOST, remote_ref="c-1")
    _wire_http(monkeypatch, ConnectionError("down"))
    with pytest.raises(cs.ChatError) as e:
        await fed.relay_to_host(None, conv, f"bob@{HOME}", "Bob", "text", "x", None, "ref-12345678")
    assert e.value.status_code == 502 and "NOT sent" in e.value.detail


class _Db:
    def __init__(self, handle="bob"):
        self.handle = handle

    async def execute(self, stmt, params=None):
        h = self.handle

        class _R:
            def first(self_inner):
                return (h,)
        return _R()


async def test_a_residents_post_in_a_mirror_goes_to_the_host_and_is_not_stored_here(monkeypatch):
    monkeypatch.setenv("CHAT_FEDERATION_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_BASE_URL", HOME)
    from agentvault_registry.routers import chat as chat_router
    from agentvault_registry.services import chat_federation as fed
    from agentvault_registry.services import chat_service as cs
    relayed: list = []

    async def _relay(db, conv, sender_key, sender_display, kind, body, card, client_ref):
        relayed.append((conv.remote_ref, sender_key, body, client_ref))
        return {"seq": 9, "duplicate": False}

    async def _no_insert(*a, **k):
        raise AssertionError("a mirror must not store the resident's message before the host assigns its seq")

    async def _gate(*a, **k):
        return True
    monkeypatch.setattr(fed, "relay_to_host", _relay, raising=False)
    monkeypatch.setattr(cs, "insert_message", _no_insert)
    monkeypatch.setattr(cs, "_rate_gate", _gate)
    conv = types.SimpleNamespace(id="mirror-1", kind="dm", host_registry=HOST, remote_ref="c-1")
    actor = cs.Actor("developer", developer_id=11, display_name="Bob")
    out = await chat_router._send_and_fan_out(_Db(), conv, types.SimpleNamespace(state="active"), actor, "text",
                                              "hello back", None, "ref-12345678")
    assert relayed == [("c-1", f"bob@{HOME}", "hello back", "ref-12345678")]
    assert out["relayed"] is True and out["host_seq"] == 9


async def test_step_2_an_agent_relays_under_its_did_and_a_reply_is_the_accept(monkeypatch):
    """Step 1 refused an agent here (409); step 2 (V0433) lets it relay under `did@its.home`. A reply from a PENDING
    row is the accept (the row turns active and the host hears it); a LEFT row is still refused."""
    monkeypatch.setenv("CHAT_FEDERATION_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_BASE_URL", HOME)
    from agentvault_registry.routers import chat as chat_router
    from agentvault_registry.services import chat_federation as fed
    from agentvault_registry.services import chat_service as cs
    relayed, announced = [], []

    async def _relay(db, conv, sender_key, sender_display, kind, body, card, client_ref):
        relayed.append(sender_key)
        return {"seq": 3, "duplicate": False}

    async def _announce(host, remote_ref, key, state):
        announced.append((key, state))
        return True

    async def _gate(*a, **k):
        return True
    monkeypatch.setattr(fed, "relay_to_host", _relay, raising=False)
    monkeypatch.setattr(fed, "announce_state_to_host", _announce, raising=False)
    monkeypatch.setattr(cs, "_rate_gate", _gate)

    class _CommitDb:
        async def commit(self):
            return None
    did = "did:theprotocol:sandbox-b.test:assay"
    conv = types.SimpleNamespace(id="mirror-1", kind="dm", host_registry=HOST, remote_ref="c-1")
    row = types.SimpleNamespace(state="pending")
    out = await chat_router._send_and_fan_out(_CommitDb(), conv, row, cs.Actor("agent", agent_did=did, display_name="B"),
                                              "text", "hello from an agent", None, "ref-12345678")
    for _ in range(5):
        await asyncio.sleep(0)
    assert relayed == [f"{did}@{HOME}"] and out["relayed"] is True
    assert row.state == "active" and announced == [(f"{did}@{HOME}", "active")]
    with pytest.raises(cs.ChatError) as e:
        await chat_router._send_and_fan_out(_CommitDb(), conv, types.SimpleNamespace(state="left"),
                                            cs.Actor("agent", agent_did=did, display_name="B"), "text", "x", None,
                                            "ref-12345679")
    assert e.value.status_code == 409


# ─────────────────────────────── the resident's receive ───────────────────────────────

class _R:
    def __init__(self, rows):
        self.rows = list(rows)

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return list(self.rows)

    def scalars(self):
        return self

    def scalar_one(self):
        return self.rows[0][0]


class _ReceiveDb:
    def __init__(self):
        self.added = []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        if "FROM developers WHERE" in sql:
            return _R([(11,)])
        if "UPDATE conversations SET last_seq" in sql:
            return _R([(1,)])
        return _R([])

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None

    async def commit(self):
        return None

    async def rollback(self):
        return None


class _Redis:
    def __init__(self):
        self.kv = {}

    async def set(self, key, value, ex=None, nx=False):
        self.kv[key] = value
        return True

    async def get(self, key):
        return self.kv.get(key)


def _envelope(sender_id="bob", client_ref="ref-12345678"):
    return {"v": 1, "host_registry": HOST,
            "conversation": {"id": "c-1", "kind": "dm",
                             "participants": [{"key": f"bob@{HOME}"}, {"key": f"alice@{HOST}"}]},
            "message": {"seq": 2, "kind": "text", "body": "hello back", "client_ref": client_ref,
                        "sender": {"id": sender_id, "registry": HOME, "display_name": "Bob"}}}


def _wire_receive(monkeypatch, redis):
    monkeypatch.setenv("CHAT_FEDERATION_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_BASE_URL", HOME)
    from agentvault_registry.services import chat_federation as fed
    from agentvault_registry.services import contract_xframe
    from agentvault_registry.background_tasks import leader

    async def _allowed(db, base):
        return None

    async def _resolve(db, value):
        return "sandbox-a" if "sandbox-a" in str(value or "") else None

    async def _get_redis():
        return redis
    monkeypatch.setattr(fed, "assert_peer_allowed", _allowed)
    monkeypatch.setattr(contract_xframe, "resolve_peer_name", _resolve)
    monkeypatch.setattr(leader, "get_redis", _get_redis)
    return fed


async def _stored_sender(fed, env):
    from agentvault_registry.models import ChatMessage
    db = _ReceiveDb()
    await fed.receive_delivery(db, env, "spiffe://sandbox-a.test/service/registry")
    msgs = [o for o in db.added if isinstance(o, ChatMessage)]
    assert len(msgs) == 1
    return msgs[0].sender_ptype, msgs[0].sender_id


async def test_the_resident_maps_its_own_relayed_message_back_to_its_developer(monkeypatch):
    redis = _Redis()
    fed = _wire_receive(monkeypatch, redis)
    await fed._record_relay(HOST, "c-1", "ref-12345678", f"bob@{HOME}")   # what relay_to_host writes before its POST
    assert await _stored_sender(fed, _envelope()) == ("developer", "11")


async def test_a_host_cannot_attribute_a_message_to_one_of_our_developers(monkeypatch):
    """Session A's review: without a relay record, 'our registry, dev:1' is a claim, and stays remote."""
    fed = _wire_receive(monkeypatch, _Redis())
    ptype, sid = await _stored_sender(fed, _envelope(sender_id="dev:1", client_ref="forged-000001"))
    assert ptype == "remote" and sid == f"dev:1@{HOME}"


async def test_a_record_for_another_sender_does_not_lend_its_attribution(monkeypatch):
    redis = _Redis()
    fed = _wire_receive(monkeypatch, redis)
    await fed._record_relay(HOST, "c-1", "ref-12345678", f"bob@{HOME}")
    ptype, _ = await _stored_sender(fed, _envelope(sender_id="dev:1"))    # same thread and client_ref, other sender
    assert ptype == "remote"


async def test_without_redis_an_echo_reads_as_remote_never_as_ours(monkeypatch):
    fed = _wire_receive(monkeypatch, None)
    ptype, _ = await _stored_sender(fed, _envelope())
    assert ptype == "remote"


async def test_the_relay_is_recorded_before_the_post_even_if_the_host_fails(monkeypatch):
    from agentvault_registry.services import chat_federation as fed
    from agentvault_registry.services import chat_service as cs
    from agentvault_registry.background_tasks import leader
    redis = _Redis()

    async def _get_redis():
        return redis
    monkeypatch.setattr(leader, "get_redis", _get_redis)
    _wire_http(monkeypatch, ConnectionError("down"))
    conv = types.SimpleNamespace(id="mirror-1", host_registry=HOST, remote_ref="c-1")
    with pytest.raises(cs.ChatError):
        await fed.relay_to_host(None, conv, f"bob@{HOME}", "Bob", "text", "x", None, "ref-12345678")
    assert redis.kv.get(fed._relay_record_key(HOST, "c-1", "ref-12345678")) == f"bob@{HOME}"
