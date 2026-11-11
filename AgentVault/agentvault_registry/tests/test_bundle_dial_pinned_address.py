"""V0658 (l), code-scanning #357 (py/full-ssrf, 2026-11-07, session-watch): the bundle dial connects to the address its
own check approved.

_dial_checked vetted each hop's host (https only, public unless the caller allows otherwise) and then handed the URL to
httpx, which resolved the name AGAIN to connect: the two answers need not agree. Now the vetted address is dialled, with
the name kept in the Host header and in SNI, on every redirect hop as well.

⚠ This client does not verify certificates on purpose (_bundle_client: a bootstrapping frame may serve a self-signed one
and the SPIRE bundle, not the certificate, is the trust anchor), so the pin is what bounds where the bytes come from
here; SNI and Host only keep the request the one the server would have answered by name.

DB-free: the resolver is a table whose answers for a name are taken in turn (as in test_cicd_webhook_address.py), and
the transport records the address each request reached. RED on e70fb58b2, where the dials reach the second answer.
"""
import asyncio
import ipaddress
import socket
import types

import httpx
import pytest

from agentvault_registry.services import frame_trust_manager as ftm

PUBLIC = "93.184.216.34"      # a public address the export allows in a shipped file (its G13)
PUBLIC2 = "93.184.216.35"
INTERNAL = "169.254.169.254"  # a link-local address the check refuses


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
        return [((socket.AF_INET6, socket.SOCK_STREAM, 6, "", (x, port, 0, 0)) if ":" in x
                 else (socket.AF_INET, socket.SOCK_STREAM, 6, "", (x, port))) for x in addrs]


@pytest.fixture
def dns(monkeypatch):
    d = _Dns()
    monkeypatch.setattr(socket, "getaddrinfo", d)
    return d


@pytest.fixture
def wire(dns):
    """Every request and the address it reached; `redirect` maps an address to a Location to answer with once."""
    seen, redirect = [], {}

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        try:
            ipaddress.ip_address(host)
            reached = host
        except ValueError:      # a name: the client resolves it again before it connects
            reached = dns(host, request.url.port or 443)[0][4][0]
        seen.append({"reached": reached, "url": str(request.url), "host": request.headers.get("host"),
                     "sni": request.extensions.get("sni_hostname")})
        loc = redirect.pop(reached, None)
        if loc:
            return httpx.Response(302, headers={"location": loc})
        return httpx.Response(200, text="bundle")

    def client():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)

    return types.SimpleNamespace(seen=seen, redirect=redirect, client=client)


def _dial(wire, url, **kw):
    async def go():
        async with wire.client() as c:
            return await ftm._dial_checked(c, "GET", url, kw.pop("allow_internal", False), **kw)
    return asyncio.run(go())


# --- the pin ------------------------------------------------------------------------------------------------------
def test_a_checked_hop_is_dialled_at_the_address_the_check_saw(dns, wire):
    dns.answers["frame.example"] = [[PUBLIC]]
    r, refusal = _dial(wire, "https://frame.example/bundle")
    assert refusal is None and r.status_code == 200
    one = wire.seen[0]
    assert one["reached"] == PUBLIC, "the connection must go to the checked address"
    assert one["host"] == "frame.example" and one["sni"] == "frame.example", "the name is kept for the server"
    assert "/bundle" in one["url"]


def test_a_name_that_answers_differently_the_second_time_cannot_move_the_connection(dns, wire):
    """The window the alert names: the check resolves, then the connection resolves again. The second answer here is an
    address the check would have refused."""
    dns.answers["rebind.example"] = [[PUBLIC], [INTERNAL]]
    r, refusal = _dial(wire, "https://rebind.example/bundle")
    assert refusal is None and r.status_code == 200
    assert wire.seen[0]["reached"] == PUBLIC, "the dial followed the second answer instead of the checked address"


def test_each_redirect_hop_is_pinned_too(dns, wire):
    dns.answers["first.example"] = [[PUBLIC]]
    dns.answers["second.example"] = [[PUBLIC2], [INTERNAL]]
    wire.redirect[PUBLIC] = "https://second.example/b2"
    r, refusal = _dial(wire, "https://first.example/b1")
    assert refusal is None and r.status_code == 200
    assert [s["reached"] for s in wire.seen] == [PUBLIC, PUBLIC2]
    assert wire.seen[1]["host"] == "second.example" and wire.seen[1]["sni"] == "second.example"


def test_a_relative_redirect_still_resolves_against_the_name(dns, wire):
    """The pin must not leak into the logical URL: a relative Location resolves against the name, not the address."""
    dns.answers["rel.example"] = [[PUBLIC]]
    wire.redirect[PUBLIC] = "/moved"
    r, refusal = _dial(wire, "https://rel.example/bundle")
    assert refusal is None and r.status_code == 200
    assert wire.seen[1]["host"] == "rel.example" and wire.seen[1]["url"].endswith("/moved")


def test_a_port_is_carried_into_the_dial_and_the_host_header(dns, wire):
    dns.answers["ported.example"] = [[PUBLIC]]
    r, refusal = _dial(wire, "https://ported.example:8443/bundle")
    assert refusal is None
    assert wire.seen[0]["host"] == "ported.example:8443" and f"{PUBLIC}:8443" in wire.seen[0]["url"]


# --- controls: the refusals and the by-name path are unchanged -----------------------------------------------------
def test_an_internal_host_is_still_refused(dns, wire):
    dns.answers["inside.example"] = [[INTERNAL]]
    r, refusal = _dial(wire, "https://inside.example/bundle")
    assert r is None and "internal address" in refusal
    assert wire.seen == [], "nothing may be dialled once the check refuses"


def test_a_host_that_does_not_resolve_is_still_refused(dns, wire):
    r, refusal = _dial(wire, "https://nowhere.example/bundle")
    assert r is None and "does not resolve" in refusal


def test_plain_http_is_still_refused(dns, wire):
    r, refusal = _dial(wire, "http://frame.example/bundle")
    assert r is None and "https" in refusal


def test_allow_internal_still_dials_by_name(dns, wire):
    """With allow_internal the caller has opted out of the check, so there is no checked address to pin to."""
    dns.answers["internal.svc"] = [[INTERNAL]]
    r, refusal = _dial(wire, "https://internal.svc/bundle", allow_internal=True)
    assert refusal is None and r.status_code == 200
    # httpx sets Host from the URL either way, so SNI and the dialled URL are what tell the two paths apart
    assert wire.seen[0]["sni"] is None, "no pin, so no SNI override"
    assert "internal.svc" in wire.seen[0]["url"], "the dial goes by name when the caller opted out of the check"


def test_host_is_internal_keeps_its_two_tuple(dns, wire):
    """Its other caller and test_frame_invitation_bundle_guard read (bool, why)."""
    dns.answers["inside.example"] = [[INTERNAL]]
    dns.answers["ok.example"] = [[PUBLIC]]
    assert asyncio.run(ftm._host_is_internal("inside.example", 443))[0] is True
    assert asyncio.run(ftm._host_is_internal("ok.example", 443)) == (False, "")
