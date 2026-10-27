"""§MCPTEST30 (V0524, 2026-10-01) — the unique-name probe (api_tests/contracts/unique_race.py): one team name asked twice
at once, twice in a row, and again after its team was deleted. One team and one refusal; never a server error."""
from __future__ import annotations

import asyncio
import json

from agentvault_registry.api_tests.contracts import unique_race as UR

def _ans(ok, inner, code):
    return bool(ok)


def test_the_kinds():
    assert UR.kind_of(True, {"id": "t1"}, "200", _ans) == ("created", None)
    assert UR.kind_of(False, {"_text": "Error: HTTP 409: A team named x already exists"}, "409", _ans) == ("refused", 409)
    assert UR.kind_of(False, {"_text": "Error: createOrganizationTeam returned HTTP 500: A database error occurred"},
                      "500", _ans) == ("server_error", 500)
    assert UR.kind_of(False, {}, "000", _ans) == ("no_answer", None)


def test_the_verdicts():
    ok, s, _ = UR.verdict("concurrent", [("created", None), ("refused", 409)])
    assert ok is True and s is None
    ok, s, _ = UR.verdict("concurrent", [("created", None), ("server_error", 500)])
    assert ok is False and s.startswith("BUG-FIND: race: concurrent:")
    ok, s, _ = UR.verdict("concurrent", [("created", None), ("created", None)])
    assert ok is False and "gave 2 teams" in s
    assert UR.verdict("sequential", [("created", None), ("refused", 409)])[0] is True
    assert UR.verdict("sequential", [("created", None), ("created", None)])[0] is False
    assert UR.verdict("after_delete", [("created", None)])[0] is True
    ok, s, _ = UR.verdict("after_delete", [("refused", 409)])
    assert ok is False and "stayed taken" in s
    assert UR.verdict("after_delete", [("server_error", 500)])[0] is False
    assert UR.verdict("sequential", [("no_answer", None), ("refused", 409)])[0] is None


def _outcome(name, tier, ok, code, ms, fail, inner, expect_status="success", skip_reason=None):
    return {"tool": name, "healthy": ok and not skip_reason, "error": fail, "skip_reason": skip_reason}


class _Bag:
    developer_jwt = "dev"
    flow_values = {"organization_id": "org-1"}


def test_the_run_against_a_registry_that_checks_names_and_frees_deleted_ones():
    teams = {}   # id -> [name, active]

    async def rpc(tool, args, jwt="", timeout=30):
        await asyncio.sleep(0)
        if tool == "theprotocol_createOrganizationTeam":
            if any(n == args["name"] and a for n, a in teams.values()):
                return False, {"_text": "Error: HTTP 409: A team with this name already exists"}, "409"
            tid = f"t{len(teams) + 1}"
            teams[tid] = [args["name"], True]
            return True, {"id": tid, "name": args["name"]}, "200"
        if tool == "theprotocol_listOrganizationTeams":
            return True, [{"id": t, "name": n} for t, (n, a) in teams.items() if a], "200"
        if tool == "theprotocol_deleteOrganizationTeam":
            teams[args["team_id"]][1] = False
            return True, {"ok": True}, "200"
        raise AssertionError(tool)

    out = {}
    asyncio.run(UR.run_race(rpc, lambda b: b, _Bag(), out, _outcome, _ans))
    assert sorted(out) == ["race: createOrganizationTeam after_delete", "race: createOrganizationTeam concurrent",
                           "race: createOrganizationTeam sequential"]
    assert all(r["healthy"] for r in out.values()), out
    assert not any(a for _n, a in teams.values()), "every team the probe made is deleted again"
    blob = json.dumps(out)
    assert "mcp-race-" not in blob and "mcp-seq-" not in blob


def test_the_run_against_a_registry_that_lets_the_index_answer():
    async def rpc(tool, args, jwt="", timeout=30):
        if tool == "theprotocol_createOrganizationTeam":
            return False, {"_text": "Error: createOrganizationTeam returned HTTP 500: A database error occurred"}, "500"
        return True, [], "200"

    out = {}
    asyncio.run(UR.run_race(rpc, lambda b: b, _Bag(), out, _outcome, _ans))
    assert all(r["healthy"] is False and r["error"].startswith("BUG-FIND: race:") for r in out.values())


def test_no_organization_is_not_measured():
    class Bare:
        developer_jwt = "dev"
        flow_values = {}

    out = {}
    asyncio.run(UR.run_race(None, None, Bare(), out, _outcome, _ans))
    assert len(out) == 3 and all(r["skip_reason"].startswith("NOT MEASURED") for r in out.values())
