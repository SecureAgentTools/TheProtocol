"""D6-845 (agentvault2-d6, 2026-10-26, for V0645): the emission policy page's peer drift read "not read" for every peer.

_peer_rows dialled the peer's internal mTLS lane (_to_internal_mtls_url(peer.base_url)) at
/api/v1/agents/locations/emission-policies. That lane is the peer's nginx-federation, which routes only the federation
paths, so every peer answered 404 (found by agentvault2-5b's V0643 console proof on sbx-beta, 2026-10-26 ~09:45Z), while
each peer's public host answers 200 on the same public, unauthenticated route (read 2026-10-26 ~11:10Z: sandbox-a and
sandbox-b 288 rows, sbxalphaop and sbxbetaop 286). The read now goes to the peer's public address through the crawl client
every other public peer read uses (routers/agent_locations: verified TLS, no redirects, a name resolving to this host
dialled through its public address).

RED control: on V0644's code (c9239bd2) _peer_rows never calls _crawl_get, so the first three tests fail and the last one
finds the internal-lane import.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import types

from agentvault_registry.routers import agent_locations
from agentvault_registry.services import emission_policy_view as view


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class _Client:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _patch(monkeypatch, status=200, body=None, calls=None):
    calls = calls if calls is not None else []

    async def fake_get(client, base_url, path):
        calls.append((base_url, path))
        return _Resp(status, body if body is not None else {"policies": []})

    monkeypatch.setattr(agent_locations, "_crawl_get", fake_get)
    monkeypatch.setattr(agent_locations, "_crawl_client", lambda timeout: _Client())
    return calls


def _peer(url):
    return types.SimpleNamespace(base_url=url, name="peer", peer_type="frame")


def test_the_read_goes_to_the_peers_public_address(monkeypatch):
    rows = [{"event_type": "TokensTransferred", "emit_from_registry": True, "emit_from_teg": False, "skip_in_projection": False}]
    calls = _patch(monkeypatch, body={"policies": rows})
    got, why = asyncio.run(view._peer_rows(_peer("https://sandbox-a.theprotocol.cloud:8443")))
    assert calls == [("https://sandbox-a.theprotocol.cloud", "/api/v1/agents/locations/emission-policies")]
    assert why == "ok" and got == {"TokensTransferred": rows[0]}


def test_an_operator_peer_reads_its_own_public_host(monkeypatch):
    calls = _patch(monkeypatch)
    got, why = asyncio.run(view._peer_rows(_peer("https://sbxbetaop.op.theprotocol.cloud:8443/")))
    assert calls == [("https://sbxbetaop.op.theprotocol.cloud", "/api/v1/agents/locations/emission-policies")]
    assert why == "ok" and got == {}


def test_a_refusal_names_its_status_and_the_address(monkeypatch):
    _patch(monkeypatch, status=404)
    got, why = asyncio.run(view._peer_rows(_peer("https://asia.theprotocol.cloud:8443")))
    assert got is None and why == "answered 404 at https://asia.theprotocol.cloud"


def test_a_peer_with_no_public_name_is_not_dialled(monkeypatch):
    calls = _patch(monkeypatch)
    got, why = asyncio.run(view._peer_rows(_peer("http://sbx-alpha-nginx-federation:8443")))
    assert calls == [] and got is None and why == "no public address"


def test_the_internal_lane_is_not_dialled_for_this_read():
    tree = ast.parse(inspect.getsource(view._peer_rows))
    names = {n.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for n in node.names}
    assert "_to_internal_mtls_url" not in names and "svid_client" not in names
    assert {"_crawl_client", "_crawl_get", "_get_public_url"} <= names
