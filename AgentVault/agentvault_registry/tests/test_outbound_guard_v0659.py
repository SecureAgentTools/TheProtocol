"""V0659 (p): one guard for outbound fetches a user, a card, a bundle or a peer can address.

The registry fetches addresses it is handed: an agent card's endpoint, a webhook, a bundle's source, a link a peer
sends. core/outbound_guard.py is the one check those fetches share:

  * a destination is fetched only when every address its host name resolves to is a public unicast address
    (ipaddress's is_global, an IPv4-mapped IPv6 address judged as the IPv4 address it carries, and the rule webhook
    URLs already follow, input_validators._is_internal_address); a name with one public and one non-public address
    is refused; the special-use names the agent-card pull never asks (agent_card_pullsync.reserved_tld_of) are
    refused without a lookup;
  * the connection then goes to an address that was checked (the request names its host in the Host header and,
    for https, in the TLS server name), so the answer cannot change between the check and the connection;
  * redirects are never followed by the HTTP client on its own: a redirect's target is checked like the first
    address, or the request is refused;
  * each refusal is counted (registry_outbound_refused_total, by site and class of refusal) and logged at WARNING
    with the site and the class, never the address;
  * the sandbox allowance for the private ranges is explicit: OUTBOUND_GUARD_SANDBOX_ALLOW_PRIVATE, off by default,
    honoured only where the registry's sandbox flag (the one the agent-card pull reads) is set.

No test here touches the network: socket.getaddrinfo answers from a table (an unknown name fails as NXDOMAIN) and the
connection layer is an httpx.MockTransport that records every request that reaches it.
RED on 553347408 (origin/v0657/cut): agentvault_registry.core.outbound_guard does not exist; every case fails at
the import.
"""
from __future__ import annotations

import importlib
import json
import logging
import socket

import httpx
import pytest
from prometheus_client import REGISTRY

MODULE = "agentvault_registry.core.outbound_guard"
PUBLIC_V4 = "93.184.215.14"
PUBLIC_V6 = "2606:4700:4700::1111"
DNS = {
    "agent.example.com": [PUBLIC_V4],
    "redirector.example.com": [PUBLIC_V4],
    "v6.example.net": [PUBLIC_V6],
    "dual.example.org": [PUBLIC_V6, PUBLIC_V4],
    "mapped-public.example.com": ["::ffff:" + PUBLIC_V4],
    "loopback.example.com": ["127.0.0.1"],
    "private.example.com": ["10.1.2.3"],
    "metadata.example.com": ["169.254.169.254"],
    "mapped.example.com": ["::ffff:127.0.0.1"],
    "mixed.example.com": [PUBLIC_V4, "192.168.7.7"],
    "ula.example.com": ["fd12:3456::1"],
    "shared.example.com": ["100.100.100.200"],
    "zero.example.com": ["0.0.0.0"],
    "multicast.example.com": ["224.0.1.1"],
    "docker-agent": ["172.18.0.5"],
}
SANDBOX_ENV = ("SANDBOX_MODE", "CC_TARGET_ENVIRONMENT", "OUTBOUND_GUARD_SANDBOX_ALLOW_PRIVATE")


def _guard():
    try:
        return importlib.import_module(MODULE)
    except ImportError as e:
        pytest.fail(f"{MODULE} is missing: the outbound fetches share no guard ({e})")


@pytest.fixture(autouse=True)
def asked(monkeypatch):
    """socket.getaddrinfo answers from DNS (an unknown name is NXDOMAIN); the names asked, in order."""
    for k in SANDBOX_ENV:
        monkeypatch.delenv(k, raising=False)
    names = []

    def getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        names.append(host)
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
    return names


class Upstream:
    """The connection layer: records each request that reaches it; answers by (Host header, path), 200 otherwise."""

    def __init__(self, routes=None, refuse_connect=()):
        self.seen = []
        self.routes = dict(routes or {})
        self.refuse_connect = set(refuse_connect)
        self.transport = httpx.MockTransport(self)

    def __call__(self, request):
        self.seen.append(request)
        if request.url.host in self.refuse_connect:
            raise httpx.ConnectError("connection refused", request=request)
        answer = self.routes.get((request.headers.get("host"), request.url.path))
        if answer is not None:
            return answer()
        return httpx.Response(200, json={"host": request.headers.get("host"), "body": request.content.decode()})


def _refused(site, reason):
    return REGISTRY.get_sample_value("registry_outbound_refused_total", {"site": site, "reason": reason}) or 0.0


def _redirect(location):
    return lambda: httpx.Response(302, headers={"Location": location})


async def test_a_public_name_is_fetched_through_an_address_that_was_checked(asked):
    g = _guard()
    up = Upstream()
    async with g.guarded_client("t_public_name", inner=up.transport, timeout=5.0) as client:
        r = await client.get("https://agent.example.com/.well-known/agent-card.json")
    assert r.status_code == 200 and str(r.url) == "https://agent.example.com/.well-known/agent-card.json"
    assert asked == ["agent.example.com"], "the name is looked up once, by the guard"
    (sent,) = up.seen
    assert sent.url.host == PUBLIC_V4 and sent.url.path == "/.well-known/agent-card.json", "pinned to the checked address"
    assert sent.headers["host"] == "agent.example.com"
    assert sent.extensions.get("sni_hostname") == "agent.example.com", "the certificate is verified for the name"
    assert sent.headers.get("connection") == "close", "a connection made for one name serves no other"


async def test_an_ipv6_name_a_port_and_an_address_literal(asked):
    g = _guard()
    up = Upstream()
    async with g.guarded_client("t_public_forms", inner=up.transport) as client:
        assert (await client.get("http://v6.example.net:8080/a2a?x=1")).status_code == 200
        assert (await client.get(f"https://{PUBLIC_V4}/card")).status_code == 200
    first, second = up.seen
    assert (first.url.host, first.url.port, first.url.query) == (PUBLIC_V6, 8080, b"x=1")
    assert first.headers["host"] == "v6.example.net:8080" and "sni_hostname" not in first.extensions
    assert second.url.host == PUBLIC_V4 and second.headers["host"] == PUBLIC_V4
    assert second.headers.get("connection") == "close"
    assert asked == ["v6.example.net"], "an address literal is checked as written, with no lookup"


REFUSED = [
    ("http://loopback.example.com/x", "loopback"),
    ("http://private.example.com/x", "private"),
    ("http://metadata.example.com/latest/meta-data/", "link_local"),
    ("http://mapped.example.com/x", "loopback"),
    ("http://ula.example.com/x", "private"),
    ("http://shared.example.com/x", "non_global"),
    ("http://zero.example.com/x", "unspecified"),
    ("http://multicast.example.com/x", "multicast"),
    ("http://127.0.0.1:8000/internal", "loopback"),
    ("http://[::1]:8000/internal", "loopback"),
    ("http://169.254.169.254/latest/meta-data/", "link_local"),
    ("http://192.168.1.9:8200/x", "private"),
    ("http://[::ffff:10.0.0.1]/x", "private"),
    ("http://[2002:7f00:1::1]/x", "loopback"),
    ("http://localhost:8000/x", "reserved_name"),
    ("https://agent.invalid/x", "reserved_name"),
    ("https://box.localhost/x", "reserved_name"),
    ("https://child.agents.local/x", "reserved_name"),
    ("ftp://agent.example.com/x", "scheme"),
]


@pytest.mark.parametrize("url,reason", REFUSED)
async def test_a_non_public_destination_is_refused_before_anything_connects(asked, url, reason):
    g = _guard()
    up = Upstream()
    async with g.guarded_client("t_refused", inner=up.transport) as client:
        with pytest.raises(g.OutboundRefused) as e:
            await client.get(url)
    assert (e.value.reason, e.value.site, e.value.hop) == (reason, "t_refused", "first"), str(e.value)
    assert up.seen == [], "nothing may reach the connection layer"
    assert isinstance(e.value, httpx.RequestError), "a call site's existing handlers still see a failed request"
    assert e.value.request.url == httpx.URL(url)
    if reason in ("reserved_name", "scheme"):
        assert asked == [], "refused without a lookup"


async def test_a_name_with_one_public_and_one_non_public_address_is_refused(asked):
    g = _guard()
    up = Upstream()
    async with g.guarded_client("t_mixed", inner=up.transport) as client:
        with pytest.raises(g.OutboundRefused) as e:
            await client.get("https://mixed.example.com/card")
    assert e.value.reason == "private" and up.seen == [] and asked == ["mixed.example.com"]


async def test_an_ipv4_mapped_address_is_judged_as_the_ipv4_address_it_carries():
    g = _guard()
    assert g.address_refusal("::ffff:127.0.0.1") == "loopback"
    assert g.address_refusal("::ffff:10.0.0.1") == "private"
    assert g.address_refusal("::ffff:169.254.169.254") == "link_local"
    assert g.address_refusal("::ffff:" + PUBLIC_V4) is None
    up = Upstream()
    async with g.guarded_client("t_mapped_public", inner=up.transport) as client:
        assert (await client.get("https://mapped-public.example.com/x")).status_code == 200
    assert up.seen[0].url.host == PUBLIC_V4, "connected to as the IPv4 address it carries"


@pytest.mark.parametrize("address,reason", [
    ("8.8.8.8", None), ("1.1.1.1", None), (PUBLIC_V4, None), (PUBLIC_V6, None),
    ("127.0.0.1", "loopback"), ("127.8.9.10", "loopback"), ("::1", "loopback"),
    ("0.0.0.0", "unspecified"), ("::", "unspecified"),
    ("169.254.169.254", "link_local"), ("fe80::1", "link_local"),
    ("224.0.1.1", "multicast"), ("ff0e::1", "multicast"),
    ("10.0.0.1", "private"), ("172.16.5.4", "private"), ("192.168.0.1", "private"), ("fd00::1", "private"),
    ("100.64.0.1", "non_global"), ("192.0.2.10", "non_global"), ("198.18.0.1", "non_global"),
    ("240.0.0.1", "non_global"), ("255.255.255.255", "non_global"), ("2001:db8::1", "non_global"),
    ("64:ff9b::7f00:1", "non_global"), ("not-an-address", "malformed"),
])
def test_the_address_rule(address, reason):
    assert _guard().address_refusal(address) == reason


@pytest.mark.parametrize("location,reason", [
    ("http://127.0.0.1:8200/internal", "loopback"),
    ("http://private.example.com/internal", "private"),
    ("http://localhost/internal", "reserved_name"),
    ("http://169.254.169.254/latest/meta-data/", "link_local"),
])
async def test_a_redirect_to_a_non_public_address_is_refused(asked, location, reason):
    g = _guard()
    up = Upstream({("redirector.example.com", "/card"): _redirect(location)})
    before = _refused("t_redirect_refused", reason)
    async with g.guarded_client("t_redirect_refused", inner=up.transport) as client:
        with pytest.raises(g.OutboundRefused) as e:
            await client.fetch("GET", "https://redirector.example.com/card", max_redirects=3)
    assert (e.value.reason, e.value.hop) == (reason, "redirect"), str(e.value)
    assert [s.headers["host"] for s in up.seen] == ["redirector.example.com"], "only the first hop connected"
    assert _refused("t_redirect_refused", reason) == before + 1


async def test_a_redirect_to_a_public_address_is_checked_like_the_first_and_followed(asked):
    g = _guard()
    up = Upstream({("redirector.example.com", "/card"): _redirect("/hop"),
                   ("redirector.example.com", "/hop"): _redirect("https://v6.example.net/card")})
    async with g.guarded_client("t_redirect_followed", inner=up.transport) as client:
        r = await client.fetch("GET", "https://redirector.example.com/card", max_redirects=3)
    assert r.status_code == 200 and str(r.url) == "https://v6.example.net/card"
    assert [h.status_code for h in r.history] == [302, 302]
    assert [(s.url.host, s.headers["host"], s.url.path) for s in up.seen] == [
        (PUBLIC_V4, "redirector.example.com", "/card"), (PUBLIC_V4, "redirector.example.com", "/hop"),
        (PUBLIC_V6, "v6.example.net", "/card")], "a relative hop joins the name, and every hop is pinned"
    assert asked == ["redirector.example.com", "redirector.example.com", "v6.example.net"], "every hop is looked up"


async def test_redirects_are_never_followed_automatically(asked):
    g = _guard()
    up = Upstream({("redirector.example.com", "/card"): _redirect("https://agent.example.com/card")})
    async with g.guarded_client("t_no_auto_follow", inner=up.transport) as client:
        r = await client.get("https://redirector.example.com/card")
        assert r.status_code == 302 and len(up.seen) == 1
        r = await client.fetch("GET", "https://redirector.example.com/card")
        assert r.status_code == 302 and len(up.seen) == 2, "fetch follows nothing unless asked to"
        with pytest.raises(ValueError):
            await client.get("https://redirector.example.com/card", follow_redirects=True)
    assert len(up.seen) == 2
    with pytest.raises(ValueError):
        g.guarded_client("t_no_auto_follow", follow_redirects=True)


async def test_a_chain_longer_than_the_cap_is_refused(asked):
    g = _guard()
    up = Upstream({("redirector.example.com", "/loop"): _redirect("/loop")})
    before = _refused("t_redirect_cap", "redirect_limit")
    async with g.guarded_client("t_redirect_cap", inner=up.transport) as client:
        with pytest.raises(g.OutboundRefused) as e:
            await client.fetch("GET", "https://redirector.example.com/loop", max_redirects=2)
    assert (e.value.reason, e.value.hop) == ("redirect_limit", "redirect")
    assert len(up.seen) == 3, "the first request and two followed hops, then the refusal"
    assert _refused("t_redirect_cap", "redirect_limit") == before + 1


async def test_each_refusal_is_counted_with_its_site_and_logged_without_the_address(caplog):
    g = _guard()
    caplog.set_level(logging.WARNING, logger=MODULE)
    before, other = _refused("t_counted", "loopback"), _refused("t_other_site", "loopback")
    up = Upstream()
    async with g.guarded_client("t_counted", inner=up.transport) as client:
        for _ in range(2):
            with pytest.raises(g.OutboundRefused) as e:
                await client.get("http://loopback.example.com:8200/secret")
    assert _refused("t_counted", "loopback") == before + 2
    assert _refused("t_other_site", "loopback") == other
    lines = [r for r in caplog.records if r.name == MODULE and r.levelno == logging.WARNING]
    assert len(lines) == 2
    for text in [r.getMessage() for r in lines] + [str(e.value)]:
        assert "site=t_counted" in text and "reason=loopback" in text and "hop=first" in text, text
        for leaked in ("loopback.example.com", "127.0.0.1", "8200", "/secret"):
            assert leaked not in text, text


SANDBOX_PRIVATE = ["http://private.example.com/a2a", "http://docker-agent:8080/a2a", "http://172.18.0.5:8080/a2a",
                   "http://ula.example.com/a2a"]


@pytest.mark.parametrize("flag,sandbox", [(None, None), ("true", None), (None, "true"), ("false", "true"),
                                          ("true", "false")])
async def test_the_sandbox_allowance_is_off_unless_its_flag_and_the_sandbox_flag_are_both_set(monkeypatch, flag,
                                                                                               sandbox):
    g = _guard()
    if flag is not None:
        monkeypatch.setenv("OUTBOUND_GUARD_SANDBOX_ALLOW_PRIVATE", flag)
    if sandbox is not None:
        monkeypatch.setenv("SANDBOX_MODE", sandbox)
    up = Upstream()
    async with g.guarded_client("t_sandbox_off", inner=up.transport) as client:
        for url in SANDBOX_PRIVATE:
            with pytest.raises(g.OutboundRefused) as e:
                await client.get(url)
            assert e.value.reason == "private", url
    assert up.seen == []


@pytest.mark.parametrize("sandbox_env", [("SANDBOX_MODE", "true"), ("CC_TARGET_ENVIRONMENT", "sandbox")])
async def test_in_sandbox_mode_the_flag_opens_the_private_ranges_and_nothing_else(monkeypatch, sandbox_env):
    g = _guard()
    monkeypatch.setenv("OUTBOUND_GUARD_SANDBOX_ALLOW_PRIVATE", "true")
    monkeypatch.setenv(*sandbox_env)
    up = Upstream()
    async with g.guarded_client("t_sandbox_on", inner=up.transport) as client:
        for url in SANDBOX_PRIVATE:
            assert (await client.get(url)).status_code == 200, url
        for url, reason in (("http://loopback.example.com/x", "loopback"), ("http://127.0.0.1:8000/x", "loopback"),
                            ("http://169.254.169.254/latest/meta-data/", "link_local"),
                            ("http://metadata.example.com/x", "link_local"), ("http://localhost:8000/x", "reserved_name"),
                            ("http://shared.example.com/x", "non_global"), ("http://zero.example.com/x", "unspecified")):
            with pytest.raises(g.OutboundRefused) as e:
                await client.get(url)
            assert e.value.reason == reason, url
    assert [s.url.host for s in up.seen] == ["10.1.2.3", "172.18.0.5", "172.18.0.5", "fd12:3456::1"]


async def test_the_sandbox_flag_is_the_one_the_agent_card_pull_reads(monkeypatch):
    g = _guard()
    from agentvault_registry.background_tasks import agent_card_pullsync as ps
    monkeypatch.setenv("OUTBOUND_GUARD_SANDBOX_ALLOW_PRIVATE", "true")
    up = Upstream()
    async with g.guarded_client("t_sandbox_rule", inner=up.transport) as client:
        monkeypatch.setattr(ps, "_is_sandbox_mode", lambda: True)
        assert (await client.get("http://private.example.com/x")).status_code == 200
        monkeypatch.setattr(ps, "_is_sandbox_mode", lambda: False)
        with pytest.raises(g.OutboundRefused):
            await client.get("http://private.example.com/x")
    assert len(up.seen) == 1


async def test_the_special_use_names_are_the_agent_card_pulls_own(asked, monkeypatch):
    g = _guard()
    from agentvault_registry.background_tasks import agent_card_pullsync as ps
    assert ps._RESERVED_TLDS, "the pull-sync's list is empty: check the test, not the code"
    for tld in sorted(ps._RESERVED_TLDS):
        assert (await g.inspect_destination(f"https://agent-1.{tld}/card")).refusal == "reserved_name", tld
    assert (await g.inspect_destination("https://agent-1.internal/card")).refusal is None
    monkeypatch.setattr(ps, "_RESERVED_TLDS", ps._RESERVED_TLDS | {"internal"})
    assert (await g.inspect_destination("https://agent-1.internal/card")).refusal == "reserved_name", \
        "a name the pull-sync's list gains is refused here too: one list, not a copy"
    assert asked == ["agent-1.internal"]


async def test_a_name_that_resolves_to_nothing_is_a_connect_error_not_a_refusal(asked):
    g = _guard()
    up = Upstream()
    async with g.guarded_client("t_nxdomain", inner=up.transport) as client:
        with pytest.raises(httpx.ConnectError) as e:
            await client.get("https://gone.example.com/card")
    assert not isinstance(e.value, g.OutboundRefused) and up.seen == [] and asked == ["gone.example.com"]
    assert all(_refused("t_nxdomain", reason) == 0 for reason in g.REASONS)


async def test_a_failed_connection_moves_on_to_the_next_checked_address():
    g = _guard()
    up = Upstream(refuse_connect={PUBLIC_V6})
    async with g.guarded_client("t_next_address", inner=up.transport) as client:
        r = await client.get("https://dual.example.org/card")
    assert r.status_code == 200
    assert [s.url.host for s in up.seen] == [PUBLIC_V6, PUBLIC_V4]
    assert all(s.headers["host"] == "dual.example.org" and s.extensions.get("sni_hostname") == "dual.example.org"
               for s in up.seen)


async def test_inspect_destination_decides_without_fetching_counting_or_logging(asked, caplog):
    g = _guard()
    caplog.set_level(logging.DEBUG, logger=MODULE)
    d = await g.inspect_destination("https://dual.example.org/card")
    assert (d.refusal, d.resolved, d.addresses) == (None, True, (PUBLIC_V6, PUBLIC_V4))
    d = await g.inspect_destination("https://mixed.example.com/card")
    assert (d.refusal, d.addresses) == ("private", ())
    d = await g.inspect_destination("https://gone.example.com/card")
    assert (d.refusal, d.resolved, d.addresses) == (None, False, ())
    d = await g.inspect_destination(f"http://{PUBLIC_V4}:8080/x")
    assert (d.refusal, d.literal, d.addresses) == (None, True, (PUBLIC_V4,))
    assert (await g.inspect_destination("http://localhost:8000/")).refusal == "reserved_name"
    assert (await g.inspect_destination("not a url at all")).refusal in ("scheme", "malformed")
    assert not [r for r in caplog.records if r.name == MODULE and r.levelno >= logging.WARNING]


async def test_guarded_request_is_the_one_call_form(asked):
    g = _guard()
    up = Upstream()
    r = await g.guarded_request("POST", "https://agent.example.com/hook", site="t_one_shot", inner=up.transport,
                                json={"a": 1})
    assert r.status_code == 200 and json.loads(r.json()["body"]) == {"a": 1} and up.seen[0].url.host == PUBLIC_V4
    with pytest.raises(g.OutboundRefused) as e:
        await g.guarded_request("POST", "http://private.example.com/hook", site="t_one_shot", inner=up.transport,
                                json={"a": 1})
    assert (e.value.site, e.value.reason) == ("t_one_shot", "private") and len(up.seen) == 1


@pytest.mark.parametrize("site", ["", "Agent Card", "card-pull", "x" * 65, "1st", "agent_card_pull\n", None])
def test_a_site_name_is_a_short_snake_case_label(site):
    g = _guard()
    with pytest.raises(ValueError):
        g.guarded_client(site)
    with pytest.raises(ValueError):
        g.GuardedTransport(site)


@pytest.mark.parametrize("kwarg", ["transport", "mounts", "proxy", "app"])
def test_a_guarded_client_takes_nothing_that_would_go_around_it(kwarg):
    with pytest.raises(TypeError):
        _guard().guarded_client("t_bypass", **{kwarg: object()})
