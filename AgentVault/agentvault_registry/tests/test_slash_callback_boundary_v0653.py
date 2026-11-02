"""V0653 (am), item 9 (the hardening list in the sessions' room): a slash request's callback must be UNDER a registered
peer's base URL, with a '/' boundary.

federation_disputes.receive_slash_request's Step 0 compared the callback with each ACTIVE peer's base_url by a bare
string prefix, so https://peer.example.evil.test/... passed for the peer https://peer.example. It asks _is_under now, the
same rule the slash routes use for their caller's own addresses. Moot while the request's SPIFFE bind holds (the triage),
hardened all the same. The route is called as test_settlement_origin_address.py calls it; the fake database answers the
peer rows, then stops the request at its next read, so a callback that passed Step 0 shows as that stop. BASE
(a5ef48ddd, V0652): the look-alike host passes Step 0.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import federation_disputes as fd

PEER = "https://peer.example"
SPIFFE = "spiffe://peer.example/service/peer-registry"


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _PastStep0(Exception):
    pass


class _Db:
    def __init__(self):
        self.reads = 0

    async def execute(self, *a, **k):
        self.reads += 1
        if self.reads == 1:
            return _Rows([(PEER,), ("https://other.example:844/",)])
        raise _PastStep0()


def _req(callback):
    return fd.SlashRequest(settlement_id="s-1", dispute_id=50, ruling="IN_FAVOR_OF_COMPLAINANT", amount=3,
                           complainant_did="did:c", defendant_did="did:d", origin_registry_url=PEER, callback_url=callback)


@pytest.mark.parametrize("callback", [
    "https://peer.example.evil.test/api/v1/federation/disputes/slash-confirmation",
    "https://peer.examplex/api/v1/federation/disputes/slash-confirmation",
    "https://other.example:8443/api/v1/federation/disputes/slash-confirmation",   # a peer at :844, not :8443
])
async def test_a_look_alike_host_is_refused_at_step_0(callback):
    with pytest.raises(HTTPException) as e:
        await fd.receive_slash_request(_req(callback), SPIFFE, _Db())
    assert e.value.status_code == 400
    assert str(e.value.detail).startswith("Callback URL must belong to a registered peer registry")


@pytest.mark.parametrize("callback", [
    "https://peer.example/api/v1/federation/disputes/slash-confirmation",
    "https://PEER.example/api/v1/federation/disputes/slash-confirmation",
    "https://other.example:844/api/v1/federation/disputes/slash-confirmation",
])
async def test_control_a_callback_under_a_peer_passes_step_0(callback):
    with pytest.raises(_PastStep0):
        await fd.receive_slash_request(_req(callback), SPIFFE, _Db())
