"""§MCPTEST30 (2026-09-30) — a credential cached at MODULE level outlives the run that minted it.

The federation suite runs inside a long-lived gunicorn worker. `test_rbac_5cluster_matrix._DEV_CACHE` and
`test_operator_provisioning_flow._STATE` kept each test developer's JWT for the life of that worker, so the 03:10Z
nightly of 2026-09-30, landing on a worker an earlier run had used, presented expired tokens (ACCESS_TOKEN_EXPIRE_MINUTES
is 90) and reported every 401 as "foreign cluster returned non-403": seven hard failures that were the instrument's own
stale credential. Pinned here offline with a stub rig: a usable cached token is reused, an expiring one is re-minted, a
refused one is dropped, and a 401 is reported as the instrument's state, never as an RBAC verdict.
"""
from __future__ import annotations

import asyncio
import base64
import json
import time

import pytest

from agentvault_registry.api_tests.federation_suite import rig as R
from agentvault_registry.api_tests.federation_suite.tests import test_operator_provisioning_flow as OP
from agentvault_registry.api_tests.federation_suite.tests import test_rbac_5cluster_matrix as RB


def _jwt(sub: int, exp_in: float) -> str:
    def b(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{b({'alg': 'HS256'})}.{b({'sub': str(sub), 'exp': int(time.time() + exp_in)})}.sig"


def test_seconds_left_reads_exp_and_refuses_what_it_cannot_read():
    assert 3500 < R.jwt_seconds_left(_jwt(7, 3600)) <= 3600
    assert R.jwt_seconds_left(_jwt(7, -60)) < 0
    for junk in (None, "", "abc", "a.b", "a.%%%.c"):
        assert R.jwt_seconds_left(junk) is None
    assert R.jwt_usable(_jwt(7, 3600)) and not R.jwt_usable(_jwt(7, 200)) and not R.jwt_usable(_jwt(7, -1))
    assert not R.jwt_usable(None)


class StubClient:
    def __init__(self, token_for):
        self.token_for = token_for
        self.calls = []

    async def call(self, tool, args=None, **kw):
        self.calls.append(tool)
        if tool == "adminGetDeveloperToken":
            return {"access_token": self.token_for()}
        return {}


class StubRig:
    def __init__(self, client):
        self.client = client

    def mcp(self, label):
        return self.client


@pytest.fixture(autouse=True)
def _clean_caches():
    RB._DEV_CACHE.clear()
    OP._STATE.clear()
    yield
    RB._DEV_CACHE.clear()
    OP._STATE.clear()


def test_rbac_reuses_a_usable_token_and_remints_an_expiring_one():
    fresh = {"exp": 3600}
    client = StubClient(lambda: _jwt(41, fresh["exp"]))
    rig = StubRig(client)
    dev_id, tok1 = asyncio.run(RB._ensure_rbac_dev(rig, "admin_support"))
    assert dev_id == 41 and client.calls.count("adminGetDeveloperToken") == 1
    asyncio.run(RB._ensure_rbac_dev(rig, "admin_support"))
    assert client.calls.count("adminGetDeveloperToken") == 1, "a usable cached token must be reused"
    # the worker lives on; the cached token is now expired (the 03:10Z shape)
    RB._DEV_CACHE["admin_support"] = (41, _jwt(41, -120))
    _id, tok2 = asyncio.run(RB._ensure_rbac_dev(rig, "admin_support"))
    assert client.calls.count("adminGetDeveloperToken") == 2, "an expired cached token must be re-minted"
    assert R.jwt_usable(tok2)


def test_rbac_a_401_on_the_own_endpoint_is_the_instrument_and_drops_the_token(monkeypatch):
    client = StubClient(lambda: _jwt(42, 3600))
    rig = StubRig(client)
    codes = iter([401])

    async def probe(_rig, _jwt_, _endpoint):
        return next(codes, 403)

    monkeypatch.setattr(RB, "_probe_with_dev", probe)
    captured = {}

    async def assert_within(**kw):
        ok = await kw["predicate"]()
        captured["state"] = dict(kw["capture_state"]())
        return ok

    rig.assert_within = assert_within
    # federation_test registers a spec and returns the coroutine function itself
    ok = asyncio.run(RB.test_rbac_admin_support(rig))
    assert ok is False
    assert "instrument state, not an RBAC verdict" in captured["state"]["fail"]
    assert "admin_support" not in RB._DEV_CACHE, "a refused token must be dropped so the next attempt re-mints"


def test_operator_candidate_token_is_reminted_once_it_expires():
    client = StubClient(lambda: _jwt(275, 3600))
    rig = StubRig(client)
    asyncio.run(OP._ensure_candidate_dev(rig))
    asyncio.run(OP._ensure_candidate_dev(rig))
    assert client.calls.count("adminGetDeveloperToken") == 1
    OP._STATE["dev_jwt"] = _jwt(275, -30)
    _id, tok = asyncio.run(OP._ensure_candidate_dev(rig))
    assert client.calls.count("adminGetDeveloperToken") == 2 and R.jwt_usable(tok)
    assert OP._STATE.get("dev_id") == 275


def test_the_sentinel_mints_its_own_token_while_the_rest_of_the_file_reuses_it():
    """§MCPTEST30 2026-10-06: fed run 556a8afd came 65 min after 0d4f8bde on one worker; the sentinel took the cached
    candidate, made no call, and a pass with no probe reads vacuous (a red). The sentinel asks for a fresh mint."""
    client = StubClient(lambda: _jwt(275, 3600))
    rig = StubRig(client)
    asyncio.run(OP._ensure_candidate_dev(rig))
    asyncio.run(OP._ensure_candidate_dev(rig))
    assert client.calls.count("adminGetDeveloperToken") == 1, "the other tests keep reusing a usable token"

    async def assert_within(**kw):
        return await kw["predicate"]()

    rig.assert_within = assert_within
    assert asyncio.run(OP.test_candidate_bootstrap(rig)) is True
    assert client.calls.count("adminGetDeveloperToken") == 2, "the sentinel must mint, never hand back the cache"
    asyncio.run(OP._ensure_candidate_dev(rig))
    assert client.calls.count("adminGetDeveloperToken") == 2, "what the sentinel minted is the cache again"
