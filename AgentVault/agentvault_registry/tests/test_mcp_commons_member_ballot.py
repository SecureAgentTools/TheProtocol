"""§MCPTEST30 (V0552): the commons ballot's success path, measured on a second developer's work.

The season lifecycle held castCommonsBallot to its refusal only (the runner's own submission: own_submission, or
not_a_member). A member's points count only for ANOTHER developer's work, so the probe mints a throwaway developer,
verifies it through the admin bridge (a developer creates an agent only once verified), creates its agent, submits its
work to the run's own season, and the runner's sentinel gives that submission 10 points; the close must then tally the
ballot. Where the runner is no member, the target asks for a device confirmation, or the second developer cannot be made,
the two rows say NOT MEASURED and why; a ballot the route will not take, or a close that does not count it, fails.
"""
from __future__ import annotations

import asyncio
import types

import pytest

from agentvault_registry.api_tests.contracts import mcp_lifecycles as L
from agentvault_registry.api_tests.contracts import mcp_switches as M

VOTE, TALLY = "commons: " + L.COMMONS_VOTE_CHECK, "commons: " + L.COMMONS_TALLY_CHECK
OWN = (422, "Error: HTTP 422: own_submission: a member never gives points to their own developer's work: 9.")
NOT_MEMBER = (403, "Error: HTTP 403: not_a_member: only members vote. Bond an agent to become one.")


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def _fake_rpc(answers, seen, default_jwt=""):
    # V0614: the fake keeps the transport's own rule. /mcp/rpc answers 401 to a tools/call that carries no bearer,
    # whatever the tool's tier (mcp/server.py), and the runner's rpc sends none for jwt="" while its admin bridge falls
    # back to the run's developer token (default_jwt). A fake that took a bearer-less call let the commons probe's
    # getAgentToken(jwt="") pass here while it read NOT MEASURED on every real run.
    async def rpc(tool, args, jwt="", timeout=15):
        jwt = jwt or default_jwt
        seen.append((tool, dict(args), jwt))
        if not jwt:
            return False, {"jsonrpc": "2.0", "id": None, "error": {
                "code": -32001, "message": "Authentication required. Use OAuth or pass Bearer token."}}, "401"
        ans = answers[tool]
        if callable(ans):
            ans = ans(args)
        code, payload = ans
        if 200 <= int(code) < 300:
            return True, {"result": payload}, str(code)
        return False, {"result": {"_text": payload} if isinstance(payload, str) else payload}, str(code)
    return rpc


def _parse(body):
    return (body or {}).get("result") or {}


def _tally(counted=1, voters=1):
    return {"id": 4, "status": "closed",
            "tally": {"ballots_cast": 1, "ballots_counted": counted, "awarded": "0.000000", "unallocated": "1.000000",
                      "rows": [{"submission_id": 77, "voters": voters, "median_points": "10.000000", "share": "0",
                                "amount": "0.000000", "capped": False, "reason": "too_few_voters"}]}}


def _answers(**over):
    a = {
        "theprotocol_getCommonsSeasons": (200, {"seasons": [], "currency": "SBXA"}),
        "theprotocol_adminCommonsOpenSeason": (201, {"id": 4, "status": "open", "budget": "1.000000"}),
        "theprotocol_getCommonsSeason": lambda args: (200, {"id": 4, "status": _STATE["status"], "budget": "1.000000"}),
        # the runner's sentinel submits (id 9); the second developer's agent submits (id 77)
        "theprotocol_submitCommonsWork": lambda args: (201, {"id": 77 if args["agent_jwt"] == "peer-agent" else 9,
                                                             "season_id": 4, "status": "submitted"}),
        "theprotocol_getMyCommonsSeason": (200, {"season_id": 4, "my_submissions": [{"id": 9}], "is_member": True}),
        "theprotocol_castCommonsBallot": lambda args: (
            OWN if args["allocations"] == {"9": 10}
            else (200, {"season_id": 4, "allocations": dict(args["allocations"]), "total_points": 10, "digest": "ab12"})),
        "theprotocol_adminCommonsPaySeason": (409, "Error: HTTP 409: season_not_closed: season 4 is open."),
        "theprotocol_adminCommonsWriteOffAward": (409, "Error: HTTP 409: season_not_closed: season 4 is open."),
        "theprotocol_adminCommonsStrikeSubmission": (200, {"id": 9, "status": "struck"}),
        "theprotocol_adminCommonsCloseSeason": lambda args: _set("closed", 200, _tally()),
        "theprotocol_adminCommonsCancelSeason": lambda args: _set("cancelled", 200, {"id": 4, "status": "cancelled"}),
        "theprotocol_forceEmailVerify": (200, {"id": 501, "is_verified": True}),
        "theprotocol_createAgent": (200, {"did": "did:theprotocol:peer", "client_id": "cid", "client_secret": "csec"}),
        "theprotocol_getAgentToken": (200, {"access_token": "peer-agent", "token_type": "bearer"}),
        "theprotocol_requestAccountDeletion": (202, {"status": "pending_deletion"}),
    }
    a.update(over)
    return a


_STATE = {"status": "open"}


def _set(status, code, body):
    _STATE["status"] = status
    return code, body


def _run(answers, mint=True):
    _STATE["status"] = "open"
    seen, outcomes, minted = [], {}, []

    async def mint_throwaway(role):
        minted.append(role)
        return {"email": "peer@throwaway-pl.example.com", "password": "pw", "developer_id": "501",
                "access_token": "peer-dev"}

    async def dev_login(email, password):
        return "200", {"access_token": "peer-dev-again"}

    bag = types.SimpleNamespace(developer_jwt="dev", sentinel_jwt="sentinel",
                                rpc_admin=_fake_rpc(answers, seen, default_jwt="dev"),
                                admin_lifecycle_rows={}, event_verifier=None, flow_values={}, dev_login=dev_login)
    if mint:
        bag.mint_throwaway = mint_throwaway

    async def go():
        M.use_target({"commons_enabled": True})
        await L.lifecycle_commons_season(_fake_rpc(answers, seen), _parse, bag, outcomes)
    asyncio.run(go())
    return seen, outcomes, bag.admin_lifecycle_rows, minted


def test_a_member_ballot_for_another_developers_work_is_taken_and_tallied():
    seen, rows, admin, minted = _run(_answers())
    assert minted == ["commons"]
    assert rows[VOTE]["healthy"] and rows[TALLY]["healthy"], (rows[VOTE], rows[TALLY])
    tools = [t for t, _a, _j in seen]
    # the second developer is verified by an admin, makes its agent, submits; the runner votes; the run cancels; the
    # second developer asks for its own deletion last
    i = tools.index("theprotocol_forceEmailVerify")
    assert tools[i:i + 5] == ["theprotocol_forceEmailVerify", "theprotocol_createAgent", "theprotocol_getAgentToken",
                              "theprotocol_submitCommonsWork", "theprotocol_castCommonsBallot"]
    verify_args, verify_jwt = [(a, j) for t, a, j in seen if t == "theprotocol_forceEmailVerify"][0]
    assert verify_args == {"developer_id": 501} and verify_jwt == "dev", "the admin verifies, never the throwaway"
    create_jwt = [j for t, _a, j in seen if t == "theprotocol_createAgent"][0]
    assert create_jwt == "peer-dev", "the agent is the second developer's, made with its own credential"
    ballots = [a for t, a, _j in seen if t == "theprotocol_castCommonsBallot"]
    assert ballots[0]["allocations"] == {"9": 10} and ballots[1] == {"agent_jwt": "sentinel", "season_id": 4,
                                                                     "allocations": {"77": 10}}
    assert tools[-1] == "theprotocol_requestAccountDeletion"
    ev = rows[TALLY]["result_excerpt"]
    assert ev["ballots_counted"] == 1 and ev["row"]["voters"] == 1, ev
    assert rows[VOTE]["result_excerpt"]["submission_id"] == 77 and rows[VOTE]["result_excerpt"]["total_points"] == 10


def test_the_peer_agents_token_rides_the_second_developers_bearer():
    """V0614: getAgentToken is Tier 0, but /mcp/rpc refuses every bearer-less tools/call (401). The probe called it with
    jwt="", so both commons rows read NOT MEASURED on every nightly since V0552; it rides the second developer's own
    token now."""
    seen, rows, admin, minted = _run(_answers())
    assert [j for t, _a, j in seen if t == "theprotocol_getAgentToken"] == ["peer-dev"]
    assert "HTTP 401" not in str(rows[VOTE].get("skip_reason")), rows[VOTE]


def test_the_fake_refuses_a_bearerless_call_as_the_transport_does():
    # the control: the test above proves something only while this fake refuses what the transport refuses
    ok, body, code = asyncio.run(_fake_rpc(_answers(), [])("theprotocol_getAgentToken", {"client_id": "c"}))
    assert (ok, code) == (False, "401") and body["error"]["code"] == -32001
    ok, _body, code = asyncio.run(_fake_rpc(_answers(), [], default_jwt="dev")("theprotocol_getAgentToken", {}))
    assert (ok, code) == (True, "200"), "the admin bridge falls back to the run's developer token"


def test_a_runner_that_is_no_member_measures_nothing_and_mints_nobody():
    seen, rows, admin, minted = _run(_answers(**{"theprotocol_castCommonsBallot": NOT_MEMBER}))
    assert minted == [] and "theprotocol_createAgent" not in [t for t, _a, _j in seen]
    assert not rows[VOTE]["healthy"] and "not a member" in rows[VOTE]["skip_reason"]
    assert rows[TALLY]["skip_reason"] == rows[VOTE]["skip_reason"]
    # §MCPTEST30 (V0636): the refusal is held as before, on its own row; the tool's own row (the member's ballot) says
    # why it was not measured
    assert rows["refusal: castCommonsBallot a ballot for its own developer's submission"]["healthy"]
    assert not rows["theprotocol_castCommonsBallot"]["healthy"]
    assert "not a member" in rows["theprotocol_castCommonsBallot"]["skip_reason"]


def test_a_device_confirmation_is_named_not_failed():
    step_up = {"status": "step_up_required", "message": "confirm on your device", "step_up": {"challenge_id": "c1"},
               "next": "confirm"}
    answers = _answers(**{"theprotocol_castCommonsBallot": lambda args: (
        OWN if args["allocations"] == {"9": 10} else (200, step_up))})
    seen, rows, admin, minted = _run(answers)
    assert not rows[VOTE]["healthy"] and "presence" in rows[VOTE]["skip_reason"]
    assert rows[TALLY]["skip_reason"].startswith("NOT MEASURED: this target asks a member to confirm")


def test_a_refused_member_ballot_fails_and_a_close_that_does_not_count_it_is_a_finding():
    refused = _answers(**{"theprotocol_castCommonsBallot": lambda args: (
        OWN if args["allocations"] == {"9": 10} else (422, "Error: HTTP 422: unknown_submission: these are not live"))})
    seen, rows, admin, minted = _run(refused)
    assert not rows[VOTE]["healthy"] and not rows[VOTE]["skip_reason"]
    assert "did not take a member's ballot" in rows[VOTE]["fail_reason"]
    assert rows[TALLY]["skip_reason"] and not rows[TALLY]["healthy"]
    uncounted = _answers(**{"theprotocol_adminCommonsCloseSeason": lambda args: _set("closed", 200, _tally(counted=0))})
    seen, rows, admin, minted = _run(uncounted)
    assert rows[VOTE]["healthy"] and not rows[TALLY]["healthy"]
    assert rows[TALLY]["fail_reason"].startswith("BUG-FIND: commons: the member's accepted ballot was not counted")


def test_a_second_developer_that_cannot_make_an_agent_is_named():
    seen, rows, admin, minted = _run(_answers(**{"theprotocol_createAgent": (403, "Error: HTTP 403: Only verified "
                                                                                  "developers can request bootstrap tokens")}))
    assert not rows[VOTE]["healthy"] and "createAgent for the second developer answered HTTP 403" in rows[VOTE]["skip_reason"]
    assert "theprotocol_castCommonsBallot" in rows and [a for t, a, _j in seen if t == "theprotocol_castCommonsBallot"] == [
        {"agent_jwt": "sentinel", "season_id": 4, "allocations": {"9": 10}}]
    # the throwaway still asks for its own deletion
    assert [t for t, _a, _j in seen][-1] == "theprotocol_requestAccountDeletion"


def test_a_second_developer_the_mint_already_verified_is_used_as_it_is():
    """V0556: the admin rail answers 400 "already verified" for a throwaway the mint verified itself; that is the state
    the step wants (the 2026-10-03 nightly read both rows NOT MEASURED on that sentence)."""
    already = (400, "Error: HTTP 400: Developer email is already verified")
    seen, rows, admin, minted = _run(_answers(**{"theprotocol_forceEmailVerify": already}))
    assert rows[VOTE]["healthy"] and rows[TALLY]["healthy"], (rows[VOTE], rows[TALLY])
    tools = [t for t, _a, _j in seen]
    assert tools[tools.index("theprotocol_forceEmailVerify") + 1] == "theprotocol_createAgent"


def test_any_other_verify_refusal_still_names_why():
    refused = (403, "Error: HTTP 403: admin_users flag required")
    seen, rows, admin, minted = _run(_answers(**{"theprotocol_forceEmailVerify": refused}))
    assert not rows[VOTE]["healthy"] and "forceEmailVerify for the second developer answered HTTP 403" in rows[VOTE]["skip_reason"]
    assert "theprotocol_createAgent" not in [t for t, _a, _j in seen]


@pytest.mark.parametrize("answer,ok,starts", [
    (_tally(), True, None),
    (_tally(counted=0), False, "BUG-FIND: commons: the member's accepted ballot was not counted"),
    (_tally(voters=0), False, "BUG-FIND: commons: the tally has no voter for submission 77"),
    ({"id": 4, "status": "closed", "tally": {"ballots_cast": 1, "ballots_counted": 1, "rows": []}}, False,
     "BUG-FIND: commons: the tally has no voter"),
    ({"id": 4, "status": "closed", "tally": None}, False, "the closed season's answer carries no tally"),
    ({"id": 4, "status": "closed", "tally": {"rows": []}}, False, "the closed season's tally names no ballots_counted"),
])
def test_the_tally_judgement(answer, ok, starts):
    healthy, why, _ev = L.judge_commons_tally(answer, 77)
    assert healthy is ok
    if starts:
        assert why.startswith(starts)


def test_every_row_prefix_a_lifecycle_writes_reaches_the_results():
    # rows that name no tool are carried into the run only under a known prefix: the commons probe's first version was not
    # in the list, and its rows would have been dropped without a word. Every module-level prefix constant counts.
    import ast
    import inspect

    from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
    from agentvault_registry.api_tests.contracts import achievement_claims

    found = {L._COMMONS, achievement_claims.PREFIX}
    for node in ast.parse(inspect.getsource(L)).body:
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
                and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id.startswith("_")
                and node.value.value.endswith(": ") and node.value.value[:-2].replace("_", "").isalpha()):
            found.add(node.value.value)
    assert {"mcp_protocol: ", "owner_scoping: ", "commons: "} <= found, found
    missing = sorted(p for p in found if p not in F._SYNTHETIC_ROW_PREFIXES)
    assert not missing, f"lifecycle row prefixes the flow would drop: {missing}"
