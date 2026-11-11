"""V0660 (l): the call sites a user, a card or a peer can address go through the guard.

V0659 (p) built the guard and wired nothing. This holds the five httpx sites to it, and the web push
path to inspect_destination, with the list lead approved (room seq 2675) after the census.

No test here touches the network: socket.getaddrinfo answers from a table, and where a request would be
sent the connection layer is an httpx.MockTransport. Each site gets the pair the order asks for: an
INTERNAL destination is refused AT THAT SITE, and a PUBLIC one still passes, because a guard that refuses
everything is as broken as one that refuses nothing.
"""
from __future__ import annotations

import importlib
import socket

import httpx
import pytest

GUARD = "agentvault_registry.core.outbound_guard"

PUBLIC_V4 = "93.184.216.34"
DNS = {
    "card.example.com": [PUBLIC_V4],          # a public agent card host
    "agent.example.com": [PUBLIC_V4],
    "inside.example.com": ["10.1.2.3"],       # a card pointing at a private address
    "metadata.example.com": ["169.254.169.254"],
    "loopback.example.com": ["127.0.0.1"],
}
SANDBOX_ENV = ("SANDBOX_MODE", "CC_TARGET_ENVIRONMENT", "OUTBOUND_GUARD_SANDBOX_ALLOW_PRIVATE")


@pytest.fixture(autouse=True)
def dns(monkeypatch):
    """getaddrinfo answers from the table above; an unknown name is NXDOMAIN."""
    for k in SANDBOX_ENV:
        monkeypatch.delenv(k, raising=False)

    def getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        if host not in DNS:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        out = []
        for addr in DNS[host]:
            if ":" in addr:
                out.append((socket.AF_INET6, socket.SOCK_STREAM, 6, "", (addr, port or 0, 0, 0)))
            else:
                out.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, port or 0)))
        return out

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


class Upstream:
    """The connection layer: records what reaches it and answers 200, so a public fetch can succeed."""

    def __init__(self, body=None, status=200):
        self.seen = []
        self._body = body if body is not None else {"name": "Fetched", "protocolVersion": "1.0"}
        self._status = status
        self.transport = httpx.MockTransport(self)

    def __call__(self, request):
        self.seen.append(request)
        return httpx.Response(self._status, json=self._body)


def guard():
    return importlib.import_module(GUARD)


# ── 1. the agent card pull ───────────────────────────────────────────────────────────────────────────

class TestTheCardPull:
    async def test_a_card_pointing_inside_is_refused(self, monkeypatch):
        m = importlib.import_module("agentvault_registry.background_tasks.agent_card_pullsync")
        up = Upstream()
        g = guard()
        # m.guarded_client, not the guard's: the client is built through the name THIS MODULE resolved, so a
        # module that still builds its own has no such name and this test fails rather than passing on the
        # guard's behaviour alone (proven: 9 of 16 red on the unwired tree, this among them).
        async with m.guarded_client("agent_card_pull", inner=up.transport, timeout=5.0) as client:
            with pytest.raises(g.OutboundRefused) as e:
                await m.fetch_agent_card(client, "https://inside.example.com/.well-known/agent.json", {})
        assert e.value.site == "agent_card_pull"
        assert not up.seen, "nothing may reach the connection layer for a private address"

    async def test_a_public_card_still_fetches(self, monkeypatch):
        m = importlib.import_module("agentvault_registry.background_tasks.agent_card_pullsync")
        up = Upstream()
        async with m.guarded_client("agent_card_pull", inner=up.transport, timeout=5.0) as client:
            resp = await m.fetch_agent_card(client, "https://card.example.com/.well-known/agent.json", {})
        assert resp.status_code == 200
        assert len(up.seen) == 1, "the control must really have fetched"

    def test_the_module_builds_no_raw_client(self, monkeypatch):
        """The pull's clients (two of them) must be the guard's."""
        m = importlib.import_module("agentvault_registry.background_tasks.agent_card_pullsync")
        src = importlib.import_module("inspect").getsource(m)
        assert "guarded_client(" in src, "the pull still builds its own unguarded client"
        assert src.count("httpx.AsyncClient(") == 0, "a raw httpx.AsyncClient is left in the pull"


# ── 2. the health probe (the redirect-following one lead put first) ──────────────────────────────────

class TestTheHealthProbe:
    async def test_an_agent_declaring_an_internal_address_is_refused(self, monkeypatch):
        """⚠ the word the probe returns cannot tell a REFUSAL from a connection that simply failed: both end
        as `unreachable`. So the proof is the counter — a refusal is counted under this site, a dead
        connection is not — and the client is built through the name THIS MODULE resolved."""
        m = importlib.import_module("agentvault_registry.background_tasks.agent_health_checker")
        up = Upstream()
        g = guard()
        counter = _Counter()
        monkeypatch.setattr(g, "OUTBOUND_REFUSED_TOTAL", counter)
        async with m.guarded_client("agent_health", inner=up.transport, timeout=5.0) as client:
            health, detail = await m._probe_declared(client, "https://metadata.example.com/a2a")
        assert health in ("unreachable", "unhealthy"), f"a refused probe answered {health}"
        assert not up.seen, "nothing may reach the connection layer for a link-local address"
        assert {"site": "agent_health", "reason": "link_local"} in counter.seen, (
            f"the probe did not refuse: nothing was counted for this site ({counter.seen})")

    async def test_a_public_agent_still_probes_healthy(self, monkeypatch):
        m = importlib.import_module("agentvault_registry.background_tasks.agent_health_checker")
        up = Upstream()
        async with m.guarded_client("agent_health", inner=up.transport, timeout=5.0) as client:
            health, detail = await m._probe_declared(client, "https://agent.example.com/a2a")
        assert health == "healthy", f"the control answered {health} ({detail})"
        assert up.seen, "the control must really have probed"

    def test_the_probe_no_longer_asks_the_client_to_follow_redirects(self):
        """The guard refuses follow_redirects= outright, because an unchecked hop is the whole hole. The
        probe must ask for hops through fetch(max_redirects=n) instead."""
        m = importlib.import_module("agentvault_registry.background_tasks.agent_health_checker")
        src = importlib.import_module("inspect").getsource(m)
        assert "follow_redirects=True" not in src, "the probe still asks the client to follow hops unchecked"
        assert "guarded_client(" in src, "the health checker still builds its own unguarded client"


# ── 3. the eval runner ──────────────────────────────────────────────────────────────────────────────

class TestTheEvalRunner:
    def test_it_builds_a_guarded_client(self):
        m = importlib.import_module("agentvault_registry.background_tasks.eval_runner")
        src = importlib.import_module("inspect").getsource(m)
        assert "guarded_client(" in src, "the eval runner still posts to an agent endpoint unguarded"
        assert "httpx.AsyncClient(" not in src, "a raw httpx.AsyncClient is left in the eval runner"


# ── 4. the instruct post (the site my own census missed) ────────────────────────────────────────────

class TestTheInstructPost:
    def test_it_builds_a_guarded_client(self):
        m = importlib.import_module("agentvault_registry.routers.agent_channels")
        src = importlib.import_module("inspect").getsource(m)
        assert "guarded_client(" in src, "POST /agents/{did}/instruct still posts to the card's endpoint unguarded"
        assert "httpx.AsyncClient(" not in src, "a raw httpx.AsyncClient is left in agent_channels"


# ── 5. the buy call: the check resolved, then the client resolved again ─────────────────────────────

class TestTheBuyCall:
    def test_the_buy_call_is_handed_a_guarded_client(self):
        """assert_callable_endpoint resolves and approves; the client then resolved the name AGAIN and
        connected to whatever it got. The guard connects only to an address it checked, which closes that
        window rather than narrowing it.

        Written first as "service_purchase builds a guarded client", which was the wrong premise: the
        client is the CALLER's, and the caller must not hand it the shared settle client, because that
        one dials issuers and peers an operator set and the guard is explicitly not for those. So the
        guard belongs at the buy call in a2a_payment, for that one call, and that is what this holds."""
        caller = importlib.import_module("agentvault_registry.routers.a2a_payment")
        src = importlib.import_module("inspect").getsource(caller)
        assert "guarded_client(" in src, "the buy call still uses an unguarded client"
        assert 'guarded_client("service_buy"' in src, "the buy call's guarded client is not named for the site"
        assert "sp.call_agent(agent_client" in src, "call_agent is still handed the shared settle client"

    def test_the_settle_client_is_left_alone(self):
        """The control for the test above, and the reason the scope is narrow: guarding settlement would
        be a side effect of hardening a buy, so the shared client must still be the plain one."""
        caller = importlib.import_module("agentvault_registry.routers.a2a_payment")
        src = importlib.import_module("inspect").getsource(caller)
        assert "_settle_client = httpx.AsyncClient(" in src, "the settle client was changed by this order"

    def test_the_pre_check_is_kept(self):
        """The guard does not judge the scheme or embedded credentials, so assert_callable_endpoint earns
        its keep: https only, no credentials. Removing it would lose a rule the guard never had."""
        m = importlib.import_module("agentvault_registry.services.service_purchase")
        assert hasattr(m, "assert_callable_endpoint")
        with pytest.raises(m.UnsafeEndpoint):
            m.assert_callable_endpoint("http://card.example.com/a2a")
        with pytest.raises(m.UnsafeEndpoint):
            m.assert_callable_endpoint("https://user:pw@card.example.com/a2a")


# ── 6. web push: pywebpush is not httpx, so the guard is asked rather than used ─────────────────────

class TestWebPush:
    def test_a_stored_internal_target_is_skipped_before_send(self, monkeypatch):
        """The endpoint comes from the subscriber's browser, and the send is made by pywebpush, so the
        site asks inspect_destination what the guard would decide and skips rather than fetching."""
        m = importlib.import_module("agentvault_registry.background_tasks.push_notify")
        src = importlib.import_module("inspect").getsource(m)
        assert "inspect_destination" in src, "web push sends to a stored target without asking the guard"

    async def test_the_guard_can_answer_about_an_address_without_fetching(self):
        """The tool this site needs, proven to exist and to discriminate. It is a coroutine: it resolves,
        which is I/O, so it is awaited like any other lookup."""
        g = guard()
        inside = await g.inspect_destination("https://inside.example.com/p")
        public = await g.inspect_destination("https://card.example.com/p")
        assert inside.refusal is not None, "a private address must be refusable without fetching"
        assert public.refusal is None, "a public address must pass, or the check refuses everything"


# ── 7. one refusal series for a site whose two halves refuse in two places (V0660 (l)) ──────────────
# session-code signed this shape in the room (seq 2710): a public record_refusal rather than a second
# counter at the call site, so the webpush rail's registration half and its sender half are one series.

class _Counter:
    """Stands in for registry_outbound_refused_total: it records the label values, never a number."""

    def __init__(self) -> None:
        self.seen = []

    def labels(self, **kw):
        self.seen.append(kw)
        return self

    def inc(self, *_a, **_kw) -> None:
        pass


class _Row:
    """The fields the web push sender reads off a device registration."""

    def __init__(self, target):
        self.id = 4242
        self.target = target
        self.p256dh = "p"
        self.auth = "a"


class TestRecordRefusal:
    def test_the_labels_are_a_fixed_set(self, monkeypatch):
        """A metric label nobody chose is unbounded cardinality in production, so an unknown reason and a
        site that is not a site name raise instead of becoming a new label."""
        g = guard()
        counter = _Counter()
        monkeypatch.setattr(g, "OUTBOUND_REFUSED_TOTAL", counter)
        for reason in g.REASONS:                       # every class the guard itself raises is recordable
            g.record_refusal("webpush", reason)
        assert [s["reason"] for s in counter.seen] == list(g.REASONS)
        with pytest.raises(ValueError):
            g.record_refusal("webpush", "endpoint_looks_wrong")
        with pytest.raises(ValueError):
            g.record_refusal("Web Push!", "loopback")
        assert len(counter.seen) == len(g.REASONS), "a refused call must not reach the counter either"

    async def test_both_halves_of_web_push_land_in_one_series(self, monkeypatch):
        """The registration refuses an address as it is stored; the sender skips a row stored earlier. Both
        count under one site with one label, or an operator reads two unrelated numbers for one rail."""
        from fastapi import HTTPException

        g = guard()
        counter = _Counter()
        monkeypatch.setattr(g, "OUTBOUND_REFUSED_TOTAL", counter)
        dp = importlib.import_module("agentvault_registry.routers.device_push")
        pn = importlib.import_module("agentvault_registry.background_tasks.push_notify")

        body = dp.WebPushSubscribeIn(endpoint="http://localhost/push/abc", keys={"p256dh": "p", "auth": "a"})
        with pytest.raises(HTTPException) as refused:
            await dp.webpush_subscribe(body=body, dev=object(), db=object())
        assert refused.value.status_code == 422
        assert "push_endpoint_refused" in str(refused.value.detail)

        # The sender is reached with no database and no VAPID key: the address is asked about first, which is
        # also why a target that will be refused costs nothing.
        assert not await pn._send_webpush(_Row("http://localhost/push/abc"), "t", "m", None)

        assert counter.seen == [{"site": "webpush", "reason": "reserved_name"}] * 2, counter.seen

    async def test_a_public_target_is_refused_by_neither_half(self, monkeypatch):
        """The control: the same code lets a public endpoint through and counts nothing, so the series above
        is a decision about the address rather than a rail that refuses everything."""
        g = guard()
        counter = _Counter()
        monkeypatch.setattr(g, "OUTBOUND_REFUSED_TOTAL", counter)
        verdict = await g.inspect_destination("https://card.example.com/push/abc")
        assert verdict.refusal is None
        assert counter.seen == [], "a destination that passes must count nothing"

