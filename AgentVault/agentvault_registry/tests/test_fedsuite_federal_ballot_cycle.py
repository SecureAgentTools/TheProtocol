"""§MCPTEST30 (V0555, 2026-10-03): the cross-frame governance row drives §MEMBERSHIP D2's federal ballots, two-phase.

His word: "check if you can fix cross frame governance now that we already worked on the voting. it was broken". The
row was red by design as §FEDPROOF F7 (an elevated proposal lived in the home's store; the peer tallied its own).
With FEDERATION_BALLOT_MODE=on a federation proposal is decided by registries, one signed ballot each, and a
member-mode registry's ballot is its members' result from an hour-long vote, so the row FINISHES the oldest cycle the
peer has not cast in and STARTS one when none is pending (agentvault2-33's spec). Pinned offline with a scripted rig:
what each phase asks, in which order, and what it must never ask (a tally before both ballots, a veto, a second
cycle while one is pending).
"""
from __future__ import annotations

import json

import pytest

from agentvault_registry.api_tests.federation_suite.rig import PreconditionUnmet
from agentvault_registry.api_tests.federation_suite.tests import test_federation_mechanisms_driven as drv

FID, LID = "11111111-2222-3333-4444-555555555555", 4242
HOME_NAME = "Sandbox Beta"


class _Script:
    """A rig's REST and MCP answers, by (method, endpoint prefix, label); every call is recorded."""

    def __init__(self, *, mode=True, open_=None, cast=None, tally=None, can_vote=True, elevate_ballot=True):
        self.calls = []
        self.mode, self.open_ = mode, open_ or []
        self.cast = cast or (201, {"recorded": True, "choice": "for",
                                   "basis": {"mode": "members", "voters": 1, "points_for": 10.0, "points_against": 0.0}})
        self.tally = tally or (200, {"ballot_mode": True, "status": "PASSED", "cast": 2, "eligible": 3, "for": 2,
                                     "against": 0, "abstain": 0, "quorum_met": True, "participation_met": True,
                                     "multi_registry_met": True, "two_thirds_met": True, "not_counted": []})
        self.can_vote, self.elevate_ballot = can_vote, elevate_ballot

    async def rest(self, rig, method, endpoint, *, label="sandbox-A-admin", body=None, jwt=None):
        self.calls.append((method, endpoint, label, json.dumps(body, sort_keys=True) if body is not None else None))
        if endpoint == "/api/v1/governance/federation-ballots":
            hosts = [{"host": "self", "name": "x", "proposals": []}]
            if label == "sandbox-A-admin":
                hosts.append({"host": HOME_NAME, "name": HOME_NAME, "proposals": self.open_, "error": None})
            return 200, {"ballot_mode": self.mode, "hosts": hosts}
        if endpoint == "/api/v1/admin/federation/ballots" and label == "sandbox-A-admin":
            return self.cast
        if endpoint == "/api/v1/admin/federation/ballots" and label == "sandbox-B-admin":
            return 201, {"recorded": True, "host": "self", "choice": "for", "basis": {"mode": "operator"}}
        if endpoint.endswith("/tally"):
            return self.tally
        if endpoint == "/api/v1/governance/federation/propose":
            return 201, {"id": "99999999-0000-0000-0000-000000000000", "ballot_mode": self.elevate_ballot}
        if endpoint == "/api/v1/admin/federation/ballots/local-vote":
            return 201, {"local_proposal_id": LID, "ends_at": "2026-10-03T05:00:00+00:00"}
        if endpoint == "/api/v1/governance/voting-power":
            return 200, {"canVote": self.can_vote or any("reputation-bond" in c[1] for c in self.calls),
                         "votingPower": 10.0, "membership": {"missing": [] if self.can_vote else ["bond"]}}
        if endpoint.startswith("/api/v1/agents/") and endpoint.endswith("/authz/roles"):
            return 200, {"roles": ["trader", "client", "governor"]}
        if endpoint.endswith("/vote"):
            return 200, {"voting_power": 10.0}
        return 200, {"status": "locked"}

    async def call(self, rig, label, tool, args):
        self.calls.append(("MCP", tool, label, None))
        return {"client_id": "c", "client_secret": "s", "did": "did:theprotocol:voter"}, None

    def asked(self, needle):
        return [c for c in self.calls if needle in c[1]]


@pytest.fixture()
def script(monkeypatch):
    holder = {}

    def use(**kw):
        sc = _Script(**kw)
        holder["s"] = sc
        monkeypatch.setattr(drv, "_rest", sc.rest)
        monkeypatch.setattr(drv, "_call", sc.call)

        async def _cycle(rig):
            return {"at": 0, "notes": {"home": "sandbox-B", "peer": "sandbox-A-admin", "proposal_id": 77,
                                       "local_status": "PASSED"}}

        async def _switches(rig, label):
            return {"governance_weight_mode": "member" if label == "sandbox-A" else "lock"}

        async def _name(rig, label):
            return HOME_NAME

        async def _jwt(rig, label, cid, sec, tag):
            return "agent.jwt.value"
        monkeypatch.setattr(drv, "_policy_cycle", _cycle)
        monkeypatch.setattr(drv, "target_switches", _switches)
        monkeypatch.setattr(drv, "_card_name", _name)
        monkeypatch.setattr(drv, "_agent_jwt", _jwt)
        return sc
    return use


async def _run():
    # awaited, never asyncio.run(): a sync test that runs a loop leaves the next file without one
    return await drv.test_elevation_reaches_the_peer_floor(object())


def _open(cast_here=False, fid=FID, end="2026-10-04T03:00:00+00:00"):
    return {"id": fid, "title": "federation suite: standard quorum 10 to 11 (probe, restored after)",
            "end_timestamp": end, "cast_here": cast_here}


async def test_switched_off_reads_not_measured_and_asks_nothing(script):
    sc = script(mode=False)
    with pytest.raises(PreconditionUnmet, match="switched_off"):
        await _run()
    assert not sc.asked("/federation/propose") and not sc.asked("/tally") and not sc.asked("/admin/federation/ballots")


async def test_no_pending_cycle_starts_one_and_tallies_nothing(script):
    sc = script(open_=[])
    with pytest.raises(PreconditionUnmet, match="cycle_started"):
        await _run()
    elevate = sc.asked("/federation/propose")
    assert len(elevate) == 1 and '"duration_seconds": 172800' in elevate[0][3] and elevate[0][2] == "sandbox-B-admin"
    lv = sc.asked("/ballots/local-vote")
    assert len(lv) == 1 and lv[0][2] == "sandbox-A-admin" and f'"host": "{HOME_NAME}"' in lv[0][3]
    assert [c[1] for c in sc.calls if c[1].endswith("/vote")] == [f"/api/v1/governance/proposals/{LID}/vote"]
    assert not sc.asked("/tally") and not sc.asked("/veto")
    assert not sc.asked("reputation-bond"), "a developer that already is a member bonds nothing"
    roles = sc.asked("/authz")
    assert [(c[0], c[1].rsplit("/", 2)[-2:], c[3]) for c in roles] == [("POST", ["authz", "roles"], '{"role": "governor"}')], \
        "governor is added through the one-role rail, no other grant touched"


async def test_a_cycle_whose_members_vote_is_open_waits_and_starts_no_other(script):
    sc = script(open_=[_open()], cast=(409, {"error": "local_vote_open", "ends_at": "2026-10-03T05:00:00+00:00"}))
    with pytest.raises(PreconditionUnmet, match="cycle_pending.*closes at 2026-10-03T05:00"):
        await _run()
    assert not sc.asked("/tally") and not sc.asked("/federation/propose")


async def test_a_finished_cycle_is_green_and_the_next_one_starts(script):
    sc = script(open_=[_open()])
    r = await _run()
    assert r.passed, r.failure_detail
    order = [c[1] for c in sc.calls if c[1] in ("/api/v1/admin/federation/ballots",) or c[1].endswith("/tally")
             or c[1] == "/api/v1/governance/federation/propose"]
    assert order == ["/api/v1/admin/federation/ballots", "/api/v1/admin/federation/ballots",
                     f"/api/v1/governance/federation/proposals/{FID}/tally", "/api/v1/governance/federation/propose"]
    peer_cast, home_cast = [c for c in sc.calls if c[1] == "/api/v1/admin/federation/ballots"]
    assert peer_cast[2] == "sandbox-A-admin" and '"choice"' not in peer_cast[3], "the members decide; no choice is sent"
    assert home_cast[2] == "sandbox-B-admin" and '"choice": "for"' in home_cast[3] and '"host": "self"' in home_cast[3]
    assert not sc.asked("/veto")


async def test_a_failed_tally_is_red_with_the_ballots_in_the_sentence(script):
    script(open_=[_open()], tally=(200, {"ballot_mode": True, "status": "FAILED", "cast": 1, "eligible": 3, "for": 1,
                                         "multi_registry_met": False}))
    r = await _run()
    assert not r.passed and "FAILED" in r.failure_detail and FID in r.failure_detail


async def test_a_peer_ballot_no_member_voted_in_is_not_its_members_result(script):
    script(open_=[_open()], cast=(201, {"recorded": True, "choice": "abstain",
                                        "basis": {"mode": "members", "voters": 0, "points_for": 0.0}}))
    r = await _run()
    assert not r.passed and "not its members' result" in r.failure_detail


async def test_a_second_pending_cycle_is_finished_first_and_none_is_started(script):
    sc = script(open_=[_open(fid="22222222-0000-0000-0000-000000000000", end="2026-10-05T03:00:00+00:00"),
                       _open(end="2026-10-04T03:00:00+00:00")])
    r = await _run()
    assert r.passed
    assert sc.asked(f"/federation/proposals/{FID}/tally"), "the OLDEST cycle is finished"
    assert not sc.asked("/federation/propose"), "no new cycle while another is pending"


async def test_a_peer_that_already_cast_is_not_asked_again(script):
    sc = script(open_=[_open(cast_here=True)])
    with pytest.raises(PreconditionUnmet, match="cycle_started"):
        await _run()
    assert not [c for c in sc.calls if c[1] == "/api/v1/admin/federation/ballots"]


async def test_a_developer_that_is_no_member_bonds_once_from_the_agents_own_wallet(script):
    sc = script(open_=[], can_vote=False)
    with pytest.raises(PreconditionUnmet, match="cycle_started"):
        await _run()
    bond = sc.asked("reputation-bond")
    assert len(bond) == 1 and '"funder_did": "did:theprotocol:voter"' in bond[0][3]
    assert sc.asked("/teg/treasury/fund-agent")
