"""§MCPTEST30 (tester batch 2 item 3, agentvault2-d3, Guild order gwo_e3bad842b1a5943022b01d40): on a target torn down
after its run, the season lifecycle PAYS the closed season it opened.

adminCommonsPaySeason and adminCommonsWriteOffAward were held to their refusal on the open season only (both refusal-only
on the sbx-alpha nightly of 2026-10-31, run 60e40b9afff04e7c). On a pair (MCP_TESTER_EPHEMERAL_TARGET) the closed
season's award (the member's ballot for the second developer's work) is held to write-off's rule (award_not_failed: only
a payment that failed or never answered is written off, and a healthy target never gives a run one), then paid: the
answer, the season and the award read paid and the recipient's balance on the event store's own projection grew by what
was funded. A paid season cannot be cancelled (season_settled, a refusal row); the cancel's own success is measured on a
second, empty season of the run's own. A standing frame keeps today's lifecycle. RED on the code before: nothing pays.
"""
from __future__ import annotations

import asyncio
import types
from decimal import Decimal

import pytest

from agentvault_registry.api_tests.contracts import mcp_lifecycles as L
from agentvault_registry.api_tests.contracts import mcp_switches as M
from agentvault_registry.api_tests.contracts.earned_ad_ephemeral import EPHEMERAL_ENV

PAY, WRITE_OFF, CANCEL = ("theprotocol_adminCommonsPaySeason", "theprotocol_adminCommonsWriteOffAward",
                          "theprotocol_adminCommonsCancelSeason")
PAY_ROW = "admin_effect: adminCommonsPaySeason"
WRITE_OFF_ROW = "refusal: adminCommonsWriteOffAward an award that was never sent"
CANCEL_ROW = "refusal: adminCommonsCancelSeason a season that was paid"
PEER = "did:theprotocol:peer"
MEMBER = "did:theprotocol:member-of-the-run"   # V0651 (tester batch 3 item 2): a member of the run's own, on a pair
MEMBER2 = "did:theprotocol:second-member-of-the-run"   # the second: a submission needs two voters to be funded
NOT_A_MEMBER = (403, "Error: HTTP 403: not_a_member: Only members of this registry can do this. A member is a developer "
                     "with an agent holding the reputation bond here, funded by the agent or the owner's wallet, at "
                     "least 30 days old (GOVERNANCE_WEIGHT_MODE=member).")
OWN = (422, "Error: HTTP 422: own_submission: a member never gives points to their own developer's work: 9.")


class _World:
    def __init__(self, *, ledger_moves=True, stays_closed=False, partial=False, runner_member=True,
                 member_age_rule=False, deposit_refused=False, min_voters=2, refuse_ballot_of=()):
        self.ledger_moves, self.stays_closed, self.partial = ledger_moves, stays_closed, partial
        # V0652: the world keeps the server's rule (services/commons.tally): submission 77 is funded, and the closed
        # season names its award, only when min_voters distinct members gave it points. Before, this fake awarded any
        # closed season, so the run's one-ballot season of V0651's pair proof (the runner itself a member, nobody
        # else: too_few_voters) passed here while its pay read NOT MEASURED on the pair.
        self.min_voters, self.refuse_ballot_of = min_voters, tuple(refuse_ballot_of)
        self.ballots = {}
        # V0651: whether the runner's developer is a member here, whether the target keeps the 30-day bond age (a pair
        # without batch 3's NIGHTLY_FLAGS), whether the member's own deposit is refused
        self.runner_member, self.member_age_rule, self.deposit_refused = runner_member, member_age_rule, deposit_refused
        self.deposits = []
        self.state = {}
        self.opens = 0
        self.award = {"id": 31, "status": "pending", "amount": "1.000000", "funded_amount": "0.000000"}
        self.balance = Decimal("5")
        self.seen = []

    def voters_for_77(self):
        return sum(1 for alloc in self.ballots.values() if int(alloc.get("77", 0)) > 0)

    def funded(self):
        return self.voters_for_77() >= self.min_voters

    def _season(self, sid):
        subs = [{"id": 9, "submitter_did": "did:theprotocol:sentinel", "status": "struck", "award": None},
                {"id": 77, "submitter_did": PEER, "status": "submitted",
                 "award": dict(self.award) if self.state.get(sid) in ("closed", "paid") and self.funded() else None}]
        return {"id": sid, "status": self.state.get(sid), "budget": "1.000000", "min_voters": self.min_voters,
                "submissions": subs if sid == 4 else []}

    def answer(self, tool, args):
        sid = args.get("season_id")
        if tool == "theprotocol_getCommonsSeasons":
            return 200, {"seasons": [], "currency": "SBXA"}
        if tool == "theprotocol_adminCommonsOpenSeason":
            self.opens += 1
            new = 3 + self.opens
            self.state[new] = "open"
            return 201, {"id": new, "status": "open", "budget": "1.000000", "min_voters": self.min_voters}
        if tool == "theprotocol_getCommonsSeason":
            return 200, self._season(sid)
        if tool == "theprotocol_submitCommonsWork":
            return 201, {"id": 77 if args["agent_jwt"] == "peer-agent" else 9, "season_id": 4, "status": "submitted"}
        if tool == "theprotocol_getMyCommonsSeason":
            return 200, {"season_id": 4, "my_submissions": [{"id": 9}], "is_member": True}
        if tool == "theprotocol_castCommonsBallot":
            if args["agent_jwt"] == "sentinel" and not self.runner_member:
                return NOT_A_MEMBER
            if args["agent_jwt"].startswith("member") and self.member_age_rule:
                return NOT_A_MEMBER
            if args["agent_jwt"] in self.refuse_ballot_of:
                return 409, "Error: HTTP 409: season_not_open: season 4 is closed."
            if args["allocations"] == {"9": 10}:
                return OWN
            self.ballots[args["agent_jwt"]] = dict(args["allocations"])   # one per member, replaceable
            return 200, {"season_id": 4, "allocations": dict(args["allocations"]), "total_points": 10, "digest": "ab"}
        if tool == WRITE_OFF:
            if self.state[sid] == "open":
                return 409, f"Error: HTTP 409: season_not_closed: season {sid} is open."
            return 409, (f"Error: HTTP 409: award_not_failed: award {args['award_id']} is pending and was never sent; "
                         "only a payment that failed or never answered is written off.")
        if tool == PAY:
            if self.state[sid] != "closed":
                return 409, f"Error: HTTP 409: season_not_closed: season {sid} is {self.state[sid]}."
            funded = "0.500000" if self.partial else "1.000000"
            if not self.stays_closed and not self.partial:
                self.state[sid] = "paid"
            self.award.update(status="partial" if self.partial else "paid", funded_amount=funded)
            if self.ledger_moves:
                self.balance += Decimal(funded)
            return 200, {"season": {"id": sid, "status": self.state[sid]},
                         "payments": [{"recipient_did": PEER, "amount": "1.000000", "funded": funded,
                                       "status": "partial" if self.partial else "paid"}],
                         "unpaid_awards": 0 if not self.partial else 1, "needs_decision": []}
        if tool == "theprotocol_adminCommonsStrikeSubmission":
            return 200, {"id": 9, "status": "struck"}
        if tool == "theprotocol_adminCommonsCloseSeason":
            self.state[sid] = "closed"
            n, funded = self.voters_for_77(), self.funded()
            return 200, {"id": sid, "status": "closed",
                         "tally": {"ballots_cast": len(self.ballots), "ballots_counted": len(self.ballots),
                                   "awarded": "1.000000" if funded else "0", "unallocated": "0" if funded else "1",
                                   "rows": [{"submission_id": 77, "voters": n,
                                             "median_points": "10.000000" if funded else "0",
                                             "share": "1" if funded else "0", "amount": "1.000000" if funded else "0",
                                             "capped": False, "reason": None if funded else "too_few_voters"}]}}
        if tool == CANCEL:
            if self.state[sid] == "paid":
                return 409, f"Error: HTTP 409: season_settled: season {sid} is paid."
            self.state[sid] = "cancelled"
            return 200, {"id": sid, "status": "cancelled"}
        if tool == "theprotocol_adminQueryEventStore":
            assert args["path"] == f"/api/v1/projections/balance/{PEER}"
            return 200, {"status_code": 200, "response": {"liquid_balance": str(self.balance)}}
        if tool == "theprotocol_forceEmailVerify":
            return 200, {"id": 501, "is_verified": True}
        if tool == "theprotocol_createAgent":
            if args["name"].startswith("mcp-commons-member-2-"):
                return 200, {"did": MEMBER2, "client_id": "member2-cid", "client_secret": "member2-csec"}
            for n in range(3, 7):
                if args["name"].startswith(f"mcp-commons-member-{n}-"):
                    return 200, {"did": f"{MEMBER}-{n}", "client_id": f"member{n}-cid", "client_secret": "x-csec"}
            if args["name"].startswith("mcp-commons-member-"):
                return 200, {"did": MEMBER, "client_id": "member-cid", "client_secret": "member-csec"}
            return 200, {"did": PEER, "client_id": "cid", "client_secret": "csec"}
        if tool == "theprotocol_getAgentToken":
            if args["client_id"] == "member-cid":
                return 200, {"access_token": "member-agent", "token_type": "bearer"}
            if args["client_id"].startswith("member") and args["client_id"].endswith("-cid"):
                return 200, {"access_token": args["client_id"][:-4] + "-agent", "token_type": "bearer"}
            return 200, {"access_token": "peer-agent", "token_type": "bearer"}
        if tool == "theprotocol_adminRequest":
            if (args["method"], args["endpoint"]) == ("GET", "/api/v1/reputation-bond/config"):
                return 200, {"status_code": 200, "ok": True, "response": {"mode": "enforce", "amount": "250.000000"}}
            if (args["method"], args["endpoint"]) == ("POST", "/api/v1/teg/treasury/fund-agent"):
                b = args["body"]
                assert b["target_agent_did"].startswith(MEMBER) or b["target_agent_did"] == MEMBER2
                assert b["reason"] == "admin_grant"
                assert Decimal(b["amount"]) >= Decimal("252.5"), "the bond and its margin"
                return 200, {"status_code": 200, "ok": True, "response": {"status": "completed"}}
            raise AssertionError(args)
        if tool == "theprotocol_depositReputationBond":
            assert args["agent_jwt"].startswith("member"), "a member bonds itself, from its own balance"
            self.deposits.append(args["amount"])
            if self.deposit_refused:
                return 400, "Error: HTTP 400: insufficient_balance: the agent holds less than the bond."
            return 200, {"bond_id": 3, "amount": "250.000000", "status": "locked", "message": "Bond locked"}
        if tool == "theprotocol_requestAccountDeletion":
            return 202, {"status": "pending_deletion"}
        raise AssertionError(tool)

    def rpc(self, default_jwt=""):
        async def rpc(tool, args, jwt="", timeout=15):
            code, payload = self.answer(tool, dict(args))
            self.seen.append((tool, dict(args)))
            if 200 <= int(code) < 300:
                return True, {"result": payload}, str(code)
            return False, {"result": {"_text": payload} if isinstance(payload, str) else payload}, str(code)
        return rpc


def _parse(body):
    return (body or {}).get("result") or {}


def _run(w: _World, monkeypatch, *, pair=True):
    if pair:
        monkeypatch.setenv(EPHEMERAL_ENV, "true")
    else:
        monkeypatch.delenv(EPHEMERAL_ENV, raising=False)

    async def fast(_s):
        return None
    monkeypatch.setattr(asyncio, "sleep", fast)

    async def mint_throwaway(role):
        if role == "commons-member":
            return {"email": "member@throwaway-pl.example.com", "password": "pw2", "developer_id": "502",
                    "access_token": "member-dev"}
        if role == "commons-member-2":
            return {"email": "member2@throwaway-pl.example.com", "password": "pw3", "developer_id": "503",
                    "access_token": "member2-dev"}
        if role.startswith("commons-member-"):
            n = role.rsplit("-", 1)[1]
            return {"email": f"member{n}@throwaway-pl.example.com", "password": f"pw{n}", "developer_id": f"50{n}",
                    "access_token": f"member{n}-dev"}
        return {"email": "peer@throwaway-pl.example.com", "password": "pw", "developer_id": "501",
                "access_token": "peer-dev"}

    async def dev_login(email, password):
        return "200", {"access_token": "peer-dev-again"}
    bag = types.SimpleNamespace(developer_jwt="dev", sentinel_jwt="sentinel", rpc_admin=w.rpc("dev"),
                                admin_lifecycle_rows={}, event_verifier=None, flow_values={}, dev_login=dev_login,
                                mint_throwaway=mint_throwaway)
    outcomes = {}

    async def go():
        M.use_target({"commons_enabled": True})
        await L.lifecycle_commons_season(w.rpc(), _parse, bag, outcomes)
    asyncio.run(go())
    return outcomes, bag.admin_lifecycle_rows


def _ok(row):
    return bool(row) and row.get("healthy") and not row.get("skip_reason") and not row.get("fail_reason")


def test_a_pair_pays_its_season_and_measures_the_cancel_on_a_second_one(monkeypatch):
    w = _World()
    rows, admin = _run(w, monkeypatch)
    for name in (PAY_ROW, WRITE_OFF_ROW, CANCEL_ROW):
        assert _ok(rows.get(name)), (name, rows.get(name))
    assert _ok(admin.get(CANCEL)), admin.get(CANCEL)
    assert w.state == {4: "paid", 5: "cancelled"} and w.balance == Decimal("6")
    tools = [t for t, _a in w.seen]
    assert tools.count(PAY) == 2, "the open season's refusal, then the closed season's payment"
    assert tools.index(WRITE_OFF, tools.index("theprotocol_adminCommonsCloseSeason")) < tools.index(
        PAY, tools.index("theprotocol_adminCommonsCloseSeason")), "the write-off is held to its rule before the payment"


def test_a_standing_frame_pays_nothing(monkeypatch):
    w = _World()
    rows, admin = _run(w, monkeypatch, pair=False)
    assert PAY_ROW not in rows and CANCEL_ROW not in rows
    assert w.state == {4: "cancelled"} and w.balance == Decimal("5")
    assert [t for t, _a in w.seen].count(PAY) == 1, "only the refusal on the open season"


@pytest.mark.parametrize("world,needle", [
    ({"ledger_moves": False}, "the ledger did not record the payment"),
    ({"stays_closed": True}, "season status='closed'"),
    ({"partial": True}, "unpaid_awards=1"),
])
def test_a_payment_the_reads_do_not_show_is_a_finding(monkeypatch, world, needle):
    w = _World(**world)
    rows, admin = _run(w, monkeypatch)
    row = rows[PAY_ROW]
    assert not row["healthy"] and needle in str(row.get("fail_reason")), row
    if w.state.get(4) == "paid":
        # the season IS paid, whatever the read-back found: its cancel stays the refusal row, never a red cancel
        assert _ok(rows.get(CANCEL_ROW)) and _ok(admin.get(CANCEL)), (rows.get(CANCEL_ROW), admin.get(CANCEL))


# ── V0651 (tester batch 3 item 2): a member of the run's own, on a pair ─────────────────────────────────────────────────
def _ballots(w):
    return [a for t, a in w.seen if t == "theprotocol_castCommonsBallot"]


def test_a_pair_without_a_member_makes_its_own_and_pays(monkeypatch):
    w = _World(runner_member=False)
    rows, admin = _run(w, monkeypatch)
    assert _ok(rows.get(PAY_ROW)), rows.get(PAY_ROW)
    assert _ok(rows.get("theprotocol_castCommonsBallot")), rows.get("theprotocol_castCommonsBallot")
    assert [b["agent_jwt"] for b in _ballots(w)] == ["sentinel", "member-agent", "member2-agent"], \
        "refused, then the run's member, then its second (a submission is funded with two voters)"
    assert w.deposits == [250, 250] and w.state == {4: "paid", 5: "cancelled"}
    deletions = [t for t, _a in w.seen if t == "theprotocol_requestAccountDeletion"]
    assert len(deletions) == 3, "the second developer and both members ask for their deletion"
    assert "member-csec" not in repr(rows) and "member-agent" not in repr(rows) and "member2-agent" not in repr(rows)


def test_a_standing_frame_without_a_member_makes_none(monkeypatch):
    w = _World(runner_member=False)
    rows, admin = _run(w, monkeypatch, pair=False)
    assert "not a member on this target" in str(rows["theprotocol_castCommonsBallot"].get("skip_reason"))
    assert w.deposits == [] and PAY_ROW not in rows
    assert not [a for t, a in w.seen if t == "theprotocol_createAgent" and a["name"].startswith("mcp-commons-member-")]


def test_a_member_the_age_rule_refuses_is_said_not_failed(monkeypatch):
    w = _World(runner_member=False, member_age_rule=True)
    rows, admin = _run(w, monkeypatch)
    why = str(rows["theprotocol_castCommonsBallot"].get("skip_reason"))
    assert "GOVERNANCE_MEMBER_MIN_BOND_AGE_DAYS" in why and not rows["theprotocol_castCommonsBallot"].get("fail_reason")
    assert PAY_ROW not in rows and w.state.get(4) == "cancelled"


def test_a_refused_deposit_is_said(monkeypatch):
    w = _World(runner_member=False, deposit_refused=True)
    rows, admin = _run(w, monkeypatch)
    why = str(rows["theprotocol_castCommonsBallot"].get("skip_reason"))
    assert "no member of the run's own could be made" in why and "bond deposit answered HTTP 400" in why, why
    assert len(_ballots(w)) == 1, "no ballot without a member"


# ── V0652: the season's voter minimum, whoever the run's first voter is (the V0651 pair proof nt261101x1) ─────────────
def _deletions(w):
    return [t for t, _a in w.seen if t == "theprotocol_requestAccountDeletion"]


def test_a_pair_where_the_runner_is_a_member_adds_a_voter_of_its_own_and_pays(monkeypatch):
    """V0651's proof: the runner's agents bonded from their own funds (production's posture, no backstop), so its
    developer was a member, the run made no member of its own, and the season closed on one ballot (too_few_voters):
    its pay read NOT MEASURED. RED before: the run casts the runner's ballot alone and nothing is paid."""
    w = _World()
    rows, admin = _run(w, monkeypatch)
    assert [(b["agent_jwt"], b["allocations"]) for b in _ballots(w)] == [
        ("sentinel", {"9": 10}), ("sentinel", {"77": 10}), ("member2-agent", {"77": 10})], _ballots(w)
    assert _ok(rows.get(PAY_ROW)), rows.get(PAY_ROW)
    assert w.deposits == [250] and w.state == {4: "paid", 5: "cancelled"} and w.balance == Decimal("6")
    assert len(_deletions(w)) == 2, "the second developer and the run's member ask for their deletion"
    assert "member2-agent" not in repr(rows) and "member2-csec" not in repr(rows)


def test_a_standing_frame_where_the_runner_is_a_member_makes_no_member(monkeypatch):
    w = _World()
    rows, admin = _run(w, monkeypatch, pair=False)
    assert not [a for t, a in w.seen if t == "theprotocol_createAgent" and a["name"].startswith("mcp-commons-member")]
    assert w.deposits == [] and PAY_ROW not in rows and len(_ballots(w)) == 2


def test_a_voter_of_its_own_that_cannot_be_made_is_said_on_the_pay_row(monkeypatch):
    w = _World(deposit_refused=True)
    rows, admin = _run(w, monkeypatch)
    row = rows[PAY_ROW]
    why = str(row.get("skip_reason"))
    assert not row.get("healthy") and not row.get("fail_reason"), row
    assert "1 of the 2 voters a submission needs" in why and "member 2 of the run's own could not be made" in why, why
    assert "bond deposit answered HTTP 400" in why, why
    assert _ok(rows.get("theprotocol_castCommonsBallot")), "the runner's own ballot was taken"
    assert w.state.get(4) == "cancelled", "an unpaid season is still given back"


def test_a_refused_ballot_of_a_member_of_its_own_is_said(monkeypatch):
    w = _World(refuse_ballot_of=("member2-agent",))
    rows, admin = _run(w, monkeypatch)
    why = str(rows[PAY_ROW].get("skip_reason"))
    assert "1 of the 2 voters" in why and "member 2's ballot answered HTTP 409" in why, why


def test_a_season_that_needs_three_voters_gets_two_of_its_own(monkeypatch):
    w = _World(min_voters=3)
    rows, admin = _run(w, monkeypatch)
    assert [b["agent_jwt"] for b in _ballots(w)] == ["sentinel", "sentinel", "member2-agent", "member3-agent"]
    assert _ok(rows.get(PAY_ROW)), rows.get(PAY_ROW)
    assert w.deposits == [250, 250] and len(_deletions(w)) == 3


def test_a_pair_without_a_member_that_needs_three_voters_makes_three(monkeypatch):
    w = _World(runner_member=False, min_voters=3)
    rows, admin = _run(w, monkeypatch)
    assert [b["agent_jwt"] for b in _ballots(w)] == ["sentinel", "member-agent", "member2-agent", "member3-agent"]
    assert _ok(rows.get(PAY_ROW)), rows.get(PAY_ROW)
    assert len(_deletions(w)) == 4


def test_the_season_minimum_is_read_from_the_season():
    assert L._season_min_voters({"min_voters": 3}) == 3
    assert L._season_min_voters({"min_voters": 1}) == 1
    for bad in ({}, {"min_voters": 0}, {"min_voters": "3"}, {"min_voters": True}, None, []):
        assert L._season_min_voters(bad) == 2, bad


def test_the_fake_keeps_the_servers_voter_rule():
    # the control: the tests above prove something only while one voter funds nothing here, as on the server
    w = _World()
    w.ballots = {"sentinel": {"77": 10}}
    assert not w.funded() and w._season(4)["submissions"][1]["award"] is None
    w.ballots["member2-agent"] = {"77": 10}
    w.state[4] = "closed"
    assert w.funded() and w._season(4)["submissions"][1]["award"]["status"] == "pending"


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
