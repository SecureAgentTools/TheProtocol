"""§MCPTEST30 (V0636): the admin platform tools on objects the run made, or on a frame setting written back as it
reads (agentvault2-aa; step 2 of sessionlogs2026/BACKLOG_2026-10-19_MCP_REFUSAL_ONLY_PASSES.md).

On V0635 each of these passed on one refusal (404 for an id that names nothing). Here:

  broadcasts      a broadcast of the run's own: updateBroadcast (its body reads the new text), retractBroadcast
                  (is_active false), reinstateBroadcast (true again); retracted at the end, whatever happened
  bundle report   a bundle a developer of the run made, reported by a second developer of the run, the report
                  dismissed by dismissBundleReport (listAdminBundlesReports reads it resolved); the bundle deleted
  emission        setEventEmissionPolicy writes one policy row back with the values it reads (no change)
  API tester      testApiEndpoint on a public read of the target, /public/registry-config (the route answers what
                  that read answered)
  canaries        toggleCanaryPath twice on the first active path (inactive, then active again: the second toggle
                  runs whatever happened in between) and fireCanaryPath on it (scheduled: getCanaryResults reads a
                  fire after it); the canary runner fires the same path on its own schedule. On a follower (every
                  cloud operator) or a paused fleet no runner fires it: since V0637 the route says so (409), a
                  refusal row, and the fire is NOT MEASURED there, said

The diagnostics tools (runAllDiagnostics, runDiagnosticsSubset, triggerDiagnosticAction) need no lifecycle here: the
admin lifecycle command_center_self runs them on the frame itself, and the sweep keeps those successes as
`earned: <tool>` beside their pinned refusals (test_flow_mcp_lifecycle.kept_lifecycle_rows).

Not here: uploadRegistryCardIcon (it replaces the frame's own icon on its signed card; the run never does),
adminGrafanaQuery (no Grafana is wired to a sandbox frame: the tool says so), generateTutorialProof and
adminRevokeAttestation (recorded by the zk v2 lifecycle on its own proofs, agentvault2-66).
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.contracts.earned_fixtures import (
    Throwaways, effect, effect_name, effect_unmeasured, lc, own_developer_id, refusal_step, said, step,
)
from agentvault_registry.api_tests.federation_suite.broadcast_cleanup import composed_id

ADMIN = "admin"
TOOLS = ("theprotocol_updateBroadcast", "theprotocol_retractBroadcast", "theprotocol_reinstateBroadcast",
         "theprotocol_dismissBundleReport", "theprotocol_setEventEmissionPolicy", "theprotocol_testApiEndpoint",
         "theprotocol_toggleCanaryPath", "theprotocol_fireCanaryPath")
# a write-back never touches a row the supply invariant depends on, even with its own values
_MONEY_EVENTS = {"TokensTransferred", "TokensIssued", "TokensStaked", "TokensUnstaked", "TransactionFeeCollected",
                 "CrossRegistryTransferCompleted", "RewardsDistributed", "TokensBurned", "LedgerBalanceChanged"}


async def _admin_read(bag: Any, parse: Any, tool: str, args: Dict[str, Any]) -> Tuple[bool, Any, str]:
    rpc_admin = getattr(bag, "rpc_admin", None)
    if rpc_admin is None:
        return False, {}, ""
    ok, body, code = await rpc_admin(tool, args, jwt=bag.developer_jwt, timeout=30)
    inner = parse(body) if isinstance(body, dict) else {}
    return bool(ok), inner, str(code)


def _bug(outcomes: Dict[str, dict], tool: str, why: str) -> None:
    lc()._bugfind(outcomes, effect_name(tool), "admin_effect", f"{tool.replace('theprotocol_', '')}: {why}")


def _passed(outcomes: Dict[str, dict], tool: str) -> bool:
    row = outcomes.get(effect_name(tool))
    return bool(row and row.get("healthy"))


def _rows(v: Any, *keys: str) -> List[Dict[str, Any]]:
    """The list an answer carries: itself, or under one of `keys` (an MCP list answer may be wrapped)."""
    if isinstance(v, list):
        return [r for r in v if isinstance(r, dict)]
    if isinstance(v, dict):
        for k in keys:
            if isinstance(v.get(k), list):
                return [r for r in v[k] if isinstance(r, dict)]
    return []


async def lifecycle_earn_platform_admin(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    """The admin platform tools (the module docstring), each part on its own so one failing part leaves the rest."""
    if getattr(bag, "rpc_admin", None) is None:
        for tool in TOOLS:
            effect_unmeasured(outcomes, tool, "this flow carries no admin bridge (bag.rpc_admin)")
        return
    for part, tools in ((_broadcast, TOOLS[:3]), (_bundle_report, TOOLS[3:4]), (_emission_policy, TOOLS[4:5]),
                        (_api_tester, TOOLS[5:6]), (_canary, TOOLS[6:8])):
        try:
            await part(rpc, parse, bag, outcomes)
        except Exception as e:                                         # noqa: BLE001
            for tool in tools:
                if effect_name(tool) not in outcomes:
                    effect_unmeasured(outcomes, tool, f"the lifecycle raised {type(e).__name__}: {str(e)[:160]} "
                                                      f"before it reached this tool")


async def _broadcast_row(bag: Any, parse: Any, bid: int) -> Optional[Dict[str, Any]]:
    ok, ans, _c = await _admin_read(bag, parse, "theprotocol_getAdminBroadcasts", {})
    for r in _rows(ans, "broadcasts", "items", "results"):
        if r.get("id") == bid:
            return r
    return None


async def _settle_retracted(bag: Any, parse: Any, bid: int, outcomes: Dict[str, dict]) -> None:
    """The run's own broadcast ends retracted, read back; asked once more; a broadcast still live is said on the
    retract's row. §MCPTEST30 V0639 (agentvault2-aa, 2026-10-24): the final retract's answer was never read, and after
    the reinstate step a retract that missed left the broadcast live on the console's header: six on the two sandbox
    operators (one per run, 01:28Z to 13:44Z), none on the frames, while every run read clean. The route itself worked
    when asked again (204, inactive)."""
    row: Optional[Dict[str, Any]] = None
    for attempt in range(2):
        await _admin_read(bag, parse, "theprotocol_retractBroadcast", {"broadcast_id": bid})
        row = await _broadcast_row(bag, parse, bid)
        if row is not None and row.get("is_active") is False:
            return
        if attempt == 0:
            await asyncio.sleep(2)
    _bug(outcomes, "theprotocol_retractBroadcast",
         f"the run's own broadcast {bid} reads is_active={(row or {}).get('is_active')!r} after its final retract, "
         f"asked twice: it stays on the console's header until an administrator retracts it")


async def _broadcast(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    tag = int(time.time())
    own = own_developer_id(bag)
    if own is None:
        for tool in TOOLS[:3]:
            effect_unmeasured(outcomes, tool, "the run names no developer of its own to address its broadcast to, and a "
                                              "broadcast to every developer of the federation is not the run's to send")
        return
    ok, ans, code = await _admin_read(bag, parse, "theprotocol_composeBroadcast", {
        "title": "MCP tester: a broadcast of its own",
        "body": "The MCP tester made this to update, retract and reinstate it; it is retracted again at once.",
        "broadcast_type": "info", "target_developer_id": own})
    bid = composed_id(ans) if ok else None
    if not bid:
        for tool in TOOLS[:3]:
            effect_unmeasured(outcomes, tool, f"no broadcast of the run's own could be composed (HTTP {code})")
        return
    try:
        new_body = f"The MCP tester updated its own broadcast ({tag}); it is retracted again at once."
        tool = "theprotocol_updateBroadcast"
        await effect(bag, parse, tool, {"broadcast_id": bid, "body": new_body}, outcomes)
        if _passed(outcomes, tool):
            r = await _broadcast_row(bag, parse, bid)
            if r is None or r.get("body") != new_body:
                _bug(outcomes, tool, f"the broadcast's body reads {(r or {}).get('body')!r:.80} afterwards")
        tool = "theprotocol_retractBroadcast"
        await effect(bag, parse, tool, {"broadcast_id": bid}, outcomes)
        if _passed(outcomes, tool):
            r = await _broadcast_row(bag, parse, bid)
            if r is None or r.get("is_active") is not False:
                _bug(outcomes, tool, f"the broadcast reads is_active={(r or {}).get('is_active')!r} after the retract")
        tool = "theprotocol_reinstateBroadcast"
        await effect(bag, parse, tool, {"broadcast_id": bid}, outcomes,
                     check=lambda a: None if a.get("is_active") in (True, None) else "the answer reads it inactive")
        if _passed(outcomes, tool):
            r = await _broadcast_row(bag, parse, bid)
            if r is None or r.get("is_active") is not True:
                _bug(outcomes, tool, f"the broadcast reads is_active={(r or {}).get('is_active')!r} after the reinstate")
    finally:
        # nothing of the run's stays on a console's header, and a broadcast that does is said
        await _settle_retracted(bag, parse, bid, outcomes)


async def _bundle_report(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    tool = "theprotocol_dismissBundleReport"
    t = Throwaways(rpc, parse, bag, "bundle-report")
    bid = None
    owner: Dict[str, Any] = {}
    try:
        owner = await t.developer("bundle-owner")
        agent = await t.agent(owner, "a")
        reporter = await t.developer("bundle-reporter")
        if agent.get("why") or reporter.get("why"):
            effect_unmeasured(outcomes, tool, f"no bundle owner and reporter of the run's own: "
                                              f"{agent.get('why') or reporter.get('why')}")
            return
        ok, body, code = await rpc("theprotocol_createBundle", {"bundle_data": {
            "agent_dids": [agent["did"]], "kind": "snapshot", "name": f"mcp-earn-report-{int(time.time())}",
            "visibility": "public", "sign": True}}, jwt=owner["access_token"], timeout=60)
        made = parse(body) if isinstance(body, dict) else {}
        bid = str(made.get("id")) if ok and isinstance(made, dict) and made.get("id") else None
        if not bid:
            effect_unmeasured(outcomes, tool, f"no bundle of the run's own could be made (HTTP {code}: {said(made)})")
            return
        ok, body, code = await rpc("theprotocol_reportBundle", {
            "bundle_id": bid, "reason": "other", "details": "MCP tester: its own bundle, reported to be dismissed"},
            jwt=reporter["access_token"], timeout=30)
        rep = parse(body) if isinstance(body, dict) else {}
        if not ok:
            effect_unmeasured(outcomes, tool, f"the run's own bundle could not be reported (HTTP {code}: {said(rep)})")
            return
        rid = rep.get("report_id") or rep.get("id") if isinstance(rep, dict) else None
        if not isinstance(rid, int):
            okl, lst, _c = await _admin_read(bag, parse, "theprotocol_listAdminBundlesReports", {})
            mine = [r for r in _rows(lst, "reports", "items", "results") if str(r.get("bundle_id")) == bid]
            rid = mine[0].get("id") if mine and isinstance(mine[0].get("id"), int) else None
        if not isinstance(rid, int):
            effect_unmeasured(outcomes, tool, "the report on the run's own bundle named no id the admin list shows")
            return
        await effect(bag, parse, tool, {"report_id": rid, "resolution": "dismissed",
                                        "note": "MCP tester: its own report"}, outcomes,
                     check=lambda a: None if a.get("dismissed") is True or a.get("ok") is True
                     else f"the answer reads {sorted(a)[:6]}")
        await refusal_step(bag.rpc_admin, parse, tool, ADMIN, {"report_id": 2_000_000_000, "resolution": "dismissed"},
                           bag.developer_jwt, outcomes, "a report that does not exist", codes=(404,),
                           text="not found")
    finally:
        if bid and owner.get("access_token"):
            await rpc("theprotocol_deleteBundle", {"bundle_id": bid}, jwt=owner["access_token"], timeout=30)
        await t.close()


async def _emission_policy(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    tool = "theprotocol_setEventEmissionPolicy"
    ok, ans, code = await _admin_read(bag, parse, "theprotocol_getEventEmissionPolicies", {})
    rows = [r for r in _rows(ans, "policies", "items", "results") if r.get("event_type")
            and r["event_type"] not in _MONEY_EVENTS
            and all(isinstance(r.get(k), bool) for k in ("emit_from_teg", "emit_from_registry", "skip_in_projection"))]
    if not rows:
        effect_unmeasured(outcomes, tool, f"no policy row to write back could be read (HTTP {code})")
        return
    row = sorted(rows, key=lambda r: r["event_type"])[0]
    args = {k: row[k] for k in ("event_type", "emit_from_teg", "emit_from_registry", "skip_in_projection")}
    await effect(bag, parse, tool, args, outcomes)
    if _passed(outcomes, tool):
        ok2, ans2, code2 = await _admin_read(bag, parse, "theprotocol_getEventEmissionPolicies", {})
        now = next((r for r in _rows(ans2, "policies", "items", "results") if r.get("event_type") == row["event_type"]),
                   None)
        if now is None or any(now.get(k) != args[k] for k in args):
            _bug(outcomes, tool, f"the policy of {row['event_type']} reads differently after it was written back "
                                 f"with its own values")
    await refusal_step(bag.rpc_admin, parse, tool, ADMIN,
                       {"event_type": "McpTesterNoSuchEvent", "emit_from_teg": False, "emit_from_registry": True},
                       bag.developer_jwt, outcomes, "an event type with no policy", codes=(404,), text="No policy")


async def _api_tester(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    tool = "theprotocol_testApiEndpoint"
    # the API tester's paths are relative to /api/v1 (its own example: "/agents")
    await effect(bag, parse, tool, {"endpoint_path": "/public/registry-config", "method": "GET"}, outcomes,
                 check=lambda a: None if not a or str(a.get("status_code") or a.get("status") or "200").startswith("2")
                 or a.get("success") is True else f"the read it ran answered {a.get('status_code') or a.get('status')!r}")


async def _canary(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    ok, st, code = await _admin_read(bag, parse, "theprotocol_getCanaryStatus", {})
    paths = [p for p in _rows(st, "paths", "items", "canary_paths") if isinstance(p.get("id"), int)]
    active = [p for p in paths if p.get("is_active") is True]
    if not active:
        for tool in TOOLS[6:8]:
            effect_unmeasured(outcomes, tool, f"this target has no active canary path (HTTP {code}, {len(paths)} paths)")
        return
    pid = active[0]["id"]
    tool = "theprotocol_toggleCanaryPath"
    try:
        await effect(bag, parse, tool, {"path_id": pid}, outcomes,
                     check=lambda a: None if a.get("is_active") is False else f"the answer reads is_active={a.get('is_active')!r}")
    finally:
        # the path is active again whatever happened above; if the first toggle never landed, nothing is toggled
        if _passed(outcomes, tool):
            ok2, back, code2 = await _admin_read(bag, parse, tool, {"path_id": pid})
            if not (ok2 and isinstance(back, dict) and back.get("is_active") is True):
                _bug(outcomes, tool, f"the second toggle did not make the path active again (HTTP {code2})")
    tool = "theprotocol_fireCanaryPath"
    # §MCPTEST30 V0637: a follower's runner fires a path only on its master's dispatch, and a paused fleet fires
    # nothing; the route refuses a manual fire there with its reason (admin_canary.fire_would_not_run)
    okf, fleet, _cf = await _admin_read(bag, parse, "theprotocol_adminCanaryFleetStatus", {})
    fleet = fleet if okf and isinstance(fleet, dict) else {}
    if fleet.get("mode") == "follower" or fleet.get("fleet_paused"):
        follower = fleet.get("mode") == "follower"
        await refusal_step(bag.rpc_admin, parse, tool, ADMIN, {"path_id": pid}, bag.developer_jwt, outcomes,
                           "a manual fire on a follower" if follower else "a manual fire while the fleet is paused",
                           codes=(409,), text="follower" if follower else "paused")
        effect_unmeasured(outcomes, tool, ("this registry's canary runner is a follower: it fires a path only on its "
                                           "master's dispatch" if follower else "the canary fleet is paused")
                          + ", so no manual fire runs here (the route says so, 409)")
        return
    before = time.time()
    ok, _ = await effect(bag, parse, tool, {"path_id": pid}, outcomes, check=lambda a: None if a.get("scheduled") is True
                         else f"the answer reads scheduled={a.get('scheduled')!r}")
    if not ok:
        return
    for _ in range(6):
        await asyncio.sleep(5)
        okr, res, _c = await _admin_read(bag, parse, "theprotocol_getCanaryResults", {"path_id": pid, "limit": 3})
        if okr and any(_after(r, before) for r in _rows(res, "results", "items")):
            return
    _bug(outcomes, tool, "getCanaryResults shows no fire of the path within 30 s of the scheduled one")


def _after(r: Dict[str, Any], t0: float) -> bool:
    from datetime import datetime
    for k in ("fired_at", "created_at", "started_at", "timestamp"):
        v = r.get(k)
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp() >= t0 - 1
            except ValueError:
                continue
    return False


LIFECYCLES: List[Dict[str, Any]] = [
    {"name": "earn_platform_admin", "runner": lifecycle_earn_platform_admin},
]
