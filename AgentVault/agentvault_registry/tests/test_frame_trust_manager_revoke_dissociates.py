"""§HELLOFRAME (2026-09-18): a frame revoke removes the peer's SPIRE bundle even though the frame's own workload entries
federate with it. SPIRE's default deletion mode (restrict) refuses such a delete, so the revoke rail reported
`spire_bundle_remove_ok: false` on every approved pair (measured on sbx-alpha: "cannot delete bundle; federated with 7
registration entries") and the peer's root stayed in every proxy's bundle. The manager now deletes with -mode dissociate."""
import asyncio

import pytest

from agentvault_registry.services import frame_trust_manager as ftm


def _manager():
    return ftm.FrameTrustManager(spire_container="x-spire-server", local_trust_domain="x.example.org")


def test_remove_peer_bundle_dissociates_the_entries(monkeypatch):
    seen = []

    async def fake_exec(container, cmd, *, timeout=0, stdin_data=None):
        seen.append((container, list(cmd)))
        return 0, "bundle deleted.", ""

    monkeypatch.setattr(ftm, "_run_docker_exec", fake_exec)
    res = asyncio.run(_manager().remove_peer_bundle("hello.example.org"))
    assert res.ok, res.message
    assert len(seen) == 1
    container, cmd = seen[0]
    assert container == "x-spire-server"
    assert cmd[:3] == [ftm.SPIRE_BIN_PATH, "bundle", "delete"]
    assert cmd[cmd.index("-mode") + 1] == "dissociate"
    assert cmd[cmd.index("-id") + 1] == "spiffe://hello.example.org"


def test_remove_peer_bundle_reports_a_refusal(monkeypatch):
    async def fake_exec(container, cmd, *, timeout=0, stdin_data=None):
        return 1, "", 'Error: failed to delete federated bundle "spiffe://hello.example.org": datastore-sql: cannot delete bundle; federated with 7 registration entries'

    monkeypatch.setattr(ftm, "_run_docker_exec", fake_exec)
    res = asyncio.run(_manager().remove_peer_bundle("hello.example.org"))
    assert not res.ok and "federated with 7 registration entries" in res.message


def test_remove_peer_bundle_not_found_is_success(monkeypatch):
    async def fake_exec(container, cmd, *, timeout=0, stdin_data=None):
        return 1, "", "Error: bundle not found"

    monkeypatch.setattr(ftm, "_run_docker_exec", fake_exec)
    assert asyncio.run(_manager().remove_peer_bundle("hello.example.org")).ok
