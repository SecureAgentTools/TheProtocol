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
OWN = (422, "Error: HTTP 422: own_submission: a member never gives points to their own developer's work: 9.")


class _World:
    def __init__(self, *, ledger_moves=True, stays_closed=False, partial=False):
        self.ledger_moves, self.stays_closed, self.partial = ledger_moves, stays_closed, partial
        self.state = {}
        self.opens = 0
        self.award = {"id": 31, "status": "pending", "amount": "1.000000", "funded_amount": "0.000000"}
        self.balance = Decimal("5")
        self.seen = []

    def _season(self, sid):
        subs = [{"id": 9, "submitter_did": "did:theprotocol:sentinel", "status": "struck", "award": None},
                {"id": 77, "submitter_did": PEER, "status": "submitted",
                 "award": dict(self.award) if self.state.get(sid) in ("closed", "paid") else None}]
        return {"id": sid, "status": self.state.get(sid), "budget": "1.000000",
                "submissions": subs if sid == 4 else []}

    def answer(self, tool, args):
        sid = args.get("season_id")
        if tool == "theprotocol_getCommonsSeasons":
            return 200, {"seasons": [], "currency": "SBXA"}
        if tool == "theprotocol_adminCommonsOpenSeason":
            self.opens += 1
            new = 3 + self.opens
            self.state[new] = "open"
            return 201, {"id": new, "status": "open", "budget": "1.000000"}
        if tool == "theprotocol_getCommonsSeason":
            return 200, self._season(sid)
        if tool == "theprotocol_submitCommonsWork":
            return 201, {"id": 77 if args["agent_jwt"] == "peer-agent" else 9, "season_id": 4, "status": "submitted"}
        if tool == "theprotocol_getMyCommonsSeason":
            return 200, {"season_id": 4, "my_submissions": [{"id": 9}], "is_member": True}
        if tool == "theprotocol_castCommonsBallot":
            if args["allocations"] == {"9": 10}:
                return OWN
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
            return 200, {"id": sid, "status": "closed",
                         "tally": {"ballots_cast": 1, "ballots_counted": 1, "awarded": "1.000000", "unallocated": "0",
                                   "rows": [{"submission_id": 77, "voters": 1, "median_points": "10.000000",
                                             "share": "1", "amount": "1.000000", "capped": False}]}}
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
            return 200, {"did": PEER, "client_id": "cid", "client_secret": "csec"}
        if tool == "theprotocol_getAgentToken":
            return 200, {"access_token": "peer-agent", "token_type": "bearer"}
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


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
