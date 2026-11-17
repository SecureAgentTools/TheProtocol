"""V0662, item 16 (order gwo_d721ad2f8118863d62815103; PLAN_2026-11-13_DELIVERY_OUTBOUND_PACKAGE.md): one outbound
guard for the last two dialers.

The V0659 (p) guard (core/outbound_guard: decide the destination, refuse a non-public one, connect only to an address
it checked, count each refusal under its site) carried six call sites. Two dialers kept checks of their own: a
developer webhook's delivery (SEC-14, shared with the CI/CD deployment webhook) and a frame's trust-bundle dial
(V0658 (l)). Both go through the guard now, so the rule lives in one place and every refusal is counted where the
others are (registry_outbound_refused_total{site}).

Per site: a name that resolves to a private address at the moment of the connection is refused there, nothing is
sent, and the guard counts it under that site. The bundle dial keeps its own rules on top: https on every hop,
an administrator-named internal host reached as named (an operator's address, outside the guard), and a sandbox
same-host peer's private address allowed where the frame opts in, never loopback or link-local.
Red on 95f3477c7: the two dialers refuse with their own checks, so the guard counts nothing for them.
"""
from __future__ import annotations

import asyncio
import socket

import httpx
import pytest

from agentvault_registry.core import outbound_guard as og
from agentvault_registry.services import frame_trust_manager as ftm
from agentvault_registry.services.webhook_service import WebhookService, post_to_checked_address

PUBLIC = "93.184.216.34"   # a public address the export allows in a shipped file


class _Dns:
    """socket.getaddrinfo from a table; a name's answers are taken in turn, the last one kept."""

    def __init__(self):
        self.answers, self.asked = {}, []

    def __call__(self, host, port, *a, **k):
        self.asked.append(host)
        seq = self.answers.get(host)
        if not seq:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        addrs = seq.pop(0) if len(seq) > 1 else seq[0]
        return [((socket.AF_INET6, socket.SOCK_STREAM, 6, "", (a, port, 0, 0)) if ":" in a
                 else (socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port))) for a in addrs]


@pytest.fixture
def dns(monkeypatch):
    d = _Dns()
    monkeypatch.setattr(socket, "getaddrinfo", d)

    async def resolve(host, port):        # the bundle module's own lookup (its allow-internal decision) reads the same table
        return sorted({i[4][0] for i in d(host, port)})
    monkeypatch.setattr(ftm, "_resolve", resolve)
    return d


def _wire(seen):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"url": str(request.url), "host": request.headers.get("host")})
        return httpx.Response(200, text='{"keys": [], "spiffe_sequence": 1}' + " " * 16)
    return httpx.MockTransport(handler)


def _refused(site, reason):
    c = og.OUTBOUND_REFUSED_TOTAL
    return c.labels(site=site, reason=reason)._value.get() if c is not None else 0.0


# --- a developer webhook, and the CI/CD webhook that shares its send -----------------------------------------------

def test_a_webhook_to_a_name_resolving_private_is_refused_by_the_guard(dns):
    dns.answers["hooks.example.org"] = [["10.20.30.40"]]
    seen = []
    svc = WebhookService()
    svc.client = httpx.AsyncClient(transport=_wire(seen), timeout=5)
    before = _refused("webhook_delivery", "private")
    with pytest.raises(Exception) as e:
        asyncio.run(svc._post_to_checked_address("https://hooks.example.org/h", b"{}", {}))
    assert "refused" in str(e.value).lower()
    assert seen == [], "nothing is sent"
    assert _refused("webhook_delivery", "private") == before + 1, "the guard decided it, under the webhook's site"


def test_the_ci_cd_webhook_counts_under_its_own_site(dns):
    dns.answers["deploy.example.org"] = [["127.0.0.1"]]
    seen = []
    client = httpx.AsyncClient(transport=_wire(seen), timeout=5)
    before = _refused("cicd_webhook", "loopback")
    with pytest.raises(Exception):
        asyncio.run(post_to_checked_address(client, "https://deploy.example.org/d", b"{}", {}, site="cicd_webhook"))
    assert seen == [] and _refused("cicd_webhook", "loopback") == before + 1


def test_a_webhook_to_a_public_name_is_sent_to_the_checked_address_and_the_client_stays_open(dns):
    # control: the delivery still goes out, pinned, and the service's own client survives the send (the guard does not
    # close a connection layer it was handed)
    dns.answers["hooks.example.org"] = [[PUBLIC]]
    seen = []
    svc = WebhookService()
    svc.client = httpx.AsyncClient(transport=_wire(seen), timeout=5)
    r1 = asyncio.run(svc._post_to_checked_address("https://hooks.example.org/h", b"{}", {}))
    r2 = asyncio.run(svc._post_to_checked_address("https://hooks.example.org/h", b"{}", {}))
    assert r1.status_code == r2.status_code == 200
    assert [s["url"] for s in seen] == [f"https://{PUBLIC}/h"] * 2 and seen[0]["host"] == "hooks.example.org"


# --- a frame's trust-bundle dial --------------------------------------------------------------------------------------

def test_a_bundle_host_resolving_private_at_the_dial_is_refused_by_the_guard(dns):
    dns.answers["frame.example.org"] = [[PUBLIC], ["192.168.7.7"]]   # public for the allow-internal decision, private at the dial
    seen = []

    async def go():
        # fetch_remote_bundle's sequence: its allow-internal decision looks the name up first (public), then the dial
        internal, _ = await ftm._host_is_internal("frame.example.org", 443)
        async with httpx.AsyncClient(transport=_wire(seen), timeout=5) as c:
            return await ftm._dial_checked(c, "GET", "https://frame.example.org/bundle", allow_internal=internal)
    before = _refused("frame_trust_bundle", "private")
    r, refusal = asyncio.run(go())
    assert r is None and "internal" in refusal and seen == []
    assert _refused("frame_trust_bundle", "private") == before + 1


def test_a_sandbox_same_host_peer_may_be_private_never_loopback(dns):
    dns.answers["peer.example.org"] = [["172.18.0.5"]]
    dns.answers["loop.example.org"] = [["127.0.0.1"]]
    seen = []

    async def go(url):
        async with httpx.AsyncClient(transport=_wire(seen), timeout=5) as c:
            return await ftm._dial_checked(c, "GET", url, allow_internal=False, allow_private=True)
    r, refusal = asyncio.run(go("https://peer.example.org/bundle"))
    assert refusal is None and r.status_code == 200 and seen[-1]["url"] == "https://172.18.0.5/bundle"
    before = _refused("frame_trust_bundle", "loopback")
    r, refusal = asyncio.run(go("https://loop.example.org/bundle"))
    assert r is None and refusal and _refused("frame_trust_bundle", "loopback") == before + 1


def test_an_administrator_named_internal_host_is_dialled_as_named(dns):
    # control: an internal ORIGINAL a federation administrator named (same-host frames over the compose network) is an
    # operator's address, outside the guard; it is reached, and the guard counts nothing
    seen = []

    async def go():
        async with httpx.AsyncClient(transport=_wire(seen), timeout=5) as c:
            return await ftm._dial_checked(c, "GET", "https://10.0.0.9/bundle", allow_internal=True)
    r, refusal = asyncio.run(go())
    assert refusal is None and r.status_code == 200 and seen[-1]["url"] == "https://10.0.0.9/bundle"
