"""§pass47 B1 — Unit tests for `_to_internal_mtls_url`.

The helper rewrites peer-cached public URLs to forms reachable from inside
agentvault_identity_network on port 8443. The cluster-host shortcut and the
DNS-gate fallback together cover the cases that caused §pass38e and §pass44
incidents — these tests pin the contract so future refactors don't regress.

These tests don't require a database, FastAPI app, or network — they hit the
helper directly with synthetic URLs.
"""
from __future__ import annotations

import sys
import pathlib
from unittest.mock import patch


_PROJ_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJ_ROOT / "src"))


def _h():
    """Import the helper lazily so this test file can be discovered without
    a full registry import context (the helper itself only needs urllib + socket)."""
    from agentvault_registry.routers.teg_integration import _to_internal_mtls_url
    return _to_internal_mtls_url


def test_cluster_host_api_theprotocol_cloud_rewritten_to_8443():
    """Frame A mainframe alias — must hit nginx-a on the identity network."""
    assert _h()("https://api.theprotocol.cloud/api/v1/teg") == "https://api.theprotocol.cloud:8443"


def test_cluster_host_frame_b_rewritten_to_8443():
    """Frame B mainframe alias."""
    assert _h()("https://frame-b.theprotocol.cloud/x") == "https://frame-b.theprotocol.cloud:8443"


def test_cluster_host_op_subdomain_rewritten_to_8443():
    """Cloud-op via .op. subdomain — alias on identity network at :8443."""
    assert _h()("https://op-paris.op.theprotocol.cloud/api") == "https://op-paris.op.theprotocol.cloud:8443"
    assert _h()("https://op-tokyo.op.theprotocol.cloud:30000/x") == "https://op-tokyo.op.theprotocol.cloud:8443"


def test_frame_b_op_subdomain_rewritten_to_op_then_8443():
    """Frame B operators carry .frame-b.theprotocol.cloud — rewrite to .op. then 8443."""
    assert _h()("https://op-paris.frame-b.theprotocol.cloud/x") == "https://op-paris.op.theprotocol.cloud:8443"


def test_legacy_aliases_rewritten_to_api_then_8443():
    """Pre-Sovereign aliases `registry.theprotocol.cloud`, `agentvault-nginx-a`,
    `nginx-a` map to `api.theprotocol.cloud:8443`."""
    for legacy in (
        "https://registry.theprotocol.cloud/x",
        "https://agentvault-nginx-a/x",
        "https://nginx-a:8443/x",
    ):
        assert _h()(legacy) == "https://api.theprotocol.cloud:8443", legacy


def test_empty_url_passthrough():
    assert _h()("") == ""


def test_unparseable_url_passthrough():
    # `urlparse` returns an object with hostname=None for these.
    assert _h()("not-a-url") == "not-a-url"


def test_unknown_public_host_with_rfc1918_resolution_falls_through_to_8443():
    """If host resolves to a private IP it's reachable on the identity network,
    so :8443 rewrite applies even for non-cluster hosts."""
    with patch("agentvault_registry.routers.teg_integration._is_rfc1918", return_value=True), \
         patch("socket.gethostbyname", return_value="172.16.1.5"):
        assert _h()("https://strange.example/api") == "https://strange.example:8443"


def test_unknown_public_host_with_public_ip_returns_original():
    """Non-cluster + non-RFC1918 → return the original public_url unchanged
    (legacy DNS-gate behavior preserved)."""
    with patch("agentvault_registry.routers.teg_integration._is_rfc1918", return_value=False), \
         patch("socket.gethostbyname", return_value="93.184.216.34"):
        assert _h()("https://strange.example/api") == "https://strange.example/api"


def test_dns_failure_returns_original():
    """If hostname doesn't resolve at all, fall through to original URL —
    don't crash, the caller will get the network error itself."""
    import socket as _s
    with patch("socket.gethostbyname", side_effect=_s.gaierror):
        assert _h()("https://ghost.example/api") == "https://ghost.example/api"
