"""§MCPTEST30 (V0542): a console that cannot reach the store a sweep's events land in asks the target to run the poll.

Every cloud-op delta run recorded from EU's console read "local_emission: NOTHING VERIFIED" and "es_reachable: warn":
its events land in its operator's parent store, sbx-beta's, and EU cannot resolve sbx-beta-event-store ("Temporary failure
in name resolution", 111 event types), while the same run's peer facts, relayed through the target since §PEERVANTAGE,
read fine. The target answers the poll now (`/admin/mcp-tester/emissions-via-target`, no address taken), and a first pass
that reads nothing returns at once instead of waiting out the settle window on failing reads.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import mcp_tester as mt

DELTA = "flow_mcp_lifecycle_cloudop_sandboxdelta_complete"


def _request(body, key="good"):
    async def _json():
        return body
    return SimpleNamespace(headers={"X-Internal-Key": key}, json=_json)


@pytest.fixture
def target(monkeypatch):
    calls = []

    async def collect(since_iso, sweep_dids, *, expect_types=None, diag=None, flow_name=""):
        calls.append({"since": since_iso, "dids": set(sweep_dids), "types": list(expect_types or []), "flow": flow_name})
        diag["__url__"] = "http://sbx-beta-event-store:8200"
        return {"OrganizationCreated": {"present": True, "matched": True}}

    monkeypatch.setattr(mt, "_proxy_key_ok", lambda k: k == "good")
    monkeypatch.setattr(mt, "_collect_emissions", collect)
    return calls


async def test_the_target_answers_the_poll_for_the_named_flow(target):
    out = await mt.emissions_via_target(_request({"since": "2026-10-02T01:29:38+00:00", "dids": ["did:a", "did:b"],
                                                  "expect_types": ["OrganizationCreated"], "flow_name": DELTA}))
    assert out["seen"] == {"OrganizationCreated": {"present": True, "matched": True}}
    assert target == [{"since": "2026-10-02T01:29:38+00:00", "dids": {"did:a", "did:b"},
                       "types": ["OrganizationCreated"], "flow": DELTA}]


async def test_the_target_refuses_without_the_internal_key_and_takes_no_address(target):
    with pytest.raises(HTTPException) as ei:
        await mt.emissions_via_target(_request({"flow_name": DELTA}, key="wrong"))
    assert ei.value.status_code == 401 and target == []
    # an address in the body is not read: the store is the node's own mapping of the flow
    await mt.emissions_via_target(_request({"flow_name": DELTA, "store": "http://10.0.0.1:8200", "url": "http://x"}))
    assert set(target[-1]) == {"since", "dids", "types", "flow"}


async def test_the_target_caps_the_dids(target):
    with pytest.raises(HTTPException) as ei:
        await mt.emissions_via_target(_request({"dids": [f"did:{i}" for i in range(mt._RELAY_MAX_DIDS + 1)]}))
    assert ei.value.status_code == 422


class _Client:
    def __init__(self, answer):
        self.answer = answer

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        if isinstance(self.answer, Exception):
            raise self.answer
        code, body = self.answer
        return SimpleNamespace(status_code=code, json=lambda: body)


@pytest.mark.parametrize("answer, expect", [
    ((200, {"seen": {"OrganizationCreated": {"present": True, "matched": False}}, "diag": {"__url__": "u"}}),
     ({"OrganizationCreated": {"present": True, "matched": False}}, {"__url__": "u"})),
    ((401, {"detail": "internal key required"}), None),     # a target that will not answer
    ((200, {"seen": {}, "diag": {}}), None),                # a target that read nothing either
    (ConnectionError("refused"), None),                     # a target that does not answer at all
])
async def test_the_console_takes_the_targets_answer_or_none(monkeypatch, answer, expect):
    import httpx
    monkeypatch.setattr(mt, "API_TEST_TARGET_URL", "http://sbx-alpha-registry:8000")
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _Client(answer))
    assert await mt._emissions_via_target("2026-10-02T01:29:38+00:00", {"did:a"}, ["OrganizationCreated"], DELTA) == expect


async def test_a_first_pass_that_reads_nothing_does_not_wait_out_the_settle_window(monkeypatch):
    """The control on the waste: with a 60 s window and an unresolvable store, the poll returns at once and empty."""
    import httpx

    class _Down:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, *a, **k):
            raise httpx.ConnectError("[Errno -3] Temporary failure in name resolution")

    monkeypatch.setattr(mt, "_EMIT_SETTLE_S", 60.0)
    monkeypatch.setattr(mt, "_emission_store_for", lambda flow: ("http://sbx-beta-event-store:8200", "k"))
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _Down())
    diag = {}
    t0 = time.monotonic()
    out = await mt._collect_emissions("2026-10-02T01:29:38+00:00", {"did:a"}, expect_types=["OrganizationCreated"],
                                      diag=diag, flow_name=DELTA)
    assert out == {} and time.monotonic() - t0 < 5
    assert "Temporary failure in name resolution" in diag.get("OrganizationCreated", "")
