"""§SECFIX-9 (2026-09-25) — the TEG's Host check runs by its own flag, not by ENVIRONMENT.

Measured before: the TrustedHostMiddleware in main.py was added only when settings.environment == "production", and
ENVIRONMENT was unset on all 24 running TEG containers, so no TEG checked a Host header at all; its list also named
Frame A's containers, not the names the current TEGs are dialed by (eu-teg, teg-layer through nginx-teg, a peer's
public name through nginx-federation, a unix socket's client-chosen Host).

RED control: run with PYTHONPATH naming the tree before the fix; core/trusted_hosts.py does not exist there and the
main.py source check sees the environment gate.
"""
from __future__ import annotations

import asyncio
import pathlib

from teg_core_service.core import trusted_hosts as th

MAIN = pathlib.Path(th.__file__).resolve().parents[1] / "main.py"


def _policy(**kw):
    return th.HostPolicy(extra=kw.get("extra", ()), suffixes=kw.get("suffixes", ("theprotocol.cloud",)),
                         own_hostnames=kw.get("own", ("c0ffee123456",)))


def test_host_header_parsing():
    assert th.host_of("eu-teg:8080") == "eu-teg"
    assert th.host_of("API.TheProtocol.Cloud") == "api.theprotocol.cloud"
    assert th.host_of("[::1]:8080") == "::1"
    assert th.host_of("::1") == "::1"
    assert th.host_of("localhost.") == "localhost"
    for bad in (None, "", " ", "a b", "x:port", "[::1", "[::1]x", "user@host", "host/path"):
        assert th.host_of(bad) is None, bad


def test_the_names_todays_callers_use_are_accepted():
    p = _policy()
    for name in ("localhost", "127.0.0.1", "::1", "teg-layer", "eu-teg", "cloud-op-amsterdam-teg", "c0ffee123456",
                 "172.16.29.18", "10.0.0.5", "api.theprotocol.cloud", "eu.theprotocol.cloud", "theprotocol.cloud"):
        assert p.allowed(th.host_of(name)), name


def test_a_dotted_name_outside_the_suffixes_is_not_trusted():
    p = _policy()
    for name in ("evil.example", "theprotocol.cloud.evil.io", "xtheprotocol.cloud", "8.8.8.8", "2001:4860:4860::8888",
                 "", None, "bad_label!", "ünicode"):
        assert not p.allowed(th.host_of(name) if name else None), name


def test_the_extra_list_and_wildcards_widen_it():
    p = _policy(extra=("partner.example.org", "*.lab.example.net"), suffixes=("example.com",))
    assert p.allowed("partner.example.org")
    assert p.allowed("a.lab.example.net") and p.allowed("lab.example.net")
    assert p.allowed("x.example.com")
    assert not p.allowed("api.theprotocol.cloud"), "the suffixes replace the default, they do not add to it"


def test_an_unknown_mode_serves_as_observe_and_says_so(caplog):
    assert th.resolve_mode("ENFORCE") == "enforce"
    assert th.resolve_mode(None) == "observe"
    assert th.resolve_mode("enforc") == "observe"
    assert any("not one of" in r.getMessage() for r in caplog.records)


def _drive(mode, host):
    served = []

    async def app(scope, receive, send):
        served.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    gate = th.TrustedHostsGate(app, mode=mode, policy=_policy())
    sent = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return {"type": "http.request", "body": b""}

    headers = [(b"host", host.encode())] if host is not None else []
    asyncio.run(gate({"type": "http", "path": "/api/v1/admin/fx/reserve", "headers": headers, "client": ("172.16.0.9", 1)},
                     receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    return status, served


def _count(mode):
    c = th.TEG_UNTRUSTED_HOST_TOTAL
    return c.labels(mode=mode)._value.get() if c is not None else None


def test_observe_serves_and_counts_a_miss():
    before = _count("observe")
    assert _drive("observe", "evil.example") == (200, ["/api/v1/admin/fx/reserve"])
    if before is not None:
        assert _count("observe") == before + 1
    assert _drive("observe", "eu-teg:8080") == (200, ["/api/v1/admin/fx/reserve"])
    if before is not None:
        assert _count("observe") == before + 1, "a trusted host is not counted"


def test_enforce_refuses_a_miss_and_serves_a_trusted_host():
    assert _drive("enforce", "evil.example") == (400, [])
    assert _drive("enforce", None) == (400, [])
    assert _drive("enforce", "teg-layer:8080") == (200, ["/api/v1/admin/fx/reserve"])


def test_off_passes_everything_and_counts_nothing():
    before = _count("off")
    assert _drive("off", "evil.example") == (200, ["/api/v1/admin/fx/reserve"])
    if before is not None:
        assert _count("off") == before


def test_main_no_longer_keys_the_host_check_on_environment():
    src = MAIN.read_text(encoding="utf-8")
    assert "app.add_middleware(TrustedHostsGate)" in src
    assert "TrustedHostMiddleware," not in src
    assert 'if settings.environment == "production":\n    # Configure with production domains' not in src
