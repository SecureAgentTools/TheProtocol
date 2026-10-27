"""§MCPTEST30 (2026-10-01) — the run's own AGORA fixture at the end of its life.

lifecycle_admin_scratch_listing measures the three listing admin tools that were permanent skips on the listing phase 3
made for the run (approve recorded from phase 3; halt then resume, each read from the answer; delist), and
_retire_scratch_org deletes the organization that owns it. Measured before this: the teardown named the org by
`organization_id` while deleteOrganization takes `org_id`, so none was ever deleted (140 on sbx-alpha, 58 and 25 on the
sandbox operators), and a listing that is not delisted refuses the delete anyway.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from agentvault_registry.api_tests.contracts import mcp_admin_lifecycles as A
from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F


def _ok(obj, code="200"):
    return True, {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(obj)}]}}, code


def _refuse(code, detail):
    return False, {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text",
                                                                       "text": f"Error: HTTP {code}: {detail}"}],
                                                         "isError": True}}, str(code)


class Venue:
    def __init__(self, halt_noop=False, resume_fails=False):
        self.status, self.halt_noop, self.resume_fails, self.calls = "trading", halt_noop, resume_fails, []

    async def rpc(self, tool, args, jwt="", timeout=20):
        self.calls.append((tool, dict(args)))
        if tool == "theprotocol_adminAgoraHaltListing":
            if args["halted"] and not self.halt_noop:
                self.status = "halted"
            elif not args["halted"] and not self.resume_fails:
                self.status = "trading"
            return _ok({"symbol": args["listing_ref"], "status": self.status, "approved": True})
        if tool == "theprotocol_adminAgoraDelistListing":
            self.status = "delisted"
            return _ok({"listing_id": "lst-1", "orders_cancelled": 1, "symbol": args["listing_ref"]})
        return _refuse(404, "no fake")


class Bag:
    def __init__(self, **fv):
        self.developer_jwt = "admin-jwt"
        self.flow_values = dict(fv)


def _run(venue, bag):
    outcomes = {}
    asyncio.run(A.lifecycle_admin_scratch_listing(venue.rpc, F._parse_rpc_result, bag, outcomes))
    return outcomes


def test_the_runs_own_listing_is_halted_resumed_and_delisted_and_the_approve_is_recorded():
    venue = Venue()
    bag = Bag(scratch_listing="P3ABCD",
              scratch_listing_approve={"status": 200, "answer": {"symbol": "P3ABCD", "status": "trading", "approved": True}})
    out = _run(venue, bag)
    assert {k: v["healthy"] for k, v in out.items()} == {
        "theprotocol_adminAgoraApproveListing": True, "theprotocol_adminAgoraHaltListing": True,
        "theprotocol_adminAgoraDelistListing": True}
    assert [c[1].get("halted") for c in venue.calls if c[0].endswith("HaltListing")] == [True, False]
    assert venue.status == "delisted" and bag.flow_values["scratch_listing_delisted"] is True
    assert all(c[1]["listing_ref"] == "P3ABCD" for c in venue.calls), "only ever the run's own listing"
    assert all(v["probe_expect_status"] == "success" for v in out.values())


@pytest.mark.parametrize("kw,needle", [(dict(halt_noop=True), "not halted"), (dict(resume_fails=True), "resume did not")])
def test_a_halt_that_did_not_halt_or_a_resume_that_did_not_resume_is_a_bug_find(kw, needle):
    out = _run(Venue(**kw), Bag(scratch_listing="P3ABCD"))
    row = out["theprotocol_adminAgoraHaltListing"]
    assert row["healthy"] is False and row["fail_reason"].startswith("BUG-FIND") and needle in row["fail_reason"]


def test_no_scratch_listing_means_no_call_at_all():
    venue = Venue()
    assert _run(venue, Bag()) == {} and venue.calls == []


def test_the_retirement_names_org_id_delists_and_sweeps_a_funded_treasury(monkeypatch):
    calls, http = [], []
    state = {"deletes": 0}

    async def call(tool, args):
        calls.append((tool, dict(args)))
        state["deletes"] += 1
        if state["deletes"] == 1:
            return _refuse(409, '{"blockers": [{"kind": "funded_treasury", "balance": "1"}]}')
        return _ok({"message": "deleted"})

    async def call_admin(tool, args):
        calls.append((tool, dict(args)))
        return _ok({"listing_id": "l", "orders_cancelled": 0, "symbol": args["listing_ref"]})

    async def fake_http(container, method, path, **kw):
        http.append((method, path, kw.get("headers"), json.loads(kw["body"])))
        return "200", "{}"
    monkeypatch.setattr(F, "_http_in_target", fake_http)
    note = asyncio.run(F._retire_scratch_org("reg", call, call_admin, "org-1", "P3ABCD", "owner-jwt", "did:dest"))
    assert calls[0] == ("theprotocol_adminAgoraDelistListing", {"listing_ref": "P3ABCD"})
    assert calls[1] == ("theprotocol_deleteOrganization", {"org_id": "org-1"}), "the tool takes org_id"
    assert http == [("POST", "/api/v1/organizations/org-1/treasury/sweep", {"Idempotency-Key": "mcp-tester-retire-org-1"},
                     {"dest_agent_did": "did:dest"})]
    assert note == "delist HTTP 200; treasury sweep HTTP 200; organization delete HTTP 200"


def test_an_already_delisted_listing_is_not_delisted_twice_and_nothing_raises():
    calls = []

    async def call(tool, args):
        calls.append(tool)
        raise RuntimeError("transport down")

    async def call_admin(tool, args):
        calls.append(tool)
        return _ok({})
    note = asyncio.run(F._retire_scratch_org("reg", call, call_admin, "org-1", "P3ABCD", "j", "d", already_delisted=True))
    assert calls == ["theprotocol_deleteOrganization"] and "raised RuntimeError" in note


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
