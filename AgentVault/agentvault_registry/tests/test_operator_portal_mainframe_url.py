"""_resolve_mainframe_url(): fall back only when the configured host is unreachable.

WHY THIS EXISTS. The provisioner writes CENTRAL_REGISTRY_URL as an internal
docker name, which resolves only when the operator shares a network with its
frame. The old code rescued exactly one such name by literal
(`agentvault_registry_a`) and was blind to every other frame's — so both sandbox
operators answered `502 Mainframe call failed: [Errno -3] Temporary failure in
name resolution` on every operator-portal action (measured 2026-09-05).

CONTROL (measured 2026-09-05, pre-fix module loaded in the image): given
`CENTRAL_REGISTRY_URL=http://sbx-alpha-registry:8000` the old resolver returned
that string verbatim — an unresolvable host — while
`http://agentvault_registry_a:8000` was rescued to the public URL. That
asymmetry IS the bug, and it is what
`test_unresolvable_non_production_name_falls_back` pins. The pre-fix module has
no `_resolve_cache`/`socket` reference, so these cases cannot be re-run against
it directly; the control is that behavioural demonstration, not a re-run.
"""
import socket

import pytest

from agentvault_registry.routers import operator_portal_actions as opa


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """Each case starts with an empty resolver cache and a known env."""
    opa._resolve_cache.clear()
    for k in ("CENTRAL_REGISTRY_URL", "MAINFRAME_PROXY_URL", "MAINFRAME_PUBLIC_URL"):
        monkeypatch.delenv(k, raising=False)
    yield
    opa._resolve_cache.clear()


def _dns(monkeypatch, resolvable):
    """Pin resolution to an explicit set; everything else raises like a real miss."""
    calls = []

    def fake_getaddrinfo(host, *a, **kw):
        calls.append(host)
        if host in resolvable:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]
        raise socket.gaierror(-3, "Temporary failure in name resolution")

    monkeypatch.setattr(opa.socket, "getaddrinfo", fake_getaddrinfo)
    return calls


def test_resolvable_internal_name_is_used_verbatim(monkeypatch):
    """A co-networked operator keeps internal routing — the fix must not reroute it."""
    _dns(monkeypatch, {"sbx-alpha-registry"})
    monkeypatch.setenv("CENTRAL_REGISTRY_URL", "http://sbx-alpha-registry:8000")
    assert opa._resolve_mainframe_url() == "http://sbx-alpha-registry:8000"


def test_unresolvable_non_production_name_falls_back(monkeypatch):
    """THE BUG: any internal name that is not the one hardcoded literal."""
    _dns(monkeypatch, set())
    monkeypatch.setenv("CENTRAL_REGISTRY_URL", "http://sbx-alpha-registry:8000")
    assert opa._resolve_mainframe_url() == "https://api.theprotocol.cloud"


def test_generalisation_subsumes_the_old_literal(monkeypatch):
    """The replaced special case must still behave exactly as it did."""
    _dns(monkeypatch, set())
    monkeypatch.setenv("CENTRAL_REGISTRY_URL", "http://agentvault_registry_a:8000")
    assert opa._resolve_mainframe_url() == "https://api.theprotocol.cloud"


def test_public_fallback_is_per_node(monkeypatch):
    """A sandbox operator must fall back to ITS frame, never the production apex."""
    _dns(monkeypatch, set())
    monkeypatch.setenv("CENTRAL_REGISTRY_URL", "http://sbx-beta-registry:8000")
    monkeypatch.setenv("MAINFRAME_PUBLIC_URL", "https://sandbox-b.theprotocol.cloud")
    assert opa._resolve_mainframe_url() == "https://sandbox-b.theprotocol.cloud"


def test_unset_configured_url_uses_public(monkeypatch):
    _dns(monkeypatch, set())
    assert opa._resolve_mainframe_url() == "https://api.theprotocol.cloud"


def test_resolution_is_cached(monkeypatch):
    """A repeated miss must not re-pay the resolver timeout on every call."""
    calls = _dns(monkeypatch, set())
    monkeypatch.setenv("CENTRAL_REGISTRY_URL", "http://sbx-alpha-registry:8000")
    opa._resolve_mainframe_url()
    opa._resolve_mainframe_url()
    assert calls == ["sbx-alpha-registry"], f"expected one lookup, got {calls}"
