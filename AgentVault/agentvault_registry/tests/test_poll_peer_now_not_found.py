"""§MCPTEST30 (V0550): POST /admin/consul/peers/{peer_id}/poll-now answers a peer that does not exist with 404.

The compliance poller returns {"status": "error", "detail": "peer_id=999999 not found"} for an unknown peer and the
route passed it on with a 200, so pollPeerComplianceNow's nonexistent peer read as a success (agentvault2-45, pinning
the sweep's refusals). A skip (the peer is there, the poller declined) stays a 200.
"""
from __future__ import annotations

import asyncio
import types

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import consul_admin


class _Poller:
    def __init__(self, result):
        self.result = result

    async def force_single_peer_poll(self, peer_id, dry_run_only=True):
        return self.result


def _call(result, monkeypatch):
    monkeypatch.setattr(consul_admin, "get_compliance_poller", lambda: _Poller(result))
    admin = types.SimpleNamespace(email="admin@phase6.invalid")
    return asyncio.run(consul_admin.poll_peer_now(peer_id=999999, request=None, admin=admin))


def test_a_peer_that_does_not_exist_is_a_404(monkeypatch):
    with pytest.raises(HTTPException) as e:
        _call({"status": "error", "detail": "peer_id=999999 not found"}, monkeypatch)
    assert e.value.status_code == 404 and e.value.detail == "peer_id=999999 not found"


def test_controls_a_skip_and_a_poll_stay_answers(monkeypatch):
    assert _call({"status": "skipped", "detail": "peer is blacklisted"}, monkeypatch)["status"] == "skipped"
    assert _call({"status": "ok", "drift": False}, monkeypatch)["status"] == "ok"
    # an error that is not a missing peer is not turned into a 404
    assert _call({"status": "error", "detail": "fetch failed"}, monkeypatch)["status"] == "error"
