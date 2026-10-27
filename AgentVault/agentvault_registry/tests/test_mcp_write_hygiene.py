"""§MCPTEST30 (V0525, 2026-10-01) — the write-hygiene probe (api_tests/contracts/write_hygiene.py): hostile text into a
team name, an API key name and a webhook description; a server error is the finding, every object made is removed.
Measured by hand on sbx-alpha (V0521): a NUL in a team name and in an API key name answered 500; V0524 answers 422."""
from __future__ import annotations

import asyncio
import json

from agentvault_registry.api_tests.contracts import write_hygiene as WH


def _ans(ok, inner, code):
    return bool(ok)


def test_the_values_carry_the_runs_tag():
    vals = dict(WH.hostile("abc12345"))
    assert set(vals) == {"nul", "escape", "long"}
    assert all(v.startswith("mcp-hyg-abc12345") for v in vals.values())
    assert "\x00" in vals["nul"] and vals["escape"].endswith("%_\\") and len(vals["long"]) > 4000


def test_the_kinds_and_the_verdict():
    assert WH.kind_of(True, {"id": 1}, "200", _ans) == ("stored", None)
    assert WH.kind_of(False, {"_text": "Error: HTTP 422: A text value carries a NUL character"}, "422", _ans) == ("refused", 422)
    assert WH.kind_of(False, {"_text": "Error: createApiKey failed (HTTP 500): A database error occurred"}, "500", _ans)[0] == "server_error"
    ok, s, ev = WH.verdict({"nul": ("server_error", 500), "escape": ("stored", None), "long": ("refused", 422)}, 0)
    assert ok is False and "(nul)" in s and ev["nul"] == "server_error HTTP 500"
    ok, s, ev = WH.verdict({"nul": ("refused", 422), "escape": ("stored", None), "long": ("refused", 422)}, 1)
    assert ok is True and ev["litter"] == 1
    assert WH.verdict({"nul": ("no_answer", None), "escape": ("no_answer", None), "long": ("no_answer", None)}, 0)[0] is None


def _outcome(name, tier, ok, code, ms, fail, inner, expect_status="success", skip_reason=None):
    return {"tool": name, "healthy": ok and not skip_reason, "error": fail, "skip_reason": skip_reason}


class _Bag:
    developer_jwt = "dev"
    flow_values = {"organization_id": "org-1"}


def test_the_run_removes_every_object_it_made():
    teams, keys, hooks = {}, {}, {}

    async def rpc(tool, args, jwt="", timeout=30):
        await asyncio.sleep(0)
        if tool == "theprotocol_createOrganizationTeam":
            if "\x00" in args["name"]:
                return False, {"_text": "Error: HTTP 422: A text value carries a NUL character"}, "422"
            if len(args["name"]) > 255:
                return False, {"_text": "Error: HTTP 422: String should have at most 255 characters"}, "422"
            tid = f"t{len(teams)}"; teams[tid] = args["name"]
            return True, {"id": tid}, "200"
        if tool == "theprotocol_listOrganizationTeams":
            return True, [{"id": t, "name": n} for t, n in teams.items()], "200"
        if tool == "theprotocol_deleteOrganizationTeam":
            teams.pop(args["team_id"]); return True, {}, "200"
        if tool == "theprotocol_createApiKey":
            if len(args["key_name"]) > 200:
                return False, {"_text": "Error: key_name must be at most 200 chars"}, "200"
            kid = len(keys) + 1; keys[kid] = args["key_name"]
            return True, {"api_key_info": {"id": kid}}, "200"
        if tool == "theprotocol_getMyApiKeys":
            return True, {"api_keys": [{"id": k, "description": n, "is_active": True} for k, n in keys.items()]}, "200"
        if tool == "theprotocol_revokeApiKey":
            keys.pop(args["key_id"]); return True, {}, "200"
        if tool == "theprotocol_createWebhook":
            assert args["url"].endswith(".invalid/hook")
            wid = f"w{len(hooks)}"; hooks[wid] = args["url"]
            return True, {"id": wid}, "200"
        if tool == "theprotocol_getMyWebhooks":
            return True, {"webhooks": [{"id": w, "url": u} for w, u in hooks.items()]}, "200"
        if tool == "theprotocol_deleteWebhook":
            hooks.pop(args["webhook_id"]); return True, {}, "200"
        raise AssertionError(tool)

    out = {}
    asyncio.run(WH.run_write_hygiene(rpc, lambda b: b, _Bag(), out, _outcome, _ans))
    assert sorted(out) == ["write_hygiene: createApiKey", "write_hygiene: createOrganizationTeam", "write_hygiene: createWebhook"]
    assert all(r["healthy"] for r in out.values()), out
    assert teams == {} and keys == {} and hooks == {}, "every object the probe made is removed again"
    assert "mcp-hyg-" not in json.dumps(out)


def test_no_organization_skips_only_the_team():
    class Bare:
        developer_jwt = "dev"
        flow_values = {}

    async def rpc(tool, args, jwt="", timeout=30):
        return False, {"_text": "Error: HTTP 422: no"}, "422"

    out = {}
    asyncio.run(WH.run_write_hygiene(rpc, lambda b: b, Bare(), out, _outcome, _ans))
    assert out["write_hygiene: createOrganizationTeam"]["skip_reason"].startswith("NOT MEASURED")
    assert out["write_hygiene: createApiKey"]["healthy"] is True


def test_the_lifecycle_is_registered_and_its_rows_are_synthetic():
    from agentvault_registry.api_tests.contracts import mcp_lifecycles as L
    from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
    assert any(e["name"] == "write_hygiene" and e["runner"] is L.lifecycle_write_hygiene for e in L.LIFECYCLES)
    assert WH.PREFIX in F._SYNTHETIC_ROW_PREFIXES
