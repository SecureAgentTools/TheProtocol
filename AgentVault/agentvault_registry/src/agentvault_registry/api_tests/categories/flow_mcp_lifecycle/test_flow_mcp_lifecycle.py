"""MCP Lifecycle Flow — phase 1 full-sweep MCP tester.

Walks the live MCP `tools/list` and exercises every tool via JSON-RPC.

For each tool:
  1. Look up an explicit contract (contracts/mcp_contracts.py) — fall through
     to DEFAULT_CONTRACT if none.
  2. Resolve `${fixture}` placeholders in `arguments` from the McpFixtureBag.
  3. Invoke `tools/call` via the MCP server's /mcp/rpc endpoint inside the
     registry container (same channel mcp-stdio-bridge uses).
  4. Assert `expect_status` (success / error_4xx / error_5xx / any) and
     `expect_keys` presence in the result.
  5. Aggregate into the standard APITestBase results shape so the
     existing api-tester archive + pass-rate plumbing eats it for free.

Sandbox-only by default — runs against registry-test (port 8002 inside
the container, /mcp/rpc relative). Mainframe runs are configured by
the scheduled-regression cron (see PLAN_2026-05-25_MCP_TESTER_SCHEDULED_REGRESSION.md).

Catches by design:
  • Wrapper field-name drift (BUG-5 events, BUG-10 lock_period, BUG-15 reason_code)
    via expect_keys + post-call follow-up reads
  • Missing response keys (BUG-9 stake_id) via expect_keys
  • Wrong status enum case (BUG-17 funding status) via expect_status=success
    with an enum value
  • Voting-power disagreement (BUG-20) via cross-check between getMyBalance
    and getMyVotingPower
  • Stale-snapshot reply tools (BUG-22) via post-call refetch
"""
from __future__ import annotations

import asyncio
import base64
import functools
import json
import logging
import os
import random
import re
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Set, Tuple

from agentvault_registry.api_tests.base import APITestBase
from agentvault_registry.api_tests.multiframe_helpers import (
    SANDBOX_TARGET, get_target,
    exec_in_container, _split_http_body_code, _HTTP_MARKER,
    login_admin, run_psql_in_db_container,
)
from agentvault_registry.api_tests.contracts.mcp_contracts import (
    MCP_CONTRACTS, DEFAULT_CONTRACT, McpContract, McpFixtureBag,
    get_contract, resolve_args, unresolved_fixtures, contract_count, skipped_tools,
)
from agentvault_registry.api_tests.contracts.mcp_lifecycles import LIFECYCLES, lifecycle_count, result_excerpt
from agentvault_registry.api_tests.contracts import credential_exposure
from agentvault_registry.api_tests.contracts import result_shape   # §MCPTEST30: the protocol shape of every answer
from agentvault_registry.api_tests.contracts import critical_words as _words   # §MCPTEST30 W6: the critical words
from agentvault_registry.api_tests.contracts import mcp_switches as _switches   # §MCPTEST30 (V0550)
from agentvault_registry.api_tests.contracts import refusal_reasons as _refusal_reasons   # §MCPTEST30 (V0643)
from agentvault_registry.api_tests.contracts.mcp_tier_consistency import run_tier_consistency_check
__all__ = ["TestFlowMcpLifecycle", "_evaluate_contract", "_parse_rpc_result"]


def _cloudop_sweep_concurrency(default: int = 3) -> int:
    """Bounded concurrency for a CLOUD-OP sweep — deliberately lower than the
    frame default.

    §CLOUDOPMCP 2026-09-04, measured: a sandbox cloud-op registry runs
    `gunicorn --workers 2`, while `_sweep_concurrency()` defaults to 8 because it
    was tuned for Sandbox-A's 8 workers (see its docstring). Eight in-flight
    requests against two workers starved the admin `tools/list` — a single 112 KB
    response — which came back as curl `000` (connection reset) or a failed exec
    (rc=127). The flow then reported `admin_tools: 0` and SUCCESS, silently
    dropping 321 of 756 tools. Size the fan-out to the target, not to the frame.

    Override with MCP_TESTER_CLOUDOP_CONCURRENCY.
    """
    import os
    try:
        v = int(os.environ.get("MCP_TESTER_CLOUDOP_CONCURRENCY", str(default)) or default)
    except Exception:                                        # noqa: BLE001
        v = default
    return max(1, min(v, 16))


def _sweep_concurrency(default: int = 8) -> int:
    """Bounded concurrency for the per-tool sweep loops.

    Sandbox-A registry runs `uvicorn --workers 8`, so ~8 in-flight calls keep
    the workers busy without starving the 2-worker sandbox TEG (TEG-touching
    tools are exercised by the sequential Phase-4 lifecycles, not the sweep).
    Override with env MCP_TESTER_SWEEP_CONCURRENCY; set =1 to force the legacy
    sequential path (instant rollback, no rebuild).
    """
    import os
    try:
        v = int(os.environ.get("MCP_TESTER_SWEEP_CONCURRENCY", str(default)) or default)
    except (TypeError, ValueError):
        v = default
    return max(1, v)


def _lifecycle_concurrency(default: int = 6) -> int:
    """Bounded concurrency for the lifecycle ORCHESTRATOR loops (Phase 4 public,
    Phase 6 admin). Lifecycles are server-latency-bound (~1-2.5s/call) AND wait
    on event verification (up to ~15s, 5x3s retry), so overlapping independent
    orchestrators is the dominant wall-clock lever (these two phases were ~86%
    of the run). Kept below the sweep default because orchestrators do multi-call
    create->verify->delete flows with event assertions (burst -> ES projection
    lag, absorbed by the 5x3s retry). Override with env
    MCP_TESTER_LIFECYCLE_CONCURRENCY; =1 forces the legacy sequential path.
    """
    import os
    try:
        v = int(os.environ.get("MCP_TESTER_LIFECYCLE_CONCURRENCY", str(default)) or default)
    except (TypeError, ValueError):
        v = default
    return max(1, v)


# §SWEEPORDER (2026-09-24): a sweep runs its tools concurrently, so a TOGGLE PAIR raced. The nightly called
# adminCanaryFleetPause and adminCanaryFleetResume in the same second and whichever landed second won: sbx-alpha's canary
# fleet was left paused on 3 of 5 nights (09-20, 09-21, 09-24), dark until the next night's order. A tool whose name
# carries a RESTORE verb now runs after every other item of the same sweep has finished, so a sweep ends by putting back
# what it changed. Word-level on the camelCase name ("disable" is not "enable"); items that are not tools are unaffected.
_RESTORE_VERBS = frozenset({
    "resume", "reinstate", "unblock", "unquarantine", "reactivate", "restore", "unhide", "unpause", "lift", "enable",
})


def _tool_name_words(name: str) -> List[str]:
    return [w.lower() for w in re.findall(r"[A-Z]?[a-z0-9]+", name.split("theprotocol_", 1)[-1])]


def _is_restorer_item(item) -> bool:
    name = item.get("name") if isinstance(item, dict) else (item if isinstance(item, str) else None)
    return bool(name) and any(w in _RESTORE_VERBS for w in _tool_name_words(name))


async def _bounded_sweep(items, worker, *, concurrency, on_progress=None):
    """Run `worker(item)` over `items` with bounded concurrency, returning the
    per-item results in INPUT ORDER.

    `worker` is an async callable returning that item's contribution (any type
    — typically a list of ContractOutcome). `on_progress(done, total)` (async,
    optional) is awaited as each item completes, to drive the heartbeat.

    The semaphore caps concurrent docker-exec calls so the sweep overlaps the
    per-call process-spawn + network latency instead of serializing it, while
    staying within the sandbox's worker budget. concurrency=1 ⇒ sequential
    (legacy behaviour, exact rollback).
    """
    sem = asyncio.Semaphore(max(1, int(concurrency)))
    total = len(items)
    done = 0

    async def _run(idx, item):
        nonlocal done
        async with sem:
            res = await worker(item)
        done += 1
        if on_progress is not None:
            try:
                await on_progress(done, total)
            except Exception:
                pass
        return idx, res

    indexed = list(enumerate(items))
    pairs = list(await asyncio.gather(*[_run(i, it) for i, it in indexed if not _is_restorer_item(it)]))
    restorers = [(i, it) for i, it in indexed if _is_restorer_item(it)]
    if restorers:  # §SWEEPORDER: only after every other item of this sweep has finished
        pairs += await asyncio.gather(*[_run(i, it) for i, it in restorers])
    pairs.sort(key=lambda p: p[0])
    return [res for _idx, res in pairs]


def _autogen_keys() -> set:
    """Lazy-load autogen keys; returns empty set if module absent."""
    try:
        from agentvault_registry.api_tests.contracts.mcp_contracts_autogen import MCP_AUTOGEN_CONTRACTS
        return set(MCP_AUTOGEN_CONTRACTS.keys())
    except ImportError:
        return set()

logger = logging.getLogger(__name__)

# §MCPTEST-MCP9 (Commander-approved): the substring `_record_never_invoke_skip`
# stamps on tools the standing operating rules forbid the sweep from ever
# calling (provisioning, teardown, sim start/stop, api-tester forks, canary
# pause). Those rows carry healthy=True AND a skip_reason, so before this split
# they inflated BOTH `passed` and `skipped` — 742 tools reporting 763 outcomes,
# and a headline of "29 skipped" when only 8 were genuinely unexercised.
# "refused by policy" and "could not be tested" are different facts.
# §MCPTEST-MCP10: single source of truth, shared with routers/mcp_tester.py,
# which re-derives the same split when it persists a finished run. A duplicated
# literal here would drift the moment the wording changes.
from agentvault_registry.core.policy_marks import POLICY_DENIED_MARK as _POLICY_DENIED_MARK


# ─── §SKIPCENSUS 2026-09-06 — turning "113 skipped" into something readable ──
#
# The operator sweeps report a bare count: 642 passed / 113 skipped. A number
# with no families in it is exactly the state the FEDERATION suite was in before
# its taxonomy, and reading those eleven paragraphs by hand is what found two
# live defects (a money rail that answered 200 and never credited, and an FX
# capability absent from every cloud operator). A pass FLOOR cannot see a test
# that vanishes into "skipped"; a CENSUS can.
#
# The families below are derived from the reasons this module and the contract
# table actually emit — grepped, not imagined — the same discipline as
# `federation_suite/skip_codes.py`. An unmatched reason counts as
# `unclassified`, which is a complaint about the reader, not the skip.
_SKIP_FAMILIES = [
    # §MCPSWEEP 2026-09-27 — a probe the dispatcher refused before the tool ran (invalid params, tool not found):
    # a TESTER defect, never a product one; it measured nothing about the tool.
    ("probe_never_reached_tool", re.compile(r"probe never reached the tool", re.I),
     "the lifecycle's call was refused by the MCP dispatcher before the tool ran (arguments the tool does not "
     "declare, a required one missing, or a tool this bridge does not carry) — a tester defect; the tool itself "
     "was not measured"),
    # ⚠ ORDER MATTERS — first match wins, and the words overlap. `db_debris`
    # goes FIRST because its own reason ends "Cover in destructive bucket",
    # which a bare /destructive/ swallowed (caught by this file's own control
    # table on the first run: db_debris -> destructive_infra). The infra family
    # therefore names INFRASTRUCTURE, not the adjective.
    ("db_debris", re.compile(r"leaves DB debris|Creates a new (agent|developer)", re.I),
     "the tool creates rows every run would leave behind; covered elsewhere"),
    ("destructive_infra", re.compile(
        r"provisions|teardown|tears down|REAL cloud operator|WHOLE frame|"
        r"destructive[ /]?(teardown|heavy|infra)", re.I),
     "the tool provisions or destroys real infrastructure (operators, frames, "
     "containers) — excluded by DESIGN, never a gap"),
    ("recursive_tester", re.compile(r"recursive", re.I),
     "the tool re-invokes the API tester itself and would loop — excluded by design"),
    ("cloudop_admin_contract_gap", re.compile(r"cloud-op admin contract_gap", re.I),
     "no expect_keys and no outputSchema.required for this tool at cloud-op admin "
     "tier — a real contract gap, and the largest family on an operator sweep"),
    # §RUNNERCRED-3 2026-09-07 — named for what is TRUE of every member (a
    # lifecycle sold a 4xx as a pass on a success contract), not for a cause. The
    # first version called this `runner_credential_dead`; a body census showed 25
    # of 40 were a dead token and the rest were deliberate refusal probes and
    # semantic 4xx, so the name asserted more than the evidence.
    ("lifecycle_4xx_sold_as_pass", re.compile(r"lifecycle recorded a (401|403) as healthy", re.I),
     "a lifecycle step ran under expect_status='any', returned 401/403, and was "
     "recorded healthy — while the tool's own contract expects success. The success "
     "path was NOT measured. The row carries the response body: read it to see "
     "whether this was the sweep's own dead credential (25 of 40 on 2026-09-07) or "
     "a refusal the lifecycle provoked on purpose"),
    ("cloudop_lacks_frame_fixture_or_flag", re.compile(
        r"cloud-op (flag-gated|fixture unavailable)", re.I),
     "the operator differs from its FRAME by configuration or seeded data, so "
     "the tool cannot be exercised there — a flag the frame sets and the "
     "operator does not (measured, not assumed), or a row seeded on the frame "
     "only. Neither a contract gap nor a mainframe-only tool: the tool EXISTS "
     "here and the environment cannot supply its precondition"),
    ("cloudop_no_sentinel_jwt", re.compile(r"cloud-op tier-2 fixture missing", re.I),
     "tier-2 needs a sentinel agent JWT the operator sweep does not mint"),
    ("default_contract_required_params", re.compile(
        r"default contract: tool has required params", re.I),
     "the tool declares required parameters and has no explicit contract to "
     "supply them — add one, or it can never be exercised"),
    ("phase3_fixture_missing", re.compile(r"phase-3|Phase-3", re.I),
     "an entity id the sweep's own setup did not publish (or publishes LATER "
     "than this measurement — read it as debt, confirm against the run's skips)"),
    ("mainframe_only", re.compile(r"mainframe-only", re.I),
     "the tool exists only on a mainframe; a sandbox or operator cannot run it"),
    ("known_product_gap", re.compile(r"BUG-\d+|No pagination", re.I),
     "a named product limitation the contract refuses to pretend around"),
    ("needs_live_entity", re.compile(
        r"needs a (live|known)|resolve dynamically|no static fixture", re.I),
     "the tool needs an entity that must exist at run time and this tier has none"),
    ("heavy", re.compile(r"\bheavy\b", re.I),
     "excluded for cost/side effects rather than for correctness"),
    # ── the families the DECLARED contract skips actually use ────────────────
    # Added after classifying MCP_CONTRACTS and finding 34 of 58 `unclassified`
    # — which is the census doing its job: it said there was something to read,
    # and reading it turned up two parked DEFECTS (below) among the deliberate
    # exclusions. Ordered before nothing; `tool_contract_defect` goes FIRST of
    # this group because "probed:" means the tool WAS exercised and found
    # broken, which no other family should be allowed to absorb.
    ("tool_contract_defect", re.compile(r"probed:\s*the (MCP )?tool", re.I),
     "⚠ NOT AN EXCLUSION — the tool WAS probed and the tool/route contract is "
     "broken (a body missing a field the endpoint requires; a parameter typed "
     "INTEGER by the tool and parsed as something else by the route). These are "
     "defects parked as skips and are the ones worth reading first"),
    ("self_credential_or_sentinel", re.compile(
        r"mints a real API key|could (revoke|delete) the (key|one)|"
        r"deletes an API key|deletes the sentinel agent", re.I),
     "the probe would mint, revoke or delete the credential (or the sentinel "
     "agent) the rest of the sweep authenticates with — the same class as "
     "self_state_mutation, named separately because these reasons describe the "
     "OBJECT rather than the owner"),
    ("self_state_mutation", re.compile(
        r"the sweep's own|the CALLER's session|the calling agent's own|"
        r"this registry's federation licence|sweep agent's", re.I),
     "probing it would change the SWEEP's own session, credentials, agent or "
     "posture and break every later step — excluded by design"),
    ("moves_value", re.compile(r"moves value|reward pool|payout pool|staking distribution|payout distribution", re.I),
     "the tool moves real value; the sweep does not fire those blind"),
    ("provisioning_his_word", re.compile(r"PROVISIONING [-—] HIS word", re.I),
     "provisioning is his decision (CLAUDE.md: M6 provisioning LAST and HIS), "
     "not a gap in the sweep"),
    ("destructive_entity", re.compile(r"DESTRUCTIVE"),
     "destroys or resets a real entity (cancels orders and refunds escrow; "
     "restarts an operator) — needs a throwaway fixture, never a blind sweep"),
    ("mutates_shared_state", re.compile(
        r"writes agent liveness|kicks the .* worker|mutates the caller's own flare|"
        r"pairs with .*; only meaningful after", re.I),
     "the probe would change state OTHER measurements read, so a green run would "
     "be bought by disturbing its neighbours"),
    ("no_entity_to_aim_at", re.compile(r"nothing non-existent to aim at", re.I),
     "the refusal axis needs an entity to name and this tool takes none — the "
     "axis does not apply, which is different from the tool being unmeasured"),
    ("data_not_class_difference", re.compile(r"not by node CLASS", re.I),
     "the nodes differ here by DATA rather than by node class, so a cross-node "
     "comparison would be measuring the fixtures"),
    # §MCPTEST30 (V0545): a call whose answer never arrived (the exec lost it, or curl reached no server). Before the
    # probe family below, which would otherwise take it for a probe that had nothing to decide.
    ("transport_lost", re.compile(r"^NOT MEASURED: no HTTP status came back"),
     "no HTTP status came back for the call: the tester's own transport lost the answer (the server may have answered) "
     "or no server answered at all. A read is asked once more first; a write never is"),
    # §MCPTEST30 (V0545): LAST on purpose, so every family above still wins. The probe rows (pagination, list/detail,
    # filters, owner scoping, bounds) write "NOT MEASURED: <why>" when the run gave them nothing to decide; every one of
    # them landed in `unclassified` (round 11: the strict run's ten probe skips), which buried the reasons nobody had
    # read under ten that each name their own cause.
    ("probe_not_measured", re.compile(r"^NOT MEASURED: "),
     "a probe (pagination, list/detail, filters, owner scoping, page bounds) had nothing to decide on this run: an "
     "empty or short list, a list that moved under it, a fixture or an answer it did not get. Each row's sentence names "
     "which; none is a pass"),
]


def classify_tool_skip(reason: Optional[str]) -> str:
    """Map one tool skip_reason onto a family, or `unclassified`."""
    text = reason or ""
    for code, pat, _meaning in _SKIP_FAMILIES:
        if pat.search(text):
            return code
    return "unclassified"


def outcome_counts(outcomes) -> Dict[str, int]:
    """One sweep's rows in four disjoint classes that add up to its row count.

    §MCPTEST30 (V0539): a row the run did not call is never a pass. A tool a standing rule forbids the tester to call
    carries the policy mark in its skip_reason (core/policy_marks.py); the admin lifecycle's guard records it with
    `healthy=True` (mcp_admin_lifecycles._record_never_invoke_skip: "so the aggregator buckets it as skipped") and a
    contract's skip_reason without it, and `passed` counted `healthy`: 19 of a run's 20 such rows were passes, the 20th
    was not, and the console's Policy-denied card said they count against the pass rate. Measured on EU's history
    2026-10-01: strict run 8a6ad7313a8f4666 recorded passed 1157 of 1184 rows = 1138 called + 19 never called, and its
    four counts summed to 1203.
    """
    passed = skipped = policy_denied = failed = 0
    for o in outcomes:
        reason = getattr(o, "skip_reason", None)
        if reason:
            if _POLICY_DENIED_MARK in reason:
                policy_denied += 1
            else:
                skipped += 1
        elif getattr(o, "healthy", False):
            passed += 1
        else:
            failed += 1
    return {"total": len(outcomes), "passed": passed, "skipped": skipped, "policy_denied": policy_denied,
            "failed": failed}


def skip_census(outcomes) -> Dict[str, Any]:
    """Census the skips of one sweep, with the meanings beside the counts.

    Returns {"skip_census": {...}, "skip_code_meanings": {...},
             "unclassified_examples": [...]} — the examples are what a reader
    needs to add the next family, and their absence is what let skips sit unread.
    """
    census: Dict[str, int] = {}
    examples: List[str] = []
    for o in outcomes:
        r = getattr(o, "skip_reason", None)
        if not r or _POLICY_DENIED_MARK in r:
            continue
        code = classify_tool_skip(r)
        census[code] = census.get(code, 0) + 1
        if code == "unclassified" and len(examples) < 5:
            examples.append(f"{getattr(o, 'tool_name', '?')}: {r[:120]}")
    used = {c for c, _p, _m in _SKIP_FAMILIES if c in census}
    return {
        "skip_census": dict(sorted(census.items(), key=lambda kv: -kv[1])),
        "skip_code_meanings": {c: m for c, _p, m in _SKIP_FAMILIES if c in used},
        "unclassified_examples": examples,
    }


# ---------------------------------------------------------------------------
# MCP RPC helpers — local to this module (mirrors flow_mcp_smoke's style)
# ---------------------------------------------------------------------------

async def _mcp_get(target, path: str, jwt: str = "") -> Tuple[bool, dict, str]:
    """GET to the MCP server inside the registry container."""
    auth_header = f"-H 'Authorization: Bearer {jwt}'" if jwt else ""
    rc, out = await asyncio.to_thread(
        exec_in_container, target.a_registry_container, [
            "sh", "-c",
            f"curl -sS {auth_header} -w '\\n{_HTTP_MARKER}%{{http_code}}--' "
            f"http://localhost:8000{path}",
        ], 15,
    )
    body, code = _split_http_body_code(out)
    if rc != 0:
        return False, {"_raw": body[:200]}, code
    if not (code and code.startswith("2")):
        return False, {"_raw": body[:200]}, code
    try:
        return True, json.loads(body), code
    except Exception:
        return True, {"_raw": body[:200]}, code


# ---------------------------------------------------------------------------
# Phase C bug-finder layer (2026-05-26) — EventStore + audit row verifiers
# ---------------------------------------------------------------------------

async def _query_recent_events(target, event_type: str, limit: int = 50,
                                jwt: str = "") -> List[Dict[str, Any]]:
    """Query EventStore for the most recent N events of one type.

    Uses the registry's admin proxy `/api/v1/admin/events/search?event_type=X&limit=N`
    which delegates to EventStore's /api/v1/events/ over the existing
    internal/mTLS path (registry already has the SPIRE SVID). Avoids needing
    to handshake mTLS from the test runner.

    Returns list of {id, event_type, aggregate_id, data, timestamp, ...}
    or an empty list on failure. Caller does the time-window + agent-DID
    filter.
    """
    auth_header = f"-H 'Authorization: Bearer {jwt}'" if jwt else ""
    # event_type as URL-encoded query param. Sort DESC by default.
    enc_type = urllib.parse.quote(event_type, safe="")
    path = f"/api/v1/admin/events/search?event_type={enc_type}&limit={limit}&sort_order=desc"
    rc, out = await asyncio.to_thread(
        exec_in_container, target.a_registry_container, [
            "sh", "-c",
            f"curl -sS {auth_header} -w '\\n{_HTTP_MARKER}%{{http_code}}--' "
            f"'http://localhost:8000{path}'",
        ], 8,
    )
    body, code = _split_http_body_code(out)
    if rc != 0 or not code.startswith("2"):
        # §MCPTEST-MCP8: return None — "the lookup failed" — NOT [] — "there are
        # no rows". They are different facts and conflating them produced a
        # phantom product defect: run 21 reported updateNotificationPrefs
        # "didn't audit" while the row sat in Postgres at 11:49:43.615, a full
        # 6.2 s INSIDE the window starting 11:49:37.422 that the check declared
        # empty. The curl below runs with an 8 s budget against an admin query,
        # on a box that hits load 200 during the sweep — so the timeout, not the
        # pipeline, is what "proved" the absence. Absence of evidence is not
        # evidence of absence.
        return None
    try:
        parsed = json.loads(body)
        # Registry proxy returns {"events": [...], "count": N, "frame": "A"}
        if isinstance(parsed, dict):
            return parsed.get("events") or []
        if isinstance(parsed, list):
            return parsed
        return []
    except Exception:
        return []


# ── Phase F.5 — Generic eventually() helper (Gap-5) ─────────────────────
# Polls `predicate()` every `gap` seconds for up to `timeout` seconds.
# `predicate` returns None to indicate "now consistent" (success), or any
# non-None string to indicate "still inconsistent — here's why". Returns
# (consistent, last_reason). Used by lifecycles asserting eventual
# consistency on federation/sync/cache surfaces beyond EventStore lag.
async def _eventually(
    predicate,
    timeout: float = 60.0,
    gap: float = 2.0,
) -> Tuple[bool, Optional[str]]:
    """Generic eventual-consistency poller for lifecycle assertions."""
    deadline = asyncio.get_event_loop().time() + float(timeout)
    last_reason: Optional[str] = "not-yet-polled"
    while asyncio.get_event_loop().time() < deadline:
        try:
            if asyncio.iscoroutinefunction(predicate):
                last_reason = await predicate()
            else:
                last_reason = predicate()
        except Exception as e:
            last_reason = f"predicate raised: {e!r}"
        if last_reason is None:
            return True, None
        await asyncio.sleep(gap)
    return False, last_reason


async def _verify_post_call_assertions(
    target, contract, tool_name: str, pre_call_iso: str,
    jwt: str, bag: "McpFixtureBag",
) -> Tuple[bool, Optional[str]]:
    """Phase C bug-finder layer (2026-05-26) — runs AFTER `_evaluate_contract`
    passes the basic shape check.

    Verifies:
      • Every `contract.expect_events` event_type has at least one row in
        EventStore newer than pre_call_iso (catches BUG-10 silent NO-OP class).
      • If `contract.expect_audit_row` is True OR (None AND mutation): at least
        one security_audit_logs row exists with target_id=tool_name and
        timestamp >= pre_call_iso (catches mcp_tool calls bypassing the audit
        pipe — assertion class #4 from the Phase 5 handover).

    Returns (ok, fail_reason).
    """
    # Event-emission check
    if contract.expect_events:
        try:
            since_dt = datetime.fromisoformat(pre_call_iso.replace("Z", "+00:00"))
            if since_dt.tzinfo is None:
                since_dt = since_dt.replace(tzinfo=timezone.utc)
        except Exception:
            since_dt = datetime.now(timezone.utc) - asyncio.get_event_loop().time().__class__(0)  # type: ignore
        # Build a single query per declared event_type and filter by timestamp.
        # ES projection can lag 30-60s under sweep load (feedback_es_verifier_lag_under_sweep);
        # retry up to 3 times with 2s gaps before declaring missing.
        for expected_evt in contract.expect_events:
            found = False
            last_err_count = 0
            for attempt in range(3):
                events = await _query_recent_events(target, expected_evt, limit=50, jwt=jwt)
                recent = []
                for e in events:
                    ts = e.get("timestamp")
                    if not isinstance(ts, str):
                        continue
                    try:
                        edt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if edt.tzinfo is None:
                            edt = edt.replace(tzinfo=timezone.utc)
                        if edt >= since_dt:
                            recent.append(e)
                    except Exception:
                        continue
                last_err_count = len(events)
                if recent:
                    found = True
                    break
                if attempt < 2:
                    await asyncio.sleep(2.0)
            if not found:
                return False, (
                    f"missing event: '{expected_evt}' not emitted in EventStore "
                    f"since {pre_call_iso} after 3 retries (call returned 2xx but no event "
                    f"landed within 4s — silent NO-OP class). Total {expected_evt} events "
                    f"in EventStore window: {last_err_count}"
                )

    # ── Phase F.5 — Eventual consistency (Gap-5) ────────────────────────
    # If contract declares an `expect_consistency_within` window AND a
    # `consistency_check` predicate, poll the predicate every 2s until it
    # returns None (consistent) or the budget elapses. Generalizes the
    # EventStore retry pattern to ANY eventually-consistent surface
    # (federation_sync, pull-sync, eigentrust epoch, redis pub/sub).
    if (
        getattr(contract, "expect_consistency_within", None)
        and getattr(contract, "consistency_check", None)
    ):
        deadline = asyncio.get_event_loop().time() + float(contract.expect_consistency_within)
        last_reason: Optional[str] = "not-yet-polled"
        while asyncio.get_event_loop().time() < deadline:
            try:
                last_reason = contract.consistency_check(bag)
            except Exception as e:
                last_reason = f"consistency_check raised: {e!r}"
            if last_reason is None:
                break
            await asyncio.sleep(2.0)
        if last_reason is not None:
            return False, (
                f"consistency violation: {last_reason} after "
                f"{contract.expect_consistency_within}s budget"
            )

    # Audit-row check
    # Default behavior:
    #   - expect_audit_row=True  → require a row
    #   - expect_audit_row=False → skip the check
    #   - expect_audit_row=None  → require a row IF tool name suggests mutation
    want_audit = contract.expect_audit_row
    if want_audit is None:
        prefixes = ("create", "update", "delete", "transfer", "stake",
                    "unstake", "submit", "revoke", "approve", "reject",
                    "set", "enable", "disable", "suspend", "reinstate",
                    "patch", "equip", "unequip", "customize")
        op = tool_name.replace("theprotocol_", "")
        want_audit = any(op.startswith(p) for p in prefixes)
    if want_audit:
        # §MCPTEST-MCP7: the audit row is written on a path that completes AFTER
        # the tool's response returns, so a check fired immediately after the
        # call races it. PROVEN: success rows for updateNotificationPrefs and
        # updateMyDeveloperLocation existed at 08:48:23/08:48:33 — inside the
        # 08:44-09:03 run window — while the run reported them "missing".
        # One settle-and-requery turns a race into a real assertion; a genuinely
        # un-audited tool still fails, it just fails for the right reason.
        # MEASURED on run 16 (box at load ~157): the rows for
        # updateNotificationPrefs / updateMyDeveloperLocation were written at
        # 09:49:54.762 and 09:49:57.762 against call times of 09:49:48.150 and
        # 09:49:50.241 — i.e. 6.6 s and 7.5 s late. A single 1.5 s retry (run 15,
        # which passed at load ~100) was luck, not a fix. Poll to ~13 s.
        _AUDIT_BACKOFF = (1.5, 2.5, 3.0, 3.0, 3.0)
        ok_rows = []
        _query_ever_succeeded = False
        for _attempt in range(len(_AUDIT_BACKOFF) + 1):
            rows = await _query_recent_audit_rows(
                target, tool_name, pre_call_iso, jwt=jwt)
            if rows is not None:
                _query_ever_succeeded = True
                ok_rows = [r for r in rows if r.get("outcome") == "success"
                                               and r.get("target_id") == tool_name]
                if ok_rows:
                    break
            if _attempt < len(_AUDIT_BACKOFF):
                await asyncio.sleep(_AUDIT_BACKOFF[_attempt])
        if not ok_rows and not _query_ever_succeeded:
            # Every lookup failed. We have NO evidence either way, so we must not
            # claim a pipeline regression — that is the false-positive that cost
            # two runs. Log loudly and let the tool stand on its own result.
            logger.error(
                "[MCP-AuditProbe] %s: every audit-log lookup FAILED (timeout or "
                "non-2xx) — audit assertion INCONCLUSIVE, not asserting absence.",
                tool_name,
            )
            return True, None
        if not ok_rows:
            return False, (
                f"missing audit row: no security_audit_logs entry for "
                f"target_id='{tool_name}' outcome='success' since {pre_call_iso} "
                f"(call returned 2xx but didn't audit — pipe regression)"
            )

    return True, None


async def _query_recent_audit_rows(target, tool_name: str, since_iso: str,
                                     jwt: str = "") -> Optional[List[Dict[str, Any]]]:
    """Query security_audit_logs via /api/v1/admin/audit-logs.

    Returns rows where target_id=<tool_name> created since `since_iso`.
    The endpoint already supports filtering by target_id + since_hours;
    we just convert since_iso → hours-ago for the API.
    """
    # Convert since_iso to hours-ago for the API
    try:
        since_dt = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - since_dt
        hours_ago = max(1, int(delta.total_seconds() / 3600) + 1)
    except Exception:
        hours_ago = 1
    auth_header = f"-H 'Authorization: Bearer {jwt}'" if jwt else ""
    path = f"/api/v1/admin/audit-logs?target_id={tool_name}&since_hours={hours_ago}&limit=10"
    rc, out = await asyncio.to_thread(
        exec_in_container, target.a_registry_container, [
            "sh", "-c",
            f"curl -sS {auth_header} -w '\\n{_HTTP_MARKER}%{{http_code}}--' "
            f"http://localhost:8000{path}",
        ], 25,   # §MCPTEST-MCP8: 8 s was below the admin-query latency under sweep load
    )
    body, code = _split_http_body_code(out)
    if rc != 0 or not code.startswith("2"):
        # §MCPTEST-MCP10 2026-08-08 — return None ("the lookup failed"), never []
        # ("there are no rows"). This is the SAME defect §MCPTEST-MCP8 fixed in the
        # sibling ES-event query; I fixed only that one and left this twin, which
        # is the fix-one-of-N shape again.
        #
        # It DEFEATED the INCONCLUSIVE guard written to prevent exactly this: a
        # timed-out lookup returned [], the caller read `rows is not None` as
        # "the query worked", set `_query_ever_succeeded = True`, found no success
        # row, and reported "call returned 2xx but didn't audit — pipe regression"
        # about a row that WAS in the table.
        # MEASURED on updateNotificationPrefs: the harness claimed absence since
        # 14:25:27.204 while the row sat at 14:25:31.905 (4.70 s later); a fresh
        # re-measure gave 4.83 s. The audit pipe was never broken.
        return None
    try:
        parsed = json.loads(body)
        items = parsed.get("items", []) if isinstance(parsed, dict) else []
        # Filter by timestamp >= since_iso (the API rounds to hours)
        out_rows = []
        for r in items:
            ts = r.get("timestamp")
            if isinstance(ts, str):
                try:
                    row_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if row_dt.tzinfo is None:
                        # security_audit_logs.timestamp is naive UTC
                        row_dt = row_dt.replace(tzinfo=timezone.utc)
                    if row_dt >= since_dt:
                        out_rows.append(r)
                except Exception:
                    out_rows.append(r)
        return out_rows
    except Exception:
        # Unparseable body: we learned nothing, same as a transport failure.
        return None


async def _mcp_rpc_list_tools(target, jwt: str = "") -> Tuple[bool, list, str]:
    """JSON-RPC tools/list — distinct method from tools/call.

    Returns (ok, list_of_tools, http_code).
    """
    auth_header = f"-H 'Authorization: Bearer {jwt}'" if jwt else ""
    rpc_body = {
        "jsonrpc": "2.0",
        "method": "tools/list",
        "params": {},
        "id": int(time.time() * 1000) % 1_000_000,
    }
    body_b64 = base64.b64encode(json.dumps(rpc_body).encode()).decode()
    rc, out = await asyncio.to_thread(
        exec_in_container, target.a_registry_container, [
            "sh", "-c",
            f"echo '{body_b64}' | base64 -d | "
            f"curl -sS -X POST {auth_header} "
            f"-H 'Content-Type: application/json' "
            f"--data-binary @- "
            f"-w '\\n{_HTTP_MARKER}%{{http_code}}--' "
            "http://localhost:8000/mcp/rpc",
        ], 20,
    )
    body, code = _split_http_body_code(out)
    if rc != 0 or not code.startswith("2"):
        return False, [], code
    try:
        parsed = json.loads(body)
        tools = parsed.get("result", {}).get("tools") or []
        return True, tools, code
    except Exception:
        return False, [], code


async def _mcp_rpc_list_tools_admin(target, jwt: str = "") -> Tuple[bool, list, str]:
    """tools/list against /mcp/admin/rpc — admin bridge (302 tools).

    Phase 6: separate JSON-RPC endpoint from the public bridge. Admin
    bridge enforces is_admin=True on tools/call (discovery methods pass
    through anonymously). Commander dev JWT works.
    """
    auth_header = f"-H 'Authorization: Bearer {jwt}'" if jwt else ""
    rpc_body = {
        "jsonrpc": "2.0",
        "method": "tools/list",
        "params": {},
        "id": int(time.time() * 1000) % 1_000_000,
    }
    body_b64 = base64.b64encode(json.dumps(rpc_body).encode()).decode()
    rc, out = await asyncio.to_thread(
        exec_in_container, target.a_registry_container, [
            "sh", "-c",
            f"echo '{body_b64}' | base64 -d | "
            f"curl -sS -X POST {auth_header} "
            f"-H 'Content-Type: application/json' "
            f"--data-binary @- "
            f"-w '\\n{_HTTP_MARKER}%{{http_code}}--' "
            "http://localhost:8000/mcp/admin/rpc",
        # §CLOUDOPMCP 2026-09-04: was 20s. The admin bridge answers tools/list with
        # ~112 KB (321 tools with full schemas); on a cloud-op that has just served
        # the 435-tool public sweep, that exec exceeded 20s and returned rc!=0 with
        # NO output, so _split_http_body_code produced an EMPTY code and the whole
        # admin half silently vanished (admin_tools=0, 321 tools unswept) while the
        # flow still reported success — a listing timeout read as "no admin surface".
        # Measured: the same helper called standalone returns 321 tools in ~1s.
        ], 90,
    )
    body, code = _split_http_body_code(out)
    if rc != 0 or not code.startswith("2"):
        # Do not let a transport failure masquerade as an empty surface — say which.
        return False, [], (code or f"exec-failed(rc={rc})")
    try:
        parsed = json.loads(body)
        tools = parsed.get("result", {}).get("tools") or []
        return True, tools, code
    except Exception:
        return False, [], code


async def _mcp_rpc_call_admin(
    target,
    tool_name: str,
    arguments: dict,
    jwt: str = "",
    timeout: int = 30,
) -> Tuple[bool, dict, str]:
    """JSON-RPC tools/call against /mcp/admin/rpc (admin MCP bridge).

    Phase 6: identical shape to _mcp_rpc_call but hits the admin endpoint.
    Bearer must be a developer JWT with is_admin=True on every call.
    """
    auth_header = f"-H 'Authorization: Bearer {jwt}'" if jwt else ""
    rpc_body = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
        "id": int(time.time() * 1000) % 1_000_000,
    }
    body_b64 = base64.b64encode(json.dumps(rpc_body).encode()).decode()
    rc, out = await asyncio.to_thread(
        exec_in_container, target.a_registry_container, [
            "sh", "-c",
            f"echo '{body_b64}' | base64 -d | "
            f"curl -sS -X POST {auth_header} "
            f"-H 'Content-Type: application/json' "
            f"--data-binary @- "
            f"-w '\\n{_HTTP_MARKER}%{{http_code}}--' "
            "http://localhost:8000/mcp/admin/rpc",
        ], timeout,
    )
    body, code = _split_http_body_code(out)
    if rc != 0:
        return False, {"_raw": body[:200]}, code
    try:
        parsed = json.loads(body) if body else {}
    except Exception:
        parsed = {"_raw": body[:200]}
    # §MCPTEST30: every response the sweep receives feeds the credential exposure census (kind + path, no value)
    credential_exposure.record(tool_name, parsed)
    result_shape.record(tool_name, parsed)
    _words.record(tool_name, parsed)
    has_error = isinstance(parsed, dict) and "error" in parsed
    ok = code.startswith("2") and not has_error
    # pass73.3.19: unmask MCP-wrapped backend errors (transport-200 carrying an
    # inner "Error: HTTP NNN") so the sweep records the REAL status, not a false
    # 200/healthy. Only rewrites a 2xx that's actually a wrapped error.
    if ok:
        _wrapped = _wrapped_http_status(parsed)
        if _wrapped is not None:
            ok = False
            code = str(_wrapped)
    return ok, parsed, code


async def _mcp_rpc_call(
    target,
    tool_name: str,
    arguments: dict,
    jwt: str = "",
    timeout: int = 30,
) -> Tuple[bool, dict, str]:
    """JSON-RPC tools/call against the MCP server inside the registry container.

    `jwt` is required for Tier 2/3/admin tools. The MCP server's dispatcher
    will pop an inline `agent_jwt` from arguments if present (Tier 2 inline
    override).
    """
    auth_header = f"-H 'Authorization: Bearer {jwt}'" if jwt else ""
    rpc_body = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
        "id": int(time.time() * 1000) % 1_000_000,
    }
    body_b64 = base64.b64encode(json.dumps(rpc_body).encode()).decode()
    rc, out = await asyncio.to_thread(
        exec_in_container, target.a_registry_container, [
            "sh", "-c",
            f"echo '{body_b64}' | base64 -d | "
            f"curl -sS -X POST {auth_header} "
            f"-H 'Content-Type: application/json' "
            f"--data-binary @- "
            f"-w '\\n{_HTTP_MARKER}%{{http_code}}--' "
            "http://localhost:8000/mcp/rpc",
        ], timeout,
    )
    body, code = _split_http_body_code(out)
    if rc != 0:
        return False, {"_raw": body[:200]}, code
    try:
        parsed = json.loads(body) if body else {}
    except Exception:
        parsed = {"_raw": body[:200]}
    # §MCPTEST30: every response the sweep receives feeds the credential exposure census (kind + path, no value)
    credential_exposure.record(tool_name, parsed)
    result_shape.record(tool_name, parsed)
    _words.record(tool_name, parsed)
    has_error = isinstance(parsed, dict) and "error" in parsed
    ok = code.startswith("2") and not has_error
    # pass73.3.19: unmask MCP-wrapped backend errors (transport-200 carrying an
    # inner "Error: HTTP NNN") so the sweep records the REAL status, not a false
    # 200/healthy. Only rewrites a 2xx that's actually a wrapped error.
    if ok:
        _wrapped = _wrapped_http_status(parsed)
        if _wrapped is not None:
            ok = False
            code = str(_wrapped)
    return ok, parsed, code


# ── §MCPTEST30 (2026-10-01) — a RAW JSON-RPC post, for the protocol conformance lifecycle ────────────────────
async def _mcp_rpc_raw(target, body: str, *, path: str = "/mcp/rpc", jwt: str = "", query: str = "",
                       headers: Optional[List[str]] = None, timeout: int = 30) -> Tuple[str, Any, str]:
    """One POST of `body` (any text: a request, a notification, a batch, broken JSON) to the target's MCP endpoint.

    `_mcp_rpc_call` can only send `tools/call`; the conformance lifecycle has to ask initialize, tools/list pages,
    resources, prompts, tasks and the error paths too. Returns (http_code, parsed JSON or None, raw text[:4000]).
    Every parsed answer also feeds the credential exposure census, under `mcp:<method>`."""
    import shlex as _shlex
    hdrs = list(headers or [])
    if jwt:
        hdrs.append(f"Authorization: Bearer {jwt}")
    if not any(h.lower().startswith("content-type:") for h in hdrs):
        hdrs.append("Content-Type: application/json")
    if not any(h.lower().startswith("accept:") for h in hdrs):
        hdrs.append("Accept: application/json")
    flags = " ".join(f"-H {_shlex.quote(h)}" for h in hdrs)
    url = f"http://localhost:8000{path}" + (f"?{query}" if query else "")
    body_b64 = base64.b64encode(body.encode()).decode()
    rc, out = await asyncio.to_thread(
        exec_in_container, target.a_registry_container, [
            "sh", "-c",
            f"echo '{body_b64}' | base64 -d | curl -sS --connect-timeout 5 --max-time {max(int(timeout), 3)} "
            f"-X POST {flags} --data-binary @- -w '\\n{_HTTP_MARKER}%{{http_code}}--' {_shlex.quote(url)}",
        ], timeout,
    )
    raw, code = _split_http_body_code(out)
    if rc != 0:
        return code or "0", None, (raw or "")[:400]
    try:
        parsed = json.loads(raw) if (raw or "").strip() else None
    except Exception:
        parsed = None
    try:
        method = (json.loads(body) or {}).get("method") if body.strip().startswith("{") else None
    except Exception:
        method = None
    if parsed is not None:
        _who = f"mcp:{method or 'raw'}"
        if method == "tools/call":   # §MCPTEST30 (V0525): a probe's tools/call answer is the tool's own, census-wise
            try:
                _who = str(((json.loads(body) or {}).get("params") or {}).get("name") or _who)
            except Exception:
                pass
        credential_exposure.record(_who, parsed)
        result_shape.record(f"mcp:{method or 'raw'}", parsed)
        _words.record(_who, parsed)
    return code, parsed, (raw or "")[:4000]


# ── Phase F.4 — Cross-frame RPC helper (Gap-4) ───────────────────────────
async def _mcp_rpc_call_b(
    target,
    tool_name: str,
    arguments: dict,
    jwt: str = "",
    timeout: int = 30,
) -> Tuple[bool, dict, str]:
    """Same as `_mcp_rpc_call` but targets target.b_registry_container.

    Used by the cross-frame parity walker to call the SAME tool against
    sandbox-B and diff the response shape against sandbox-A. Returns the
    parsed body so the caller can extract top-level keys.
    """
    auth_header = f"-H 'Authorization: Bearer {jwt}'" if jwt else ""
    rpc_body = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
        "id": int(time.time() * 1000) % 1_000_000,
    }
    body_b64 = base64.b64encode(json.dumps(rpc_body).encode()).decode()
    # §pass73.3.19: exec_in_container's `timeout` arg is a NO-OP (docker SDK
    # exec_run has no timeout → blocks forever if registry-B is unresponsive,
    # the original cause of the 68-min Phase-5c stall). Bound the curl itself
    # with --max-time/--connect-timeout so it ALWAYS self-terminates and the
    # worker thread returns; the walk adds an asyncio.wait_for cap on top.
    _curl_max = max(int(timeout), 3)
    rc, out = await asyncio.to_thread(
        exec_in_container, target.b_registry_container, [
            "sh", "-c",
            f"echo '{body_b64}' | base64 -d | "
            f"curl -sS --connect-timeout 5 --max-time {_curl_max} -X POST {auth_header} "
            f"-H 'Content-Type: application/json' "
            f"--data-binary @- "
            f"-w '\\n{_HTTP_MARKER}%{{http_code}}--' "
            "http://localhost:8000/mcp/rpc",
        ], timeout,
    )
    body, code = _split_http_body_code(out)
    if rc != 0:
        return False, {"_raw": body[:200]}, code
    try:
        parsed = json.loads(body) if body else {}
    except Exception:
        parsed = {"_raw": body[:200]}
    # §MCPTEST30: every response the sweep receives feeds the credential exposure census (kind + path, no value)
    credential_exposure.record(tool_name, parsed)
    result_shape.record(tool_name, parsed)
    _words.record(tool_name, parsed)
    has_error = isinstance(parsed, dict) and "error" in parsed
    ok = code.startswith("2") and not has_error
    # pass73.3.19: unmask MCP-wrapped backend errors (transport-200 carrying an
    # inner "Error: HTTP NNN") so the sweep records the REAL status, not a false
    # 200/healthy. Only rewrites a 2xx that's actually a wrapped error.
    if ok:
        _wrapped = _wrapped_http_status(parsed)
        if _wrapped is not None:
            ok = False
            code = str(_wrapped)
    return ok, parsed, code


# Curated list of public/read-only tools whose RESPONSE SHAPE should be
# identical between Frame A and Frame B (values can differ — agent counts,
# fixtures, peer lists — but the top-level keys must match).
#
# Expanded from 25 → 50 in §pass72-followup (2026-05-26 evening) — broadens
# coverage to federation peer-list, tokenomics, reputation, arena, bundles,
# attestation, identity/SPIRE, and activity surfaces. Each entry must work
# with empty args (Phase 5c calls every tool with {}).
_CROSS_FRAME_PARITY_TOOLS: List[str] = [
    # ─── Original 25 (Phase F shipping set) ─────────────────────────────
    # Discovery + network
    "theprotocol_discoverAgents",
    "theprotocol_discoverRegistries",
    "theprotocol_getNetworkStats",
    "theprotocol_getNetworkHealth",
    # Staking + APY
    "theprotocol_getLockPayoutTiers",
    "theprotocol_getLockStats",
    "theprotocol_getLockPayoutTiersTeg",
    "theprotocol_getLockPayoutStats",
    "theprotocol_getLockPayoutRuns",
    # Governance
    "theprotocol_getGovernanceProposals",
    # Federation
    "theprotocol_getFederationInfo",
    "theprotocol_getFederationHealthCheck",
    "theprotocol_getFederationNetworkStats",
    # Registry card / public config
    "theprotocol_getRegistryCard",
    "theprotocol_getWellKnownRegistryCard",
    "theprotocol_getPublicRegistryConfig",
    "theprotocol_getAuthRegistrationConfig",
    # EventStore + fees
    "theprotocol_getPublicEventStoreStats",
    "theprotocol_getFeeCurrentRate",
    # Fiat onramp
    "theprotocol_getFiatTiers",
    "theprotocol_getFiatProviders",
    "theprotocol_getFiatStatsPublic",
    # Templates + operator apps
    "theprotocol_listAgentTemplates",
    "theprotocol_listAgentBuilderTemplates",
    "theprotocol_listPublicOperatorApplications",
    # ─── Expansion +25 (§pass72-followup, 2026-05-26 evening) ───────────
    # Every entry below was synthetically pre-flighted against sandbox-A vs
    # sandbox-B with empty args — shapes verified identical, no auth-tier
    # errors, no 400/401/404 mismatches. Tools that returned envelope drift
    # (e.g. listFederationRegistries — A returns {registries,total}, B
    # returns bare list) were intentionally EXCLUDED and filed for wrapper
    # normalization. Tools that 401/404 with empty args (e.g.
    # listFederationPeers needs mTLS; getRevokedIdentities is admin-gated)
    # were also EXCLUDED because they belong on the error-path contract
    # list, not the parity-shape list.
    #
    # Tokenomics + reputation — global aggregates
    "theprotocol_getTegPrice",
    "theprotocol_getTegReputationRankings",
    "theprotocol_getReputationComputationStatus",
    # Arena (games) — list-style public match feed
    "theprotocol_listArenaMatches",
    # Bundles + CI/CD templates — public marketplace surfaces
    "theprotocol_getFeaturedBundles",
    "theprotocol_getPipelineTemplates",
    # Attestation + agent-card lists — public discovery
    "theprotocol_getAttestationSigningPubkey",
    "theprotocol_getAttestationHealth",
    "theprotocol_listAgentCards",
    # Identity / SPIRE — well-known JWKS (each frame has its own bundle but
    # the JWKS envelope is identical)
    "theprotocol_getSpireJWKS",
    "theprotocol_getWellKnownDevJwks",
    # Public showcase + stack-health meta surface
    "theprotocol_getPublicShowcaseAgents",
    "theprotocol_getStackHealth",
    # Downloads + achievements + system activity feed — global content
    "theprotocol_getDownloadsManifest",
    "theprotocol_getAchievementCatalog",
    "theprotocol_getSystemActivityFeed",
    # Developer stats + circuit catalog
    "theprotocol_getDeveloperStats",
    "theprotocol_getCircuits",
    # Auth profile — self-introspection, both sides authenticated with the
    # same JWT type so shape matches
    "theprotocol_getAuthProfile",
    # Agent locations — emission-policy + trusted-registries surface
    "theprotocol_getAgentLocationsEmissionPolicies",
    "theprotocol_getAgentLocationsTrustedRegistries",
    # TEG policy compliance dashboard
    "theprotocol_getTegPoliciesComplianceDashboard",
    # MCP stdio bridge JS — static source served by both frames (text content,
    # parses to identical shape)
    "theprotocol_getMcpStdioBridgeJs",
    "theprotocol_getMcpStdioBridgeAdminJs",
    # ─── §pass73 task E expansion +5 (2026-05-26) ───────────────────────────
    # All five wrappers verified shape-clean across sandbox-A ↔ sandbox-B post
    # the §pass73 task C envelope-normalization fix (the federation/community/
    # operator-applications/policy-compliance wrappers were leaking the
    # `body` key from the _public_get error envelope; that's now stripped).
    # Synthetic pre-flight: `/tmp/probe_list_wrappers.py` confirms each returns
    # identical keys set on both frames.
    #
    # Agent-locations list (the registry's own agent geo registry)
    "theprotocol_getAgentLocations",
    # Federation cross-registry agent + registry card lists (no envelope drift now)
    "theprotocol_listFederationAgentCards",
    "theprotocol_listFederationRegistryCards",
    # Community announcements (operator-controlled news feed)
    "theprotocol_getCommunityAnnouncements",
    # Federation policy-compliance roll-up (per-peer adherence summary)
    "theprotocol_getFederationPolicyCompliance",
]


def _shape_signature(body: dict) -> Set[str]:
    """Extract a 'shape signature' from a response body — the set of top-level
    keys (for dict responses) plus a marker token for the type. Lets us diff
    A vs B at the structural level without caring about VALUES (which legitimately
    differ between frames)."""
    if not isinstance(body, dict):
        return {f"__type:{type(body).__name__}"}
    sig: Set[str] = set()
    for k, v in body.items():
        if isinstance(v, dict):
            sig.add(f"{k}:dict")
        elif isinstance(v, list):
            sig.add(f"{k}:list")
        elif v is None:
            sig.add(f"{k}:null")
        elif isinstance(v, bool):
            sig.add(f"{k}:bool")
        elif isinstance(v, (int, float)):
            sig.add(f"{k}:num")
        else:
            sig.add(f"{k}:str")
    return sig


async def _cross_frame_parity_walk(target, dev_jwt: str) -> Dict[str, Any]:
    """Phase F.4 (Gap-4) — call ~25 read-only tools against both A and B and
    diff response shapes. Tracks tools where shapes diverge as
    `cross_frame_drift`. Returns a dict with counts + diff details.
    """
    probed = 0
    drifts: List[Dict[str, Any]] = []
    a_unreachable = 0
    b_unreachable = 0
    timed_out = 0
    skipped: List[Dict[str, Any]] = []
    # §MCPTEST30 (V0541): the tools whose two answers were actually compared. `probed` counts attempts, the unreachable
    # and timed-out ones too, so a walk that compared nothing still read as "A↔B: 0 drift".
    compared: List[str] = []
    # ── §Phase-5c harden (2026-06-27) — per-SIDE timeout + B-fuse ───────────
    # Now that sandbox cross-frame mTLS is LIVE (S5) the B-side calls do REAL
    # cross-frame work, so under canary/settlement load a single B-call can
    # block for many seconds. The prior code wrapped the A+B gather in ONE 20s
    # cap, which (a) discarded a good A result when only B was slow and (b) let
    # a run of slow probes keep the test-flow worker busy long enough for
    # uvicorn's liveness supervisor to SIGKILL it mid-walk → the httpx client
    # driving the sweep saw "Server disconnected" → run=failed (intermittent,
    # load-dependent — confirmed in runs 1e93/2aaf which died in Phase 5c). Now:
    #   • EACH side runs under its OWN asyncio.wait_for(_PROBE_CALL_CAP_S): a
    #     slow/blocking B-call is abandoned, that tool is recorded skipped, and
    #     the walk CONTINUES (never blocks the loop, never raises out of a probe).
    #   • a B-side FUSE: after _B_FAIL_FUSE consecutive B timeouts the walk goes
    #     A-only for the remainder (don't re-block on a degraded B 40+ times).
    #   • a tighter total walk budget so Phase 5c can never dominate the run.
    _PROBE_CURL_TIMEOUT = 8       # curl --max-time inside each call (frees the
                                  #   worker thread fast even if the call is dropped)
    _PROBE_CALL_CAP_S = 12        # per-SIDE asyncio hard cap (> curl max-time so a
                                  #   legit-slow-but-completing call still passes)
    _WALK_BUDGET_S = 180          # total wall for the whole walk (was 360); a healthy
                                  #   ~50-tool walk runs well under this, a degraded one
                                  #   hard-stops here long before it can stall the worker
    _B_FAIL_FUSE = 5              # consecutive B timeouts → probe A-only for the rest
    _walk_start = time.monotonic()
    b_fused = False
    _b_consec_skips = 0
    # Cross-frame parity only applies when a real B frame is configured
    # (cloud-op flows pass b_registry_container="" and skip this walk).
    if not getattr(target, "b_registry_container", ""):
        return {"probed": 0, "drifts": 0, "drift_details": [],
                "a_unreachable": 0, "b_unreachable": 0, "timed_out": 0,
                "skipped": [], "skipped_count": 0, "b_fused": False, "compared": 0, "compared_tools": []}

    async def _bounded_side(coro, side: str):
        """Run one side's MCP call under a hard per-call wall. On timeout/error
        return a skip-sentinel (code '__skip__') so the walk records the tool +
        CONTINUES — a slow/blocking cross-frame call can never stall the walk or
        the worker. `coro` is always awaited/closed by wait_for."""
        try:
            return await asyncio.wait_for(coro, timeout=_PROBE_CALL_CAP_S)
        except asyncio.TimeoutError:
            return (False, {"_skip": f"{side} timeout >{_PROBE_CALL_CAP_S}s"}, "__skip__")
        except Exception as e:
            return (False, {"_skip": f"{side} {type(e).__name__}"}, "__skip__")

    for tool_name in _CROSS_FRAME_PARITY_TOOLS:
        if time.monotonic() - _walk_start > _WALK_BUDGET_S:
            logger.warning(
                f"cross-frame parity walk budget ({_WALK_BUDGET_S}s) exceeded "
                f"after {probed} tools — emitting partial result")
            break
        probed += 1
        # Once B has fused (degraded under load) probe A-only and record the
        # tool as b_unreachable — keeps the walk alive without re-blocking on B.
        if b_fused:
            a_ok, a_body, a_code = await _bounded_side(
                _mcp_rpc_call(target, tool_name, {}, jwt=dev_jwt, timeout=_PROBE_CURL_TIMEOUT), "A")
            if a_code == "__skip__":
                timed_out += 1
                skipped.append({"tool": tool_name, "a": a_body.get("_skip"), "b": "fused"})
            else:
                b_unreachable += 1
            continue
        # Both sides in parallel, each INDEPENDENTLY bounded (so a slow B does
        # not discard a good A and cannot exceed _PROBE_CALL_CAP_S wall).
        a_res, b_res = await asyncio.gather(
            _bounded_side(_mcp_rpc_call(target, tool_name, {}, jwt=dev_jwt, timeout=_PROBE_CURL_TIMEOUT), "A"),
            _bounded_side(_mcp_rpc_call_b(target, tool_name, {}, jwt=dev_jwt, timeout=_PROBE_CURL_TIMEOUT), "B"),
        )
        a_ok, a_body, a_code = a_res
        b_ok, b_body, b_code = b_res
        # B-side fuse bookkeeping (consecutive B skips → go A-only).
        if b_code == "__skip__":
            _b_consec_skips += 1
            if _b_consec_skips >= _B_FAIL_FUSE and not b_fused:
                b_fused = True
                logger.warning(
                    f"cross-frame B-side fused after {_B_FAIL_FUSE} consecutive "
                    f"timeouts — probing A-only for the remaining tools "
                    f"(sandbox-B degraded under load; walk stays alive)")
        else:
            _b_consec_skips = 0
        # Either side abandoned → record + continue (never block, never raise).
        if a_code == "__skip__" or b_code == "__skip__":
            timed_out += 1
            skipped.append({
                "tool": tool_name,
                "a": a_body.get("_skip") if a_code == "__skip__" else "ok",
                "b": b_body.get("_skip") if b_code == "__skip__" else "ok",
            })
            continue
        # Skip if either side wasn't reachable — that's a separate concern
        if not a_ok and not a_code.startswith("2"):
            a_unreachable += 1
            continue
        if not b_ok and not b_code.startswith("2"):
            b_unreachable += 1
            continue
        # Compare shape signatures
        compared.append(tool_name)
        a_sig = _shape_signature(a_body)
        b_sig = _shape_signature(b_body)
        if a_sig != b_sig:
            only_a = sorted(a_sig - b_sig)
            only_b = sorted(b_sig - a_sig)
            drifts.append({
                "tool": tool_name,
                "only_in_a": only_a[:10],
                "only_in_b": only_b[:10],
            })
    return {
        "probed": probed,
        "drifts": len(drifts),
        "drift_details": drifts[:25],
        "a_unreachable": a_unreachable,
        "b_unreachable": b_unreachable,
        "timed_out": timed_out,
        "skipped": skipped[:25],
        "skipped_count": len(skipped),
        "b_fused": b_fused,
        "compared": len(compared),
        "compared_tools": compared,
    }


# ---------------------------------------------------------------------------
# Contract evaluation
# ---------------------------------------------------------------------------

# §TESTBED (2026-09-19): two fixtures the network's sandbox had SEEDED BY HAND and a fresh frame never has: the AGORA
# listing the exchange read tools name (API_TEST_EXCHANGE_LISTING, else the retired tier's TUTCO) and the support review
# grant (API_TEST_SUPPORT_GRANT_ID). Measured on the first kit sandbox run (larchsbx): 5 reds, each a 404 in the server's own
# words "listing 'TUTCO' not found" / "No such review grant". With the variable UNSET and that phrase, the row is a named
# SKIP (a coverage hole, never a pass); a 404 on a fixture the frame DID name, or any other answer, still fails.
_EXCHANGE_FIXTURE_TOOLS = frozenset({"theprotocol_getAgoraListing", "theprotocol_getAgoraOrderBook",
                                     "theprotocol_getAgoraTrades", "theprotocol_getAgoraCandles"})


def _fixture_absent_reason(tool_name, healthy, skip_reason, status_code, fail_reason, env=None):
    env = os.environ if env is None else env
    if healthy or skip_reason or status_code != 404:
        return None
    fr = (fail_reason or "").lower()
    if tool_name in _EXCHANGE_FIXTURE_TOOLS and not env.get("API_TEST_EXCHANGE_LISTING") \
            and "listing" in fr and "not found" in fr:
        return ("fixture not seeded on this frame: the exchange read tools name the listing in API_TEST_EXCHANGE_LISTING "
                "(unset here, so the retired tier's TUTCO) and this frame has no such listing. Seed a listing and name "
                "it; NOT a defect in the tool.")
    if tool_name == "theprotocol_adminReviewMessages" and not env.get("API_TEST_SUPPORT_GRANT_ID") \
            and "no such review grant" in fr:
        return ("fixture not seeded on this frame: the review tools read the grant in API_TEST_SUPPORT_GRANT_ID (unset "
                "here). Seed a support ticket and a review grant and name it; NOT a defect in the tool.")
    return None


@dataclass
class ContractOutcome:
    tool_name: str
    contract_tier: str
    healthy: bool
    status_code: int
    elapsed_ms: int
    skip_reason: Optional[str]
    fail_reason: Optional[str]
    has_explicit_contract: bool
    args_used: Dict[str, Any]
    result_excerpt: Dict[str, Any]
    # Strict-mode outcome categories (2026-05-26):
    #   tier_drift: contract claimed tier-N but server demanded different auth
    #     (catches drift between MCP server.py TIER_N_TOOLS sets and wrapper code)
    #   contract_gap: tool was reached but no explicit contract exists AND
    #     the live tool's outputSchema has no required keys to derive from —
    #     means the tool is being walked but not really tested. Fail loudly.
    tier_drift: bool = False
    contract_gap: bool = False


def _parse_rpc_result(parsed: dict) -> Dict[str, Any]:
    """Extract the inner tool-result from a JSON-RPC envelope.

    JSON-RPC tools/call wraps the tool's return inside `result.content[0].text`
    as a JSON-encoded string. We unwrap it for assertion purposes. Falls
    back to the raw `result` field if unwrap fails.
    """
    if not isinstance(parsed, dict):
        return {}
    result = parsed.get("result") or {}
    content = result.get("content") or []
    if isinstance(content, list) and content and isinstance(content[0], dict):
        text = content[0].get("text") or ""
        if isinstance(text, str):
            try:
                return json.loads(text)
            except Exception:
                # Tools that return non-JSON text fall through
                return {"_text": text[:400]}
    return result if isinstance(result, dict) else {}


_WRAPPED_HTTP_RE = re.compile(r'HTTP[:\s]\s*(\d{3})')

# ── Self-harm guard: never point a destructive developer tool at the runner ──
# §MCPTEST-MCP2 2026-08-08. MEASURED root cause of the 401 cascade (69 of 79
# hard failures): the admin sweep filled every required `developer_id` param
# with the literal `1` — which IS the runner's own account (`admin@test.sandbox`,
# the same developer whose JWT authenticates the whole sweep).
#
# `suspend_developer` sets is_suspended AND bumps `developers.token_version`
# (admin_developers.py). Bumping that column invalidates EVERY live access
# token for that developer, so every later call returned
#   "Error: HTTP 401: Could not validate credentials".
# Proof it was self-inflicted: developer 1 carried token_version=14 while every
# other developer on the same registry sat at 0.
#
# It also defeated the re-login retry *silently*: a suspended developer cannot
# mint new tokens, so `login_admin` failed, the retry's `if _ok_re` guard fell
# through, and nothing was logged — which is why the retry read as "fired 0
# times" while the real damage was already done.
#
# Same class as the API tester's "the suite suspends its own fixture agent".
# Fix: destructive developer-targeting tools get a THROWAWAY victim id.
_SELF_HARMING_DEV_TOOLS = frozenset({
    "theprotocol_suspendDeveloper",
    "theprotocol_reinstateDeveloper",       # pairs with suspend — same target
    "theprotocol_softDeleteDeveloper",
    "theprotocol_forceDeveloperPasswordReset",
    "theprotocol_revokeDeveloperApiKeys",
    "theprotocol_disableDeveloper2FA",
    "theprotocol_updateDeveloperAdminFlags",
    "theprotocol_patchDeveloperQuota",
    "theprotocol_forceEmailVerify",
})

# An id no developer holds: the tool answers 404, an honest, non-destructive outcome, which is strictly better than
# revoking our own credentials mid-sweep. §MCPSWEEP 2026-09-27: this was 2, "the seeded non-admin test developer,
# deliberately NOT the runner"; on the tester frame id 2 IS the runner (admin@test.sandbox), so the day a lifecycle
# stopped covering one of the tools above, the sweep would have suspended or deleted itself.
_VICTIM_DEVELOPER_ID = 999999

# Tools that destroy the CALLER'S OWN session and take no target parameter, so
# no id-routing can protect against them. `logoutSession` bumps the caller's
# `developers.token_version`, which revokes every live token for that developer
# — measured: dev1 tv 15 -> 16 and the caller's JWT 401s on the next request.
# These are healed (re-login) immediately after the call instead of skipped, so
# the tool is still genuinely exercised.
_CALLER_SCOPED_SESSION_KILLERS = frozenset({
    "theprotocol_logoutSession",
})


def _resolve_developer_id_param(tool_name: str) -> int:
    """Pick the `developer_id` to hand a tool that requires one.

    Read-only tools get id 1 (the frame's first developer: an account with data to inspect, not necessarily the
    runner). Anything that MUTATES a developer is redirected to an id nobody holds, so the sweep can never revoke
    the credential it is running on.
    """
    if tool_name in _SELF_HARMING_DEV_TOOLS:
        return _VICTIM_DEVELOPER_ID
    return 1


# §MCPTEST-MCP10 (2026-08-08) — TRANSPORT TIMEOUT ≠ CONTRACT FAILURE.
#
# The wrappers call their OWN registry over HTTP (`REGISTRY_SELF_URL`). During a
# 742-tool sweep that self-call queues behind the sweep itself, so a tool whose
# endpoint answers instantly can still exceed the wrapper's 15 s client timeout.
# MEASURED on run e0a1ac89: `operatorPortalSelfRestart` returned its correct 503
# at 22 752 ms and PASSED, while its sibling `operatorPortalSelfLogs` — same
# guard, same immediate 503, same contract — timed out at 22 987 ms and was
# recorded as a contract failure. A 235 ms difference decided pass vs fail.
# `smartSend` failed the same way ("Smart send request timed out").
#
# That is our load reported as the endpoint's behaviour — the same class as the
# stale-token stamp (§MCPTEST) and the suspended-runner cascade
# (§MCPTEST-MCP2). Retry ONCE with a longer budget before classifying. If it
# times out again the failure stands and is reported: this hides slowness, not
# breakage.
#
# Deliberately PRECISE. It keys off timeout signatures only, never a bare 4xx,
# so a genuine contract failure can never be retried into a pass. No contract in
# mcp_contracts.py expects a timeout message (verified: 0 matches), so this can
# never mask an intended one.
_TRANSPORT_TIMEOUT_MARKS = (
    "ReadTimeout", "ConnectTimeout", "PoolTimeout", "WriteTimeout",
    "TimeoutException", "ConnectError", "timed out",
)


def _looks_like_transport_timeout(rpc_body: dict) -> bool:
    """True when the tool's error is OUR transport giving up, not the endpoint.

    Reads the same wrapped-error fields as `_wrapped_http_status`. Note the bare
    class names: until §MCPTEST-MCP10 the wrappers returned `str(e)` and httpx
    timeout exceptions stringify EMPTY, so this evidence did not exist in the
    payload at all — the operator saw "Error: " and nothing else.
    """
    try:
        inner = _parse_rpc_result(rpc_body)
    except Exception:
        return False
    if not isinstance(inner, dict):
        return False
    for key in ("_text", "error", "detail", "message"):
        v = inner.get(key)
        if isinstance(v, str) and any(m in v for m in _TRANSPORT_TIMEOUT_MARKS):
            return True
    return False


async def _retry_transport_timeout(rpc_caller, target, tool_name, args, jwt,
                                   rpc_ok, rpc_body, rpc_code, *, budget=75):
    """One longer-budget retry when the failure is OUR transport, not the tool.

    §MCPTEST-MCP10. Factored out deliberately: the first draft inlined this at
    ONE of the FOUR classification sites (`_sweep_one_public`), leaving the
    admin sweep and both cloud-op sweeps exposed to the identical flake. That is
    the §MCPTEST-FE2 shape — a repair that covers one of N paths and reads as
    covering all of them — and an AST check of the call sites is what caught it,
    not review. Every site now calls this, so the coverage is countable.

    Returns the (possibly retried) ``(ok, body, code)`` triple unchanged when
    the failure was not a timeout.
    """
    # §MCPTEST-MCP10b — a NON-HTTP status code is a transport failure too.
    # My first cut keyed only on timeout markers in the BODY, so a call that
    # never got an answer at all — curl's `000`, empty body — fell straight
    # through and was classified as a contract failure. MEASURED on run
    # 8be284f1: `adminCanaryFleetStatus :: expected success but got HTTP 000`,
    # the single remaining failure, and exactly the case the retry exists for.
    # This is the same predicate the auth matrix now uses (`_measured`): if we
    # never got an HTTP answer, we learned nothing about the endpoint.
    _no_http_answer = not (str(rpc_code).isdigit() and 100 <= int(rpc_code) <= 599)
    if rpc_ok or not (_no_http_answer or _looks_like_transport_timeout(rpc_body)):
        return rpc_ok, rpc_body, rpc_code
    logger.warning(
        "[MCP-TimeoutRetry] %s hit a transport timeout (code=%s) — retrying "
        "once at %ss before classifying", tool_name, rpc_code, budget,
    )
    _r_ok, _r_body, _r_code = await rpc_caller(
        target, tool_name, args, jwt=jwt, timeout=budget,
    )
    _r_no_answer = not (str(_r_code).isdigit() and 100 <= int(_r_code) <= 599)
    if _r_ok or not (_r_no_answer or _looks_like_transport_timeout(_r_body)):
        logger.warning(
            "[MCP-TimeoutRetry] %s healed on retry (%s -> %s) — the first "
            "result was our load, not the endpoint", tool_name, rpc_code, _r_code,
        )
        return _r_ok, _r_body, _r_code
    logger.error(
        "[MCP-TimeoutRetry] %s timed out AGAIN at %ss — recording the failure; "
        "this is not transient", tool_name, budget,
    )
    return rpc_ok, rpc_body, rpc_code


def _wrapped_http_status(parsed: dict) -> Optional[int]:
    """Unmask an MCP-wrapped backend error returned as transport-200.

    pass73.3.19 (2026-05-28): the MCP dispatcher catches a backend error and
    formats it as the tool's RESULT — inner text "Error: HTTP 404: …" (→
    `{"_text": "Error: HTTP 404: …"}`) or a leaked `{"error"/"detail": "…"}`.
    The JSON-RPC envelope is still HTTP 200 with no top-level `error`, so the
    sweep recorded a FALSE 200/healthy (176 such rows found 2026-05-28). Detect
    the pattern and return the real 4xx/5xx code so callers can record reality.
    Returns None on a genuine success (no wrapped error). Conservative: only
    fires on the wrapper's literal "Error:"-prefixed text + an HTTP NNN code,
    so legit payloads that merely mention an HTTP number are untouched.
    """
    try:
        inner = _parse_rpc_result(parsed)
    except Exception:
        return None
    if not isinstance(inner, dict):
        return None
    # §CLOUDOPMCP2 2026-09-05 — B6's envelope, BOTH lanes (V0223). The converted
    # wrappers deliberately stop using `error` so the dispatcher no longer eats the
    # RFC7807 detail; they return {status_code, upstream_error, body|detail, path}
    # with NO `_text` and NO `error`. None of those old keys is present, so the scan
    # below returned None and the row would record a FALSE 200/healthy — precisely
    # the class this function exists to prevent (see the docstring: 176 such rows,
    # 2026-05-28), reintroduced through a new key. Worse than a false fail: the
    # gate-marker branch only runs for `not healthy`, so a genuinely REFUSED tool
    # would never reach it and would count as a pass.
    # The envelope states the upstream status outright, so trust it over any string
    # parse — but only when `upstream_error` is also present, which is what makes it
    # this envelope rather than a payload that merely has a `status_code` field.
    if isinstance(inner.get("upstream_error"), str) and inner.get("upstream_error").strip():
        sc = inner.get("status_code")
        if isinstance(sc, int) and 400 <= sc < 600:
            return sc
    for key in ("_text", "error", "detail", "upstream_error", "body"):
        v = inner.get(key)
        # Two wrapper error formats carry a backend status code:
        #   (a) _public_get/_dev_request → "Error: HTTP 404: …"   ("Error:" prefix)
        #   (b) _agent_get/_agent_post   → "getRelayStatus returned HTTP 401"
        # pass73.3.19: format (b) lacks the "Error:" prefix and was silently
        # missed — tier-2 backend 4xx/5xx were recorded as false 200s. Catch both.
        if isinstance(v, str) and "HTTP" in v and ("Error:" in v or "returned HTTP" in v):
            m = _WRAPPED_HTTP_RE.search(v)
            if m:
                code = int(m.group(1))
                if 400 <= code < 600:
                    return code
    # pass73.3.19 follow-up (2026-05-28): wrapper-VALIDATION errors carry NO HTTP
    # code — e.g. {"_text": "Error: agent_dids (list) is required"} or "Error: "
    # (empty) or a leaked {"error": "<msg>"} from a wrapper's own arg check. These
    # were counted as FALSE 200/healthy (Bucket A, ~9 tools found 2026-05-28: the
    # bulkRefreshAgentCards class). The wrapper rejected the call → synthetic 400.
    # PRECISE so legit payloads that merely contain the substring "error" (e.g.
    # getMyLockStatus's {"system_status":...}) are untouched: only a `_text`
    # that LITERALLY starts with "Error:" (the _format_tool_result error format),
    # or a top-level non-empty string `error` key (the {"error": "..."} wrapper format).
    t = inner.get("_text")
    e = inner.get("error")
    # §MCPTEST30 (V0552): a TRANSPORT failure of the tool's own call to its route is not the wrapper refusing its
    # arguments. "Error: ReadTimeout" read as a synthetic 400, so an any-status probe counted it a healthy refusal:
    # testApiEndpoint timed out in rounds 16 and 17 and passed, getAdminWorkersStatus timed out on an operator and
    # passed, getAdminDeveloperDetail timed out (its route made one query per agent, 6,685 of them) and read NOT
    # MEASURED. A timeout is the route not answering in time (504), a broken connection the route unreachable (502).
    for v in (t, e):
        if isinstance(v, str) and v.strip():
            transport = _inner_transport_status(v)
            if transport is not None:
                return transport
    if isinstance(t, str) and t.strip().startswith("Error:"):
        return 400
    if isinstance(e, str) and e.strip():
        return 400
    return None


_INNER_TIMEOUT_RE = re.compile(r"\b(ReadTimeout|WriteTimeout|PoolTimeout|ConnectTimeout|TimeoutException)\b"
                               r"|\btimed out after \d+(\.\d+)?s\b")
_INNER_CONNECT_RE = re.compile(r"\b(ConnectError|RemoteProtocolError|ReadError|WriteError)\b")


def _inner_transport_status(text: str) -> Optional[int]:
    """504 when the tool's own call to its route timed out, 502 when it could not complete it; None otherwise. Only
    the exception names httpx raises, as the tools render them ("Error: ReadTimeout"), and the tools' own sentence
    ("Request timed out after 30.0s"), never prose that mentions one."""
    head = text.strip()
    if not head.startswith("Error:") and len(head) > 80:
        return None
    if _INNER_TIMEOUT_RE.search(head[:120]):
        return 504
    if _INNER_CONNECT_RE.search(head[:120]):
        return 502
    return None



# ── §ADMINMATRIX — module level so it is unit-testable ──────────────────
# THE SAFETY RULE, derived rather than hand-listed. A probe only reaches a
# tool BODY if that tool's gate is broken — which is the finding this matrix
# exists to produce, and also the action it would perform. Measured here:
# of 321 admin tools, 166 have REQUIRED arguments and are refused at dispatch
# (`-32602`, a TypeError on the call signature) whatever their gate does, so
# probing them is free. The 155 with no required args are the reachable set,
# and among them the ones whose NAME says they act are the ones whose
# accidental execution is not an acceptable price for the finding:
# rotateRegistrySigningKey, startSimulation/stopSimulation (the standing sim
# rule), fundSimulationAgents, issueFrameBSimulation,
# cloudOperatorSelfRestart, the canary fleet pause/resume.
#
# A hand list would rot as tools are added; this asks the SCHEMA and the verb.
# It over-skips (a read named `getAdminFundingAll` matches `fund`), which is
# the safe direction, and every skip is REPORTED in `admin_matrix_not_probed`
# so the gap is visible instead of assumed.
# Pacing for the admin matrix (see the 429 note in the sweep). Env-tunable so a
# node with a different `RATE_LIMIT_DEFAULT` can be measured without a code change.
# 2.0 s at concurrency 2 is ~1 probe/sec. Measured: 0.4 s (~5/sec) still met the
# bucket on roughly half the probes, so the effective budget for a NON-admin caller
# on this route is far below the 1000/minute the env advertises. One per second is
# the rate at which the phase stops fighting the limiter; the shared cooldown below
# is the safety net, not the plan.
_ADMIN_MATRIX_PACE_SEC = float(os.environ.get("MCP_TESTER_ADMIN_MATRIX_PACE_SEC", "2.0") or 2.0)
# How many times a 429 is retried after a window-scale backoff. ONE was the
# original, and the full pass measured what it costs: 80 of 281 probes
# unmeasured while the time budget went unused. Bounded, and the deadline still
# wins over it.
_ADMIN_MATRIX_429_RETRIES = int(
    os.environ.get("MCP_TESTER_ADMIN_MATRIX_429_RETRIES", "3") or 3)
_ADMIN_MATRIX_429_BACKOFF_SEC = float(
    os.environ.get("MCP_TESTER_ADMIN_MATRIX_BACKOFF_SEC", "20") or 20)
# A WALL-CLOCK BUDGET, because the honest rate is the limiter's, not ours. Measured
# on this tier: the bucket for a NON-admin caller on /mcp/admin/rpc yields roughly
# 8 measured probes a minute once the public matrix has spent its share, so all 281
# admin tools would take ~35 minutes — a price no routine sweep should pay. The
# phase therefore probes what it can inside the budget and REPORTS what it did not
# reach, instead of either lying about coverage or running for half an hour.
_ADMIN_MATRIX_BUDGET_SEC = float(
    os.environ.get("MCP_TESTER_ADMIN_MATRIX_BUDGET_SEC", "120") or 120)

_ADMIN_ACTS_RE = re.compile(
    r"(teardown|delete|revoke|suspend|remove|reset|rotate|stop|start|restart|"
    r"provision|mint|issue|fund|transfer|slash|quarantine|blacklist|purge|sweep|"
    r"trigger|run|force|apply|approve|reject|retract|disable|enable|distribute|"
    r"refund|replay|reconcile|pause|resume|lift|hide|create|update|patch|set)",
    re.I)

def _admin_probe_is_safe(tool: dict) -> bool:
    """True when a `{}` probe cannot execute this tool even with a broken gate."""
    if ((tool.get("inputSchema") or {}).get("required") or []):
        return True                      # refused at dispatch, body unreachable
    name = (tool.get("name") or "").replace("theprotocol_", "")
    return not _ADMIN_ACTS_RE.search(name)

def _wrong_tier_rejected(status: int, body: Any) -> bool:
    """Did the server REFUSE this wrong-tier call? (the auth matrix's one predicate)

    §EVTYPES8 2026-09-06 — lifted verbatim out of the central matrix so the cloud-op
    matrix asks the SAME question. Two implementations of "was this refused?" drift,
    and the drift is invisible: each side keeps reporting zero violations for its own
    reasons. One function, both callers.

    Counts as a rejection:
      1. HTTP 401/403 — an explicit auth refusal.
      2. a JSON-RPC top-level error.
      3. a wrapper-error envelope in result.content[0].text carrying an auth or
         permission word, or simply "Error:" (the dispatcher renders wrapper
         {error: "X"} as content text "Error: X" — the F.1 false-positive fix).
      4. a MISSING-ARG wrapper error, which is also a rejection: the call was made
         with `{}` on purpose, so the tool did not perform the operation either way.

    Deliberately LENIENT. A false "rejected" costs coverage; a false "accepted" is
    reported as a privilege-escalation violation, and that is the expensive mistake.
    """
    if status in (401, 403):
        return True
    if not isinstance(body, dict):
        return False
    if body.get("error"):
        return True
    try:
        content = (body.get("result") or {}).get("content") or []
        text = ""
        if content and isinstance(content[0], dict):
            text = (content[0].get("text") or "")
        tl = text.lower()
        return (
            tl.startswith("error:") or
            "auth" in tl or "permission" in tl or
            "unauthor" in tl or "forbidden" in tl or
            "not allowed" in tl or "is required" in tl or
            "missing" in tl or "must be admin" in tl or
            "could not validate" in tl or "invalid" in tl
        )
    except Exception:                                            # noqa: BLE001
        return False


_GATE_WORDS = ("auth", "permission", "unauthor", "forbidden", "not allowed", "could not validate", "token", "jwt",
               "credential", "admin")


def _wrong_tier_refused_before_gate(body: Any) -> bool:
    """§MCPSWEEP 2026-09-27 — was this wrong-tier `{}` call refused BEFORE any tier gate ran?

    The matrix calls every tool with `{}` on purpose (with an open gate, real arguments could make the probe perform
    the action). For a tool with required arguments the dispatcher then refuses the call before it runs the tool
    (-32602: the arguments do not fit its signature), or the tool checks its arguments before its tier and answers
    "X is required". `_wrong_tier_rejected` counts both as refusals, deliberately leniently, so they are never scored
    as accepts; but they measured nothing about the gate. They are counted apart, like an inconclusive probe: neither
    a measured refusal nor a violation."""
    if not isinstance(body, dict):
        return False
    err = body.get("error")
    if isinstance(err, dict) and err.get("code") in (-32700, -32600, -32601, -32602):
        return True
    try:
        content = (body.get("result") or {}).get("content") or []
        text = (content[0].get("text") or "") if content and isinstance(content[0], dict) else ""
    except Exception:                                            # noqa: BLE001
        return False
    tl = text.lower()
    names_missing = " is required" in tl or " are required" in tl or "missing" in tl
    return names_missing and not any(w in tl for w in _GATE_WORDS)


def _schema_required_keys(tool: Dict[str, Any]) -> List[str]:
    """Pull the required-keys list from a tool's outputSchema.

    MCP tools advertise outputSchema in tools/list. We use its `required`
    array as the strict-mode floor for response-shape assertions when the
    contract didn't supply explicit `expect_keys`. Empty list → no schema
    information available → caller must treat as a contract gap.
    """
    if not isinstance(tool, dict):
        return []
    out = tool.get("outputSchema")
    if not isinstance(out, dict):
        return []
    req = out.get("required")
    if isinstance(req, list):
        return [k for k in req if isinstance(k, str)]
    return []


def _coerce_type_spec(spec):
    """Normalize an expect_types value to a tuple of python types.

    Accepts a single type, a tuple of types, or a string alias like
    "int|float|str|bool|list|dict|number". Anything unrecognized → object
    (matches anything, surfacing as a no-op rather than a runtime crash).
    """
    _aliases = {
        "int": int, "integer": int,
        "float": float, "number": (int, float),
        "str": str, "string": str,
        "bool": bool, "boolean": bool,
        "list": list, "array": list,
        "dict": dict, "object": dict,
    }
    if isinstance(spec, str):
        return _aliases.get(spec, object)
    if isinstance(spec, type):
        return spec
    if isinstance(spec, tuple) and all(isinstance(s, (type, tuple)) for s in spec):
        return spec
    return object



# §RUNNERCRED 2026-09-07 — A LIFECYCLE OUTCOME MUST NOT LAUNDER AN AUTH FAILURE
# INTO A PASS.
#
# A lifecycle/setup outcome takes precedence over the per-tool contract sweep
# (three sites), and it is trusted whole — including its `healthy` flag. MEASURED
# on the 2026-09-07 flagship run: 93 rows were healthy with a recorded 401/403,
# and 31 of them have contracts that expect SUCCESS. Control, same image, fresh
# credential: `getMyDeletionStatus` and `getMyMcpAuditLog` both answer 200 with
# real data. So those 31 are the RUNNER'S OWN token dying mid-sweep (the 401
# cascade this file already documents at length) being reported as endpoint health.
#
# A 401 is not a pass and it is not the endpoint's failure either — it is a
# measurement that could not be taken. Blaming the tool would be the false
# NEGATIVE the retry exists to prevent; passing it is the false POSITIVE, which is
# worse because nobody goes looking. So: neither. It becomes a loud skip.
#
# A contract that DELIBERATELY pins a 401/403 refusal (expect_status error_4xx) is
# untouched — that is a measurement, and 54 rows in the same run are exactly that.
_LAUNDERED_STATUSES = (401, 403)


def _credential_laundering_guard(outcome_dict: dict, tool_name: str) -> Optional[str]:
    """Return a skip reason when a recorded outcome sells a 4xx as a pass.

    None means the outcome is trustworthy and should be used as recorded.

    §RUNNERCRED-3 2026-09-07 — THIS FUNCTION USED TO NAME A CAUSE AND THE CAUSE WAS
    WRONG FOR PART OF THE POPULATION. It said "the sweep's token was dead or it
    lacked authority… that is OURS, not the endpoint's". Censusing the 40 rows BY
    BODY rather than by status:

        25  "Could not validate credentials"            ← genuinely our dead token
         1  "Invalid or expired refresh token"          ← authRefresh probing a bad
                                                          token ON PURPOSE
         1  "You don't hold the 'phoenix' encirclement…"  ← a semantic 403 (V0643's words)
         …  empty excerpts (called with jwt="") and wrapper text

    and, measured by hand, `requestAccountDeletion` answers **401 "Invalid
    password."** for a wrong confirmation password while the caller's token stays
    perfectly valid. A 401 is not proof of anything about the credential — which is
    this project's own rule (classify by the response BODY, never the status) and I
    broke it in the first version of this guard.

    So the reason no longer asserts a cause. It states the invariant that is
    objectively true of every row it catches — a lifecycle recorded `healthy` under
    `expect_status="any"` while the call returned 4xx and this tool's contract
    expects success, so the success path was never measured — and it CARRIES THE
    BODY so the reader sees the actual cause instead of my guess.
    """
    try:
        if not outcome_dict.get("healthy"):
            return None
        st = int(outcome_dict.get("status_code") or 0)
        if st not in _LAUNDERED_STATUSES:
            return None
        # §MCPTEST30 (V0551): a tool the target switched off was judged by its switch in the lifecycle (the documented
        # status AND the code word, never "any"); that refusal is the row's measurement, even where the tool's contract
        # says do not call (round 17 called tegLockDirect, claimTegPayouts and triggerLockPayoutRun unmeasured)
        if _switches.switched_off(tool_name) is not None and outcome_dict.get("switched_off"):
            return None
        c = get_contract(tool_name)
        if getattr(c, "expect_status", None) in ("error_4xx", "error_5xx", "error"):
            return None          # the refusal IS the contract — a real measurement
        _body = ""
        try:
            _ex = outcome_dict.get("result_excerpt")
            _body = (json.dumps(_ex) if not isinstance(_ex, str) else _ex)[:90]
        except Exception:        # noqa: BLE001
            _body = ""
        # §MCPTEST30 (V0644): where the refusal is by design (refusal_reasons), the row says why as well
        _by_design = _refusal_reasons.declared(tool_name)
        return (
            f"lifecycle recorded a {st} as healthy — the step ran under "
            f"expect_status='any' while this tool's contract expects SUCCESS, so the "
            f"success path was not measured. "
            + (f"By design: {_by_design}. " if _by_design else "")
            + f"The body says: {_body or '(no excerpt)'}"
        )
    except Exception:            # noqa: BLE001 — a guard must never break the sweep
        return None


def _fan_row_verdict(outcome_dict: dict, tool_name: str) -> dict:
    """§FANCLAIM 2026-09-07 — THE COVERAGE FAN MAY NOT ANSWER A CONTRACT'S QUESTION
    WITH AN EASIER ONE.

    A lifecycle "coverage fan" probe calls a tool with deliberately-invalid input
    under `expect_status="any"` — it asks *did anything at all come back*. When such
    a row exists, the fan writes it into the tool's result and RETURNS, so the tool's
    own contract is never run.  For a tool whose contract says `expect_status=
    "success"` that is two different questions with one answer: the row reads healthy
    and the SUCCESS path was never measured.  Measured 2026-09-07: **81 tools** in
    that position, **41 of them carrying an explicit `skip_reason`** the fan
    overrode — a declarative "do not sweep this / this cannot be measured here"
    answered by a probe that only asked whether the server was awake.  The twelve
    he was shown (`tegSystemTransfer`, `claimTegPayouts`, the three bridge tools,
    `blockFederationAgent` …) are a sample of that 81, not the population.

    This is `override_coverage_fan` as a DEFAULT instead of an opt-in: that flag
    exists for exactly this and was set on 5 of 483 contracts.  Rather than flip 81
    tools into really CALLING their success path — which for a bridge mint or a
    federation block means the suite performing the act, the refusal-contract-
    becomes-an-action hazard — the row is recorded as NOT MEASURED and says so.
    Skips are counted separately from passes, so the number stops overstating.

    Returns the outcome dict to use (a copy when it had to be adjusted).
    """
    d = outcome_dict
    _cred_skip = _credential_laundering_guard(d, tool_name)
    if _cred_skip:
        d = dict(d)
        d["healthy"] = False
        d["skip_reason"] = _cred_skip
        d["fail_reason"] = None
        return d
    # SCOPE, deliberately narrow: only a HAND-CURATED contract. `get_contract`
    # falls back to DEFAULT_CONTRACT, which also says expect_status="success", so
    # keying on the resolved contract would flip 267 rows instead of 81 — including
    # 167 tools nobody has ever written a requirement for. For those the any-status
    # probe is thin coverage, not zero (it proves the tool dispatches and does not
    # 5xx), and re-grading them on my own judgment would trade one wrong number for
    # another. They are told apart by `has_explicit_contract` instead. What is NOT
    # defensible is the sweep contradicting a requirement a person actually wrote —
    # that is this branch.
    if tool_name not in MCP_CONTRACTS:
        return d
    contract = get_contract(tool_name)
    # A contract that expects a refusal is ANSWERED by an any-status probe; a probe
    # that already failed keeps its failure (that is a real finding, not a gap).
    # §FANCLAIM-2 2026-09-07 — A 4xx CANNOT DEMONSTRATE A SUCCESS PATH. A 2xx CAN.
    # The first version fired on any healthy any-probe, and under expect_status="any"
    # `healthy` means only `code < 500` — so it swept up rows where the probe actually
    # got a 2xx and declared them "no success-path coverage". That is false: the tool
    # was called and it succeeded; what went unchecked is the contract's `expect_keys`
    # SHAPE, which is a weaker claim and not the same finding. He read the headline as
    # a regression, and on those rows he was right to.
    # The class this exists for is a REFUSAL sold as a pass — 400/404/422 and the
    # 401/403 the laundering guard already takes. Keep it to that.
    _code = d.get("status_code")
    _is_2xx = isinstance(_code, int) and 200 <= _code < 300
    if (contract.expect_status == "success"
            and (d.get("probe_expect_status") or "success") == "any"
            and d.get("healthy")
            and not _is_2xx):
        d = dict(d)
        d["healthy"] = False
        d["fail_reason"] = None
        _declared = contract.skip_reason or getattr(contract, "success_path_unmeasured", None)
        d["skip_reason"] = (
            (f"contract says: {_declared}" if _declared else
             f"no success-path coverage: the only call this sweep makes is an "
             f"any-status reachability probe with deliberately-invalid input, and it "
             f"was REFUSED (HTTP {_code})")
            + " — the contract requires expect_status='success', so this row is "
              "NOT MEASURED, not a pass (§FANCLAIM). Give the tool a fixture and "
              "`override_coverage_fan=True` to hold it to its contract."
        )
    return d


def _evaluate_contract(
    tool: Dict[str, Any],
    contract: McpContract,
    rpc_ok: bool,
    rpc_status: str,
    rpc_body: Dict[str, Any],
    bag: McpFixtureBag,
    *,
    has_explicit_contract: bool = False,
) -> Tuple[bool, Optional[str]]:
    """Apply the contract's expectations against the actual response —
    strict mode (2026-05-26).

    Returns (healthy, fail_reason). `healthy=True` means contract satisfied.

    Strict-mode rules (handover HANDOVER_2026-05-26_SANDBOX_PARITY_AND_REAL_MCP_TESTS):
      • Default contract WITHOUT explicit `expect_keys` falls back to the
        tool's `outputSchema.required`. If neither exists → contract gap
        → healthy=False with reason "no shape assertion (contract gap)".
      • `expect_status="error_4xx"`/`error_5xx"` MUST be paired with
        `expect_error_message_contains` OR `expect_error_keys`. Bare
        "expected to fail" passes are doctrine-banned.
      • Every declared `expect_types` key is isinstance-checked.
      • Skip is NOT healthy — caller decides outcome category. We still
        short-circuit here to skip downstream checks.
    """
    # Skip path — caller folds into outcome.skip_reason
    if contract.skip_reason:
        return True, None

    inner = _parse_rpc_result(rpc_body)
    code_int = int(rpc_status) if rpc_status.isdigit() else 0
    err = (rpc_body or {}).get("error", {}) if isinstance(rpc_body, dict) else {}
    err_msg = err.get("message") if isinstance(err, dict) else str(err)
    # pass73.3.19: wrapped backend errors arrive as transport-200 with the real
    # message inside result.content text ({"_text": "Error: HTTP 404: …"}), NOT
    # as a JSON-RPC top-level error. _wrapped_http_status already rewrote the
    # code; mirror that here so expect_error_message_contains can match the
    # wrapped text instead of seeing an empty err_msg (which silently failed
    # every error-path contract — getTrustScore/operatorPortal*/etc).
    if not err_msg and isinstance(inner, dict):
        # §CLOUDOPMCP2 2026-09-05 — B6's envelope again (see _wrapped_http_status).
        # The converted wrappers carry no `_text`/`error`, so without the last two
        # keys `err_msg` stays empty on V0223 and every expect_error_message_contains
        # contract fails with "no message" — losing the diagnostic exactly where the
        # conversion was meant to ADD one.
        # `body` before `upstream_error` on purpose: `body` is the upstream RFC7807
        # detail and therefore the one carrying the gate phrase ("... is not enabled
        # on this registry"), while `upstream_error` is only the "X returned HTTP N"
        # summary. First non-empty wins, so the richer source must come first.
        for _k in ("_text", "error", "detail", "message", "body", "upstream_error"):
            _v = inner.get(_k)
            if isinstance(_v, str) and _v:
                err_msg = _v
                break

    # Status-class check first
    if contract.expect_status == "success":
        if not rpc_ok:
            return False, f"expected success but got HTTP {rpc_status}: {err_msg or 'no message'}"
    elif contract.expect_status in ("error_4xx", "error_5xx", "error"):
        # STRICT: bare error_4xx/error_5xx is banned. Require an explicit
        # error-body assertion (message substring OR error-payload keys).
        if not (contract.expect_error_message_contains or contract.expect_error_keys):
            return False, (
                f"banned pattern: expect_status='{contract.expect_status}' without "
                f"expect_error_message_contains/expect_error_keys — see handover"
            )
        # §MCPTEST30 (V0541): "error" takes either class; the body must still name an expected refusal
        lo, hi = {"error_4xx": (400, 500), "error_5xx": (500, 600)}.get(contract.expect_status, (400, 600))
        if not (lo <= code_int < hi):
            return False, f"expected {contract.expect_status} but got {rpc_status} ok={rpc_ok}"
        # Verify error message substring
        if contract.expect_error_message_contains:
            _wanted = contract.expect_error_message_contains
            _alts = list(_wanted) if isinstance(_wanted, (list, tuple)) else [_wanted]
            if not err_msg or not any(a in err_msg for a in _alts):
                return False, (
                    f"expected error message contains one of "
                    f"{_alts} got '{err_msg or ''}'"
                )
        # Verify error payload keys
        if contract.expect_error_keys:
            err_body = err if isinstance(err, dict) else {}
            missing = [k for k in contract.expect_error_keys if k not in err_body]
            if missing:
                return False, f"missing keys in error body: {missing}"
        return True, None
    # "any" — no status check

    # Resolve required-keys (strict mode, 2026-05-26):
    # - explicit `contract.expect_keys` always wins (operator's intent)
    # - empty `expect_keys` → fall back to tool's outputSchema.required
    # - both empty → contract gap (fail loudly; "fancy ping" prevention)
    required_keys = list(contract.expect_keys or [])
    derived = False
    if not required_keys:
        required_keys = _schema_required_keys(tool)
        derived = True
        if not required_keys:
            return False, (
                "contract gap: no expect_keys AND no outputSchema.required — "
                "add explicit expect_keys or declare outputSchema on the tool"
            )

    if required_keys:
        missing = [k for k in required_keys if k not in inner]
        if missing:
            origin = "(derived from outputSchema)" if derived else "(explicit)"
            return False, f"missing keys: {missing} required={required_keys} {origin}"

    # expect_types: isinstance check per declared field
    if contract.expect_types:
        for key, spec in contract.expect_types.items():
            if key not in inner:
                continue  # missing keys already handled above
            wanted = _coerce_type_spec(spec)
            if not isinstance(inner[key], wanted):
                return False, (
                    f"type mismatch for '{key}': got {type(inner[key]).__name__} "
                    f"expected {wanted}"
                )

    # side_effect_assert callback (required on every mutation contract)
    if contract.side_effect_assert is not None:
        try:
            ok = contract.side_effect_assert(inner, bag)
            if not ok:
                return False, "side_effect_assert returned False"
        except Exception as e:
            return False, f"side_effect_assert raised: {e!r}"

    return True, None


# §MCPTEST30 (V0551): a refusal contract carries no expect_keys BY DESIGN: _evaluate_contract judges it by its status
# class and its phrase (and refuses a bare one as the banned pattern). The operator admin sweep read "no expect_keys" as
# "nothing to judge by" and skipped it as a contract gap, so V0550's 81 refusal pins (override_coverage_fan, which also
# drops the fan row) went unmeasured on every operator: sandboxalpha 93 -> 166 skipped in round 17 while 73 of them had
# passed in round 16 through the fan. A gap is a SUCCESS contract with no shape to hold the answer to.
_REFUSAL_STATUSES = ("error_4xx", "error_5xx", "error")


def _cloudop_admin_contract_gap(contract: McpContract) -> bool:
    """True when the operator admin sweep has nothing to judge a call by (no shape and no refusal to hold it to)."""
    return not contract.expect_keys and contract.expect_status not in _REFUSAL_STATUSES


# ---------------------------------------------------------------------------
# Fixture bag bootstrap
# ---------------------------------------------------------------------------

# ─── §pass73.2 task G — orphan sweeper ────────────────────────────────────
# Capture row counts on entity tables that lifecycles touch. Delta between
# pre-sweep and post-sweep snapshots reveals which lifecycles create entities
# they don't clean up. Useful as a hygiene gauge — many tables intentionally
# accumulate (attestations, contracts, reputation_bonds are immutable by
# protocol; agent_logs/metrics are time-series). Surfaces in flow_values as
# `orphans_by_table`. Observation only — does NOT fail the sweep.
_ORPHAN_TRACKED_TABLES = (
    "developers",
    "agents",
    "agent_cards",
    "agent_pipelines",
    "agent_versions",
    "agent_deployments",
    "organizations",
    "organization_members",
    "developer_api_keys",
    "support_tickets",
    "peer_registries",
    "frame_invitations",
    "federation_licenses",
    "bundle_reports",
    "admin_broadcasts",
    "disputes",
    "agent_flags",
    # Intentionally-accumulating (tracked for visibility, won't fail):
    "attestations",
    "reputation_bonds",
    "bridge_transactions",
)


async def _snapshot_row_counts(db_container_name: str, db_name: Optional[str] = None) -> Dict[str, int]:
    """Capture row counts for tracked tables. Returns {table: count}. -1 = error."""
    if not db_container_name:
        return {}
    # Build a single multi-SELECT to minimize round-trips
    union_sql = " UNION ALL ".join(
        f"SELECT '{t}' AS tbl, COUNT(*) AS n FROM {t}"
        for t in _ORPHAN_TRACKED_TABLES
    )
    rc, out = await asyncio.to_thread(
        exec_in_container, db_container_name, [
            "psql", "-U", "postgres", "-d", db_name,
            "-t", "-A", "-F", "|",
            "-c", union_sql,
        ], 30,
    )
    snapshot: Dict[str, int] = {}
    if rc != 0:
        logger.warning(f"orphan snapshot failed rc={rc} out={(out or '')[:200]}")
        return {t: -1 for t in _ORPHAN_TRACKED_TABLES}
    for line in (out or "").splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = line.split("|")
        if len(parts) >= 2 and parts[1].isdigit():
            snapshot[parts[0].strip()] = int(parts[1].strip())
    # Fill any missing tables with -1
    for t in _ORPHAN_TRACKED_TABLES:
        snapshot.setdefault(t, -1)
    return snapshot


def _diff_row_counts(before: Dict[str, int], after: Dict[str, int]) -> Dict[str, int]:
    """Return {table: delta} for tables where after > before. -1 sentinels skipped."""
    deltas: Dict[str, int] = {}
    for table in _ORPHAN_TRACKED_TABLES:
        b = before.get(table, -1)
        a = after.get(table, -1)
        if b == -1 or a == -1:
            continue
        if a > b:
            deltas[table] = a - b
    return deltas


async def _required_bond_amount(container: str) -> Optional[str]:
    """The reputation bond THIS registry actually requires, read from its own policy.

    §CLOUDOPMCP2 2026-09-05. §REPBOND makes the bond per-registry policy
    (`REPUTATION_BOND_AMOUNT`, GRANT x 25% = 250 on a 1,000 grant) and the deposit
    route refuses anything under it:

        400 "The bond must be at least 250 SBXA (asked 50)."   services/reputation_bond.py

    Both sentinel fixtures used to hardcode a number — 10 on the central path, 50 on the
    cloud-op path — chosen when the policy default was small. With the sandbox at
    enforce/250 the deposit 400'd, the sentinel held NO bond, and every bond-gated site
    then refused it: authorizePayment 403 ("holds no reputation bond ... requires a bond
    of 250 SBXA"), guildBid 403 at setup, getMyReputationBondStatus 404.

    So read it. A hardcoded 250 would rot exactly the way 10 and 50 did — the amount is
    policy and policy differs per registry. `/reputation-bond/config` is public (no auth;
    measured 200 on both a frame and a cloud-op). Returns None when the policy cannot be
    read, and the caller then SKIPS the deposit with a named reason instead of guessing —
    guessing is how this broke in the first place.
    """
    if not container:
        return None
    try:
        rc, out = await asyncio.to_thread(
            exec_in_container, container, [
                "sh", "-c",
                "curl -sS --max-time 15 http://localhost:8000/api/v1/reputation-bond/config",
            ], 20)
    except Exception as e:                                            # noqa: BLE001
        logger.warning("bond policy read failed on %s (non-fatal): %r", container, e)
        return None
    if rc != 0 or not out:
        logger.warning("bond policy unreadable on %s: rc=%s", container, rc)
        return None
    for line in reversed([ln for ln in str(out).splitlines() if ln.strip()]):
        if not line.lstrip().startswith("{"):
            continue
        try:
            amt = json.loads(line).get("amount")
        except Exception:                                             # noqa: BLE001
            continue
        if amt is not None:
            return str(amt)
    logger.warning("bond policy on %s carried no 'amount'", container)
    return None


# §MCPSWEEP 2026-09-27 (agentvault2-41): the proposal chain. createProposal answered
#   403 "This frame requires 100 locked units to open a proposal (governance.min_stake_to_propose_avt); you hold 10 locked."
#   (V0643's words)
# on sbx-alpha in every sweep of the day (03:09Z, 14:05Z, 20:50Z), so `proposal_id` never reached flow_values and
# getProposalDetail, getProposalVotes and getMyVoteOnProposal skipped as "fixture missing". Step 9b's governor grant
# (2026-09-06) closed the permission half; the stake half is the frame's own policy (§FRAMEPOLICY: shipped default 100,
# bounded to [10, 10000] by the network) while the fixture staked a literal 10. Same rule as the bond: read the amount
# from THIS frame's policy, never hardcode it. The public card does not carry it (its declared_params hold the base
# network parameters only), so it is read from the resolved policy with the runner's admin token (`admin_enforcement`,
# held by the runner on the tester frames).
_PROPOSAL_STAKE_BASE = 10.0
_PROPOSAL_STAKE_CEILING = 1000.0   # the sentinel is funded 5000 and bonds 250: a proposal never takes more than this


def _proposal_stake_from_resolved(body: str) -> Tuple[Optional[float], str]:
    """(governance.min_stake_to_propose_avt from a /admin/enforcement/policy/resolved answer, "") or (None, why)."""
    try:
        doc = json.loads(body)
    except Exception:                                                 # noqa: BLE001
        return None, "the resolved policy is not JSON"
    governed = doc.get("governed") if isinstance(doc, dict) else None
    entry = governed.get("governance.min_stake_to_propose_avt") if isinstance(governed, dict) else None
    val = entry.get("value") if isinstance(entry, dict) else None
    if val is None:
        return None, "the resolved policy names no governance.min_stake_to_propose_avt"
    try:
        return float(val), ""
    except (TypeError, ValueError):
        return None, f"governance.min_stake_to_propose_avt is not a number ({val!r})"


def _proposal_stake_amount(required: Optional[float], base: float = _PROPOSAL_STAKE_BASE,
                           ceiling: float = _PROPOSAL_STAKE_CEILING) -> Tuple[float, str]:
    """(what the fixture stakes, "") or (the base, why the proposal step will still be refused)."""
    if required is None:
        return base, "the frame's minimum to propose was not read"
    if required <= base:
        return base, ""
    if required > ceiling:
        return base, (f"the frame requires {required:g} locked to propose, above the fixture's ceiling "
                      f"{ceiling:g}")
    return required, ""


async def _required_proposal_stake(container: str, admin_jwt: str) -> Tuple[Optional[float], str]:
    """The stake THIS frame requires to open a proposal, read from its own resolved policy; (None, why) when
    unreadable, and the caller then stakes the base and says so instead of guessing."""
    if not container or not admin_jwt:
        return None, "no target container or admin token to read the frame's policy with"
    try:
        rc, out = await asyncio.to_thread(
            exec_in_container, container, [
                "sh", "-c",
                f"curl -sS --max-time 15 -H 'Authorization: Bearer {admin_jwt}' "
                f"-w '\n{_HTTP_MARKER}%{{http_code}}--' "
                "http://localhost:8000/api/v1/admin/enforcement/policy/resolved",
            ], 20)
    except Exception as e:                                            # noqa: BLE001
        return None, f"the policy read raised {type(e).__name__}"
    body, code = _split_http_body_code(out or "")
    if rc != 0 or not code.startswith("2"):
        return None, f"GET /admin/enforcement/policy/resolved answered HTTP {code or 'nothing'} (rc {rc})"
    return _proposal_stake_from_resolved(body)


async def _http_in_target(container: str, method: str, path: str, *, body: Optional[bytes] = None,
                          content_type: str = "application/json", bearer: str = "",
                          timeout: int = 20, headers: Optional[Dict[str, str]] = None) -> Tuple[str, str]:
    """One HTTP call to the target registry from inside its own container (the fixture phase's standing transport).

    §MCPTEST30: the body travels base64-encoded and is decoded in the container, so a generated password is never a
    shell-quoting hazard. Returns (http_code, body_text); the code is '' when no status marker came back, which is
    the transport, not the product."""
    cmd = ""
    if body is not None:
        cmd += f"echo '{base64.b64encode(body).decode()}' | base64 -d | "
    cmd += f"curl -sS --max-time {int(timeout)} -X {method} "
    if bearer:
        cmd += f"-H 'Authorization: Bearer {bearer}' "
    for _hk, _hv in (headers or {}).items():   # plain tokens only (an Idempotency-Key); never a quote
        if "'" in _hk or "'" in str(_hv):
            raise ValueError("a header for the in-target call may not carry a quote")
        cmd += f"-H '{_hk}: {_hv}' "
    if body is not None:
        cmd += f"-H 'Content-Type: {content_type}' --data-binary @- "
    cmd += f"-w '\\n{_HTTP_MARKER}%{{http_code}}--' 'http://localhost:8000{path}'"
    try:
        rc, out = await asyncio.to_thread(exec_in_container, container, ["sh", "-c", cmd], timeout + 5)
    except Exception as e:                                             # noqa: BLE001
        return "", f"exec raised {type(e).__name__}"
    text, code = _split_http_body_code(out or "")
    return (code if rc == 0 else ""), text


def _sql_literal(v: Any) -> str:
    """A bound value as a SQL literal that cannot leave its place: a bool as itself, an int in parentheses (a negative
    one after a minus would otherwise open a `--` comment), None as NULL, a string as base64 the server decodes (the
    base64 alphabet holds no quote, backslash, semicolon or colon, so no value can close the literal or reach psql)."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return f"({int(v)})"
    if isinstance(v, str):
        return f"convert_from(decode('{base64.b64encode(v.encode()).decode()}', 'base64'), 'UTF8')"
    raise TypeError(f"no SQL literal for a {type(v).__name__}")


# SQLAlchemy text()'s own placeholder rule, so a statement means the same through either transport of _target_db
_TEXT_BIND = re.compile(r"(?<![:\w\\]):(\w+)(?!:)")


def _bind_sql(sql: str, params: Dict[str, Any]) -> str:
    """`:name` placeholders replaced by their values' literals, by text()'s own rule (a name preceded by a colon, a word
    character or a backslash is not one, nor one followed by a colon). A form the two transports would read differently
    is refused (a ValueError), never sent: a placeholder text() would bind inside a quoted literal, a name straight
    before a `::` cast, a backslash outside a literal. A placeholder without a value is a KeyError."""
    parts = re.split(r"('(?:[^']|'')*')", sql)
    for i in range(1, len(parts), 2):
        if _TEXT_BIND.search(parts[i]):
            raise ValueError("a placeholder inside a quoted literal")
    for i in range(0, len(parts), 2):
        if re.search(r"(?<![:\w\\]):\w+::", parts[i]):
            raise ValueError("a placeholder straight before a :: cast")
        if "\\" in parts[i]:   # text() reads \: as an escaped colon; psql reads a backslash as its own command
            raise ValueError("a backslash outside a quoted literal")
        parts[i] = _TEXT_BIND.sub(lambda m: _sql_literal(params[m.group(1)]), parts[i])
    return "".join(parts)


async def _db_in_target(db_container: str, sql: str, params: Dict[str, Any], *, write: bool = False,
                        ) -> Tuple[Any, Optional[str]]:
    """§MCPTEST30 (V0638): one statement on a target's own database through psql in its database container, for a
    target the runner does not run inside (a cloud operator: the runner works in the FRAME's registry). The shape of
    mcp_lifecycles._target_db: a read is (the first column of the first row, or None, None), a write (the rows changed,
    None), (None, why) when it could not be asked or its answer did not come back. A read always prints one line (a
    one-element JSON array: [null] is no row or a NULL), so an empty answer is a loss in transit (a docker exec now and
    then returns rc 0 with its output cut), never "no row". The value comes back as JSON gives it: int, bool, str or
    float (a timestamp or a uuid as its text, a numeric as a float). Values are bound by _bind_sql; nothing is logged."""
    try:
        bound = _bind_sql(sql.strip().rstrip(";"), params or {})
    except (KeyError, TypeError, ValueError) as e:
        return None, f"the statement could not be bound ({type(e).__name__}: {e})"
    stmt = bound if write else f"SELECT json_build_array((SELECT to_json(q.v) FROM ({bound}) AS q(v) LIMIT 1))"
    try:
        rc, out = await asyncio.to_thread(run_psql_in_db_container, db_container, stmt + ";")
    except Exception as e:                                             # noqa: BLE001
        return None, f"psql raised {type(e).__name__}"
    if rc != 0:
        return None, f"psql exited {rc} in {db_container}"
    lines = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    if write:
        m = re.match(r"^(?:UPDATE|DELETE|INSERT \d+) (\d+)$", lines[-1]) if lines else None
        return (int(m.group(1)), None) if m else (None, "psql named no rows changed (or its answer was lost)")
    if not lines:
        return None, "psql's answer was lost in transit (exit 0, nothing printed)"
    try:
        got = json.loads(lines[-1])
    except ValueError:
        return None, "psql's answer was not the one value asked for"
    if not (isinstance(got, list) and len(got) == 1):
        return None, "psql's answer was not the one value asked for"
    return got[0], None


async def _dev_login(container: str, email: str, password: str) -> Tuple[str, Dict[str, Any]]:
    """POST /api/v1/auth/login (form) against the target; (http_code, parsed body). Never logs anyone out."""
    form = urllib.parse.urlencode({"username": email, "password": password}).encode()
    code, text = await _http_in_target(container, "POST", "/api/v1/auth/login", body=form,
                                       content_type="application/x-www-form-urlencoded")
    try:
        parsed = json.loads(text) if text else {}
    except Exception:                                                  # noqa: BLE001
        parsed = {"_raw": (text or "")[:200]}
    return code, (parsed if isinstance(parsed, dict) else {"_raw": str(parsed)[:200]})


def _jwt_sub(token: str) -> str:
    try:
        p = token.split(".")[1]
        return str(json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4))).get("sub") or "")
    except Exception:                                                  # noqa: BLE001
        return ""


async def _mint_throwaway_developer(container: str, role: str,
                                    invite: Optional[Callable[[], Awaitable[Tuple[Optional[str], str]]]] = None,
                                    ) -> Dict[str, Any]:
    """§MCPTEST30 (2026-09-30) — register and log in a developer the SWEEP owns, for this run only.

    Two roles use it. `principal`: the non-admin credential the phase-5b auth matrix probes with, when the seeded
    `non_admin_dev@test.sandbox` is unusable; its password lives in SANDBOX_NON_ADMIN_PASSWORD, which is not on the
    tester frame, so every night since §TESTBED the mint answered rc=3 and the matrix probed that slot with an EMPTY
    bearer (a credential-less call is a different question from "is a valid non-admin refused?"). `self`: the subject
    of lifecycle_self_account_on_throwaway. Both carry the `mcp-throwaway-` tag on the reserved example.com domain, and
    both ask for their own deletion when the run is done with them.

    `invite` (§MCPTEST30 V0637): where the target registers only with an invite code (BETA_INVITE_REQUIRED, as the
    sandbox operators do), an async source of one single-use code, (code, None) or (None, why); the registration
    carries it.

    Returns {email, name, password, developer_id, access_token, refresh_token}, or {"why": ...}."""
    import secrets as _secrets
    ts, tag = int(time.time()), _secrets.token_hex(3)
    name = f"mcp-throwaway-{role}-{ts}-{tag}"
    email = f"{name}@throwaway-pl.example.com"
    try:
        from agentvault_registry.api_tests.contracts.mcp_lifecycles import _fresh_password
        password = _fresh_password()
    except Exception as e:                                             # noqa: BLE001
        return {"why": f"no password could be generated ({type(e).__name__}: {e})"}
    registration: Dict[str, Any] = {"name": name, "email": email, "password": password}
    if invite is not None:
        code, why = await invite()
        if not code:
            return {"why": f"the target registers only with an invite code, and none could be had ({why})"}
        registration["invite_code"] = code
    reg = json.dumps(registration).encode()
    code, text = await _http_in_target(container, "POST", "/api/v1/auth/register", body=reg)
    if not code.startswith("2"):
        return {"why": f"POST /auth/register answered HTTP {code or 'nothing'}: {(text or '')[:160]}"}
    code, tok = await _dev_login(container, email, password)
    if not code.startswith("2") or not tok.get("access_token"):
        detail = tok.get("detail") or tok.get("_raw") or ""
        return {"why": f"POST /auth/login answered HTTP {code or 'nothing'} for the fresh account: {str(detail)[:160]}"}
    return {"email": email, "name": name, "password": password, "developer_id": _jwt_sub(tok["access_token"]),
            "access_token": tok["access_token"], "refresh_token": tok.get("refresh_token") or ""}


async def _bootstrap_fixtures(target, dev_jwt: str) -> Optional[McpFixtureBag]:
    """Reset sandbox + grab fresh sentinel-with-secret + mint sentinel JWT.

    Calls /admin/api-test/reset-sandbox to get a fresh sentinel agent with
    client_secret returned (only revealed at create time). This is the same
    init step the HTTP api-tester uses at the start of every run — no
    parallel state.
    """
    # Reset sandbox returns the freshly-onboarded sentinel WITH client_secret
    rc, out = await asyncio.to_thread(
        exec_in_container, target.a_registry_container, [
            "sh", "-c",
            f"curl -sS -X POST -H 'Authorization: Bearer {dev_jwt}' "
            f"-H 'Content-Type: application/json' "
            f"-w '\\n{_HTTP_MARKER}%{{http_code}}--' "
            "http://localhost:8000/api/v1/admin/api-test/reset-sandbox",
        ], 30,
    )
    body, code = _split_http_body_code(out)
    if rc != 0 or not code.startswith("2"):
        logger.error(f"reset-sandbox failed: rc={rc} code={code} body={body[:200]}")
        return None
    try:
        creds = json.loads(body)
    except Exception:
        return None

    sentinel = creds.get("sentinel") or {}
    sentinel_did = sentinel.get("did", "")
    sentinel_client_id = sentinel.get("client_id", "")
    sentinel_client_secret = sentinel.get("client_secret", "")

    # Mint sentinel JWT via /api/v1/auth/agent/token
    # Note: backend accepts grant_type=password with username=client_id,
    # password=client_secret (despite the MCP wrapper calling this
    # "client_credentials flow"). See mcp/tools_agent.py:get_agent_token.
    rc, out = await asyncio.to_thread(
        exec_in_container, target.a_registry_container, [
            "sh", "-c",
            f"curl -sS -X POST -H 'Content-Type: application/x-www-form-urlencoded' "
            f"-d 'grant_type=password&username={sentinel_client_id}"
            f"&password={sentinel_client_secret}&scope=' "
            f"-w '\\n{_HTTP_MARKER}%{{http_code}}--' "
            "http://localhost:8000/api/v1/auth/agent/token",
        ], 10,
    )
    body, code = _split_http_body_code(out)
    sentinel_jwt = ""
    if rc == 0 and code.startswith("2"):
        try:
            sentinel_jwt = json.loads(body).get("access_token", "")
        except Exception:
            pass
    if not sentinel_jwt:
        logger.warning(f"sentinel JWT mint failed: rc={rc} code={code} body={body[:200]}")

    # Flow values
    rc, out = await asyncio.to_thread(
        exec_in_container, target.a_registry_container, [
            "sh", "-c",
            f"curl -sS -H 'Authorization: Bearer {dev_jwt}' "
            f"-w '\\n{_HTTP_MARKER}%{{http_code}}--' "
            "http://localhost:8000/api/v1/admin/api-test/flow-values",
        ], 10,
    )
    body, code = _split_http_body_code(out)
    flow_values: Dict[str, Any] = {}
    if rc == 0 and code.startswith("2"):
        try:
            payload = json.loads(body)
            # Reset endpoint sometimes returns {dynamic_values_cleared:true}
            if isinstance(payload, dict):
                flow_values = payload.get("flow_values", payload) or {}
        except Exception:
            pass

    # Expose sentinel raw creds for the getAgentToken contract
    flow_values["sentinel_client_id"] = sentinel_client_id
    flow_values["sentinel_client_secret"] = sentinel_client_secret

    # Decode the sentinel JWT to extract its internal agent_id (numeric).
    # Many wrappers expect `agent_id` as int rather than `agent_did`.
    sentinel_agent_id = ""
    if sentinel_jwt:
        try:
            payload = sentinel_jwt.split(".")[1]
            # Base64url-decode (add padding if needed)
            padded = payload + "=" * (4 - len(payload) % 4)
            decoded = json.loads(base64.urlsafe_b64decode(padded))
            sentinel_agent_id = str(decoded.get("agent_id") or "")
        except Exception:
            pass

    # §pass73 task B (2026-05-26): mint a non-admin developer JWT from the
    # seeded `developer@test.sandbox` fixture (is_admin=False per test_seed.py
    # TEST_DEVELOPER) so the F.1 auth-matrix can actually test admin-tier
    # rejection from a non-admin dev. Before this, the fallback was the
    # commander's admin JWT — a silent no-op (admin accepting admin).
    # §pass73 task B: use the dedicated non-admin fixture (non_admin_dev@test.sandbox)
    # seeded by test_seed.py:NON_ADMIN_DEV. The older developer@test.sandbox row
    # may be in an anonymized "!deleted!" state in some sandbox histories; the
    # new fixture is reset on every seed run to the password in SANDBOX_NON_ADMIN_PASSWORD (see below).
    rc, out = await asyncio.to_thread(
        exec_in_container, target.a_registry_container, [
            "sh", "-c",
            # §ADMINMATRIX-3, then §MCPSWEEP 2026-09-27: ENV ONLY. `test_seed.py` gives this account the password
            # in SANDBOX_NON_ADMIN_PASSWORD, and since §TESTBED (2026-09-19) a RANDOM one nobody is told when the
            # variable is unset; the literal this used to fall back to therefore answered 401 on the tester frame
            # (measured), a credential literal that had rotted exactly as predicted here. Unset means no fixture.
            "P=$(printenv SANDBOX_NON_ADMIN_PASSWORD); "
            "[ -n \"$P\" ] || exit 3; "
            "curl -sS -X POST "
            "-H 'Content-Type: application/x-www-form-urlencoded' "
            "--data-urlencode 'username=non_admin_dev@test.sandbox' "
            "--data-urlencode \"password=$P\" "
            f"-w '\\n{_HTTP_MARKER}%{{http_code}}--' "
            "http://localhost:8000/api/v1/auth/login",
        ], 15,
    )
    body, code = _split_http_body_code(out)
    developer_jwt_nonadmin = ""
    if rc == 0 and code.startswith("2"):
        try:
            developer_jwt_nonadmin = json.loads(body).get("access_token", "")
        except Exception:
            pass

    # §ADMINMATRIX-3 2026-09-07 — A SECOND NON-ADMIN PRINCIPAL, SO THE TWO
    # MATRICES STOP COMPETING. The rate limiter buckets by PRINCIPAL
    # (`principal_rate_key` → `request.state.rl_principal`, set once a signature
    # has been checked), NOT by role — an earlier comment in this file said role
    # and was wrong, which is why the obvious fix looked useless. Two matrices
    # using ONE credential therefore share ONE bucket: the 617-probe public
    # sweep drains it and the admin sweep meets what is left, which is how a
    # full pass came back 201 measured / 80 inconclusive with its TIME budget
    # untouched (`budget_skipped: 0`).
    #
    # `developer@test.sandbox` is the second seeded non-admin fixture
    # (`test_seed.py`, `is_admin: False`), and its password comes from
    # SANDBOX_DEVELOPER_PASSWORD rather than a literal — unlike the mint above,
    # which carries one and will break silently the day that seed rotates.
    # Measured on this tier before wiring: login 200.
    developer_jwt_nonadmin2 = ""
    rc2, out2 = await asyncio.to_thread(
        exec_in_container, target.a_registry_container, [
            "sh", "-c",
            "P=$(printenv SANDBOX_DEVELOPER_PASSWORD); [ -n \"$P\" ] || exit 3; "
            "curl -sS -X POST "
            "-H 'Content-Type: application/x-www-form-urlencoded' "
            "--data-urlencode 'username=developer@test.sandbox' "
            "--data-urlencode \"password=$P\" "
            f"-w '\\n{_HTTP_MARKER}%{{http_code}}--' "
            "http://localhost:8000/api/v1/auth/login",
        ], 15,
    )
    body2, code2 = _split_http_body_code(out2)
    if rc2 == 0 and code2.startswith("2"):
        try:
            developer_jwt_nonadmin2 = json.loads(body2).get("access_token", "")
        except Exception:
            pass
    if not developer_jwt_nonadmin2:
        logger.info(
            "second non-admin developer JWT unavailable (rc=%s code=%s) — the admin "
            "matrix will share the public matrix's bucket, which costs coverage, "
            "not correctness", rc2, code2)
    # §MCPTEST30 (2026-09-30) — when the seeded non-admin fixture is unusable, the sweep makes its OWN non-admin for the
    # run instead of probing that slot with an empty bearer (which every nightly since §TESTBED did).
    nonadmin_source = "seeded non_admin_dev@test.sandbox" if developer_jwt_nonadmin else ""
    nonadmin_principal: Dict[str, Any] = {}
    if not developer_jwt_nonadmin:
        _p = await _mint_throwaway_developer(target.a_registry_container, "principal")
        if _p.get("access_token"):
            developer_jwt_nonadmin = _p["access_token"]
            nonadmin_principal = _p
            nonadmin_source = f"throwaway {_p['email']} (registered for this run; the seeded fixture is unusable)"
            logger.info("non-admin fixture unusable (rc=%s code=%s); using this run's throwaway %s", rc, code,
                        _p["email"])
        else:
            logger.warning(
                f"non-admin developer JWT mint failed: rc={rc} code={code} body={body[:200]} "
                "(rc=3: SANDBOX_NON_ADMIN_PASSWORD is not set on the target, so non_admin_dev@test.sandbox holds a "
                f"password nobody is told), and no throwaway could be made either ({_p.get('why')}). F.1 admin-tier "
                "rejection probe will degrade to an empty bearer."
            )
    self_subject = await _mint_throwaway_developer(target.a_registry_container, "self")
    if not self_subject.get("access_token"):
        logger.warning("self-account subject unavailable (%s); those tools stay NOT MEASURED this run",
                       self_subject.get("why"))

    # §MCPSWEEP 2026-09-27 — the runner's own id, from its token's `sub`. The literal "1" was labelled
    # admin@test.sandbox; on the tester frame id 1 is the FRAME admin and the runner is id 2, so a probe written as a
    # self-add (the team-member lifecycle) added another account to the runner's team.
    runner_developer_id = "1"
    try:
        _payload = (dev_jwt or "").split(".")[1]
        _claims = json.loads(base64.urlsafe_b64decode(_payload + "=" * (-len(_payload) % 4)))
        if str(_claims.get("sub", "")).isdigit():
            runner_developer_id = str(_claims["sub"])
    except Exception:                                            # noqa: BLE001 — keep the old default, say so
        logger.warning("runner developer id not read from its token; bag.developer_id falls back to 1")

    # §MCPTEST30 (V0636): the AGORA listing the four exchange read tools name. API_TEST_EXCHANGE_LISTING names one where
    # it is set; unset (every sandbox frame since §TESTBED), the run asks the target's own market and takes its busiest
    # trading listing. The four reads read NOT MEASURED every night ("TUTCO" is a retired tier's) while sbx-alpha held
    # five trading listings, one with about 5,000 trades a day (measured 2026-10-24). None trading: the default stays and
    # the rows say so (_fixture_absent_reason).
    _live_listing = await _live_exchange_listing(target, dev_jwt)
    return McpFixtureBag(
        **({"exchange_listing": _live_listing} if _live_listing else {}),
        sentinel_did=sentinel_did,
        sentinel_jwt=sentinel_jwt,
        sentinel_agent_id=sentinel_agent_id,
        second_agent_did=flow_values.get("second_agent_did", sentinel_did),  # fallback
        second_agent_jwt=flow_values.get("second_agent_jwt", sentinel_jwt),
        developer_jwt=dev_jwt,
        developer_id=runner_developer_id,
        admin_jwt=dev_jwt,  # commander is admin
        developer_jwt_nonadmin=developer_jwt_nonadmin,
        developer_jwt_nonadmin2=developer_jwt_nonadmin2,
        nonadmin_source=nonadmin_source,
        nonadmin_principal=nonadmin_principal,
        self_subject=self_subject,
        dev_login=functools.partial(_dev_login, target.a_registry_container),
        flow_values=flow_values,
    )


async def _live_exchange_listing(target, jwt: str) -> str:
    """The symbol of the target's busiest trading AGORA listing, or "" (API_TEST_EXCHANGE_LISTING set, no listing
    trading, or the market unreadable). Read only."""
    if os.environ.get("API_TEST_EXCHANGE_LISTING"):
        return ""
    try:
        ok, body, _ = await _mcp_rpc_call(target, "theprotocol_getAgoraListings", {}, jwt=jwt, timeout=30)
        rows = _parse_rpc_result(body).get("listings") if ok else None
        trading = [r for r in (rows or []) if isinstance(r, dict) and r.get("status") == "trading" and r.get("symbol")]
        trading.sort(key=lambda r: -float(((r.get("stats") or {}).get("trades_24h") or 0)))
        return str(trading[0]["symbol"]) if trading else ""
    except Exception:                                                   # noqa: BLE001 — no listing is a named skip
        return ""


# ---------------------------------------------------------------------------
# Phase-3 fixture-setup phase
# ---------------------------------------------------------------------------

def _setup_failure_text_from_result(inner: Any) -> str:
    """Same resolution order, applied to an already-unwrapped tool result."""
    if not isinstance(inner, dict):
        return ""
    for _k in ("_text", "error", "detail", "message", "body", "upstream_error"):
        _v = inner.get(_k)
        if isinstance(_v, str) and _v:
            return _v
    return ""


def _setup_failure_text(rpc_body: Any) -> str:
    """The product's own sentence for a failed setup create, if it said one.

    Unwraps the JSON-RPC envelope, then defers to the single resolver above so
    there is ONE place that mirrors _check_contract's key order. Two copies of
    that order is two chances for the setup log and the sweep's evaluator to
    disagree about what a tool answered — which is exactly the §EVTYPES3 defect.
    """
    try:
        inner = _parse_rpc_result(rpc_body) if isinstance(rpc_body, dict) else {}
    except Exception:                                        # noqa: BLE001
        return ""
    return _setup_failure_text_from_result(inner)


# ── §EVTYPES5 2026-09-06 — a sweep must state the POSTURE it measured ────────
# WHY. agentvault2-60 measured that cloud-op-sbxalphaop-registry and
# cloud-op-sbxbetaop-registry carry NO AGENT_RBAC_MODE and NO
# AGENT_DELEGATION_MODE (unset = off, byte-inert) while the frame they hang off
# ENFORCES both. Every authorization result this sweep collects on those two
# operators is therefore a reading of an UNENFORCED surface — and nothing in the
# output said so. A run that does not name its posture invites the reader to
# compare it with the frame's, which is the one comparison it cannot support.
#
# CLAUDE.md's own words for this class: "a flag claim in prose is a hypothesis;
# docker inspect is the answer". So ask the node, print the answer, and carry it
# in flow_values where a later reader will find it beside the numbers.
#
# ⚠ THE VARIABLES ARE NAMED, ONE printenv EACH. Never a prefix grep over a
# container's environment — that is how a §FABRICVERIFY probe printed an
# operator's admin password into a transcript.
_POSTURE_VARS = ("AGENT_RBAC_MODE", "AGENT_DELEGATION_MODE", "LIABILITY_MODE")


async def _read_posture(container: str) -> Dict[str, str]:
    """{var: value} for the posture flags, '' when unset. Never raises."""
    out: Dict[str, str] = {}
    for var in _POSTURE_VARS:
        try:
            rc, val = await asyncio.to_thread(
                exec_in_container, container, ["sh", "-c", "printenv %s || true" % var], 15)
            out[var] = (val or "").strip() if rc == 0 else ""
        except Exception:                                    # noqa: BLE001
            out[var] = ""
    return out


async def _read_target_switches(container: str) -> Dict[str, Any]:
    """§MCPTEST30 (V0550): hold this run to the switches its target reports (api_tests/contracts/mcp_switches.py).

    Read from the target's public registry-config, from inside its own container. Never raises: a config that cannot
    be read switches nothing, and the run's flow_values say it was not read, so a refusal read against the wrong
    expectation is attributable."""
    code, text = await _http_in_target(container, "GET", "/api/v1/public/registry-config")
    cfg: Any = None
    if code == "200":
        try:
            cfg = json.loads(text)
        except Exception:                                    # noqa: BLE001
            cfg = None
    switches = _switches.use_target(cfg)
    return {"target_switches": switches, "target_switches_read": isinstance(cfg, dict),
            "target_switches_off": sorted(t for t in _switches.SWITCHED_TOOLS if _switches.switched_off(t)),
            **({} if isinstance(cfg, dict) else {"target_switches_reason": f"registry-config answered HTTP {code or 'nothing'}"})}


def _posture_complaints(posture: Dict[str, str]) -> List[str]:
    """PART 14's pairing rule, checked instead of assumed.

    `AGENT_RBAC_MODE` and `AGENT_DELEGATION_MODE` must move together: with
    enforce+off, `resolve_capability` is never consulted, so any agent whose
    authority rides an `att_` capability token keeps only its (correctly empty)
    role set and is DENIED. Doctrine states the rule; nothing measured it.
    """
    rbac = (posture.get("AGENT_RBAC_MODE") or "").lower()
    deleg = (posture.get("AGENT_DELEGATION_MODE") or "").lower()
    out: List[str] = []
    if bool(rbac) != bool(deleg) or (rbac and deleg and rbac != deleg):
        out.append(
            "AGENT_RBAC_MODE=%r and AGENT_DELEGATION_MODE=%r disagree — PART 14 "
            "says they must always move together; enforce+off denies every agent "
            "whose authority rides a capability token" % (rbac or "unset", deleg or "unset"))
    if not rbac and not deleg:
        out.append(
            "IRONKEY is OFF on this node (both flags unset) — every authorization "
            "result in this run is a reading of an UNENFORCED surface and must not "
            "be compared with an enforcing frame's")
    return out


# ── §EVTYPES8 2026-09-06 — THE ASSERTIONS THE COVERAGE FAN SWALLOWED ──────
# A row is decided by lifecycle > setup > contract (see the block at the sweep).
# That is deliberate for the CALL — a create must not run twice — but it also
# threw away the contract's ASSERTION: the setup recorder wrote `healthy=ok`,
# i.e. "the RPC did not refuse", and never looked at the response shape. 19
# hand-written contracts sit on setup-path tools, and 10 of those are ALSO
# fixture-skipped on the operators (no phase-3 there), so their `expect_keys`
# ran on NO node in the fleet. An assertion that executes nowhere measures
# nothing — the same class as a gate whose scope excludes the files it claims.
#
# The fix asserts against the response setup ALREADY has, so nothing is called
# twice. Two deliberate narrowings, both load-bearing:
#
#   • ONLY the success-shape half (`expect_keys`). A contract's
#     `expect_status="error_4xx"` + phrase describes a refusal to the JUNK
#     arguments the contract declares; setup calls the same tool with VALID
#     arguments and is answered 2xx. Applying the refusal half here would fail
#     a correct create for not being broken. Those contracts get their run via
#     `override_coverage_fan` instead (a refusal writes nothing, so calling it
#     a second time is free).
#   • ONLY hand-written contracts (`tool in MCP_CONTRACTS`). `get_contract()`
#     back-fills empty `expect_keys` from the harvest file; those keys were
#     harvested from a call with the CONTRACT's arguments, never from setup's,
#     so treating them as a floor here would invent failures nobody measured.
def _setup_shape_failure(tool_name: str, inner: Any) -> Optional[str]:
    """Return a fail reason if a successful setup create misses its declared shape.

    None = nothing to assert, or the assertion passed. Never raises: a bad
    contract must not take down phase-3 fixture creation.
    """
    if tool_name not in MCP_CONTRACTS:
        return None
    try:
        contract = get_contract(tool_name)
    except Exception:
        return None
    if contract.skip_reason:
        return None
    # Refusal contracts describe a different call — see the block above.
    if contract.expect_status in ("error_4xx", "error_5xx", "error"):
        return None
    keys = list(contract.expect_keys or [])
    if not keys:
        return None
    if not isinstance(inner, dict):
        return (
            "setup-phase create returned 2xx but the contract's shape assertion "
            "could not run: result is %s, not an object (expected keys %r)"
            % (type(inner).__name__, keys)
        )
    missing = [k for k in keys if k not in inner]
    if missing:
        return (
            "setup-phase create returned 2xx but the contract's shape assertion "
            "failed: missing keys %r (declared expect_keys=%r, got %r)"
            % (missing, keys, sorted(inner.keys())[:12])
        )
    return None


async def _create_scratch_listing(call, setup_outcomes: Dict[str, "ContractOutcome"], org: str,
                                  funding_agent_did: str, jwt: str, draws: int = 3) -> str:
    """§AGORAFIX (2026-09-28) — the phase-3 scratch listing on a fresh RANDOM symbol, redrawn when the venue says 409.

    A random symbol can collide: every run leaves its P3 listing on the venue (112 on sbx-alpha that day), and V0486's
    tester-self (57a8390dffa540ef) drew P3C494, listed by a run on 2026-09-05, so the venue's correct 409 "symbol taken"
    was scored as a hard failure. The org is fresh every run, so a 409 here names the SYMBOL: draw again, up to `draws`
    times. The recorder keeps the LAST attempt per tool (setup_outcomes is keyed by tool), so a clean redraw leaves a
    clean row, while a create that fails for any other reason, or collides every time, still reads red. Returns the
    last symbol drawn (the caller approves it, as before)."""
    sym = ""
    for _ in range(max(1, draws)):
        sym = ("P3" + uuid.uuid4().hex[:4]).upper()[:6]
        r = await call(
            "theprotocol_createAgoraListing",
            {"organization_id": org, "symbol": sym,
             "total_shares": 1000, "ipo_float": 100, "ipo_price": "1",
             "funding_agent_did": funding_agent_did},
            jwt,
        )
        row = setup_outcomes.get("theprotocol_createAgoraListing")
        if r is not None or row is None or row.status_code != 409:
            break
    return sym


def _contract_v2_candidate(row: Any) -> Optional[str]:
    """The id /contracts/v2/{cid} loads, from one row of getMyContracts (the legacy view over the contract spine): the
    spine id `ref` (`ctr_…`) when the row carries one, else a `contract_id`; never the legacy integer `id`, which is the
    old RUC id (or -1) and which the v2 route cannot find."""
    if not isinstance(row, dict):
        return None
    for k in ("ref", "contract_id"):
        v = row.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    v = row.get("id")
    return v.strip() if isinstance(v, str) and v.strip().startswith("ctr_") else None


async def _phase3_setup_entities(target, bag: McpFixtureBag,
                                  setup_outcomes: Optional[Dict[str, "ContractOutcome"]] = None) -> Dict[str, Any]:
    """Create entities the phase-3 contracts will exercise.

    Each `_create_X` call runs via MCP `tools/call` so it exercises the
    same code path the sweep uses. Failures are swallowed individually —
    a contract that needs the failed fixture will be skipped via the
    unresolved-fixture detector. We capture every successful ID into
    flow_values so downstream `${name}` references resolve.

    Phase 4: every successful create is ALSO recorded into `setup_outcomes`
    so the sweep can mark the corresponding tool as PASSED — turns a free
    side-effect of setup into ~10 hard passes for the create-side tools.

    Returns a dict of {"entity_kind": id_or_status} for the session-log
    summary block.
    """
    summary: Dict[str, Any] = {}
    setup_outcomes = setup_outcomes if setup_outcomes is not None else {}

    async def _call(tool: str, args: Dict[str, Any], jwt: str) -> Optional[Dict[str, Any]]:
        t0 = time.time()
        ok, body, code = await _mcp_rpc_call(target, tool, args, jwt=jwt, timeout=15)
        elapsed_ms = int((time.time() - t0) * 1000)
        inner = _parse_rpc_result(body) if ok else {}
        _sw = _switches.switched_off(tool)
        if _sw is not None:
            # §MCPTEST30 (V0550): the target switched this tool off, so the setup step is its refusal, held to the
            # switch; what the step would have created is absent and its dependents skip on the missing fixture
            _healthy, _fail = _switches.judge(tool, _sw, int(code) if code.isdigit() else 0,
                                              f"{_setup_failure_text(body) or ''} {json.dumps(inner, default=str)[:400]}")
            setup_outcomes[tool] = ContractOutcome(
                tool_name=tool, contract_tier="setup", healthy=_healthy,
                status_code=int(code) if code.isdigit() else 0, elapsed_ms=elapsed_ms, skip_reason=None,
                fail_reason=_fail, has_explicit_contract=True,
                args_used={k: ("<jwt>" if "jwt" in k else v) for k, v in args.items()},
                result_excerpt=result_excerpt(inner))
            logger.info("phase-3 %s: switched off here (%s), %s", tool, _sw.label(),
                        "refused as documented" if _healthy else _fail)
            return inner if ok else None
        # §EVTYPES8: the create succeeded — now hold it to its own contract's
        # declared response shape (see `_setup_shape_failure` above). A miss
        # marks the ROW unhealthy but does NOT withhold `inner` from the
        # fixture bag below: the entity really was created, and starving every
        # downstream ${fixture} over a reporting assertion would turn one
        # honest finding into a cascade of misleading skips.
        _shape_fail = _setup_shape_failure(tool, inner) if ok else None
        # Record outcome for this tool — turns setup creates into hard passes
        setup_outcomes[tool] = ContractOutcome(
            tool_name=tool,
            contract_tier="setup",
            healthy=ok and not _shape_fail,
            status_code=int(code) if code.isdigit() else 0,
            elapsed_ms=elapsed_ms,
            skip_reason=None,
            # §EVTYPES4: keep the SENTENCE, not just the status. `inner` is {} on
            # failure by the line below, so read the wrapped text here — without
            # it a setup create records "failed: HTTP 400" and the reason (a 409
            # duplicate, a missing permission) is discarded at the one moment it
            # is known. Three fixtures failed silently for days behind that.
            # §EVTYPES8 first: a shape miss is only ever set when the call
            # SUCCEEDED, so it can never mask the transport reason below.
            fail_reason=_shape_fail or None if ok else (
                "setup-phase create failed: HTTP %s%s" % (
                    code,
                    (" — " + str(_setup_failure_text(body))[:200]) if _setup_failure_text(body) else "")),
            has_explicit_contract=True,
            args_used={k: ("<jwt>" if "jwt" in k else v) for k, v in args.items()},
            result_excerpt=result_excerpt(inner),
        )
        if not ok:
            return None
        return inner

    # ── 0. Fund sentinel agent (needed for stake/payment/proposal) ─────────
    # reset-sandbox onboards the sentinel but doesn't fund it; admin treasury
    # fund-agent does. Direct HTTP since there's no MCP wrapper for this.
    rc, _ = await asyncio.to_thread(
        exec_in_container, target.a_registry_container, [
            "sh", "-c",
            f"curl -sS -X POST -H 'Authorization: Bearer {bag.developer_jwt}' "
            f"-H 'Content-Type: application/json' "
            f"-d '{{\"target_agent_did\":\"{bag.sentinel_did}\",\"amount\":\"5000\","
            f"\"reason\":\"phase-3 mcp-tester bootstrap fund\"}}' "
            "http://localhost:8000/api/v1/teg/treasury/fund-agent > /dev/null 2>&1",
        ], 15,
    )
    summary["sentinel_funded"] = "5000 AVT" if rc == 0 else "FAILED"

    # ── 0.6 Sample agent card fixture (pass73.3.19) ────────────────────────
    # Expose a real card_id + human_readable_id so getAgentCardById /
    # getAgentCardByHRI / getAgentCardByHumanReadableId can assert a genuine
    # 200 instead of an autogen error_4xx rubber-stamp. Read-only harvest via
    # raw _mcp_rpc_call (no setup_outcomes pollution); picks the first existing
    # card and skips cleanly (contracts auto-skip on unresolved ${fixture}) if
    # the registry has none.
    try:
        ok_lc, body_lc, _ = await _mcp_rpc_call(
            target, "theprotocol_listAgentCards", {},
            jwt=bag.developer_jwt, timeout=15)
        cards = _parse_rpc_result(body_lc) if ok_lc else {}
        items = cards.get("items", []) if isinstance(cards, dict) else []
        if items and isinstance(items[0], dict) and items[0].get("id"):
            card_id = items[0]["id"]
            bag.flow_values["sample_card_id"] = card_id
            summary["sample_card_id"] = card_id
            ok_c, body_c, _ = await _mcp_rpc_call(
                target, "theprotocol_getAgentCardById", {"card_id": card_id},
                jwt=bag.developer_jwt, timeout=15)
            full = _parse_rpc_result(body_c) if ok_c else {}
            cd = full.get("card_data") if isinstance(full, dict) else None
            hri = (cd.get("humanReadableId") or cd.get("human_readable_id")) if isinstance(cd, dict) else None
            if hri:
                bag.flow_values["sample_card_hri"] = hri
                summary["sample_card_hri"] = hri
        else:
            summary["sample_card_id"] = "NONE (no cards)"
    except Exception as e:
        logger.warning(f"phase-3 sample-card fixture raised (non-fatal): {e!r}")

    # ── 0.6b Sample contracts-v2 fixture (§EVTYPES 2026-09-05) ─────────────
    # getContractV2's contract hardcoded `ctr_l00000231` -- "a real, long-lived
    # contract row on sandbox-A (251 exist)". That row belonged to the RETIRED
    # sandbox tier; on this frame it 404s, and the suite reported a correct 404
    # as a failure for as long as the fresh tier has existed. A fixture with a
    # hardcoded id from another environment rots by construction: harvest one at
    # runtime instead, and let the contract auto-skip when the frame has none.
    try:
        ok_mc, body_mc, _ = await _mcp_rpc_call(
            target, "theprotocol_getMyContracts", {"agent_jwt": bag.sentinel_jwt},
            jwt=bag.developer_jwt, timeout=15)
        mine = _parse_rpc_result(body_mc) if ok_mc else {}
        rows = (mine.get("items") or mine.get("contracts") or []) if isinstance(mine, dict) else []
        if isinstance(mine, list):
            rows = mine
        cids = []
        for row in rows:
            # §MCPTEST30 (2026-10-01): getMyContracts is the LEGACY view over the contract spine, where `id` is the legacy
            # integer (-1 for a spine-native row) and `ref` is the spine id (`ctr_…`) that /contracts/v2/{cid} loads.
            # Taking `id` handed the v2 route integers it can never find, so no candidate ever verified and getContractV2
            # read "fixture missing" every night.
            rid = _contract_v2_candidate(row)
            if rid:
                cids.append(rid)
        # ⚠ Harvesting an id is not enough: /contracts/v2/{cid} enforces a PARTY
        # check (403 "Not a party to this contract" unless the caller is the
        # client/provider, or the contract is still `offered`). getMyContracts
        # lists what is "available / linked", which is a wider set than that. So
        # PROVE the candidate answers 200 for the sentinel before publishing it —
        # an unverified fixture just swaps a 404 for a 403 and still reads as a
        # product failure. If none verifies, publish nothing: the contract then
        # auto-skips on the unresolved ${fixture}, which is the honest outcome.
        # §SUITES1018 (2026-10-18): the legacy view listed nothing the sentinel is a party to on sbx-alpha, so the
        # fixture read "missing" every night. Two more sources the v2 route itself serves: the sentinel's own v2
        # contracts (GET /contracts/v2/mine, both roles) and the frame's open offers (GET /contracts/v2, browsable by
        # any agent by design). Each candidate is still verified below before it is published.
        for _src in ("/api/v1/contracts/v2/mine?limit=8", "/api/v1/contracts/v2?limit=8"):
            if len(cids) >= 8 or not bag.sentinel_jwt:
                break
            try:
                _c, _t = await _http_in_target(target.a_registry_container, "GET", _src, bearer=bag.sentinel_jwt)
                _j = json.loads(_t) if _c == "200" and _t else {}
                for _row in ((_j.get("items") or _j.get("contracts") or []) if isinstance(_j, dict) else []):
                    _cid = str((_row or {}).get("id") or (_row or {}).get("cid") or "")
                    if _cid.startswith("ctr_") and _cid not in cids:
                        cids.append(_cid)
            except Exception as _e:  # noqa: BLE001
                logger.warning(f"phase-3 contract fixture: {_src} unread ({_e!r})")
        verified = None
        for cand in cids[:8]:
            ok_v, body_v, _ = await _mcp_rpc_call(
                target, "theprotocol_getContractV2",
                {"contract_id": str(cand), "agent_jwt": bag.sentinel_jwt},
                jwt=bag.developer_jwt, timeout=15)
            got = _parse_rpc_result(body_v) if ok_v else None
            if isinstance(got, dict) and got.get("client_did"):
                verified = cand
                # the owner-scoping sweep asks a non-party agent for it; an open offer is browsable by design
                bag.flow_values["contract_v2_status"] = str(got.get("status") or "")
                break
        if verified is not None:
            bag.flow_values["contract_v2_id"] = str(verified)
            summary["contract_v2_id"] = str(verified)
        elif cids:
            summary["contract_v2_id"] = (
                "NONE VERIFIED (%d candidate(s); the sentinel is a party to none "
                "and none is an open offer)" % len(cids))
        else:
            summary["contract_v2_id"] = "NONE (no contracts on this frame)"
    except Exception as e:
        logger.warning(f"phase-3 contract fixture raised (non-fatal): {e!r}")

    # ── 0.6c Agent-log fixture (§SUITES1018 2026-10-18) ────────────────────
    # The pagination probe asks getMyAgentLogs for two pages of the sentinel's
    # logs and read NOT MEASURED every night ("0 row(s), no second page"): the
    # sentinel had written none. Three INFO lines, written once by its own
    # developer (POST /agents/{did}/logs, "developers can create logs for their
    # agents"), make the second page exist; they are never removed and never
    # written again once the agent holds three.
    try:
        if bag.sentinel_did and bag.developer_jwt:
            ok_l, body_l, _ = await _mcp_rpc_call(
                target, "theprotocol_getMyAgentLogs", {"agent_did": bag.sentinel_did, "limit": 3},
                jwt=bag.developer_jwt, timeout=15)
            have = _parse_rpc_result(body_l) if ok_l else {}
            held = len(have.get("logs") or []) if isinstance(have, dict) else 0
            for n in range(held, 3) if ok_l else ():
                await _http_in_target(
                    target.a_registry_container, "POST", f"/api/v1/agents/{bag.sentinel_did}/logs",
                    body=json.dumps({"level": "INFO", "source": "mcp-tester",
                                     "message": f"pagination fixture line {n + 1} of 3 (kept by the MCP tester)"}).encode(),
                    bearer=bag.developer_jwt)
            summary["agent_log_fixture"] = f"{max(held, 3) if ok_l else 'unread'} line(s)"
    except Exception as e:
        logger.warning(f"phase-3 agent-log fixture raised (non-fatal): {e!r}")

    # ── 0.5 Sandbox idempotency: clean up accumulated webhooks ─────────────
    # Each test run creates webhooks; reset-sandbox doesn't wipe them. The
    # backend enforces "max 10 webhooks per developer". If we've hit that
    # cap, subsequent createWebhook calls fail with HTTP 400. Defensive:
    # delete EVERY existing webhook before adding the fixture one.
    try:
        rc_list, out_list = await asyncio.to_thread(
            exec_in_container, target.a_registry_container, [
                "sh", "-c",
                f"curl -sS -H 'Authorization: Bearer {bag.developer_jwt}' "
                "http://localhost:8000/api/v1/webhooks",
            ], 10,
        )
        if rc_list == 0:
            try:
                parsed = json.loads(out_list)
                webhooks = parsed if isinstance(parsed, list) else parsed.get("webhooks", [])
            except Exception:
                webhooks = []
            for wh in webhooks:
                if not isinstance(wh, dict):
                    continue
                wid = wh.get("id")
                if not wid:
                    continue
                await asyncio.to_thread(
                    exec_in_container, target.a_registry_container, [
                        "sh", "-c",
                        f"curl -sS -X DELETE -H 'Authorization: Bearer {bag.developer_jwt}' "
                        f"http://localhost:8000/api/v1/webhooks/{wid} > /dev/null 2>&1",
                    ], 10,
                )
    except Exception as e:
        logger.warning(f"phase-3 pre-create webhook cleanup raised (non-fatal): {e!r}")

    # ── 1. Webhook ─────────────────────────────────────────────────────────
    r = await _call(
        "theprotocol_createWebhook",
        {"url": "https://webhook.example.test/phase3-mcp-tester",
         "events": ["agent.created", "agent.updated"],
         "description": "phase-3 mcp-tester fixture"},
        bag.developer_jwt,
    )
    if r and r.get("id"):
        bag.flow_values["webhook_id"] = r["id"]
        bag.flow_values["webhook_secret"] = r.get("secret", "")
        summary["webhook_id"] = r["id"]
    else:
        summary["webhook_id"] = "FAILED"

    # ── 2. Organization ────────────────────────────────────────────────────
    r = await _call(
        "theprotocol_createOrganization",
        {"name": "phase3-org-test", "description": "phase-3 mcp-tester org"},
        bag.developer_jwt,
    )
    if r and r.get("id"):
        bag.flow_values["organization_id"] = str(r["id"])
        bag.flow_values["organization_slug"] = r.get("slug") or "phase3-org-test"
        summary["organization_id"] = r["id"]

        # ── 2b. Organization team ─────────────────────────────────────────
        r2 = await _call(
            "theprotocol_createOrganizationTeam",
            {"org_id": str(r["id"]), "name": "phase3-team",
             "description": "phase-3 mcp-tester team"},
            bag.developer_jwt,
        )
        if r2 and r2.get("id"):
            bag.flow_values["team_id"] = str(r2["id"])
            summary["team_id"] = r2["id"]
    else:
        summary["organization_id"] = "FAILED"

    # ── 3. Bundle (snapshot of sentinel) ───────────────────────────────────
    r = await _call(
        "theprotocol_createBundle",
        {"bundle_data": {
            "agent_dids": [bag.sentinel_did],
            "kind": "snapshot",
            "name": "phase3-mcp-tester-bundle",
            "visibility": "private",
            "sign": True,
        }},
        bag.developer_jwt,
    )
    if r and r.get("id"):
        bag.flow_values["bundle_id"] = r["id"]
        summary["bundle_id"] = r["id"]
    else:
        summary["bundle_id"] = "FAILED"

    # ── 4. Pipeline + version ──────────────────────────────────────────────
    r = await _call(
        "theprotocol_createPipeline",
        {"agent_did": bag.sentinel_did,
         "pipeline_name": "phase3-pipeline",
         "pipeline_config": {"stages": [{"name": "noop", "type": "manual"}]},
         "trigger_type": "webhook",
         "webhook_url": "https://example.test/phase3-trigger",
         "is_active": True},
        bag.developer_jwt,
    )
    pipeline_id = (r or {}).get("pipeline_id") or (r or {}).get("id")
    if pipeline_id:
        bag.flow_values["pipeline_id"] = str(pipeline_id)
        bag.flow_values["pipeline_webhook_secret"] = (r or {}).get("webhook_secret", "")
        summary["pipeline_id"] = pipeline_id

        # Need a version before deployments can be triggered
        r2 = await _call(
            "theprotocol_createVersion",
            {"agent_did": bag.sentinel_did,
             "version": "1.0.0",
             "release_notes": "phase-4 fixture version",
             "is_stable": True},
            bag.developer_jwt,
        )
        version_id = (r2 or {}).get("version_id") or (r2 or {}).get("id")
        if version_id:
            bag.flow_values["version_id"] = str(version_id)
            summary["version_id"] = version_id
    else:
        summary["pipeline_id"] = "FAILED"

    # ── 5. API key ─────────────────────────────────────────────────────────
    r = await _call("theprotocol_createApiKey",
                    {"key_name": "phase3-mcp-tester-key"},
                    bag.developer_jwt)
    if r and r.get("api_key_info", {}).get("id"):
        bag.flow_values["api_key_id"] = str(r["api_key_info"]["id"])
        summary["api_key_id"] = r["api_key_info"]["id"]

    # ── 6. Funding request ─────────────────────────────────────────────────
    fund_args = {"agent_jwt": bag.sentinel_jwt, "amount": "10",
                 "reason": "phase-3 mcp-tester funding request — pending"}
    r = await _call("theprotocol_submitFundingRequest", fund_args, bag.developer_jwt)
    if r and r.get("id"):
        bag.flow_values["funding_request_id"] = str(r["id"])
        summary["funding_request_id"] = r["id"]

    # ── 7. A2A payment token ───────────────────────────────────────────────
    r = await _call(
        "theprotocol_authorizePayment",
        {"agent_jwt": bag.sentinel_jwt,
         "target_agent_did": bag.sentinel_did,  # self-pay for fixture; refundable
         "amount": "1",
         "ttl_seconds": 600},
        bag.developer_jwt,
    )
    if r and r.get("token_id"):
        bag.flow_values["payment_token_id"] = r["token_id"]
        bag.flow_values["payment_token"] = r.get("token", "")
        summary["payment_token_id"] = r["token_id"]

    # ── 8. Support ticket ──────────────────────────────────────────────────
    r = await _call(
        "theprotocol_submitSupportTicket",
        {"subject": "phase3-mcp-tester ticket",
         "message": "Auto-created by mcp-tester phase-3 setup. Ignore.",
         "category": "general",
         "priority": "low"},
        bag.developer_jwt,
    )
    if r and r.get("id"):
        bag.flow_values["support_ticket_id"] = str(r["id"])
        summary["support_ticket_id"] = r["id"]

    # ── 9. Stake (lock=0 for safe immediate-unstake later) ─────────────────
    # §MCPSWEEP 2026-09-27: at least this frame's governance.min_stake_to_propose_avt, so step 10's proposal can
    # open (see _required_proposal_stake); the base 10 when the frame asks for no more or cannot be read.
    _prop_min, _prop_why = await _required_proposal_stake(
        getattr(target, "a_registry_container", "") or "", bag.admin_jwt)
    _stake_amt, _stake_why = _proposal_stake_amount(_prop_min)
    summary["proposal_stake_policy"] = f"{_prop_min:g}" if _prop_min is not None else f"UNREAD: {_prop_why}"
    if _stake_why:
        logger.warning("phase-3 stake stays %g: %s%s", _stake_amt, _stake_why,
                       f" ({_prop_why})" if _prop_why else "")
    r = await _call(
        "theprotocol_lockUnits",
        {"agent_jwt": bag.sentinel_jwt, "amount": f"{_stake_amt:g}", "lock_period_days": 0},
        bag.developer_jwt,
    )
    if r and r.get("stake_id"):
        bag.flow_values["stake_id"] = r["stake_id"]
        summary["stake_id"] = r["stake_id"]

    # ── 9b. Reputation bond (sentinel is funded 5000 AVT above → can lock one) ─
    # Gives getMyReputationBondStatus a real bond so it returns 200 — the route
    # (enforcement_agent.py:234) 404s when the agent holds no bond. Idempotent
    # (returns existing if already locked); the bond is immutable/accumulating but
    # the next bootstrap's sandbox reset wipes it, so no teardown is needed.
    # §CLOUDOPMCP2 2026-09-05 — the amount is READ from this registry's own policy,
    # never hardcoded (see _required_bond_amount). The literal 10 that used to sit
    # here was refused by the deposit route once the sandbox went to enforce/250.
    _bond_amt = await _required_bond_amount(getattr(target, "a_registry_container", "") or "")
    if _bond_amt is None:
        logger.warning("phase-3 reputation bond SKIPPED — could not read this registry's "
                       "bond policy; refusing to guess an amount")
    else:
        r = await _call(
            "theprotocol_depositReputationBond",
            {"agent_jwt": bag.sentinel_jwt, "amount": float(_bond_amt)},
            bag.developer_jwt,
        )
        logger.info("phase-3 reputation bond: policy=%s bond_id=%r", _bond_amt,
                    (r or {}).get("bond_id") if isinstance(r, dict) else None)
        if isinstance(r, dict) and r.get("bond_id"):
            bag.flow_values["reputation_bond_id"] = r["bond_id"]
            summary["reputation_bond_id"] = r["bond_id"]

    # ── 9b. Give the sentinel the authority a proposal needs ──────────────
    # MEASURED 2026-09-06: createProposal answered
    #   403 "Agent lacks required permission: gov.propose"
    # on every run, so `proposal_id` never reached flow_values and
    # getProposalDetail / getProposalVotes / getMyVoteOnProposal skipped with
    # "entity setup didn't expose this ID" — a message about the FIXTURE that
    # said nothing about the AUTHORITY that was actually missing.
    # `gov.propose` lives in the `governor` role (agent_authz.ROLE_PERMISSIONS);
    # the sentinel is born with AGENT_RBAC_DEFAULT_ROLES only. This is the same
    # category as the funding, staking and reputation-bond steps above: make the
    # fixture capable of the thing its contracts test, on the sandbox, through
    # the product's own rail.
    # ⚠ PUT /agents/{did}/authz SETS the role list (it does not append), so the
    # existing roles are read first and the union is written back — writing
    # ["governor"] alone would REVOKE trader/client/staker and break every
    # money contract downstream.
    async def _ensure_governor(did: str) -> Any:
        """The governor role for one of the run's agents, through the one-role rail (V0551: POST /agents/{did}/authz/roles
        leaves every other grant and its expiry as it is; the whole-set PUT stamped one expiry on all of them). The
        rail's answer: {"role", "changed", ...}, or FAILED and why."""
        try:
            _payload = json.dumps({"role": "governor"})
            rc_p, out_p = await asyncio.to_thread(
                exec_in_container, target.a_registry_container, [
                    "sh", "-c",
                    f"curl -sS -X POST -H 'Authorization: Bearer {bag.developer_jwt}' "
                    f"-H 'Content-Type: application/json' -d '{_payload}' "
                    f"-w '\n{_HTTP_MARKER}%{{http_code}}--' "
                    f"http://localhost:8000/api/v1/agents/{did}/authz/roles",
                ], 20,
            )
            _bp, _cp = _split_http_body_code(out_p)
            if rc_p != 0 or not _cp.startswith("2"):
                return f"FAILED http={_cp or 'none'}"
            _ans = json.loads(_bp) if _bp.strip().startswith("{") else {}
            logger.info("phase-3 governor for %s: changed=%s (http=%s)", did[:24], _ans.get("changed"), _cp)
            return {"role": "governor", "changed": _ans.get("changed")}
        except Exception as e:                               # noqa: BLE001
            logger.warning("phase-3 governor grant raised (non-fatal): %r", e)
            return "FAILED"

    summary["sentinel_roles"] = await _ensure_governor(bag.sentinel_did)

    # ── 10. Governance proposal (sentinel may have voting power from stake) ──
    r = await _call(
        "theprotocol_createProposal",
        {"agent_jwt": bag.sentinel_jwt,
         "title": "phase3-mcp-tester proposal",
         "description": "Auto-created by mcp-tester phase-3 setup. Will be tallied at deadline.",
         "duration_days": 1,
         "proposal_type": "standard"},
        bag.developer_jwt,
    )
    if r and r.get("proposal_id"):
        bag.flow_values["proposal_id"] = str(r["proposal_id"])
        summary["proposal_id"] = r["proposal_id"]
    else:
        # An `if` with no `else` is how this fixture failed in silence: three
        # contracts skipped daily and the reason was never written down.
        # §MCPSWEEP 2026-09-27: `_call` answers None on a failed create, so the reason lives in the setup outcome
        # it recorded; this line said only "no proposal_id in the reply" while a 403 named the frame's policy.
        _prop_outcome = setup_outcomes.get("theprotocol_createProposal")
        summary["proposal_id"] = "FAILED — %s" % (
            str(_setup_failure_text_from_result(r))[:180]
            or str(getattr(_prop_outcome, "fail_reason", "") or "")[:180]
            or "no proposal_id in the reply")
        logger.warning("phase-3 proposal NOT created: %s", summary["proposal_id"])

    # ── 11. PHASE 4 — sentinel's own agent card (already exists from onboard) ─
    # Use getMyAgents to discover the sentinel's card_id (its own card)
    r = await _call(
        "theprotocol_getMyAgents", {}, bag.developer_jwt,
    )
    if isinstance(r, dict):
        for k in ("agents", "items", "results"):
            agents = r.get(k)
            if isinstance(agents, list):
                for a in agents:
                    if isinstance(a, dict) and a.get("did") == bag.sentinel_did:
                        cid = a.get("id") or a.get("card_id") or a.get("agent_card_id")
                        if cid:
                            bag.flow_values["agent_card_id"] = str(cid)
                            bag.flow_values["human_readable_id"] = a.get("human_readable_id") or a.get("hri") or ""
                            summary["agent_card_id"] = cid
                        break
                break

    # ── 12. PHASE 4 — Submit a TEG dispute (agent-side) ──────────────────────
    # TEG rejects self-disputes ("Cannot file a dispute against yourself"), so the
    # defendant MUST differ from the complainant. Prefer the eigentrust lifecycle's
    # second agent; mint a throwaway defendant if it isn't distinct yet (ordering-safe).
    _defendant = getattr(bag, "second_agent_did", "") or ""
    if not _defendant or _defendant == bag.sentinel_did:
        _d = await _call(
            "theprotocol_createAgent",
            {"name": f"phase4-defendant-{int(time.time())}",
             "description": "phase-4 mcp-tester dispute defendant fixture"},
            bag.developer_jwt,
        )
        if isinstance(_d, dict):
            _defendant = _d.get("did") or _d.get("agent_did") or ""
    r = None
    if _defendant and _defendant != bag.sentinel_did:
        r = await _call(
            "theprotocol_logTegDispute",
            {"agent_jwt": bag.sentinel_jwt,
             "defendant_agent_did": _defendant,
             "reason_code": "test_dispute",
             "brief_description": "phase-4 mcp-tester dispute fixture"},
            bag.developer_jwt,
        )
    if r and (r.get("dispute_log_id") or r.get("dispute_id") or r.get("id")):
        did = r.get("dispute_log_id") or r.get("dispute_id") or r.get("id")
        bag.flow_values["dispute_id"] = str(did)
        summary["dispute_id"] = did

    # ── 13. PHASE 4 — Fetch list of circuits to pick a circuit_id ────────────
    r = await _call("theprotocol_getCircuits", {}, bag.developer_jwt)
    circuits = []
    if isinstance(r, dict):
        for k in ("circuits", "items", "results"):
            v = r.get(k)
            if isinstance(v, list):
                circuits = v
                break
    if circuits:
        c0 = circuits[0]
        if isinstance(c0, dict):
            cid = c0.get("circuit_id") or c0.get("id") or c0.get("name")
            if cid:
                bag.flow_values["circuit_id"] = str(cid)
                summary["circuit_id"] = cid

    # ── 14. Agent template id — templates are seeded; pick one for getAgentTemplate ─
    r = await _call("theprotocol_listAgentTemplates", {}, bag.developer_jwt)
    tmpls = (r.get("templates") or r.get("items")) if isinstance(r, dict) else None
    if isinstance(tmpls, list) and tmpls and isinstance(tmpls[0], dict):
        tid = (tmpls[0].get("template_id") or tmpls[0].get("id")
               or tmpls[0].get("slug") or tmpls[0].get("name"))
        if tid:
            bag.flow_values["agent_template_id"] = str(tid)
            summary["agent_template_id"] = tid

    # ── 14b. §MCPTEST30 (V0545): a staking distribution id, a read-only pick (getLockPayoutRecords had a
    # standing "Phase-3: needs a known distribution_id fixture" skip; the frame runs a distribution a day) ─
    _dist = await staking_distribution_pick(_call, bag.developer_jwt)
    if _dist:
        bag.flow_values["distribution_id"] = _dist
        summary["distribution_id"] = _dist

    # ══ §MCPTEST-MCP6 2026-08-08 — THROWAWAY FIXTURES ═══════════════════════
    # These exist so ~20 tools stop being SKIPPED for want of an id. Skips count
    # against pass_pct exactly like failures, so "no fixture" and "untested" are
    # the same number — the tool is simply never exercised.
    #
    # The rule followed here: a tester may create and mutate its OWN disposable
    # objects, never live ones. Every id below points at something this function
    # just made. Nothing touches TUTCO/TUTXB (the real seeded listings) or any
    # pre-existing order, contract or policy.
    #
    # Each create was executed by hand against sandbox-A before being written,
    # so the arguments are known-good rather than inferred from a schema.

    # ── 14b. Second agent (a genuine counterparty) ─────────────────────────
    # `second_agent_jwt` on the bag FALLS BACK to the sentinel's own token when
    # nothing creates a second agent — and nothing did. That silently makes the
    # sentinel its own counterparty, which the guild correctly refuses with
    # "Cannot bid on your own task". Create a real second agent instead.
    #
    # It goes into flow_values (not the bag attribute): `bag.get()` reads
    # flow_values FIRST, so `${second_agent_jwt}` picks this up even though the
    # bag was constructed before phase-3 ran.
    r = await _call(
        "theprotocol_createAgent",
        {"name": "phase3-second-agent",
         "description": "phase-3 mcp-tester counterparty agent"},
        bag.developer_jwt,
    )
    if isinstance(r, dict) and r.get("client_id"):
        _cid = r.get("client_id"); _csec = r.get("client_secret") or ""
        _sdid = r.get("agent_did") or r.get("did") or ""
        tok = await _call(
            "theprotocol_getAgentToken",
            {"client_id": _cid, "client_secret": _csec},
            bag.developer_jwt,
        )
        _sjwt = (tok or {}).get("access_token") if isinstance(tok, dict) else None
        if _sjwt:
            bag.flow_values["second_agent_jwt"] = _sjwt
            bag.flow_values["second_agent_did"] = _sdid
            summary["second_agent_did"] = _sdid
            # §MCPTEST30 (V0550): in member mode the second agent votes too: one member, one vote, so the same
            # developer's second vote is the control (409 developer_already_voted). gov.vote lives in the governor
            # role under IRONKEY enforce, which a newborn agent lacks (agentvault2-33, 2026-10-02): without it the
            # control would read IRONKEY's 403 and say nothing of membership
            summary["second_agent_roles"] = await _ensure_governor(_sdid)
            # §CLOUDOPMCP2 2026-09-05 — this agent is the PAYEE in
            # lifecycle_a2a_payment_settle (mcp_lifecycles.py:876) and the bidder the
            # guild accepts, and under §REPBOND enforce BOTH are bond-gated sites.
            # Bonding only the sentinel was not enough: MEASURED, the refused DID in
            # authorizePayment's 403 ("holds no reputation bond. Providing services
            # here (a2a_payee) requires a bond of 250 SBXA") is THIS agent, and it
            # changes every run because phase-3 creates it fresh. It is created
            # UNFUNDED, so it must be funded before it can bond from its own balance
            # — the same two steps the sentinel gets above.
            _fund_rc, _ = await asyncio.to_thread(
                exec_in_container, target.a_registry_container, [
                    "sh", "-c",
                    f"curl -sS -X POST -H 'Authorization: Bearer {bag.developer_jwt}' "
                    f"-H 'Content-Type: application/json' "
                    f"-d '{{\"target_agent_did\":\"{_sdid}\",\"amount\":\"5000\","
                    f"\"reason\":\"phase-3 mcp-tester second-agent bond fund\"}}' "
                    "http://localhost:8000/api/v1/teg/treasury/fund-agent > /dev/null 2>&1",
                ], 15,
            )
            _sec_bond = await _required_bond_amount(
                getattr(target, "a_registry_container", "") or "")
            if _sec_bond is None:
                logger.warning("phase-3 second-agent bond SKIPPED — bond policy "
                               "unreadable; refusing to guess an amount")
            else:
                _br = await _call(
                    "theprotocol_depositReputationBond",
                    {"agent_jwt": _sjwt, "amount": float(_sec_bond)},
                    bag.developer_jwt,
                )
                logger.info("phase-3 second-agent bond: fund_rc=%s policy=%s bond_id=%r",
                            _fund_rc, _sec_bond,
                            (_br or {}).get("bond_id") if isinstance(_br, dict) else None)
        else:
            summary["second_agent_did"] = "FAILED(token)"
    else:
        summary["second_agent_did"] = "FAILED"

    # ── 15. Guild work order (throwaway) ───────────────────────────────────
    # bounty 1 AVT from the sentinel, which phase-3 funded above. Unlocks
    # guildGetOrder / guildMyWork / guildBid, which have no id to point at
    # otherwise (`guild_work_orders` is an EMPTY table on a fresh sandbox).
    r = await _call(
        "theprotocol_guildPostOrder",
        {"title": "phase3-mcp-tester order", "bounty": "1",
         "agent_jwt": bag.sentinel_jwt},
        bag.developer_jwt,
    )
    if isinstance(r, dict) and r.get("order_id"):
        bag.flow_values["guild_order_id"] = str(r["order_id"])
        summary["guild_order_id"] = r["order_id"]
    else:
        summary["guild_order_id"] = "FAILED"

    # A SECOND order purely so guildCancelOrder has its own victim. Cancelling
    # the first one would strand guildGetOrder / guildBid depending on the order
    # the sweep happens to reach them in.
    r = await _call(
        "theprotocol_guildPostOrder",
        {"title": "phase3-mcp-tester cancel-target", "bounty": "1",
         "agent_jwt": bag.sentinel_jwt},
        bag.developer_jwt,
    )
    if isinstance(r, dict) and r.get("order_id"):
        bag.flow_values["guild_order_id_cancel"] = str(r["order_id"])
        summary["guild_order_id_cancel"] = r["order_id"]

    # ── 16. TEG policies (two, deliberately) ───────────────────────────────
    # TWO because deleteTegPolicy destroys its target and the sweep's tool order
    # is not something a contract can depend on. One policy is the read/update
    # subject, a second is the delete subject, so a delete can never strand a
    # get/update that happens to run after it.
    # ⚠ FRESH CODES PER RUN. Fixed codes (`P3RDPOL` / `P3DELPOL`) were created on
    # 2026-09-03 and every run since answered 409 "Policy with this code already
    # exists", so `teg_policy_id`/`teg_policy_id_del` never resolved and
    # getTegPolicy + updateTegPolicy + deleteTegPolicy skipped for three days.
    # Two things hid it: deleteTegPolicy SOFT-deletes (is_active=false) so the
    # code is never freed, and GET /teg/policies defaults to active_only=true so
    # the leftovers are invisible until you ask for active_only=false. This is
    # the identical defect the exchange-listing fixture forty lines below already
    # documents and already solved with a fresh symbol per run.
    # §MCPTEST30 (V0641): the delete subject is made through createTegPoliciesBatch (one policy), so each create tool's
    # row is this setup's answer (lifecycle_teg_policy and lifecycle_create_teg_policies_batch file their refusals as
    # `refusal: ` rows since). The batch route answers 200 whatever it created, so its row asks for the policy back.
    for _slot, _code, _tool in (
            ("teg_policy_id", "P3R" + uuid.uuid4().hex[:4].upper(), "theprotocol_createTegPolicy"),
            ("teg_policy_id_del", "P3D" + uuid.uuid4().hex[:4].upper(), "theprotocol_createTegPoliciesBatch")):
        _one = teg_policy_batch_policy(_code, f"phase3 fixture {_slot}", "phase-3 mcp-tester throwaway policy")
        r = await _call(_tool, {"policies": [_one]} if _tool.endswith("Batch") else _one, bag.developer_jwt)
        if _tool.endswith("Batch"):
            _why = teg_policy_batch_failure(r, 1) if r is not None else None
            if _why and setup_outcomes.get(_tool) is not None:
                setup_outcomes[_tool].healthy = False
                setup_outcomes[_tool].fail_reason = "setup-phase create failed: " + _why
            _pid = teg_policy_batch_id(r)
        else:
            _pid = str((r.get("policy_id") or r.get("id") or "") if isinstance(r, dict) else "")
        if _pid:
            bag.flow_values[_slot] = _pid
            summary[_slot] = bag.flow_values[_slot]
        else:
            summary[_slot] = "FAILED"

    # ── 17. Scratch exchange listing + a live order on it ──────────────────
    # A NEW listing starts unapproved and every trade against it answers 409;
    # admin approval is the missing step (measured). With it, place / cancel /
    # ipo-buy / dividend all work — against a listing that exists only for the
    # tester. `symbol` is capped at 8 chars by the venue.
    _org = bag.flow_values.get("organization_id") or ""
    if _org:
        # MEASURED constraints: symbol is capped at 6 CHARACTERS (an 8-char one
        # answers 422 "String should have at most 6 characters"), and a venue
        # allows ONE listing per ORGANIZATION ("organization already listed or
        # symbol taken"). phase-3 creates a fresh org every run, so a fresh
        # 6-char symbol against that org is what actually succeeds.
        # The symbol is unique per run. A fixed symbol 409s on the second run
        # ("already exists"), and the setup recorder would score that create as
        # a FAILURE even though the fixture is fine — a self-inflicted red mark
        # that appears only from run 2 onward. A fresh symbol keeps the create a
        # genuine test of the create path every time.
        # §AGORAFIX (2026-09-28): a random symbol can still collide; _create_scratch_listing redraws on a 409.
        _sym = await _create_scratch_listing(_call, setup_outcomes, _org, bag.sentinel_did, bag.developer_jwt)
        # A repeat run finds the symbol already there; that is success for our
        # purposes — the fixture exists either way.
        if True:
            ok_ap, body_ap, _c = await _mcp_rpc_call_admin(
                target, "theprotocol_adminAgoraApproveListing",
                {"listing_ref": _sym}, jwt=bag.developer_jwt, timeout=15,
            )
            _inner = _parse_rpc_result(body_ap) if ok_ap else {}
            if isinstance(_inner, dict) and _inner.get("symbol"):
                bag.flow_values["scratch_listing"] = _sym
                summary["scratch_listing"] = _sym
                # §MCPTEST30: this IS adminAgoraApproveListing's success path; lifecycle_admin_scratch_listing records it
                bag.flow_values["scratch_listing_approve"] = {
                    "status": int(_c) if str(_c).isdigit() else 200,
                    "answer": {k: _inner.get(k) for k in ("symbol", "status", "approved")}}
                # A resting order so cancelAgoraOrder has a real target.
                r2 = await _call(
                    "theprotocol_placeAgoraOrder",
                    {"listing": _sym, "side": "buy", "qty": 1,
                     "order_type": "limit", "price": "1",
                     "agent_jwt": bag.sentinel_jwt},
                    bag.developer_jwt,
                )
                if isinstance(r2, dict) and r2.get("order_id"):
                    bag.flow_values["scratch_order_id"] = str(r2["order_id"])
                    summary["scratch_order_id"] = r2["order_id"]
            else:
                summary["scratch_listing"] = "FAILED"

    # ── 18. GUILD LIFECYCLE STAGING (§MCPTEST-MCP8) ────────────────────────
    # guildAward / guildSubmitWork / guildVerify each need an order in a
    # DIFFERENT state, and the sweep gives no ordering guarantee between three
    # separate contracts. So instead of one order walked through three stages
    # (which only works if the tools happen to fire in sequence), stage THREE
    # independent orders — each parked exactly one transition short of the tool
    # that will act on it. Every contract then performs one real state change
    # and is completely order-independent.
    #
    # Shapes below were all measured live on sandbox-A first:
    #   guildGetOrder -> {"order", "bids", "events"}   ← bids is TOP-LEVEL.
    #     (I first read order.bids, got null, and briefly blamed the product.)
    #   guildAward      -> {ok, order_id, status, worker, payee, firm}
    #   guildSubmitWork -> {ok, order_id, status}
    #   guildVerify     -> {ok, order_id, status, payout, fee, stars, ...}
    _worker_jwt = bag.flow_values.get("second_agent_jwt")
    _stages = [("guild_award", 0), ("guild_submit", 1), ("guild_verify", 2)]
    for _name, _advance in _stages:
        try:
            _o = await _call("theprotocol_guildPostOrder",
                             {"title": f"phase3 {_name} fixture", "bounty": "1",
                              "agent_jwt": bag.sentinel_jwt}, bag.developer_jwt)
            _oid = (_o or {}).get("order_id") if isinstance(_o, dict) else None
            if not _oid or not _worker_jwt:
                summary[_name] = "FAILED(post)"; continue
            # the counterparty bids — the sentinel cannot bid on its own task
            await _call("theprotocol_guildBid",
                        {"order_id": _oid, "price": "1", "agent_jwt": _worker_jwt},
                        bag.developer_jwt)
            _g = await _call("theprotocol_guildGetOrder", {"order_id": _oid},
                             bag.developer_jwt)
            _bids = (_g or {}).get("bids") or [] if isinstance(_g, dict) else []
            _bid = _bids[0].get("id") if _bids else None
            if _bid is None:
                summary[_name] = "FAILED(nobid)"; continue
            if _advance >= 1:   # park it AWARDED for guildSubmitWork
                await _call("theprotocol_guildAward",
                            {"order_id": _oid, "bid_id": _bid,
                             "agent_jwt": bag.sentinel_jwt}, bag.developer_jwt)
            if _advance >= 2:   # park it SUBMITTED for guildVerify
                await _call("theprotocol_guildSubmitWork",
                            {"order_id": _oid,
                             "deliverable_text": "phase-3 staged deliverable",
                             "agent_jwt": _worker_jwt}, bag.developer_jwt)
            bag.flow_values[f"{_name}_order_id"] = _oid
            if _name == "guild_award":
                bag.flow_values["guild_award_bid_id"] = _bid
            summary[_name] = _oid[:18]
        except Exception as _e:                        # noqa: BLE001
            summary[_name] = f"FAILED({str(_e)[:24]})"

    # ── 19. (REMOVED §MCPTEST-MCP8) ────────────────────────────────────────
    # A probe here fetched a live contract ref for getContractV2. It answered
    # 401 AND recorded a hard FAILURE against theprotocol_getMyContracts, which
    # had been passing — the fixture cost a working tool to chase a skipped one.
    # Net negative, so it is gone. getContractV2 stays honestly skipped.


    logger.info(f"phase-3/4 setup: created {sum(1 for v in summary.values() if v != 'FAILED')} of {len(summary)} entities")
    logger.info(f"  fixtures: {summary}")
    return summary


async def _phase7_enforcement_refusal(target, bag, dev_jwt: str) -> List[ContractOutcome]:
    """§ENFPROP — assert the ENFORCE REFUSAL, the one branch nothing else reaches.

    MEASURED with the product's own counter
    (`registry_enforcement_propagation_gate_total`): a full sweep hits only 2 of the
    6 gated sites and EVERY decision is `allow`, because no sweep agent is ever in an
    enforced status. The behaviour `enforce` exists to produce was untested.

    NO MUTATION, BY DESIGN — and the first design was worse. Suspending a sweep-owned
    payee worked for the control leg and then 401'd the refusal leg: coordinated
    suspension touches the owning developer's credentials, so suspending the payee
    invalidated the PAYER's token (both belong to the sandbox developer). Measured as
    `a2a_payee allow 4 -> 6` with the refusal leg still unreached.
    This frame already holds ~147 suspended and ~160 revoked agents, so an ENFORCED
    payee can simply be READ. No suspend, no reinstate, no cleanup, no token
    invalidation, nothing to leave dirty if the run dies halfway — and it is safe to
    run on every sweep.

    Both directions asserted, because a gate that only ever refuses is as broken as
    one that only ever allows:
      control  ACTIVE payee    -> reachable AND the refusal phrase ABSENT
      refusal  ENFORCED payee  -> 403 carrying the phrase
    """
    _PHRASE = "is refused while the enforcement stands"
    out: List[ContractOutcome] = []

    def _mk(name, healthy, status, skip, fail, excerpt=None):
        return ContractOutcome(
            tool_name=name, contract_tier="enfprop", healthy=healthy,
            status_code=status, elapsed_ms=0, skip_reason=skip, fail_reason=fail,
            has_explicit_contract=True, args_used={}, result_excerpt=excerpt or {},
        )

    try:
        from agentvault_registry.services.enforcement_propagation import propagation_mode
        _mode = propagation_mode()
    except Exception as e:  # noqa: BLE001
        out.append(_mk("enfprop_refusal", True, 0,
                       f"could not read ENFORCEMENT_PROPAGATION_MODE ({e!r}) — not measurable", None))
        return out
    if _mode != "enforce":
        out.append(_mk("enfprop_refusal", True, 0,
                       f"ENFORCEMENT_PROPAGATION_MODE={_mode!r} — shadow/off count and log but "
                       f"refuse nothing, so there is no refusal to assert", None))
        return out

    active = getattr(bag, "second_agent_did", "") or ""
    payer_jwt = getattr(bag, "sentinel_jwt", "") or ""
    if not (active and payer_jwt):
        out.append(_mk("enfprop_refusal", True, 0,
                       "no second agent / sentinel JWT in the fixture bag — nothing to assert", None))
        return out

    # An already-enforced payee, READ not made.
    enforced = ""
    try:
        from sqlalchemy import text as _text
        from agentvault_registry.database import AsyncSessionLocal as _S
        async with _S() as _db:
            # ⚠ THE BOND GATE RUNS FIRST (a2a_payment.py:440 `_rb.gate`, then :441
            # `_ep.gate`), so an enforced agent with no LOCKED bond is refused by the
            # BOND gate and the enforcement gate is never reached. MEASURED: a
            # randomly-picked enforced payee gave 403 with no enforcement phrase, and
            # this phase correctly reported "failed before the gate for an unrelated
            # reason" rather than claiming a refusal it had not seen.
            # So the payee must be enforced AND hold a locked bond. 52 such agents
            # exist on this frame (39 revoked + 13 suspended), so this is a READ.
            enforced = (await _db.execute(_text(
                "select a.did from agents a "
                "join reputation_bonds b on b.agent_did = a.did "
                "where a.status in ('suspended','revoked') and b.status = 'locked' "
                "and a.did is not null limit 1"))).scalar() or ""
    except Exception as e:  # noqa: BLE001
        out.append(_mk("enfprop_refusal", True, 0,
                       f"could not look up an enforced agent ({e!r}) — not measurable", None))
        return out
    if not enforced:
        out.append(_mk("enfprop_refusal", True, 0,
                       "no suspended/revoked agent WITH A LOCKED BOND exists on this frame — the "
                       "bond gate runs before the enforcement gate, so an unbonded payee never "
                       "reaches it; deliberately NOT mutating to manufacture one",
                       None))
        return out

    async def _authorize(payee):
        # ⚠ THE CREDENTIAL SHAPE IS NOT GUESSABLE FROM THE WRAPPER SIGNATURE.
        # `authorize_payment(auth, target_agent_did, amount, ...)` declares no
        # `agent_jwt`, which reads as "the bearer must be the agent" — WRONG: the MCP
        # bridge STRIPS `agent_jwt` from the arguments and builds the agent context
        # from it, so the bearer stays the DEVELOPER JWT (CLAUDE.md PART 11). This
        # file's own Phase-3 fixture call is the proof of the shape; I got it wrong
        # in both directions before reading it.
        ok, body, code = await _mcp_rpc_call(
            target, "theprotocol_authorizePayment",
            {"agent_jwt": payer_jwt, "target_agent_did": payee,
             "amount": "1", "ttl_seconds": 300},
            jwt=(getattr(bag, "developer_jwt", "") or dev_jwt), timeout=20)
        blob = json.dumps(body, default=str).lower()
        unreachable = ("401" in str(code)) or "requires agent" in blob or "not authenticated" in blob
        return code, blob, unreachable

    # CONTROL — must prove REACHABILITY, not just phrase-absence: "the phrase is
    # absent" is trivially true of a 401, so a control that checks only the phrase
    # passes exactly when the test is broken.
    code_c, blob_c, unreachable = await _authorize(active)
    if unreachable:
        out.append(_mk("enfprop_refusal", True, int(code_c) if str(code_c).isdigit() else 0,
                       f"payer could not reach the a2a_payee gate (status={code_c}) — nothing is "
                       f"asserted", None))
        return out
    control_clean = _PHRASE not in blob_c
    out.append(_mk("enfprop_control_active", control_clean, 200, None,
                   None if control_clean else
                   "CONTROL FAILED: the refusal phrase is present for an ACTIVE payee — the "
                   "refusal leg would pass for the wrong reason"))

    code_r, blob_r, _ = await _authorize(enforced)
    if _PHRASE in blob_r:
        out.append(_mk("enfprop_refusal", True, 403, None, None,
                       {"proof": "enforce refused an enforced payee at site=a2a_payee",
                        "payee_status": "suspended|revoked"}))
    elif str(code_r).isdigit() and 200 <= int(code_r) < 300 and "error" not in blob_r:
        out.append(_mk("enfprop_refusal", False, int(code_r), None,
                       "ENFORCE DID NOT REFUSE: the payee is suspended/revoked and "
                       "ENFORCEMENT_PROPAGATION_MODE=enforce, yet authorizePayment succeeded — "
                       "the gate at a2a_payment.py:441 did not bite"))
    else:
        out.append(_mk("enfprop_refusal", True, 0,
                       f"authorize failed before the gate for an unrelated reason "
                       f"(status={code_r}) — the refusal is NOT asserted", None))
    return out


async def _retire_scratch_org(container: str, call, call_admin, org_id: str, listing_ref: str, owner_jwt: str,
                              sweep_dest: str, already_delisted: bool = False) -> str:
    """§MCPTEST30 (2026-10-01): the run's own AGORA fixture at the end of its life: delist its listing (cancels the
    resting order and refunds its escrow), sweep the organization's treasury to the owner's agent if a deposit blocks
    the delete, then delete the organization. Measured: the teardown named the org by `organization_id` while
    deleteOrganization takes `org_id`, so no fixture organization was ever deleted (140 `phase3-org-test` on sbx-alpha,
    58 and 25 `cloudop-fixture-*` on the sandbox operators, each with a live listing, by 2026-10-01), and a listing that
    is not delisted refuses the delete anyway (E1b). Best-effort: returns a one-line account, never raises."""
    notes: List[str] = []
    try:
        if listing_ref and not already_delisted:
            _ok, _b, code = await call_admin("theprotocol_adminAgoraDelistListing", {"listing_ref": listing_ref})
            notes.append(f"delist HTTP {code}")
        if not org_id:
            return "; ".join(notes) or "nothing to retire"
        ok, body, code = await call("theprotocol_deleteOrganization", {"org_id": org_id})
        if not ok and "funded_treasury" in json.dumps(body, default=str) and sweep_dest:
            scode, _t = await _http_in_target(
                container, "POST", f"/api/v1/organizations/{org_id}/treasury/sweep",
                body=json.dumps({"dest_agent_did": sweep_dest}).encode(), bearer=owner_jwt,
                headers={"Idempotency-Key": f"mcp-tester-retire-{org_id}"})
            notes.append(f"treasury sweep HTTP {scode}")
            ok, body, code = await call("theprotocol_deleteOrganization", {"org_id": org_id})
        notes.append(f"organization delete HTTP {code}" + ("" if ok else " (kept)"))
    except Exception as e:  # noqa: BLE001 — cleanup is never a finding
        notes.append(f"raised {type(e).__name__}")
    return "; ".join(notes)


# §MCPTEST30 (V0528, 2026-10-01): the operator phase's own agents. Their names are the phase's own pattern (see
# _bootstrap_cloudop_agent; before the hex suffix existed a sentinel was `cloudop-sentinel-<epoch>`); a run lasts under
# an hour, so an older one belongs to no live run. An AGORA fixture's listing treasury agent (`cloudop-fixture-<epoch>
# Treasury ($CO....)`, keyless, made by the listing for the run's developer) belongs to its organization: its run
# retires it once _retire_scratch_org deleted the organization (V0639), and an earlier run's is taken here only while
# its organization is not active. Measured 2026-10-24: 87 active on sbxalphaop and 55 on sbxbetaop, every one of
# their organizations deleted, none holding a balance.
_CLOUDOP_FIXTURE_NAME = re.compile(r"^cloudop-(?:sentinel|second)-(\d{9,11})(?:-[0-9a-f]{6})?$")
_CLOUDOP_TREASURY_NAME = re.compile(r"^(cloudop-fixture-(\d{9,11})) Treasury \(\$CO[0-9A-F]{4}\)$")
_CLOUDOP_FIXTURE_AGE_S = 3 * 3600
_CLOUDOP_FIXTURE_CAP = 30   # earlier runs' agents retired per run: a backlog drains over runs instead of stretching one


def old_cloudop_fixtures(listing: Any, now: float, keep: Iterable[str] = (),
                         active_orgs: Optional[Set[str]] = None) -> List[str]:
    """DIDs of ACTIVE agents in a /developers/me/agents listing that an earlier operator phase left: the phase's own
    name pattern, a creation stamp older than the sweep age, never one named in `keep`; oldest first, capped. A
    fixture's treasury agent counts only when `active_orgs` (the names of the developer's active organizations) was
    read and does not hold its organization: an unread list leaves every treasury agent alone."""
    kept = set(keep)
    found: List[Tuple[int, str]] = []
    for a in listing if isinstance(listing, list) else []:
        if not isinstance(a, dict) or a.get("status") != "active" or a.get("did") in kept:
            continue
        name = str(a.get("name") or "")
        m = _CLOUDOP_FIXTURE_NAME.match(name)
        t = None if m else _CLOUDOP_TREASURY_NAME.match(name)
        if t and (active_orgs is None or t.group(1) in active_orgs):
            continue
        stamp = int(m.group(1)) if m else (int(t.group(2)) if t else None)
        if stamp is not None and a.get("did") and now - stamp > _CLOUDOP_FIXTURE_AGE_S:
            found.append((stamp, str(a["did"])))
    return [did for _t, did in sorted(found)[:_CLOUDOP_FIXTURE_CAP]]


async def _active_org_names(call) -> Optional[Set[str]]:
    """§MCPTEST30 (V0639): the names of the caller's active organizations, or None when the list could not be read (an
    unread list is never an empty one)."""
    try:
        ok, body, _code = await call("theprotocol_getMyOrganizations", {})
    except Exception:  # noqa: BLE001 — cleanup is never a finding
        return None
    inner = _parse_rpc_result(body) if isinstance(body, dict) else {}
    orgs = inner.get("organizations") if isinstance(inner, dict) else None
    if not ok or not isinstance(orgs, list):
        return None
    return {str(o.get("name")) for o in orgs if isinstance(o, dict) and o.get("is_active", True)}


_CLOUDOP_NO_PROPOSAL = ("this operator holds no governance proposal (getGovernanceProposals read 0, every status); "
                        "creating one locks a balance this sweep does not spend")


async def cloudop_pick_proposal(call: Callable, target: Any, jwt: str) -> Tuple[Optional[str], Optional[str]]:
    """§MCPTEST30 (V0545): (a proposal id the operator already holds, None), or (None, why it holds none), or
    (None, None) when the read carried no list (the fixture then stays merely missing: nothing was learned).

    A read-only pick like the agent template's: creating a proposal stakes a balance the cloud-op sweep does not
    spend, so getProposalDetail, getProposalVotes and getMyVoteOnProposal (which answers has_voted false for an agent
    that never voted) skipped as "fixture missing" on every operator run, including runs on an operator holding
    proposals. Any status serves a read."""
    ok, body, _code = await call(target, "theprotocol_getGovernanceProposals", {"status": "all", "limit": 5},
                                 jwt=jwt, timeout=15)
    r = _parse_rpc_result(body) if ok else {}
    props = r.get("proposals") if isinstance(r, dict) else None
    if not isinstance(props, list):
        return None, None
    pid = next((pp.get("id") for pp in props if isinstance(pp, dict) and pp.get("id")), None)
    return (str(pid), None) if pid else (None, _CLOUDOP_NO_PROPOSAL)


def cloudop_by_construction_reason(phrase: str, status_code: Any) -> str:
    """§MCPTEST30 (V0640): the row of a mainframe-only tool an operator refused by construction, in its own words: NOT
    MEASURED, by design (the operator sweep's gate classifier, the `_phrase` branch)."""
    return (f"NOT MEASURED on a cloud operator, by design: a mainframe-only tool, which the operator refuses by "
            f"construction ('{phrase}', HTTP {status_code}); its success path exists only on a frame")


_CLOUDOP_NO_CIRCUIT = "this operator's circuit catalog lists no active circuit (getCircuits read none with status active)"


async def cloudop_pick_circuit(call: Callable, target: Any, jwt: str) -> Tuple[Optional[str], Optional[str]]:
    """§MCPTEST30 (V0640): (the first ACTIVE circuit the operator's catalog lists, None), or (None, why it lists none),
    or (None, None) when the read carried no list. A read-only pick like the template's: the frame's bootstrap reads a
    circuit in phase 4, the operator's never did, so lifecycle_attestation_schedule returned before its first step and
    createAttestationSchedule and disableMyAttestationSchedule passed on a made-up id alone (both sandbox operators,
    2026-10-24 23:1xZ; ZKP_PHASE_5_ENABLED defaults on and both serve the catalog). A retired circuit is refused 400
    ("schedule its successor instead"), so only an active one serves."""
    ok, body, _code = await call(target, "theprotocol_getCircuits", {}, jwt=jwt, timeout=15)
    r = _parse_rpc_result(body) if ok else {}
    rows = r.get("circuits") if isinstance(r, dict) else (r if isinstance(r, list) else None)
    if not isinstance(rows, list):
        return None, None
    cid = next((c.get("circuit_id") or c.get("id") for c in rows
                if isinstance(c, dict) and str(c.get("status") or "").lower() == "active"
                and (c.get("circuit_id") or c.get("id"))), None)
    return (str(cid), None) if cid else (None, _CLOUDOP_NO_CIRCUIT)


# §MCPTEST30 (V0640): how long the operator run's own proposal stays open. The governance lifecycle votes on it and asks
# for the premature tally within the run (a few minutes); the window outlasts that with room and then closes by itself.
_CLOUDOP_OWN_PROPOSAL_SECONDS = 1800


async def cloudop_open_own_proposal(container: str, sentinel_jwt: str, *,
                                    http: Optional[Callable] = None) -> Tuple[Optional[str], Optional[str]]:
    """§MCPTEST30 (V0640): (the id of a proposal the run's sentinel opened, open for the run, None), or (None, why it
    could not open one). The vote and the premature tally are asked on this one, never on cloudop_pick_proposal's pick:
    the pick serves reads at any status and was an earlier run's, closed, so with V0639's governor grant castVote
    measured "Proposal 4 is not open for voting" and the premature tally "Only the proposal creator can trigger the
    tally" (both sandbox operators, 2026-10-24 23:1xZ, V0640's tester on V0638). POST /governance/proposals takes
    duration_seconds (the createProposal tool's floor is a day); opening one stakes and spends nothing (member mode asks
    membership, lock mode staked units)."""
    if not sentinel_jwt:
        return None, "the run has no sentinel to open a proposal of its own"
    body = json.dumps({
        "title": f"MCP tester: an operator run's own proposal {uuid.uuid4().hex[:8]}",
        "description": "Opened by the MCP tester's operator run to vote on and to ask for a premature tally; it "
                       "changes nothing and closes by itself.",
        "duration_seconds": _CLOUDOP_OWN_PROPOSAL_SECONDS, "proposal_type": "standard"}).encode()
    code, text = await (http or _http_in_target)(container, "POST", "/api/v1/governance/proposals", body=body,
                                                 bearer=sentinel_jwt)
    try:
        d = json.loads(text) if text else {}
    except ValueError:
        d = {}
    d = d if isinstance(d, dict) else {}
    pid = d.get("id") or d.get("proposal_id")
    if str(code).startswith("2") and pid:
        return str(pid), None
    said = str(d.get("detail") or d.get("message") or d.get("error") or (text or "")[:160])
    return None, f"the sentinel could not open a proposal of its own (HTTP {code or 'none'}: {said[:160]})"


async def staking_distribution_pick(call: Callable, jwt: str) -> Optional[str]:
    """§MCPTEST30 (V0545): the id of a staking distribution the target already ran, or None. `call(tool, args, jwt)`
    answers the parsed result. getLockPayoutRuns wraps the route's bare list as {distributions, total}; a
    distribution with no records still serves its records read (an empty page is an answer)."""
    r = await call("theprotocol_getLockPayoutRuns", {"limit": 5}, jwt)
    rows = r.get("distributions") if isinstance(r, dict) else (r if isinstance(r, list) else None)
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and row.get("id"):
            return str(row["id"])
    return None


def cloudop_fixture_skip(tool_name: str, unresolved: List[str], dark: Dict[str, str],
                         unavailable: Dict[str, str]) -> str:
    """The skip sentence for a cloud-op tool whose fixtures did not resolve: the subsystem that is off (§GUILDDARK),
    else what the operator was asked and does not hold (V0545), else the generic "missing" (no entity setup here)."""
    if tool_name.startswith("theprotocol_guild") and "guild" in dark:
        return f"cloud-op fixture unavailable: {unresolved!r} — {dark['guild']}"
    if unresolved and all(u in unavailable for u in unresolved):
        return (f"cloud-op fixture unavailable: {unresolved!r} — "
                + "; ".join(dict.fromkeys(unavailable[u] for u in unresolved)))
    return (f"cloud-op fixture missing: {unresolved!r} — the cloud-op sweep runs no phase-3 entity setup; what it "
            f"can publish without money it does (see 'published fixtures' in the log), and the rest needs a fundable "
            f"operator treasury (B8)")


TOKEN_SCOPE_ROW = "token_scope: operator admin at its parent frame"


async def token_scope_row(op: Any, op_jwt: str) -> "ContractOutcome":
    """§MCPTEST30 (V0529): the operator admin's token asked at its PARENT frame's MCP (its own profile, read only). Right:
    refused (401 / -32001). The finding: answered. NOT MEASURED: no answer at all (the frame unreachable), never read
    as a refusal."""
    t0 = time.time()
    from types import SimpleNamespace
    parent = SimpleNamespace(label=f"parent-of-{op.label}", a_registry_container=op.parent_registry_container,
                                   b_registry_container="")
    try:
        ok, _body, code = await _mcp_rpc_call(parent, "theprotocol_getMyDeveloperProfile", {}, jwt=op_jwt, timeout=20)
    except Exception:  # noqa: BLE001
        ok, code = False, ""
    code = str(code or "")
    answered = bool(ok) and code.startswith("2")
    refused = (not ok) and code.startswith("4")
    return ContractOutcome(
        tool_name=TOKEN_SCOPE_ROW, contract_tier="protocol", healthy=refused,
        status_code=int(code) if code.isdigit() else 0, elapsed_ms=int((time.time() - t0) * 1000),
        skip_reason=(None if (answered or refused) else
                     f"NOT MEASURED: the parent frame did not answer the operator's token (HTTP {code or 'none'})"),
        fail_reason=("BUG-FIND: token_scope: the operator admin's token authenticated at its parent frame: the two "
                     "registries accept each other's tokens, so operator developer 1 is the frame's developer 1 (its "
                     "admin)") if answered else None,
        has_explicit_contract=True, args_used={}, result_excerpt={"answered": answered, "refused": refused})


def _cloudop_result_row(op_label: str, o: "ContractOutcome", step: int) -> Dict[str, Any]:
    """One cloud-op outcome in the APITestBase result shape: the row the console shows.

    §MCPTEST30 (V0536): every outcome the sweep's summary counts goes through here, including one appended after the
    formatting loop. token_scope_row (V0529) was appended after step 6 had formatted the rows, so it was counted in
    tool_count and passed and never shown (round 10's cloud-op alpha run 9b5d52c12a3048ea: 750 counted, 749 rows): a
    BUG-FIND there would have read as one failure with no row naming it."""
    return {
        "step": step,
        "name": f"MCP tool ({op_label}): {o.tool_name} (tier={o.contract_tier})",
        "path": (
            "/mcp/admin/rpc" if o.contract_tier == "admin-bridge" else "/mcp/rpc"
        ),
        "method": "POST",
        "authRequired": (
            "none" if o.contract_tier in ("0", "1")
            else "agent" if o.contract_tier == "2"
            else "developer" if o.contract_tier == "3"
            else "admin"
        ),
        "healthy": o.healthy,
        "statusCode": o.status_code,
        "responseData": {
            "operator": op_label,
            "tool": o.tool_name,
            "has_explicit_contract": o.has_explicit_contract,
            "skip_reason": o.skip_reason,
            # §MCPTEST30 (V0550): the switch this row was held to (mcp_switches.py), or None
            "switched_off": (_swo.label() if (_swo := _switches.switched_off(o.tool_name)) else None),
            # §MCPTEST30 (V0643): the by-design reason the router says if this row passes on a refusal alone
            "declared_unmeasured": _refusal_reasons.declared(o.tool_name),
            "result_excerpt": o.result_excerpt,
            "elapsed_ms": o.elapsed_ms,
        },
        "error": o.fail_reason,
        "expected_failure": o.skip_reason is not None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# §MCPTEST30 (V0637): the earned lifecycles on a cloud operator. A lifecycle's LIFECYCLES entry may name what it needs
# beyond the target's two MCP bridges ("needs"); an operator run takes only the lifecycles it can give everything to.
#   "target_db": the lifecycle reads or writes the target's database (mcp_lifecycles._target_db). The tester runs
#                inside the FRAME's registry, so in-process that database is the operator's parent frame's; since
#                V0638 the sweep gives the operator's own, through psql in its database container (bag.target_db).
#   "peer":      a second frame of the target's own (API_TEST_FED_B_*), which an operator does not have.
CLOUDOP_OFFERS: frozenset = frozenset({"target_db"})
_NEED_SAYS = {
    "target_db": "the target's own database (this run has no way to it)",
    "peer": "a peer frame of the target's (API_TEST_FED_B_*)",
    "frame": "a frame as the target (its own operators' canaries, the frame run's second agent), which an operator is not",
}


def operator_lifecycles(lifecycles: Iterable[Dict[str, Any]], offers: Iterable[str] = CLOUDOP_OFFERS,
                        ) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """(the lifecycles a cloud operator run takes, {name: why it is not run there} for the rest)."""
    have = set(offers)
    run: List[Dict[str, Any]] = []
    not_run: Dict[str, str] = {}
    for lc in lifecycles:
        missing = [n for n in (lc.get("needs") or ()) if n not in have]
        if missing:
            not_run[str(lc.get("name"))] = "needs " + "; ".join(_NEED_SAYS.get(n, n) for n in missing)
        else:
            run.append(lc)
    return run, not_run


# §MCPTEST30 (V0638): the tools that act on the target operator ITSELF when its own admin calls them. A frame's
# lifecycles probe them as refusals (the frame admin is no operator); on an operator they are actions: 2026-10-24
# 11:56Z and 11:58Z, lifecycle_misc_safe's operatorPortalSelfRestart restarted both sandbox operators mid-sweep. No
# lifecycle an operator run takes may name one (tests/test_mcp_cloudop_earned.py).
OPERATOR_SELF_TOOLS = frozenset({
    "theprotocol_operatorPortalSelfRestart", "theprotocol_cloudOperatorSelfRestart",
    "theprotocol_restartCloudOperatorService", "theprotocol_rotateFederationLicenseSelf",
    "theprotocol_requestSelfRevocation", "theprotocol_requestFrame", "theprotocol_selfProvisionOperator",
    "theprotocol_activateOperator",
})
# The lifecycles a cloud-operator run does not take: those that probe an OPERATOR_SELF_TOOLS tool (a frame's refusal, an
# operator's action). The gate fails a lifecycle that reaches one and is not named here.
_CLOUDOP_NOT_FROM_MCP_LIFECYCLES = ("misc_safe", "self_revocation_safe")


def cloudop_lifecycle_list() -> List[Dict[str, Any]]:
    """The lifecycles a cloud-operator sweep runs: mcp_lifecycles' LIFECYCLES (its own and the earned lists it ends
    with) but those that probe a tool acting on the operator itself; operator_lifecycles then keeps those the run can
    give everything to."""
    return [lc for lc in LIFECYCLES if lc.get("name") not in _CLOUDOP_NOT_FROM_MCP_LIFECYCLES]


def operator_slug(container: str) -> str:
    """The operator's name as its stack labels it (`cloud-op-<slug>-registry`), or the container name itself."""
    m = re.match(r"^cloud-op-(.+)-registry$", container or "")
    return m.group(1) if m else (container or "")


async def cloudop_invite(rpc_admin: Callable[..., Awaitable[Tuple[bool, Any, str]]], jwt: str,
                         ) -> Tuple[Optional[str], str]:
    """One single-use invite code from the operator's own admin bridge (generateInviteCodes: no admin grant, no
    expiry; the registration it is made for spends it at once). (code, "") or (None, why)."""
    try:
        ok, body, code = await rpc_admin("theprotocol_generateInviteCodes",
                                         {"count": 1, "note": "mcp-throwaway: one run of the cloud-operator sweep"},
                                         jwt=jwt, timeout=20)
    except Exception as e:  # noqa: BLE001
        return None, f"generateInviteCodes raised {type(e).__name__}"
    got = _parse_rpc_result(body) if isinstance(body, dict) else {}
    codes = got.get("codes") if isinstance(got, dict) else None
    first = codes[0] if isinstance(codes, list) and codes and isinstance(codes[0], dict) else {}
    made = str(first.get("code") or "")
    if ok and made:
        return made, ""
    return None, f"generateInviteCodes answered HTTP {code}"


async def _probe_webhook_sink(container: str) -> Tuple[Optional[bool], str]:
    """§MCPTEST30 (V0639): does the target mount routers/sandbox_webhook_sink? Its flag is the target's environment,
    which a sweep running outside the target's process cannot read, so the target is asked: a GET on the sink's
    POST-only path answers 405 where the router is mounted and 404 where it is not (off, the router is never mounted
    and the path answers as an unknown route does). Anything else is unknown, said. A GET never reaches the sink's
    handler, so nothing is verified or written. Returns (on, why)."""
    try:
        from agentvault_registry.routers import sandbox_webhook_sink as _sink
    except ImportError:
        return None, "this tester has no webhook sink module"
    try:
        code, _t = await _http_in_target(container, "GET", f"{_sink.PATH}/mcp-probe")
    except Exception as e:  # noqa: BLE001 — a fixture, never a finding
        return None, type(e).__name__
    if code == "405":
        return True, f"{_sink.FLAG} is on there: its path answers 405 to a GET"
    if code == "404":
        return False, f"{_sink.FLAG} is off there: its path answers 404"
    return None, f"its path answered HTTP {code or 'nothing'} to a GET"


_RUN_ROLE_DID = re.compile(r"^did:[a-z0-9]+:[A-Za-z0-9.:_-]+$")


async def _grant_run_role(container: str, dev_jwt: str, did: str, role: str, hours: int = 2) -> Dict[str, Any]:
    """§MCPTEST30 (V0639): one role for the run's own agent, for `hours`, through its owner's access API (POST
    /api/v1/agents/{did}/authz/roles grants one role and leaves every other grant as it is; the grant expires by
    itself, and the agent is retired at the run's end). Says what the grant gave: the role, its expiry and the
    agent's gov.* permissions after it. Best-effort: never raises; {"granted": False, "why": ...} on a refusal."""
    out: Dict[str, Any] = {"role": role, "granted": False}
    if not _RUN_ROLE_DID.match(did or ""):
        return {**out, "why": "no agent DID to grant it to"}
    exp = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    try:
        code, txt = await _http_in_target(container, "POST", f"/api/v1/agents/{did}/authz/roles",
                                          body=json.dumps({"role": role, "expires_at": exp}).encode(), bearer=dev_jwt)
    except Exception as e:  # noqa: BLE001 — a fixture, never a finding
        return {**out, "why": type(e).__name__}
    try:
        ans = json.loads(txt) if txt else {}
    except ValueError:
        ans = {}
    if code != "200" or not isinstance(ans, dict):
        return {**out, "why": f"HTTP {code or 'no answer'}"}
    perms = ans.get("effective_permissions") if isinstance(ans.get("effective_permissions"), list) else []
    return {"role": role, "granted": True, "expires_at": exp, "changed": ans.get("changed"),
            "gov_permissions": sorted(p for p in perms if isinstance(p, str) and p.startswith("gov."))}


async def _retire_probe_orgs(call, owner_id: Any, limit: int = 25) -> Dict[str, Any]:
    """§MCPTEST30 (V0639): the organizations the createOrganization contract made on this operator, retired through
    the owner's own delete (a soft delete; refused only for an org holding a listing or a funded treasury, which a
    probe org never has). The contract makes one per run, and only the frames' orphan sweep clears them: an operator
    run has none, so sbxalphaop held 71 and sbxbetaop 49 by 2026-10-24, one per run since 2026-09-05. The name is read
    from the contract itself; only active ones owned by the run's developer are asked, at most `limit` per run, so a
    backlog drains over a few runs. Best-effort: never raises; counts only."""
    out: Dict[str, Any] = {"found": 0, "retired": 0, "refused": []}
    contract = get_contract("theprotocol_createOrganization")
    name = (getattr(contract, "arguments", None) or {}).get("name") if contract is not None else None
    if not name:
        return {**out, "error": "the createOrganization contract names no organization"}
    try:
        ok, body, code = await call("theprotocol_getMyOrganizations", {})
    except Exception as e:  # noqa: BLE001 — cleanup is never a finding
        return {**out, "error": type(e).__name__}
    inner = _parse_rpc_result(body) if isinstance(body, dict) else {}
    orgs = inner.get("organizations") if isinstance(inner, dict) else None
    if not ok or not isinstance(orgs, list):
        return {**out, "error": f"getMyOrganizations answered HTTP {code}"}
    mine = [o for o in orgs if isinstance(o, dict) and o.get("name") == name and o.get("id")
            and o.get("is_active", True) and str(o.get("owner_id")) == str(owner_id)]
    out["found"] = len(mine)
    for o in mine[:max(int(limit), 0)]:
        try:
            okd, _b, coded = await call("theprotocol_deleteOrganization", {"org_id": str(o["id"])})
        except Exception as e:  # noqa: BLE001
            out["refused"].append(type(e).__name__)
            continue
        if okd:
            out["retired"] += 1
        else:
            out["refused"].append(f"HTTP {coded}")
    out["refused"] = out["refused"][:10]
    return out


# §MCPTEST30 (V0639): the free fixtures an operator run makes for itself, each under the one name it gives it. An
# operator has no sandbox reset and the sweep removed none of them, so each stayed, one per run since 2026-09-06: by
# 2026-10-24 sbxalphaop held 63 active API keys, 63 open tickets, 63 bundles and 61 active TEG policies, sbxbetaop 48,
# 48, 48 and 45 (a policy's _del twin is the deleteTegPolicy contract's subject and goes with the run).
CLOUDOP_KEY_NAME = "cloudop-mcp-tester-key"
CLOUDOP_TICKET_SUBJECT = "cloudop-mcp-tester ticket"
CLOUDOP_BUNDLE_NAME = "cloudop-mcp-tester-bundle"
CLOUDOP_POLICY_NAME = "cloud-op fixture %s"   # % its fixture slot, teg_policy_id or teg_policy_id_del
_CLOUDOP_POLICY_CODE = re.compile(r"^CO[RD][0-9A-F]{4}$")


def _created_s(item: Any) -> Optional[float]:
    """An item's created_at as epoch seconds (a stamp without a zone is UTC), or None when it carries none."""
    raw = item.get("created_at") if isinstance(item, dict) else None
    if not isinstance(raw, str) or not raw:
        return None
    try:
        t = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).timestamp()


async def _retire_run_fixtures(call, call_admin, own: Dict[str, Any], owner_id: Any, now: float,
                               limit: int = 25) -> Dict[str, Any]:
    """§MCPTEST30 (V0639): the operator run's free fixtures at the end of the run, with those earlier runs left: its API
    key (deleteMyApiKey), its support ticket (closed through the admin's supportCloseTicket), its bundle (deleteBundle)
    and its TEG policies (deleteTegPolicy). Each is found in its own list by the exact name the run gives it (a bundle
    also by its owner, a policy also by the code the run gives it). The run's own (`own`: its fixture ids) goes first;
    an earlier run's only once it is older than the sweep age (a run lasts under an hour); at most `limit` of each kind
    per run, so a backlog drains over a few runs. A list that cannot be read retires nothing of its kind and says why.
    Best-effort: never raises; counts per kind."""
    out: Dict[str, Any] = {}

    async def _listed(tool: str, args: Dict[str, Any], key: str) -> Tuple[Optional[List[Dict[str, Any]]], str]:
        try:
            ok, body, code = await call(tool, args)
        except Exception as e:  # noqa: BLE001 — cleanup is never a finding
            return None, type(e).__name__
        inner = _parse_rpc_result(body) if isinstance(body, dict) else {}
        items = inner.get(key) if isinstance(inner, dict) else None
        if not ok or not isinstance(items, list):
            return None, f"{tool.replace('theprotocol_', '')} answered HTTP {code}"
        return [i for i in items if isinstance(i, dict)], ""

    async def _drain(kind: str, items: Optional[List[Dict[str, Any]]], why: str, own_id: Any, id_key: str,
                     retire: Callable[[Any], Awaitable[Tuple[bool, Any, Any]]]) -> None:
        if items is None:
            out[kind] = {"found": 0, "retired": 0, "refused": [], "error": why}
            return
        mine = [i for i in items if own_id and str(i.get(id_key)) == str(own_id)]
        older = [i for i in items if i not in mine and i.get(id_key) is not None
                 and (_created_s(i) or now) < now - _CLOUDOP_FIXTURE_AGE_S]
        res: Dict[str, Any] = {"found": len(mine) + len(older), "retired": 0, "refused": []}
        for i in (mine + older)[:max(int(limit), 0)]:
            try:
                ok, _b, code = await retire(i[id_key])
            except Exception as e:  # noqa: BLE001
                res["refused"].append(type(e).__name__)
                continue
            if ok:
                res["retired"] += 1
            else:
                res["refused"].append(f"HTTP {code}")
        res["refused"] = res["refused"][:10]
        out[kind] = res

    keys, why = await _listed("theprotocol_getMyApiKeys", {}, "api_keys")
    await _drain("api_keys", None if keys is None else [k for k in keys if k.get("description") == CLOUDOP_KEY_NAME
                                                         and k.get("is_active")],
                 why, own.get("api_key_id"), "id", lambda kid: call("theprotocol_deleteMyApiKey", {"key_id": str(kid)}))
    tickets, why = await _listed("theprotocol_getMySupportTickets", {"ticket_status": "open", "limit": 200}, "tickets")
    await _drain("tickets", None if tickets is None else [t for t in tickets
                                                          if t.get("subject") == CLOUDOP_TICKET_SUBJECT],
                 why, own.get("support_ticket_id"), "id",
                 lambda tid: call_admin("theprotocol_supportCloseTicket", {"ticket_id": int(tid), "status": "closed"}))
    bundles, why = await _listed("theprotocol_getMyAgentBundles", {"limit": 100}, "bundles")
    await _drain("bundles", None if bundles is None else [b for b in bundles if b.get("name") == CLOUDOP_BUNDLE_NAME
                                                          and str(b.get("source_dev_id")) == str(owner_id)],
                 why, own.get("bundle_id"), "id", lambda bid: call("theprotocol_deleteBundle", {"bundle_id": str(bid)}))
    names = {CLOUDOP_POLICY_NAME % slot for slot in ("teg_policy_id", "teg_policy_id_del")}
    policies, why = await _listed("theprotocol_listTegPolicies", {}, "policies")
    await _drain("teg_policies", None if policies is None else [
        p for p in policies if p.get("policy_name") in names and p.get("is_active", True)
        and _CLOUDOP_POLICY_CODE.match(str(p.get("policy_code") or ""))],
                 why, own.get("teg_policy_id"), "policy_id",
                 lambda pid: call("theprotocol_deleteTegPolicy", {"policy_id": str(pid)}))
    return out


async def _retire_cloudop_agents(call, call_admin, dids: List[str]) -> Dict[str, Any]:
    """§MCPTEST30 (V0528, 2026-10-01): the operator phase's own agents at the end of their life. What each holds goes back
    to the operator's treasury (the admin treasury-receive rail, which writes the ledger event), then the agent is revoked
    (the developer's delete, which also deactivates its card, so the frames' mirrors follow). Measured: the phase made a
    fresh sentinel and a second agent on every run, funded each 5000 from the operator's treasury, staked 100 and bonded
    250 from the sentinel, and removed neither: 97 active on sbxbetaop and 213 on sbxalphaop by 2026-10-01, 509,142
    units liquid, and one became the receiver of agentvault2-21's Forex lifecycle on sbx-alpha (an FX quote 503).
    Staked and bonded units stay locked on the revoked agent (their lock periods outlive a run). An agent whose balance
    could not be read is left alone: an unread balance is not a zero. Best-effort: never raises; returns counts."""
    from decimal import Decimal, InvalidOperation
    out: Dict[str, Any] = {"asked": len(dids), "returned": "0", "returned_from": 0, "revoked": 0,
                           "left_unread": 0, "refused": []}
    total = Decimal("0")
    for i in range(0, len(dids), 50):          # the batch balance route takes 50 at a time
        chunk = [d for d in dids[i:i + 50] if d]
        balances: Dict[str, Any] = {}
        try:
            _ok, body, _code = await call("theprotocol_getBatchAgentBalances", {"agent_dids": chunk})
            balances = (_parse_rpc_result(body) if isinstance(body, dict) else {}).get("balances") or {}
        except Exception:  # noqa: BLE001 — cleanup is never a finding
            balances = {}
        for did in chunk:
            entry = balances.get(did) if isinstance(balances, dict) else None
            try:
                if not isinstance(entry, dict) or entry.get("error"):
                    out["left_unread"] += 1
                    continue
                try:
                    held = Decimal(str(entry.get("balance", "0")))
                except (InvalidOperation, ValueError):
                    out["left_unread"] += 1
                    continue
                if held > 0:
                    ok, _b, code = await call_admin("theprotocol_tegTreasuryReceive", {
                        "source_agent_did": did, "amount": format(held, "f"), "reason": "mcp_tester_fixture_retired",
                        "reference_id": f"mcp-tester-retire-{did[-12:]}"})
                    if not ok:
                        out["refused"].append(f"return HTTP {code}")
                        continue        # still holding: not revoked
                    total += held
                    out["returned_from"] += 1
                ok, _b, code = await call("theprotocol_deleteMyAgentByDev", {"agent_did": did})
                if ok:
                    out["revoked"] += 1
                else:
                    out["refused"].append(f"revoke HTTP {code}")
            except Exception as e:  # noqa: BLE001
                out["refused"].append(type(e).__name__)
    out["returned"] = format(total, "f")
    out["refused"] = out["refused"][:10]
    return out


async def _phase3_teardown(target, bag: McpFixtureBag) -> None:
    """Best-effort cleanup of phase-3 entities.

    Sandbox reset (next run's bootstrap) wipes everything anyway, so this
    is mostly belt-and-suspenders. Each call swallows its own error.
    """
    async def _call(tool: str, args: Dict[str, Any], jwt: str) -> None:
        await _mcp_rpc_call(target, tool, args, jwt=jwt, timeout=10)

    fv = bag.flow_values
    if fv.get("payment_token"):
        await _call("theprotocol_releasePayment",
                    {"agent_jwt": bag.sentinel_jwt, "token": fv["payment_token"]},
                    bag.developer_jwt)
    if fv.get("stake_id"):
        await _call("theprotocol_unlockUnits",
                    {"agent_jwt": bag.sentinel_jwt, "stake_id": fv["stake_id"]},
                    bag.developer_jwt)
    if fv.get("webhook_id"):
        await _call("theprotocol_deleteWebhook", {"webhook_id": fv["webhook_id"]}, bag.developer_jwt)
    if fv.get("bundle_id"):
        await _call("theprotocol_deleteBundle", {"bundle_id": fv["bundle_id"]}, bag.developer_jwt)
    if fv.get("organization_id"):
        async def _c(tool, args):
            return await _mcp_rpc_call(target, tool, args, jwt=bag.developer_jwt, timeout=20)

        async def _ca(tool, args):
            return await _mcp_rpc_call_admin(target, tool, args, jwt=bag.developer_jwt, timeout=25)
        note = await _retire_scratch_org(target.a_registry_container, _c, _ca, str(fv["organization_id"]),
                                         str(fv.get("scratch_listing") or ""), bag.developer_jwt,
                                         str(fv.get("second_agent_did") or bag.sentinel_did or ""),
                                         already_delisted=bool(fv.get("scratch_listing_delisted")))
        logger.info(f"phase-3 teardown: the scratch organization: {note}")
    # §MCPTEST30: the run's throwaway non-admin principal asks for its own deletion, now that both wrong-tier
    # matrices are done with it (the self-account subject does the same at the end of its lifecycle).
    _p = getattr(bag, "nonadmin_principal", None) or {}
    if _p.get("email") and _p.get("password"):
        from agentvault_registry.api_tests.contracts.mcp_lifecycles import _schedule_own_deletion

        async def _rpc_td(tool, args, jwt="", timeout=20):
            return await _mcp_rpc_call(target, tool, args, jwt=jwt, timeout=timeout)
        await _schedule_own_deletion(_rpc_td, bag, _p["email"], _p["password"], "auth-matrix principal")


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

# §MCPTEST30 (2026-10-01): what a 401 says when the CALLER's credential failed (expired, revoked, unreadable), as
# opposed to a tool refusing what it was asked (setup2FA with a wrong password answers 401 "Invalid password").
_CREDENTIAL_401_PHRASES = ("could not validate credentials", "token_version", "has been revoked", "signature has expired",
                           "token expired", "token has expired", "not authenticated", "invalid token", "-32001",
                           "authentication required")


def _is_credential_401(parsed: Any) -> bool:
    try:
        blob = json.dumps(parsed, default=str).lower()
    except Exception:  # noqa: BLE001 — unreadable: treat as the credential (the old behaviour)
        return True
    return any(p in blob for p in _CREDENTIAL_401_PHRASES)


# §MCPTEST30: lifecycle rows that are checks of their own, not tools (see the merge after the public sweep)
def _refusal_words(o: Any) -> str:
    """The refusal sentence an outcome recorded, as the operator wrote it (the `Error: ` prefix off, 160 characters): what
    a classifier that recognised no phrase in it reports, instead of a guess at why (§MCPTEST30, V0524)."""
    ex = getattr(o, "result_excerpt", None) or {}
    t = ex.get("_text") if isinstance(ex, dict) else None
    t = t if isinstance(t, str) else str(getattr(o, "fail_reason", "") or "")
    return re.sub(r"\s+", " ", t.replace("Error: ", "", 1)).strip()[:160]


# §MCPTEST30: the phrases that say a tool is mainframe-only BY CONSTRUCTION, a subset of the gate phrases below (module
# level since V0641, so the healthy-refusal branch and a test read the same tuple)
CLOUDOP_BY_CONSTRUCTION_MARKERS = (
    "mainframe_only:",   # V0640: D6-820's code word, the answer's stable part
    "sovereign mainframe", "runs on mainframe", "mainframe admins", "cloud-operators federate",
    "fiat onramp is mainframe", "mainframe-only", "this feature runs on",
)


def cloudop_by_design_refusal(o: "ContractOutcome") -> Optional["ContractOutcome"]:
    """§MCPTEST30 (V0641): the by-design row for a cloud-op tool that PASSED its own contract on a refusal which says,
    in the operator's words, that the tool is mainframe-only by construction; None for any other row. The gate
    classifier reads only rows that failed their contract (a3fd8761 says the gated ones by design), so a mainframe-only
    tool whose contract accepts the refusal passed on it alone and the tester router gave it the generic refusal-only
    sentence: most of the 45 admin rows per operator left after V0640's second preview (2026-10-25 01:56-02:05Z). A
    refusal that names no such phrase (a bare 503 whose sentence the wrapper ate) is left as it is: its cause cannot be
    told. Not measured either way; only the reason is new. Only the tool's own contract row: a `refusal: ` row (or any
    lifecycle-family row) is a measurement of the refusal and stays one."""
    if not str(o.tool_name or "").startswith("theprotocol_"):
        return None
    if not o.healthy or o.skip_reason or 200 <= int(o.status_code or 0) < 300:
        return None
    blob = str(o.result_excerpt or {}).lower()
    phrase = next((m for m in CLOUDOP_BY_CONSTRUCTION_MARKERS if m in blob), None)
    if not phrase:
        return None
    ex = dict(o.result_excerpt or {})
    ex["verified_refusal"] = (f"refused by construction on a cloud-op: '{phrase}' (HTTP {o.status_code}), the "
                              "operator's contract for a mainframe-only tool")
    return ContractOutcome(
        tool_name=o.tool_name,
        contract_tier=o.contract_tier,
        healthy=False,
        status_code=o.status_code,
        elapsed_ms=o.elapsed_ms,
        skip_reason=cloudop_by_construction_reason(phrase, o.status_code),
        fail_reason=None,
        has_explicit_contract=o.has_explicit_contract,
        args_used=o.args_used,
        result_excerpt=ex,
    )


# §MCPTEST30 (V0641): the phrases in which an operator says plainly that a feature is OFF on it, a subset of the gate
# phrases below; only these may be said "the feature is off" for a refusal that passed its contract
CLOUDOP_SWITCHED_OFF_MARKERS = (
    "is not enabled on this registry", "not enabled on this registry", "not currently enabled on this registry",
    "is disabled on this registry", "are disabled on this registry", "unavailable on this node",
    # the V0641 operator preview (2026-10-25 09:5xZ): executeTutorial 503 "No tutorial sandbox is configured on this
    # registry (API_TEST_TARGET_URL is unset)", adminGrafanaQuery "Grafana credentials not configured: set
    # GRAFANA_ADMIN_PASS ... No request was sent."
    "no tutorial sandbox is configured", "grafana credentials not configured",
)


def cloudop_flag_gated_reason(phrase: str, status_code: Any) -> str:
    """The row of a tool an operator refused because the feature is off on it, in its own words: NOT MEASURED (the
    operator sweep's gate classifier, the `_flag` branch, and cloudop_switched_off_refusal)."""
    return (f"cloud-op flag-gated: the operator says '{phrase}' (HTTP {status_code}): the feature is off "
            "on this node, so its success path is not measured here")


def cloudop_switched_off_refusal(o: "ContractOutcome") -> Optional["ContractOutcome"]:
    """§MCPTEST30 (V0641): the not-measured row for a cloud-op tool that PASSED its own contract on a refusal which says,
    in the operator's words, that the feature is off on it (CLOUDOP_SWITCHED_OFF_MARKERS); None for any other row. The
    by-design branch beside it (cloudop_by_design_refusal) takes the mainframe-only words only, so a tool switched off
    on the operator passed on its refusal alone: oauthIntrospect, oauthRevoke and oauthTokenExchange on both sandbox
    operators, 501 "Cross-registry OAuth federation is not enabled on this registry (no active trusted registries
    configured)" (V0639's read, 2026-10-25). The same sentence the gate classifier gives such a refusal that failed its
    contract. Only the tool's own contract row, as there."""
    if not str(o.tool_name or "").startswith("theprotocol_"):
        return None
    if not o.healthy or o.skip_reason or 200 <= int(o.status_code or 0) < 300:
        return None
    blob = str(o.result_excerpt or {}).lower()
    phrase = next((m for m in CLOUDOP_SWITCHED_OFF_MARKERS if m in blob), None)
    if not phrase:
        return None
    return ContractOutcome(
        tool_name=o.tool_name,
        contract_tier=o.contract_tier,
        healthy=False,
        status_code=o.status_code,
        elapsed_ms=o.elapsed_ms,
        skip_reason=cloudop_flag_gated_reason(phrase, o.status_code),
        fail_reason=None,
        has_explicit_contract=o.has_explicit_contract,
        args_used=o.args_used,
        result_excerpt=dict(o.result_excerpt or {}),
    )


def cloudop_listing_row(code: Any, listing: Any, elapsed_ms: int) -> Dict[str, Any]:
    """§MCPTEST30 (V0641): createAgoraListing's own row, from the operator bootstrap's call that makes the AGORA fixture
    listing (an organization of the run's, the sentinel funding it). The bootstrap used the listing and recorded nothing,
    so the tool's row was its contract's refusal on a made-up organization alone ("organization not found": refusal only
    on both operators, V0640's previews 2026-10-24/25). A 2xx with a listing id is the success; anything else says what
    came back."""
    from agentvault_registry.api_tests.contracts.mcp_lifecycles import _make_outcome
    d = listing if isinstance(listing, dict) else {}
    lid = d.get("id") or d.get("listing_id")
    ok = str(code).startswith("2") and bool(lid)
    fail = None if ok else f"the fixture listing's create answered HTTP {code or 'none'} with no listing id"
    return _make_outcome("theprotocol_createAgoraListing", "3", ok, str(code), int(elapsed_ms), fail, d,
                         expect_status="success")


def teg_policy_batch_policy(code: str, name: str, description: str) -> Dict[str, Any]:
    """§MCPTEST30 (V0641): the one policy a bootstrap asks createTegPoliciesBatch for (its second fixture policy,
    teg_policy_id_del), in the route's own fields (TEGPolicyRequest), never an `enabled` or a `rules` it drops."""
    return {"policy_code": code, "policy_name": name, "policy_type": "compliance", "description": description}


def teg_policy_batch_failure(inner: Any, asked: int) -> Optional[str]:
    """§MCPTEST30 (V0641): why a createTegPoliciesBatch answer did not create the `asked` policies, or None when it did.
    POST /teg/policies/batch answers 200 whatever it created (success_count, failure_count and the errors; its docstring's
    "atomic" is not what it does), so a 2xx alone is no success: each asked policy must come back with its id."""
    d = inner if isinstance(inner, dict) else {}
    made = [p for p in (d.get("created_policies") or []) if isinstance(p, dict) and p.get("policy_id")]
    if len(made) == asked and not d.get("failure_count"):
        return None
    return (f"the batch answered {len(made)} of {asked} policies created (failure_count "
            f"{d.get('failure_count')!r}): {str(d.get('errors') or '')[:200] or 'no errors listed'}")


def teg_policy_batch_id(inner: Any) -> str:
    """The first created policy's id in a createTegPoliciesBatch answer, or ''."""
    d = inner if isinstance(inner, dict) else {}
    made = [p for p in (d.get("created_policies") or []) if isinstance(p, dict) and p.get("policy_id")]
    return str(made[0]["policy_id"]) if made else ""


def cloudop_policy_row(tool: str, code: Any, inner: Any, elapsed_ms: int) -> Dict[str, Any]:
    """§MCPTEST30 (V0641): createTegPolicy's or createTegPoliciesBatch's own row, from the operator bootstrap's call that
    makes the run's two TEG policies (teg_policy_id through createTegPolicy, teg_policy_id_del through the batch). The
    bootstrap kept the ids and recorded nothing, and lifecycle_teg_policy wrote createTegPolicy's row with its refusal,
    so both tools passed on a refusal alone on both sandbox operators (V0639's read, 2026-10-25). A 2xx with the policy
    id (each asked policy, for the batch) is the success; anything else says what came back."""
    from agentvault_registry.api_tests.contracts.mcp_lifecycles import _make_outcome
    d = inner if isinstance(inner, dict) else {}
    if tool == "theprotocol_createTegPoliciesBatch":
        why = teg_policy_batch_failure(d, 1)
    else:
        why = None if (d.get("policy_id") or d.get("id")) else "with no policy id"
    ok = str(code).startswith("2") and why is None
    fail = None if ok else f"the fixture policy's create answered HTTP {code or 'none'} {why or ''}".rstrip()
    return _make_outcome(tool, "3", ok, str(code), int(elapsed_ms), fail, d, expect_status="success")


# The phrases a cloud-op's refusal uses to say a feature is OFF on this node (or not hosted here), matched in the
# lowered refusal text by the cloud-op classifier in the complete flow. Each line carries the measurement that added it.
CLOUDOP_GATE_MARKERS = (
    # §MCPTEST30 (V0640): agentvault2-d6's D6-820 answers every mainframe-only refusal 404 with the code word first
    # ("mainframe_only: <the sentence>"); the code word is that answer's stable part, the sentence may be reworded
    "mainframe_only:",
    "sovereign mainframe", "runs on mainframe", "mainframe admins",
    "cloud-operators federate", "fiat onramp is mainframe",
    "is for cloud-ops only", "mainframe-only", "this feature runs on",
    "sandbox-only endpoint",
    # §2026-06-01 — explicit gate phrases the registry emits on routes a
    # federated child does not host: operator-portal / federation-license
    # gated ("Mainframe: Invalid or revoked federation license") and the
    # no-operator-application case (a cloud-op admin is not an applicant).
    "mainframe:", "federation license", "no operator application",
    # §CLOUDOPMCP 2026-09-04 — explicit feature-flag-off phrasing. Measured on
    # a cloud-op: oauthRevoke answers 501 "Cross-registry OAuth federation is
    # not enabled on this registry (no active trusted registries configured)."
    # That is the registry correctly reporting a disabled feature, not a defect.
    "is not enabled on this registry", "not enabled on this registry",
    # §EVTYPES7 2026-09-06 — the complement of the phrase above, which the
    # list did not have. MEASURED on cloud-op-sbxalphaop: three Guild tools
    # answer 503 "The Guild is disabled on this registry" and the api-test
    # rails answer 503 "api-tester execution is disabled on this registry
    # (API_TEST_EXECUTION_ENABLED=false …)". Both are the registry saying
    # plainly that a feature is off here, and both were being tolerated only
    # by the unconditional 503 branch below — i.e. for the right outcome by
    # the wrong route.
    "is disabled on this registry",
    # Docker stats: "Docker stats unavailable on this node (docker socket
    # not reachable — e.g. a consumer cloud-op)". Same class, different noun.
    "unavailable on this node",
    # §MCPTEST30 (V0524) — MEASURED in round 7 (sbxbetaop, V0515): "Fiat onramp is not currently enabled on this
    # registry." (getFiatTiers, 503) and "Contract templates are disabled on this registry" (instantiateContractTemplate,
    # 503) matched no phrase above, and the fallback then said the wrapper had dropped the operator's sentence: a cause
    # the classifier invented, the sentence was there.
    "not currently enabled on this registry", "are disabled on this registry",
    # §MCPTEST30 (V0641): the tutorial sandbox and Grafana's credentials, not configured on the operator (the V0641
    # preview: executeTutorial 503, adminGrafanaQuery 400; CLOUDOP_SWITCHED_OFF_MARKERS says them for a passing row)
    "no tutorial sandbox is configured", "grafana credentials not configured",
)


_SYNTHETIC_ROW_PREFIXES = ("mcp_protocol: ", "owner_scoping: ", "pagination: ", "idempotency: ", "bounds: ", "amount: ",
                           "list_detail: ", "hygiene: ", "race: ", "types: ", "write_hygiene: ", "range: ", "overdraft: ",
                           "revocation: ", "scope: ", "ledger: ", "filter: ", "a2a_race: ", "enum: ", "achievements: ",
                           # §MCPTEST30 (V0552): the commons ballot probe; a prefix missing here drops its rows unread
                           "commons: ",
                           # §MCPTEST30 (V0553): an admin action on the run's own object (mcp_lifecycles._ADMIN_EFFECT)
                           "admin_effect: ",
                           # §MCPTEST30 (V0556): a thread read by an agent that is no participant (mcp_lifecycles._CHAT)
                           "chat: ",
                           # §MCPTEST30 (V0636): a refusal an earned lifecycle keeps beside the tool's success
                           # (earned_fixtures.refusal_step), filed under its own name, never the tool's
                           "refusal: ",
                           # §MCPTEST30 (V0644): the local guild lifecycle's own row, every order the run opened closed
                           # (earned_agent_public.GUILD_CLOSED_ROW)
                           "guild: ",
                           # §MCPTEST30 (V0636, found by agentvault2-66): the zk v2 attestation rows
                           # (zk_v2_attestations.PREFIX) were dropped unread on every run since V0612
                           "zk v2: ",
                           # §MCPTEST30 (V0636): a real success a lifecycle measured under a tool's own name where
                           # the tool's contract pins a refusal (kept_lifecycle_rows; earned_fixtures.EARNED_ROW)
                           "earned: ")


def _real_success(d: Dict[str, Any]) -> bool:
    """A lifecycle row that measured the tool doing its job: healthy, not a named skip, a 2xx."""
    try:
        code = int(d.get("status_code") or 0)
    except (TypeError, ValueError):
        code = 0
    return bool(d.get("healthy")) and not d.get("skip_reason") and 200 <= code < 300


def kept_lifecycle_rows(lifecycle_rows: Dict[str, Dict[str, Any]], listed: set, present: set,
                        pinned: Callable[[str], bool]) -> List[Tuple[str, Dict[str, Any]]]:
    """§MCPTEST30 (V0636): the lifecycle rows a sweep keeps beside its own, as (row name, row).

    A sweep consults a lifecycle row BY TOOL NAME, and where the tool's contract pins a refusal (override_coverage_fan,
    the V0550 pins) it runs that contract instead, so a real success a lifecycle measured under the tool's name was
    thrown away: the command centre's runAllDiagnostics, runDiagnosticsSubset and triggerDiagnosticAction on the frame
    itself read refusal-only on V0635 for that reason. Such a success is kept as `earned: <tool>`, beside the pinned
    refusal. A row named for no tool (a `<family>: ` prefix of _SYNTHETIC_ROW_PREFIXES) is kept under its own name: the
    public sweep always did, the admin sweep dropped them. `present` holds the names the sweep has already emitted;
    nothing is emitted twice."""
    out: List[Tuple[str, Dict[str, Any]]] = []
    seen = set(present)
    for name in sorted(lifecycle_rows):
        d = lifecycle_rows[name]
        if not isinstance(d, dict):
            continue
        if name in listed:
            if not (pinned(name) and _real_success(d)):
                continue
            row_name = "earned: " + name.replace("theprotocol_", "", 1)
        elif name.startswith(_SYNTHETIC_ROW_PREFIXES):
            row_name = name
        else:
            continue
        if row_name in seen:
            continue
        seen.add(row_name)
        out.append((row_name, d))
    return out


def _credential_census_close(outcomes: List["ContractOutcome"], token: Any) -> Dict[str, Any]:
    """§MCPTEST30 (2026-10-01): close the run's credential exposure census (api_tests/contracts/credential_exposure.py).

    One row for the census itself, red when any tool handed out a credential it does not issue, and a BUG-FIND on that
    tool's own row. Every finding is a kind and a path, never a value. Never raises: a census that could not run says
    NOT MEASURED on its row rather than passing over nothing."""
    try:
        summary = credential_exposure.summarize(credential_exposure.end(token))
    except Exception as e:  # noqa: BLE001
        summary = {"measured": False, "error": f"{type(e).__name__}: {e}"[:200]}
    unexpected = summary.get("unexpected") or {}
    for o in outcomes:
        found = unexpected.get(o.tool_name)
        if found and not o.skip_reason:
            reason = credential_exposure.row_reason(o.tool_name, found)
            o.healthy = False
            o.fail_reason = f"{o.fail_reason} · {reason}" if o.fail_reason else reason
    measured = bool(summary.get("measured"))
    verdict = credential_exposure.verdict_text(summary) if measured else None

    def _kinds(cls: str) -> Dict[str, List[str]]:
        return {t.replace("theprotocol_", ""): sorted({f.split(" at ")[0] for f in v})
                for t, v in (summary.get(cls) or {}).items()}
    excerpt = {
        "unexpected": {t.replace("theprotocol_", ""): v for t, v in unexpected.items()},
        "responses_scanned": summary.get("responses_scanned", 0),
        "scan_errors": summary.get("scan_errors", 0),
        "counts": {c: len(summary.get(c) or {}) for c in ("issuer", "owner_read", "proxied", "informational")},
        "issuer": _kinds("issuer"), "owner_read": _kinds("owner_read"),
        "informational": _kinds("informational"), "proxied": _kinds("proxied"),
    }
    outcomes.append(ContractOutcome(
        tool_name=credential_exposure.CENSUS_ROW, contract_tier="audit",
        healthy=measured and not verdict, status_code=200 if measured else 0, elapsed_ms=0,
        skip_reason=None if measured else (
            "credential exposure census NOT MEASURED: " + (summary.get("error") or
            "no response was scanned, or the product's credential shapes could not be imported")),
        fail_reason=verdict, has_explicit_contract=True, args_used={}, result_excerpt=excerpt))
    return summary


DB_HEADROOM_ROW = "mcp_tester: db_headroom"


def _gunicorn_workers() -> Optional[int]:
    """The worker count on the command line of the gunicorn master this process runs under (`--workers N`, `-w N`,
    `--workers=N`), or None when it cannot be read."""
    try:
        with open(f"/proc/{os.getppid()}/cmdline", "rb") as fh:
            args = fh.read().decode(errors="replace").split("\0")
    except OSError:
        return None
    return workers_from_args(args)


def workers_from_args(args: List[str]) -> Optional[int]:
    for i, a in enumerate(args):
        if a in ("-w", "--workers") and i + 1 < len(args) and args[i + 1].isdigit():
            return int(args[i + 1])
        if a.startswith("--workers=") and a.split("=", 1)[1].isdigit():
            return int(a.split("=", 1)[1])
    return None


def db_headroom_verdict(used: int, mx: int, reserved: int, pools_can_hold: Optional[int]
                        ) -> Tuple[bool, Optional[str]]:
    """(healthy, the failure sentence) for the target database's client connections against its ceiling."""
    if used >= mx - reserved - 2:
        return False, (f"BUG-FIND: db headroom: the target's database holds {used} of {mx} client connections (the "
                       f"registry's pools can hold {pools_can_hold if pools_can_hold is not None else '?'}): a new "
                       f"connection is refused as 'too many clients' while every pooled one still answers")
    return True, None


async def _db_headroom_close(outcomes: List["ContractOutcome"]) -> Dict[str, Any]:
    """§MCPTEST30 (2026-10-01): the target's database connections against their ceiling, read at the end of the run,
    when the pools are fullest. agentvault2-eb measured sbx-alpha-db at 100 of 100 client backends after round 6: every
    registry worker may hold pool_size + max_overflow connections (database.py: 40 + 40) and Postgres allows 100, so
    eight workers can hold 640. A new connection then fails as "too many clients" while every pooled one answers, which
    no route check sees. Red when the database sits at its ceiling (or refuses this read for that reason); a pool
    capacity above the ceiling is recorded, not failed. Counts only. Never raises."""
    ev: Dict[str, Any] = {}
    fail = skip = None
    try:
        from sqlalchemy import text as _text
        from agentvault_registry.database import AsyncSessionLocal as _S, engine as _engine
        async with _S() as _db:
            row = (await _db.execute(_text(
                "SELECT count(*) FILTER (WHERE backend_type = 'client backend'), "
                "count(*) FILTER (WHERE backend_type = 'client backend' AND state = 'idle'), "
                "current_setting('max_connections')::int, current_setting('superuser_reserved_connections')::int "
                "FROM pg_stat_activity"))).one()
        used, idle, mx, reserved = (int(x) for x in row)
        per_worker = int(_engine.pool.size()) + int(getattr(_engine.pool, "_max_overflow", 0) or 0)
        workers = _gunicorn_workers()
        can_hold = workers * per_worker if workers else None
        ev = {"client_backends": used, "idle": idle, "max_connections": mx, "reserved": reserved,
              "pool_per_worker": per_worker, "workers": workers, "pools_can_hold": can_hold,
              "pools_exceed_the_ceiling": (can_hold > mx) if can_hold is not None else None}
        healthy, fail = db_headroom_verdict(used, mx, reserved, can_hold)
    except Exception as e:  # noqa: BLE001
        if "too many clients" in str(e).lower():
            fail = ("BUG-FIND: db headroom: the target's database refused this read as 'too many clients': it sits at "
                    "its connection ceiling")
        else:
            skip = f"NOT MEASURED: the target's database could not be read ({type(e).__name__})"
    outcomes.append(ContractOutcome(
        tool_name=DB_HEADROOM_ROW, contract_tier="audit", healthy=fail is None and skip is None,
        status_code=0 if skip else 200, elapsed_ms=0, skip_reason=skip, fail_reason=fail, has_explicit_contract=True,
        args_used={}, result_excerpt=ev))
    return ev


def _result_shape_close(outcomes: List["ContractOutcome"], token: Any) -> Dict[str, Any]:
    """§MCPTEST30 (2026-10-01): close the run's result shape census (api_tests/contracts/result_shape.py): one row for
    the census, red when any tool answered outside the protocol's promise (a success reported as a failure; an answer
    that does not validate against the outputSchema its tool declares), and a BUG-FIND on that tool's own row. Never
    raises: a census that could not run says NOT MEASURED on its row rather than passing over nothing."""
    try:
        summary = result_shape.summarize(result_shape.end(token))
    except Exception as e:  # noqa: BLE001
        summary = {"measured": False, "error": f"{type(e).__name__}: {e}"[:200]}
    findings = summary.get("findings") or {}
    for o in outcomes:
        found = findings.get(o.tool_name)
        if found and not o.skip_reason:
            reason = result_shape.row_reason(found)
            o.healthy = False
            o.fail_reason = f"{o.fail_reason} · {reason}" if o.fail_reason else reason
    measured = bool(summary.get("measured"))
    verdict = result_shape.verdict_text(summary) if measured else None
    outcomes.append(ContractOutcome(
        tool_name=result_shape.CENSUS_ROW, contract_tier="audit",
        healthy=measured and not verdict, status_code=200 if measured else 0, elapsed_ms=0,
        skip_reason=None if measured else (
            "result shape census NOT MEASURED: " + (summary.get("error") or "no response was read")),
        fail_reason=verdict, has_explicit_contract=True, args_used={},
        result_excerpt={"responses_scanned": summary.get("responses_scanned", 0),
                        "schema_checked": summary.get("schema_checked", 0),
                        "scan_errors": summary.get("scan_errors", 0),
                        "schemas_available": summary.get("schemas_available"),
                        "validator_available": summary.get("validator_available"),
                        "findings": {t.replace("theprotocol_", ""): v for t, v in findings.items()},
                        # §MCPTEST30 (V0514): counted, not a red: refusals that name no reason, with their codes
                        "reasonless_refusals": {t.replace("theprotocol_", ""): v for t, v in
                                                (summary.get("reasonless_refusals") or {}).items()}}))
    return summary


def _wording_close(outcomes: List["ContractOutcome"], token: Any, listings: Dict[str, Any]) -> Dict[str, Any]:
    """§MCPTEST30 W6 (agentvault2-aa, 2026-10-25; his words to agentvault2-69 that day: "i want the illegal wording
    completly gone before opening"): the critical words on the MCP surface (api_tests/contracts/critical_words.py).

    The LISTINGS: a listed tool whose name or description names a critical word fails its own row, and so does a renamed
    tool's old name still listed; the listings' row is red with either, and NOT MEASURED when no listing was read. The
    ANSWERS: every answer the run received is scanned, and the row names the tools whose answers carry a word; it judges
    nothing yet (answers carry data the workstreams are still rewording, the agent cards among them), it is read for the
    opening (the plan's gate: the tester reads zero on production's switches). Never raises."""
    try:
        answers = _words.answers_summary(_words.end(token))
    except Exception as e:  # noqa: BLE001
        answers = {"error": f"{type(e).__name__}: {e}"[:200]}
    listings = listings or {}
    found = {side: [f for f in v.get("findings") or []] for side, v in listings.items()}
    old = sorted({n for v in listings.values() for n in v.get("old_names") or []})
    by_tool = {f["tool"]: _words.listing_reason(f) for v in found.values() for f in v}
    for n in old:
        by_tool[n] = (by_tool[n] + " · " if n in by_tool else "") + "WORDING: an old name is listed beside its new one"
    for o in outcomes:
        reason = by_tool.get(o.tool_name)
        if reason and not o.skip_reason:
            o.healthy = False
            o.fail_reason = f"{o.fail_reason} · {reason}" if o.fail_reason else reason
    read = sorted(listings)
    n = sum(len(v) for v in found.values()) + len(old)
    excerpt = {"listings_read": read, "tools_listed": {side: v.get("listed", 0) for side, v in listings.items()},
               "old_names_listed": [x.replace("theprotocol_", "") for x in old],
               "findings": {side: [{"tool": f["tool"].replace("theprotocol_", ""), "name": f["name"],
                                    "description": f["description"]} for f in v] for side, v in found.items()}}
    outcomes.append(ContractOutcome(
        tool_name=_words.LISTING_ROW, contract_tier="audit",
        healthy=bool(read) and n == 0, status_code=200 if read else 0, elapsed_ms=0,
        skip_reason=None if read else "the critical-words listing check NOT MEASURED: no tools/list was read",
        fail_reason=(f"{n} listed tool(s) name a critical word or an old name" if read and n else None),
        has_explicit_contract=True, args_used={}, result_excerpt=excerpt))
    measured = bool(answers.get("responses_scanned"))
    outcomes.append(ContractOutcome(
        tool_name=_words.ANSWERS_ROW, contract_tier="audit",
        healthy=measured, status_code=200 if measured else 0, elapsed_ms=0,
        skip_reason=None if measured else ("the critical-words answers census NOT MEASURED: "
                                           + str(answers.get("error") or "no answer was scanned")),
        fail_reason=None, has_explicit_contract=True, args_used={}, result_excerpt=answers))
    return {"listings": excerpt, "answers": answers}


def _listing_words(tools: List[Any]) -> Dict[str, Any]:
    """One listing's critical-word findings and its old names, for _wording_close."""
    return {"listed": len(tools), "findings": _words.listing_findings(tools), "old_names": _words.old_names_listed(tools)}


class TestFlowMcpLifecycle(APITestBase):
    CATEGORY_NAME = "flow_mcp_lifecycle"
    flow_values: Dict[str, Any] = {}

    async def setup(self):
        await self.setup_category(self.CATEGORY_NAME)
        self.flow_values = {}

    async def teardown(self):
        return

    async def test_all(self, developer_token=None, agent_token=None):
        """Standard entry point — runs the lifecycle sweep."""
        std = await self.test_category_endpoints(
            category=self.CATEGORY_NAME,
            developer_token=developer_token,
            agent_token=agent_token,
            priority_only=False,
        )
        std["flow_tests"] = await self.test_mcp_lifecycle_flow(developer_token)
        return std

    async def test_mcp_lifecycle_flow(self, developer_token: Optional[str] = None) -> Dict[str, Any]:
        logger.info("=" * 60)
        logger.info("Starting MCP Lifecycle Flow (phase 1)")
        logger.info(f"Explicit contracts loaded: {contract_count()}")
        logger.info(f"Skipped tools: {len(skipped_tools())}")
        logger.info("=" * 60)

        target = get_target("sandbox")
        results: List[Dict[str, Any]] = []
        t_start = time.time()
        _census_token = credential_exposure.begin()   # §MCPTEST30: every response of this run is scanned
        _shape_token = result_shape.begin()           # §MCPTEST30: and read for the protocol's shape
        _words_token = _words.begin()                 # §MCPTEST30 W6: and for the critical words

        # MCP Tester live-progress: shared helper used across phases so the
        # heartbeat surfaces meaningful info even during the multi-minute
        # setup/lifecycle phases that happen BEFORE the per-tool sweep.
        # Writes to Redis key `mcp_tester:progress` (DB scoped to registry).
        try:
            from agentvault_registry.background_tasks.leader import get_redis  # noqa
            _mcp_progress_redis = await get_redis()
        except Exception:
            _mcp_progress_redis = None

        async def _mcp_record(*, phase: str, last_tool: str = "",
                              completed: int = 0, total: int = 0) -> None:
            if _mcp_progress_redis is None:
                return
            try:
                await _mcp_progress_redis.hset(
                    "mcp_tester:progress",
                    mapping={
                        "last_tool":  last_tool or "",
                        "completed":  str(completed),
                        "total":      str(total),
                        "phase":      phase,
                        "updated_at": str(time.time()),
                    },
                )
                await _mcp_progress_redis.expire("mcp_tester:progress", 3600)
            except Exception:
                pass

        await _mcp_record(phase="Phase 0 · login + bootstrap")

        # 1. Login as sandbox admin for the dev JWT
        ok_login, dev_jwt, det = await login_admin(target, "a")
        if not ok_login:
            return self._summarize(results, False, "sandbox admin login failed: " + det)

        # ── §pass73.2 task G — orphan sweep BASELINE ──────────────────────
        # Capture row counts on entity tables before lifecycles run. The
        # post-sweep snapshot (further down) gives us the delta per table.
        # Sandbox DB container derives from the registry name by pattern:
        #   agentvault_registry_test    → agentvault_registry_db_test
        #   agentvault_registry_test_b  → agentvault_registry_db_test_b
        _db_container_a = target.a_registry_container.replace("registry_test", "registry_db_test")
        try:
            orphan_baseline = await _snapshot_row_counts(_db_container_a)
            logger.info(f"orphan baseline captured: {len(orphan_baseline)} tables")
        except Exception as e:
            logger.warning(f"orphan baseline failed (non-fatal): {e!r}")
            orphan_baseline = {}

        # ── Phase F.3 — wrapper↔route: does each tool's request pass its route? ─────────
        # §MCPTEST30 (V0547): the build's request survey, run sealed in a child process on this image (no connection,
        # no process, none of the node's environment), read by the gate's own rule
        # (api_tests/contracts/wrapper_route_survey.py). The static check it replaces fetched /openapi.json, which
        # answers 308 since §pass52, so it never ran. Non-fatal: an unmeasured run says why.
        from agentvault_registry.api_tests.contracts import wrapper_route_survey as _wrs
        wrapper_drift_summary: Dict[str, Any] = _wrs.flow_values(await _wrs.run_survey())
        _wrapper_drift_ran = wrapper_drift_summary["wrapper_drift_measured"]
        logger.info(
            f"Wrapper-route survey: {wrapper_drift_summary['wrapper_drift']} tools whose route refuses their request, "
            f"{len(wrapper_drift_summary['wrapper_drift_known'])} named exceptions, "
            f"{wrapper_drift_summary['wrapper_drift_surveyed']} surveyed in {wrapper_drift_summary['wrapper_drift_seconds']} s"
            if _wrapper_drift_ran else f"Wrapper-route survey NOT MEASURED: {wrapper_drift_summary['wrapper_drift_reason']}"
        )

        # 2. Bootstrap fixture bag (sandbox-credentials + flow-values)
        bag = await _bootstrap_fixtures(target, dev_jwt)
        if bag is None:
            return self._summarize(results, False, "fixture bootstrap failed")

        _central_posture = await _read_posture(target.a_registry_container)
        _central_posture_notes = _posture_complaints(_central_posture)
        logger.info("central posture: %s" % _central_posture)
        _central_switches = await _read_target_switches(target.a_registry_container)
        bag.flow_values.update(_central_switches)
        logger.info("central switches: %s; switched off here: %s"
                    % (_central_switches["target_switches"], _central_switches["target_switches_off"]))
        for _c in _central_posture_notes:
            logger.warning("central posture: %s" % _c)

        await _mcp_record(phase="Phase 3 · creating fixture entities")
        # 2b. PHASE 3 — create entities, capture IDs into bag.flow_values
        # PHASE 4 — record every setup-phase create as a ContractOutcome
        setup_outcomes: Dict[str, ContractOutcome] = {}
        phase3_summary = await _phase3_setup_entities(target, bag, setup_outcomes)
        # ⚠ THIS LINE IS THE SETUP'S OWN REPORT, NOT A CREATION COUNT. It used to
        # read "created N of M entities", and it was overstating: several steps
        # record a REASON in the summary when they fail (the contract fixture
        # writes "NONE (no contracts on this frame)"), and only the literal
        # 'FAILED' was filtered — so a failed fixture was counted as a created
        # one. A count that includes its own failures is the class this project
        # keeps finding; the authoritative measure is the DEBT block below,
        # which asks the thing that actually gates a contract.
        logger.info(f"Phase-3 setup, as each step reported itself: "
                    f"{[k for k, v in phase3_summary.items() if v != 'FAILED']}")
        logger.info(f"Setup outcomes recorded: {len(setup_outcomes)}")

        # ── §EVTYPES4 2026-09-06 — name the fixture debt ONCE, before the sweep ──
        # What gates a contract is `bag.flow_values`, so ask THAT, and ask it the
        # way the sweep will: resolve every contract's arguments and collect what
        # stays `${unresolved}`. Previously this cost was paid as N scattered
        # [MCP-Skip] warnings with no total and no cause, which is why 7 skips sat
        # unread — a pass FLOOR cannot see a test that vanishes into "skipped".
        # ⚠ IT MEASURES AT PHASE-3 TIME, WHICH IS EARLIER THAN THE SWEEP. Some
        # fixtures are published later by the LIFECYCLES (application_id by
        # lifecycle_admin_light_reads, payment_token by the a2a authorize step),
        # so a name here is "not available yet", not necessarily "never". Measured
        # 2026-09-06: this block named 3, and the run ended with 1 real skip. Read
        # it as the phase-3 debt it is, and confirm against the run's own skips.
        _debt: Dict[str, List[str]] = {}
        for _tool, _c in MCP_CONTRACTS.items():
            if _c.skip_reason or not _c.arguments:
                continue
            for _f in unresolved_fixtures(resolve_args(_c.arguments, bag)):
                _debt.setdefault(_f, []).append(_tool)
        if _debt:
            logger.warning(
                "Phase-3 fixture DEBT: %d fixture(s) unresolved, blocking %d contract(s): %s",
                len(_debt), sum(len(v) for v in _debt.values()),
                {k: len(v) for k, v in sorted(_debt.items())})
            for _f, _tools in sorted(_debt.items()):
                logger.warning(
                    "  ${%s} blocks %s | the setup step said: %s", _f,
                    ", ".join(sorted(t.replace("theprotocol_", "") for t in _tools)),
                    str(phase3_summary.get(_f, "(this fixture is not attempted by the setup at all)"))[:160])
        else:
            logger.info("Phase-3 fixture debt: none — every contract fixture resolved")

        # 2c. PHASE 4 — run lifecycle orchestrators
        # Each lifecycle is an ephemeral create-test-cleanup sequence whose
        # per-tool outcomes get merged with the sweep results.
        lifecycle_outcomes: Dict[str, Dict[str, Any]] = {}

        # §MCPTEST-FE3 2026-08-07 — re-mint the developer credential on 401.
        #
        # MEASURED DEFECT: `login_admin` runs ONCE at Phase 0 and `dev_jwt` is
        # reused for the whole 742-tool sweep. Anything that invalidates the
        # session mid-run (a credential-rotating tool, a password change, an
        # expiry) turns every later developer-scoped tool into a false failure.
        # In the 2026-08-07 clean run, 68 of 79 hard failures were ONE
        # contiguous 401 cascade starting at getMyDeveloperProfile — endpoints
        # that return 200 on their own. That is a property of our token being
        # reported as a property of the platform, the same class as the API
        # suite's "requires agent JWT" stamp.
        #
        # So: a 401 is never trusted until it has survived a freshly minted
        # credential. Bounded to one re-login per call, and only when the call
        # actually used `dev_jwt` (agent/sentinel tokens are left alone).
        _relogin_lock = asyncio.Lock()

        async def _rpc(tool: str, args: dict, jwt: str = "", timeout: int = 20):
            nonlocal dev_jwt
            ok, parsed, code = await _mcp_rpc_call(
                target, tool, args, jwt=jwt, timeout=timeout)
            # §MCPTEST30: only a 401 about the CREDENTIAL earns a re-login; a tool's own refusal (a wrong password in
            # a refusal probe) is its answer, and re-minting doubled the probe and logged a stale JWT that was not one.
            if code == "401" and jwt and jwt == dev_jwt and _is_credential_401(parsed):
                async with _relogin_lock:
                    # A concurrent call may already have refreshed it.
                    if jwt == dev_jwt:
                        ok_re, fresh, _det = await login_admin(target, "a")
                        if ok_re and fresh:
                            logger.warning(
                                "[MCP-Relogin] 401 on %s with a stale dev JWT — "
                                "re-minted and retrying once", tool)
                            dev_jwt = fresh
                if dev_jwt and dev_jwt != jwt:
                    ok, parsed, code = await _mcp_rpc_call(
                        target, tool, args, jwt=dev_jwt, timeout=timeout)
            return ok, parsed, code

        # Phase C bug-finder (2026-05-26): wire the event-emission verifier
        # into the bag so lifecycles can pass `event_verifier=bag.event_verifier`
        # + `expect_events=["X","Y"]` to _exec_step. Captures a per-call
        # `pre_call_iso` window (events newer than that mark are considered
        # caused by this step).
        async def _event_verifier(event_types: List[str], tool_name: str,
                                    pre_call_iso: Optional[str] = None
                                    ) -> Tuple[bool, Optional[str]]:
            since_iso = pre_call_iso or (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
            try:
                since_dt = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
                if since_dt.tzinfo is None:
                    since_dt = since_dt.replace(tzinfo=timezone.utc)
            except Exception:
                since_dt = datetime.now(timezone.utc) - timedelta(seconds=60)
            for evt in event_types:
                # ES projection can lag (30-60s under sweep load — see the standalone
                # verifier's feedback_es_verifier_lag_under_sweep note). The original
                # single-shot query produced false "silent NO-OP" findings (e.g.
                # settlePayment's TokensTransferred landing just outside the window).
                # Retry with backoff before declaring a miss, mirroring _verify_post_call_assertions.
                found = False
                for attempt in range(8):
                    events = await _query_recent_events(target, evt, limit=25, jwt=dev_jwt)
                    recent = []
                    for e in events:
                        ts = e.get("timestamp")
                        if not isinstance(ts, str):
                            continue
                        try:
                            edt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            if edt.tzinfo is None:
                                edt = edt.replace(tzinfo=timezone.utc)
                            if edt >= since_dt:
                                recent.append(e)
                        except Exception:
                            continue
                    if recent:
                        found = True
                        break
                    if attempt < 7:
                        await asyncio.sleep(3.0)
                if not found:
                    return False, (
                        f"missing event: '{evt}' not emitted in EventStore "
                        f"after {tool_name} within ~24s/8 retries (silent NO-OP class)"
                    )
            return True, None

        bag.event_verifier = _event_verifier  # type: ignore[assignment]
        # §MCPTEST30: the protocol conformance lifecycle needs any JSON-RPC method, and an account of its own
        bag.rpc_raw = functools.partial(_mcp_rpc_raw, target)  # type: ignore[assignment]
        bag.mint_throwaway = functools.partial(_mint_throwaway_developer, target.a_registry_container)  # type: ignore[assignment]
        # §MCPTEST30 V0528: REST from inside the target, for what no MCP tool takes (a key's scopes)
        bag.http_in_target = functools.partial(_http_in_target, target.a_registry_container)  # type: ignore[assignment]
        # §MEMBERSHIP (V0551): a lifecycle whose steps span both bridges (the commons season: an admin opens, closes and
        # cancels it, an agent submits to it) calls the admin bridge through the bag; its admin rows wait in
        # bag.admin_lifecycle_rows and join the admin sweep's lifecycle rows in PHASE 6, where admin tools are judged.

        async def _rpc_admin_early(tool: str, args: dict, jwt: str = "", timeout: int = 20):
            return await _mcp_rpc_call_admin(target, tool, args, jwt=(jwt or dev_jwt), timeout=timeout)
        bag.rpc_admin = _rpc_admin_early  # type: ignore[assignment]
        bag.admin_lifecycle_rows = {}  # type: ignore[assignment]

        _lc_total = len(LIFECYCLES)
        # Parallelize the orchestrators (bounded). Each lifecycle is an
        # independent create->verify->delete unit; they share `bag` (read) and
        # write distinct keys into `lifecycle_outcomes` (per-key atomic in
        # asyncio). Server-latency-bound + event-verify waits overlap under
        # concurrency — this phase was ~7.4 min sequential.
        async def _run_one_lifecycle(lc):
            try:
                await lc["runner"](_rpc, _parse_rpc_result, bag, lifecycle_outcomes)
            except Exception as e:
                logger.warning(f"lifecycle {lc.get('name')} raised: {e!r}")
            return None
        async def _lc_progress(done, total):
            if done % 6 == 0 or done == total:
                await _mcp_record(
                    phase="Phase 4 · lifecycle orchestrators",
                    completed=done, total=total,
                )
        # §MCPTEST30: the TEG's and the EventStore's view of the sentinel before the lifecycle phase (ledger_agreement)
        from agentvault_registry.api_tests.contracts import ledger_agreement as _ledger
        _ledger0 = await _ledger.settled_snapshot(_rpc, _parse_rpc_result, bag)   # V0545: the store caught up first
        await _bounded_sweep(
            LIFECYCLES, _run_one_lifecycle,
            concurrency=_lifecycle_concurrency(), on_progress=_lc_progress,
        )
        logger.info(f"Lifecycle outcomes recorded: {len(lifecycle_outcomes)} (across {lifecycle_count()} orchestrators)")
        # the split itself is logged after the sweep, where the counters are full

        # §MCPTEST-MCP4 2026-08-08 — UNCONDITIONAL credential re-mint at the one
        # choke point that every later phase depends on.
        #
        # WHY HERE and not next to the offending tool: the lifecycle phase runs
        # `theprotocol_logoutSession`, which takes NO parameters and therefore
        # revokes THE CALLER'S token (measured: the runner's
        # `developers.token_version` ticks by exactly 1 per sweep, and its JWT
        # then 401s). My first heal was placed beside the generic RPC call in the
        # main sweep — but tools already exercised here hit
        #   `if tool_name in lifecycle_outcomes: ... return _out`
        # ~90 lines EARLIER, so that heal was unreachable for precisely the tool
        # it targeted. It logged 0 times across a full run while the damage was
        # already done. (Same unreachable-code shape as the API tester's
        # category-module early return — §MCPTEST-FE2.)
        #
        # Re-minting unconditionally here is cheap (one login), needs no
        # knowledge of WHICH lifecycle tool revoked what, and cannot be bypassed
        # by an early return, because it sits after the whole phase rather than
        # inside any per-tool branch.
        _ok_rm, _fresh_rm, _det_rm = await login_admin(target, "a")
        if _ok_rm and _fresh_rm:
            if _fresh_rm != bag.developer_jwt:
                logger.warning(
                    "[MCP-PhaseHeal] developer JWT changed after the lifecycle "
                    "phase — a lifecycle tool revoked the runner's own "
                    "credential (expected: logoutSession). Re-minted before the "
                    "main sweep.",
                )
            bag.developer_jwt = _fresh_rm
        else:
            logger.error(
                "[MCP-PhaseHeal] could not re-mint the developer JWT after the "
                "lifecycle phase (%s) — the main sweep is about to run on a "
                "possibly-dead credential; expect a 401 cascade.",
                str(_det_rm)[:160],
            )
        # §MCPTEST30: ... and after it, on the re-minted credential and before the main sweep moves the sentinel again
        from agentvault_registry.api_tests.contracts.mcp_lifecycles import _make_outcome as _lc_make_outcome
        await _ledger.close(_rpc, _parse_rpc_result, bag, _ledger0, lifecycle_outcomes, _lc_make_outcome)

        # PHASE 5 SPRINT 5.4 — Tier-set consistency static check.
        # Reads server.py + tools_*.py via AST; fast, no API calls. Returns
        # list of {tool_name, issue} dicts. We promote each finding to a
        # ContractOutcome that overrides the matching tool's healthy=False,
        # surfacing as a BUG-FIND failure in the sweep summary.
        tier_consistency_issues = []
        try:
            tier_consistency_issues = run_tier_consistency_check()
        except Exception as e:
            logger.warning(f"tier-consistency check raised: {e!r}")
        logger.info(f"Tier-consistency issues: {len(tier_consistency_issues)}")
        for issue in tier_consistency_issues:
            tname = issue.get("tool_name", "__meta__")
            # Overwrite (or create) the lifecycle_outcomes entry for the
            # offending tool so the sweep loop ingests the failure.
            lifecycle_outcomes[tname] = {
                "tool_name": tname,
                "contract_tier": "tier_consistency",
                "healthy": False,
                "status_code": 0,
                "elapsed_ms": 0,
                "skip_reason": None,
                "fail_reason": issue.get("issue", "tier-consistency drift"),
                "has_explicit_contract": True,
                "args_used": {},
                "result_excerpt": {
                    "wrapper_fn": issue.get("wrapper_fn", ""),
                    "actual_tier": issue.get("actual_tier", ""),
                    "expected_tier": issue.get("expected_tier", ""),
                },
            }

        # 3. tools/list — get the live catalog (distinct JSON-RPC method)
        ok_list, tools, code = await _mcp_rpc_list_tools(target, jwt=dev_jwt)
        if not ok_list:
            return self._summarize(results, False, f"tools/list failed: {code}")
        logger.info(f"Live tools/list count: {len(tools)}")
        _listing_words_found: Dict[str, Any] = {"public": _listing_words(tools)}   # §MCPTEST30 W6

        # 4. Sweep — one contract per tool
        outcomes: List[ContractOutcome] = []
        _mcp_tool_total = len(tools)
        _mcp_tool_done = 0
        await _mcp_record(
            phase="Phase 5 · public bridge sweep",
            completed=0, total=_mcp_tool_total,
        )

        # ── §EVTYPES7 2026-09-06 — WHAT DECIDED EACH ROW ──────────────────
        # `explicit_contracts: 726` counts contracts that EXIST, not contracts
        # that RAN. A row is decided by whichever of three things reaches it
        # first: a lifecycle orchestrator, a phase-3 setup create, or the tool's
        # own contract — and the first two take priority, so a tool exercised by
        # a lifecycle never evaluates its contract at all (deliberate, opt-out
        # via `override_coverage_fan`). Nothing said how the split fell, which
        # makes the headline read stronger than it is: this is the same class as
        # "created 27 of 29 entities" counting a step's failure as a creation.
        # Counted at the DECISION, so the three add up to the sweep's row count.
        _decided_by = {"lifecycle": 0, "setup": 0, "contract": 0}

        async def _sweep_one_public(tool):
            _out: List[ContractOutcome] = []
            tool_name = tool.get("name") if isinstance(tool, dict) else None
            if not tool_name:
                return _out
            # PHASE 4: setup-phase or lifecycle-phase outcomes take priority
            # over the per-tool contract sweep. If a lifecycle exercised this
            # tool, use its outcome directly; same for setup creates.
            # pass73.3.19 Option-A: EXCEPT when the explicit contract opted into
            # `override_coverage_fan` — then the coverage-fan probe is NOT
            # authoritative; fall through to run the real success-path contract
            # so the displayed status reflects 200, not the fan's any-status 4xx.
            if tool_name in lifecycle_outcomes and not get_contract(tool_name).override_coverage_fan:
                _decided_by["lifecycle"] += 1
                d = _fan_row_verdict(lifecycle_outcomes[tool_name], tool_name)
                _out.append(ContractOutcome(
                    tool_name=d["tool_name"],
                    contract_tier=d["contract_tier"],
                    healthy=d["healthy"],
                    status_code=d["status_code"],
                    elapsed_ms=d["elapsed_ms"],
                    skip_reason=d["skip_reason"],
                    fail_reason=d["fail_reason"],
                    # §FANCLAIM: 261 tools reached only by a lifecycle hold NO
                    # contract at all (hand-curated or autogen) and every one of
                    # them reported an explicit one, which is the number a reader
                    # uses to judge how much of the pass count was really tested.
                    has_explicit_contract=(tool_name in MCP_CONTRACTS),
                    args_used=d.get("args_used") or {},
                    result_excerpt=d.get("result_excerpt") or {},
                ))
                return _out
            # §EVTYPES8: `override_coverage_fan` was honoured against the
            # lifecycle branch above and IGNORED here, so setting it on any of
            # the ~30 setup-path tools did exactly nothing — silently, which is
            # the failure mode of every flag that can never fire. The two
            # branches now ask the same question. (Nothing relied on the old
            # behaviour: no contract carrying the flag was a setup tool when
            # this was written, so the flip changes no row by itself.)
            if tool_name in setup_outcomes and not get_contract(tool_name).override_coverage_fan:
                _decided_by["setup"] += 1
                _out.append(setup_outcomes[tool_name])
                return _out

            _decided_by["contract"] += 1
            contract = get_contract(tool_name)
            has_explicit = (tool_name in MCP_CONTRACTS) or (tool_name in _autogen_keys())

            # PHASE 1 SMART DEFAULT: tools without an explicit contract that
            # advertise required params are auto-skipped with a clear reason.
            # This prevents the default contract from spamming "missing arg"
            # failures and produces a clean map of "tools needing contracts".
            if not has_explicit:
                input_schema = tool.get("inputSchema") if isinstance(tool, dict) else None
                required_params = (input_schema or {}).get("required") if isinstance(input_schema, dict) else None
                if required_params:
                    contract = McpContract(
                        tier="1",
                        skip_reason=f"default contract: tool has required params {required_params!r} — add explicit contract",
                    )

            args = resolve_args(contract.arguments, bag)

            # PHASE 3 SMART DEFAULT: if any args still contain unresolved
            # `${name}` after resolve, the phase-3 setup didn't create that
            # fixture (entity creation failed OR contract references a fixture
            # the setup doesn't manage). Skip with clear reason.
            unresolved = unresolved_fixtures(args)
            if unresolved:
                contract = McpContract(
                    tier=contract.tier,
                    skip_reason=f"phase-3 fixture missing: {unresolved!r} — entity setup didn't expose this ID",
                )

            # Choose JWT by tier. The MCP server's outer auth gate requires
            # SOME bearer for ALL paths (returns 401 otherwise). Use dev_jwt
            # as the baseline; agent JWT is passed inline via `arguments.agent_jwt`
            # for Tier 2 tools (the dispatcher pops it and overrides the header).
            if contract.tier == "2":
                jwt_for_call = bag.developer_jwt  # outer gate
                args.setdefault("agent_jwt", bag.sentinel_jwt)  # inline tier-2 token
            elif contract.tier == "0" and tool_name == "theprotocol_getAgentToken":
                jwt_for_call = bag.developer_jwt  # outer gate; tool returns a fresh agent JWT
            else:
                # Tier 0 (utility), Tier 1 (public reads), Tier 3 (dev), admin
                jwt_for_call = bag.developer_jwt

            t0 = time.time()
            skip = bool(contract.skip_reason)
            if skip:
                # Skip is NOT healthy — surfaces as its own outcome category.
                # 2026-05-26 strict mode: never roll skips into pass rate.
                outcome = ContractOutcome(
                    tool_name=tool_name,
                    contract_tier=contract.tier,
                    healthy=False,
                    status_code=0,
                    elapsed_ms=0,
                    skip_reason=contract.skip_reason,
                    fail_reason=None,
                    has_explicit_contract=True,
                    args_used={},
                    result_excerpt={},
                )
            else:
                # Capture pre-call timestamp for event/audit-row verification.
                pre_call_iso = datetime.now(timezone.utc).isoformat()
                rpc_ok, rpc_body, rpc_code = await _mcp_rpc_call(
                    target, tool_name, args, jwt=jwt_for_call, timeout=20,
                )
                # §MCPTEST-MCP3 2026-08-08 — THE ACTUAL CAUSE of the 401 cascade.
                #
                # `theprotocol_logoutSession` takes NO parameters: it acts on
                # WHOEVER IS CALLING. The sweep calls it with its own developer
                # JWT, the handler bumps `developers.token_version`, and that
                # revokes every live token for the runner — including the one
                # the remaining ~200 tools are about to use. Measured directly:
                #   dev1 token_version 15 -> 16, and the caller's own JWT
                #   immediately answers 401 on /developers/me.
                # No `developer_id` guard can prevent this, because the tool
                # never takes an id.
                #
                # Heal in place rather than skipping: the tool still gets
                # exercised for real (it is a genuine part of the surface), and
                # the credential is re-minted on the spot so the blast radius is
                # exactly one call instead of every call that follows.
                if tool_name in _CALLER_SCOPED_SESSION_KILLERS:
                    _ok_h, _fresh_h, _det_h = await login_admin(target, "a")
                    if _ok_h and _fresh_h:
                        bag.developer_jwt = _fresh_h
                        logger.info(
                            "[MCP-SessionHeal] %s revoked the runner's own token "
                            "(by design) — re-minted immediately", tool_name,
                        )
                    else:
                        logger.error(
                            "[MCP-SessionHeal] %s revoked the runner's own token "
                            "and re-login FAILED (%s) — every later "
                            "developer-authed tool will 401",
                            tool_name, str(_det_h)[:160],
                        )
                # §MCPTEST-FE3 2026-08-07 — a 401 is never trusted until it has
                # survived a FRESHLY minted credential.
                #
                # MEASURED: `bag.developer_jwt` is minted once in Phase 0 and
                # reused across all 742 tools. When it dies mid-sweep, every
                # later tool fails as a false negative — endpoints that return
                # 200 on their own. That is a property of OUR token reported as
                # a property of the endpoint, the same class as the API suite's
                # "requires agent JWT" stamp.
                #
                # CORRECTION (§MCPTEST-MCP2 2026-08-08): an earlier revision of
                # this comment blamed token STALENESS. That was wrong and the
                # data says so — the sandbox developer JWT carries a 90-minute
                # exp against a ~15-minute sweep, so it cannot expire mid-run.
                # The token was being REVOKED, by us: see _SELF_HARMING_DEV_TOOLS
                # above. This retry stays as a safety net, but it is no longer
                # the fix — and it could never have been, because a suspended
                # developer cannot mint a replacement token.
                #
                # Bounded to one re-login per call, and only when the call
                # actually used the developer JWT (sentinel/agent tokens and
                # the deliberate wrong-tier probes are left alone, or the
                # auth-matrix would start passing vacuously).
                if (
                    rpc_code == "401"
                    and jwt_for_call
                    and jwt_for_call == bag.developer_jwt
                ):
                    _ok_re, _fresh, _det = await login_admin(target, "a")
                    if _ok_re and _fresh and _fresh != bag.developer_jwt:
                        logger.warning(
                            "[MCP-Relogin] 401 on %s with a stale developer JWT "
                            "— re-minted and retrying once", tool_name,
                        )
                        bag.developer_jwt = _fresh
                        jwt_for_call = _fresh
                        rpc_ok, rpc_body, rpc_code = await _mcp_rpc_call(
                            target, tool_name, args, jwt=_fresh, timeout=20,
                        )
                    elif not _ok_re:
                        # §MCPTEST-MCP2: THE SILENT PATH. A re-login that FAILS
                        # used to fall through logging nothing, so a sweep that
                        # had revoked its own credential looked identical to one
                        # that never needed a retry ("fired 0 times"). A dead
                        # runner credential is the single most consequential
                        # thing that can happen mid-sweep — say so, loudly.
                        logger.error(
                            "[MCP-Relogin] 401 on %s AND re-login FAILED (%s) — "
                            "the runner's own credential is dead; every later "
                            "developer-authed tool will 401. Check whether the "
                            "sweep suspended/mutated its own developer.",
                            tool_name, str(_det)[:160],
                        )
                # §MCPTEST-MCP10 — transport-timeout retry BEFORE classification.
                rpc_ok, rpc_body, rpc_code = await _retry_transport_timeout(
                    _mcp_rpc_call, target, tool_name, args, jwt_for_call,
                    rpc_ok, rpc_body, rpc_code,
                )
                ok, fail = _evaluate_contract(
                    tool, contract, rpc_ok, rpc_code, rpc_body, bag,
                    has_explicit_contract=has_explicit,
                )
                # Phase C bug-finder: only run event/audit checks if basic
                # contract eval passed. Otherwise the basic failure is the
                # better signal.
                if ok:
                    post_ok, post_fail = await _verify_post_call_assertions(
                        target, contract, tool_name, pre_call_iso,
                        jwt=dev_jwt, bag=bag,
                    )
                    if not post_ok:
                        ok = False
                        fail = post_fail
                elapsed_ms = int((time.time() - t0) * 1000)
                inner = _parse_rpc_result(rpc_body)

                # Strict-mode tier-drift detection (2026-05-26 handover):
                # If the server demands a DIFFERENT auth tier than the contract
                # claims, surface it as `tier_drift` (still healthy=False) so
                # the operator can fix server.py TIER_N_TOOLS sets OR the
                # contract's tier classification. Was previously smart-skipped
                # to "ok=True" which hid real drift between MCP wrapper tier
                # sets and the registry's auth requirements. The whole point
                # of this tester is to catch drift — re-classify, don't hide.
                tier_drift = False
                if not ok and isinstance(rpc_body, dict):
                    err_obj = rpc_body.get("error")
                    err_msg = (err_obj or {}).get("message", "") if isinstance(err_obj, dict) else ""
                    if isinstance(err_msg, str):
                        actual_tier = None
                        if "requires agent authentication" in err_msg:
                            actual_tier = "2"
                        elif "requires developer authentication" in err_msg:
                            actual_tier = "3"
                        elif "requires admin" in err_msg or "admin developer" in err_msg:
                            actual_tier = "admin"
                        if actual_tier and actual_tier != contract.tier:
                            tier_drift = True
                            fail = (
                                f"tier drift: contract='tier-{contract.tier}' "
                                f"got='requires {actual_tier} auth'"
                            )

                contract_gap = (
                    not ok
                    and not has_explicit
                    and fail is not None
                    and fail.startswith("contract gap:")
                )

                outcome = ContractOutcome(
                    tool_name=tool_name,
                    contract_tier=contract.tier,
                    healthy=ok,
                    status_code=int(rpc_code) if rpc_code.isdigit() else 0,
                    elapsed_ms=elapsed_ms,
                    skip_reason=None,
                    fail_reason=fail,
                    has_explicit_contract=has_explicit,
                    args_used=args,
                    result_excerpt=result_excerpt(inner),
                    tier_drift=tier_drift,
                    contract_gap=contract_gap,
                )
            _out.append(outcome)
            return _out

        # ── DRIVER: bounded-concurrent public bridge sweep ──────────────
        async def _pub_progress(done, total):
            if done % 12 == 0 or done == total:
                await _mcp_record(
                    phase="Phase 5 · public bridge sweep",
                    completed=done, total=total,
                )
        for _buck in await _bounded_sweep(
            tools, _sweep_one_public,
            concurrency=_sweep_concurrency(), on_progress=_pub_progress,
        ):
            outcomes.extend(_buck)

        # §MCPTEST30 (2026-10-01): a lifecycle row that names no tool (the protocol conformance checks, the owner-scoping
        # sweep) is a row of its own. The sweep above walks tools/list and consults lifecycle rows BY TOOL NAME, so these
        # would otherwise be dropped without a word.
        # §MCPTEST30 (V0636): and a real success a lifecycle measured where the tool's contract pins a refusal
        # (kept_lifecycle_rows: `earned: <tool>`).
        _listed_names = {t.get("name") for t in tools if isinstance(t, dict)}
        for _lname, _d in kept_lifecycle_rows(lifecycle_outcomes, _listed_names, {o.tool_name for o in outcomes},
                                              lambda n: bool(get_contract(n).override_coverage_fan)):
            outcomes.append(ContractOutcome(
                tool_name=_lname, contract_tier=_d.get("contract_tier") or "protocol",
                healthy=bool(_d.get("healthy")), status_code=int(_d.get("status_code") or 0),
                elapsed_ms=int(_d.get("elapsed_ms") or 0), skip_reason=_d.get("skip_reason"),
                fail_reason=_d.get("fail_reason"), has_explicit_contract=True,
                args_used={}, result_excerpt=_d.get("result_excerpt") or {},
            ))

        # §EVTYPES7 — say what decided the rows, not just how many passed.
        _dec_total = sum(_decided_by.values()) or 1
        logger.info(
            "public sweep decided by: contract %d (%.0f%%) · lifecycle %d · setup %d "
            "— only the first evaluated THIS tool's own contract; the other two take "
            "priority by design (opt out per tool with override_coverage_fan)",
            _decided_by["contract"], 100.0 * _decided_by["contract"] / _dec_total,
            _decided_by["lifecycle"], _decided_by["setup"])

        # ========================================================
        # PHASE 5b — WRONG-TIER AUTH MATRIX (Gap-1, Phase F)
        # ========================================================
        # For each tool with declared `expect_tier_rejections`, send the
        # wrong-tier credential and assert 401/403. Catches privilege-
        # escalation regressions ("removed Security(get_current_admin) by
        # accident"). Decoupled from per-tool success-path so a tool can
        # pass shape contract AND fail auth matrix independently.
        from agentvault_registry.api_tests.contracts.mcp_contracts import (
            auto_tier_rejections as _auto_tier_rejections,
        )

        auth_matrix_total = 0
        auth_matrix_violations = 0
        # §MCPTEST-MCP10 — probes we could not MEASURE, kept apart from probes
        # that were measured and passed. A probe with no HTTP answer proves
        # nothing about the gate in either direction.
        auth_matrix_inconclusive = 0
        # §MCPSWEEP — probes refused before any tier gate ran (see _wrong_tier_refused_before_gate): not measurements
        auth_matrix_before_gate = 0
        auth_matrix_before_gate_tools: List[str] = []
        auth_matrix_failed_tools: List[str] = []
        # §EVTYPES8 — tools deliberately NOT gate-probed (see
        # `never_probe_wrong_tier` on McpContract). Reported, never silent: a
        # coverage gap you can read beats one you have to infer from a total.
        auth_matrix_not_probed: List[str] = []
        # §MCPTEST30 (V0541): the tools a wrong-tier credential reached the gate of. A public tool has no wrong tier and
        # is never probed, so "rejected every wrong-tier credential" is a claim about these tools only.
        auth_matrix_probed: List[str] = []

        # §pass73 task B (2026-05-26): non-admin developer fixture is now seeded
        # from `developer@test.sandbox` (is_admin=False per test_seed.py
        # TEST_DEVELOPER). `bag.developer_jwt_nonadmin` is the minted JWT;
        # falls back to empty string when the login fails (logged in bootstrap).
        # The auth-matrix probe degrades gracefully on empty: it counts as
        # `bad_jwt=""` which the rejection logic treats as "absent token" —
        # same outcome as before, just no longer a silent no-op when the JWT
        # is present.
        _bad_jwts: Dict[str, str] = {
            "empty":                  "",
            "agent_jwt":              bag.sentinel_jwt or "",
            "developer_jwt":          bag.developer_jwt or "",
            "developer_jwt_nonadmin": bag.developer_jwt_nonadmin or "",
            "developer_jwt_nonadmin2": bag.developer_jwt_nonadmin2 or "",
        }

        await _mcp_record(
            phase="Phase 5b · wrong-tier auth matrix",
            completed=0, total=len(tools),
        )

        async def _sweep_one_authmatrix(tool):
            # Augmented-assigned enclosing counters need `nonlocal`. Each `+= 1`
            # is atomic between awaits in single-threaded asyncio, so concurrent
            # workers don't lose updates; failed_tools.append is atomic too.
            nonlocal auth_matrix_total, auth_matrix_violations, auth_matrix_inconclusive, auth_matrix_before_gate
            tool_name = tool.get("name") if isinstance(tool, dict) else None
            if not tool_name:
                return None
            contract = get_contract(tool_name)
            # §EVTYPES8: `skip_reason` stops the SWEEP and was never read here, so
            # a contract saying "not probed — tears down real containers" was
            # probed anyway. The probe is safe only while the gate it tests is
            # shut; where an open gate would cost infrastructure or recursion
            # rather than a refusal, the tool opts out explicitly and the gap is
            # reported below instead of being taken on trust.
            if contract.never_probe_wrong_tier:
                auth_matrix_not_probed.append(tool_name)
                return None
            rejections = list(contract.expect_tier_rejections) or _auto_tier_rejections(contract.tier)
            if not rejections:
                return None
            for bad_tier_key in rejections:
                bad_jwt = _bad_jwts.get(bad_tier_key, "")
                # §pass73 task B (2026-05-26): non-admin developer fixture
                # now real (`developer@test.sandbox`, is_admin=False). The
                # silent-skip for `developer_jwt_nonadmin × admin tier` is
                # gone — probes run end-to-end and must produce 401/403 or
                # the contract is broken.
                #
                # Degradation: if `bag.developer_jwt_nonadmin` is empty (login
                # failed at boot — logged in _bootstrap_fixtures), this branch
                # falls through to `bad_jwt=""` which the rejection logic
                # already treats as the "empty" case. No false violations.
                auth_matrix_total += 1
                # Minimal args — auth gate fires before arg validation
                rpc_ok, body, code = await _mcp_rpc_call(
                    target, tool_name, {}, jwt=bad_jwt, timeout=10
                )
                status = int(code) if code.isdigit() else 0

                # Did the MCP server reject this wrong-tier call?
                # Cases that count as REJECTION:
                #   1. HTTP 401/403 (explicit auth refusal)
                #   2. JSON-RPC top-level error (`{"error": {...}}`)
                #   3. Wrapper-error envelope in result.content[0].text
                #      containing auth/permission keywords OR plain "Error:"
                #      (the dispatcher formats wrapper {error: "X"} as
                #      content text "Error: X" — F.1 false-positive fix)
                #   4. Missing-arg wrapper errors are ALSO rejections —
                #      the tool didn't actually perform the operation.
                rejected = _wrong_tier_rejected(status, body)
                # §MCPTEST-MCP10 — AN UNREACHABLE PROBE IS NOT AN ACCEPT.
                # `rejected` starts False and only flips on a 401/403 or an error
                # marker, so a probe whose transport never returned an HTTP answer
                # fell through and was scored as a privilege-escalation violation.
                # MEASURED: agentHeartbeat / depositReputationBond /
                # getMyReputationBondStatus were reported as `(empty→0)` accepts,
                # and all three answer a clean 401 to a credential-less call —
                # the gate was never open. Status "0" is our transport failing,
                # the same class as the timeout misclassification and the audit
                # lookup that returned [] for "the query died".
                # §ADMINMATRIX 2026-09-06 — 429 joins the unmeasured set for the same
                # reason: the limiter's answer says nothing about the gate. The public
                # surface has not thrown one, but a matrix that would call a throttle a
                # privilege escalation is one busy afternoon away from doing so.
                _measured = (str(status).isdigit() and 100 <= int(status) <= 599
                             and int(status) != 429)
                if not _measured:
                    auth_matrix_inconclusive += 1
                    auth_matrix_total -= 1        # never measured ⇒ not a denominator
                    logger.warning(
                        "[MCP-AuthMatrix] %s(%s): probe returned no HTTP answer "
                        "(status=%r) — INCONCLUSIVE, not counted as an accept",
                        tool_name, bad_tier_key, status,
                    )
                elif _wrong_tier_refused_before_gate(body):
                    auth_matrix_before_gate += 1
                    auth_matrix_total -= 1        # the gate was never reached ⇒ not a denominator
                    auth_matrix_before_gate_tools.append(f"{tool_name}({bad_tier_key})")
                elif not rejected:
                    auth_matrix_violations += 1
                    auth_matrix_failed_tools.append(f"{tool_name}({bad_tier_key}→{status})")
                    auth_matrix_probed.append(tool_name)
                else:
                    auth_matrix_probed.append(tool_name)

        # ── DRIVER: bounded-concurrent wrong-tier auth matrix ───────────
        await _bounded_sweep(
            tools, _sweep_one_authmatrix, concurrency=_sweep_concurrency(),
        )

        await _mcp_record(
            phase="Phase 5b · wrong-tier auth matrix",
            completed=len(tools), total=len(tools),
        )
        if auth_matrix_not_probed:
            logger.warning(
                "[MCP-AuthMatrix] %d tool(s) NOT gate-probed by contract "
                "(never_probe_wrong_tier): %s", len(auth_matrix_not_probed),
                ", ".join(sorted(auth_matrix_not_probed)))
        logger.info(
            f"Auth matrix: {auth_matrix_total} probes, "
            f"{auth_matrix_violations} violations, {auth_matrix_inconclusive} inconclusive, "
            f"{auth_matrix_before_gate} refused before the gate (not measured)"
        )

        # ========================================================
        # PHASE 5c — CROSS-FRAME PARITY (Gap-4, Phase F)
        # ========================================================
        # Call ~25 public read-only tools against sandbox-A and sandbox-B
        # and diff response shapes. Tracks `cross_frame_drift` separately
        # from per-tool contract failures. Skipped if b_registry_container
        # is unreachable (e.g., sandbox-B down).
        cross_frame = {"probed": 0, "drifts": 0, "drift_details": []}
        try:
            await _mcp_record(
                phase="Phase 5c · cross-frame parity (A vs B)",
                completed=0, total=len(_CROSS_FRAME_PARITY_TOOLS),
            )
            cross_frame = await _cross_frame_parity_walk(target, dev_jwt)
            await _mcp_record(
                phase="Phase 5c · cross-frame parity (A vs B)",
                completed=cross_frame["probed"],
                total=len(_CROSS_FRAME_PARITY_TOOLS),
            )
            logger.info(
                f"Cross-frame parity: probed={cross_frame['probed']} "
                f"drifts={cross_frame['drifts']} "
                f"a_unreachable={cross_frame.get('a_unreachable', 0)} "
                f"b_unreachable={cross_frame.get('b_unreachable', 0)} "
                f"timed_out={cross_frame.get('timed_out', 0)} "
                f"skipped={cross_frame.get('skipped_count', 0)} "
                f"b_fused={cross_frame.get('b_fused', False)}"
            )
        except Exception as e:
            logger.warning(f"cross-frame parity walk raised (non-fatal): {e!r}")

        # ========================================================
        # PHASE 6 — ADMIN BRIDGE SWEEP (/mcp/admin/rpc, 302 tools)
        # ========================================================
        # Runs the parallel admin-bridge lifecycle batch, then walks the
        # admin bridge tools/list and merges outcomes into the main list.
        # Admin bridge enforces is_admin=True on tools/call — sandbox
        # commander has it.
        try:
            from agentvault_registry.api_tests.contracts.mcp_admin_lifecycles import (
                ADMIN_LIFECYCLES, admin_lifecycle_count,
            )
        except ImportError:
            ADMIN_LIFECYCLES = []
            admin_lifecycle_count = lambda: 0  # noqa: E731

        admin_lifecycle_outcomes: Dict[str, Dict[str, Any]] = {}
        # §MEMBERSHIP (V0551): the admin rows a public lifecycle recorded through bag.rpc_admin (the commons season)
        admin_lifecycle_outcomes.update(getattr(bag, "admin_lifecycle_rows", None) or {})

        # §MCPTEST-FE3 — same re-mint as _rpc; the admin bridge carries 317 of
        # the 742 tools, so a stale dev JWT here fails them all identically.
        async def _rpc_admin(tool: str, args: dict, jwt: str = "", timeout: int = 20):
            nonlocal dev_jwt
            ok, parsed, code = await _mcp_rpc_call_admin(
                target, tool, args, jwt=jwt, timeout=timeout)
            if code == "401" and jwt and jwt == dev_jwt:
                async with _relogin_lock:
                    if jwt == dev_jwt:
                        ok_re, fresh, _det = await login_admin(target, "a")
                        if ok_re and fresh:
                            logger.warning(
                                "[MCP-Relogin] 401 on admin %s with a stale dev "
                                "JWT — re-minted and retrying once", tool)
                            dev_jwt = fresh
                if dev_jwt and dev_jwt != jwt:
                    ok, parsed, code = await _mcp_rpc_call_admin(
                        target, tool, args, jwt=dev_jwt, timeout=timeout)
            return ok, parsed, code

        # Parallelize the 9 admin orchestrators (bounded) — this phase was the
        # single biggest sink (~15.5 min sequential): mostly slow server-bound
        # admin reads (getAdminDashboard ~2.5s each). Mostly read-only + write
        # distinct keys into admin_lifecycle_outcomes.
        async def _run_one_admin_lifecycle(lc):
            try:
                await lc["runner"](_rpc_admin, _parse_rpc_result, bag, admin_lifecycle_outcomes)
            except Exception as e:
                logger.warning(f"admin lifecycle {lc.get('name')} raised: {e!r}")
            return None
        await _bounded_sweep(
            ADMIN_LIFECYCLES, _run_one_admin_lifecycle,
            concurrency=_lifecycle_concurrency(),
        )
        logger.info(
            f"Admin lifecycle outcomes recorded: {len(admin_lifecycle_outcomes)} "
            f"(across {admin_lifecycle_count()} orchestrators)"
        )

        # Walk admin bridge tools/list
        ok_admin_list, admin_tools, admin_code = await _mcp_rpc_list_tools_admin(target, jwt=dev_jwt)
        if ok_admin_list:
            logger.info(f"Admin bridge tools/list count: {len(admin_tools)}")
            _listing_words_found["admin"] = _listing_words(admin_tools)   # §MCPTEST30 W6
        else:
            logger.warning(f"Admin bridge tools/list failed: {admin_code}")
            admin_tools = []

        # Apply admin contracts: lifecycle outcomes take priority, then a
        # default-call against the admin bridge with empty args. The admin
        # bridge wrapper will return its own validation error for tools
        # that need params — those land as wrapper-error outcomes that
        # still count as exercised (not a wrapper bug, just a path test).
        async def _sweep_one_admin(tool):
            _out: List[ContractOutcome] = []
            tool_name = tool.get("name") if isinstance(tool, dict) else None
            if not tool_name:
                return _out
            # pass73.3.19 Option-A: explicit `override_coverage_fan` contracts
            # are authoritative over the admin coverage-fan — fall through to
            # the real success-path call below instead of the fan's any-status row.
            if tool_name in admin_lifecycle_outcomes and not get_contract(tool_name).override_coverage_fan:
                d = _fan_row_verdict(admin_lifecycle_outcomes[tool_name], tool_name)
                _out.append(ContractOutcome(
                    tool_name=d["tool_name"],
                    contract_tier="admin-bridge",
                    healthy=d["healthy"],
                    status_code=d["status_code"],
                    elapsed_ms=d["elapsed_ms"],
                    skip_reason=d["skip_reason"],
                    fail_reason=d["fail_reason"],
                    has_explicit_contract=(tool_name in MCP_CONTRACTS),   # §FANCLAIM
                    args_used=d.get("args_used") or {},
                    result_excerpt=d.get("result_excerpt") or {},
                ))
                return _out
            # §MCPADMSKIP 2026-09-07 — AN EXPLICIT `skip_reason` BINDS HERE TOO.
            # It did not: this path went straight to the default call, so 19 admin
            # contracts carrying a deliberate "do not sweep this" were swept anyway,
            # and the run reported "cloud-op admin contract_gap — no expect_keys" for
            # tools that HAVE a contract saying why they must not be called. One of
            # them is `adminAgoraDelistListing`, whose reason reads "DESTRUCTIVE —
            # cancels all orders + refunds escrow; never blind-sweep": it was
            # blind-swept every run and survived only because empty args fail
            # validation before the action. A declarative field binds exactly the
            # consumers that read it, and this consumer did not read it.
            _adm_contract = get_contract(tool_name)
            if _adm_contract.skip_reason:
                _out.append(ContractOutcome(
                    tool_name=tool_name,
                    contract_tier="admin-bridge",
                    healthy=False,          # a skip is never a pass (2026-05-26 strict mode)
                    status_code=0,
                    elapsed_ms=0,
                    skip_reason=_adm_contract.skip_reason,
                    fail_reason=None,
                    has_explicit_contract=True,
                    args_used={},
                    result_excerpt={},
                ))
                return _out
            # Fallback: default-call against admin bridge with empty args
            # under strict mode (2026-05-26). The old code marked every
            # `path reached` as healthy=True regardless of result — that
            # was a fancy ping script. Now: evaluate against an admin
            # default contract that requires the tool's outputSchema to
            # be present, then check status + required keys. Missing
            # schema OR missing keys → fail.
            t0 = time.time()
            # Phase C bug-finder: use the schema-augmented contract for this
            # admin tool. If get_contract returns a contract with auto-filled
            # expect_keys (from the AST + live harvest), use it. Otherwise
            # fall back to an admin default that lets _evaluate_contract
            # derive keys from outputSchema.required.
            admin_default = get_contract(tool_name) if tool_name in MCP_CONTRACTS or tool_name in _autogen_keys() else McpContract(tier="admin", expect_status="success")
            # If the resolved contract has no explicit_keys but the harvest
            # produced some, augment via the same path the public sweep uses.
            if not admin_default.expect_keys:
                from agentvault_registry.api_tests.contracts.mcp_contracts import _augment_contract_with_schema  # type: ignore
                admin_default = _augment_contract_with_schema(admin_default, tool_name)
            # Phase C strict-mode: resolve contract.arguments from the bag
            # (sentinel_did etc.) so admin tools that need ID params get
            # them. Previously this was always {} which caused HTTP-400
            # "missing required positional argument" on tools like
            # getEnforcementAgentStatus.
            adm_args = resolve_args(admin_default.arguments, bag)
            # Also supply best-effort args from the tool's inputSchema for
            # any required params the contract didn't declare.
            try:
                input_schema = tool.get("inputSchema") if isinstance(tool, dict) else None
                req_params = (input_schema or {}).get("required") or []
                for p in req_params:
                    if p in adm_args:
                        continue
                    if p in ("agent_did", "did"):
                        adm_args[p] = bag.sentinel_did
                    elif p == "developer_id":
                        adm_args[p] = _resolve_developer_id_param(tool_name)
                    elif p == "event_type":
                        adm_args[p] = "TokensTransferred"
            except Exception:
                pass
            # §TESTBED (2026-09-19): the public sweep's rule, which this sweep never applied. A `${fixture}` still in the
            # arguments means the lifecycle that sets it found nothing to set (getDiagnosticConfig's
            # `${diagnostic_target_id}` on a frame with no diagnostics target: the nightly sent the placeholder itself
            # and read the 404 as a defect, every night). The honest verdict is a named skip, never the literal.
            _unresolved_adm = unresolved_fixtures(adm_args)
            if _unresolved_adm:
                _out.append(ContractOutcome(
                    tool_name=tool_name, contract_tier="admin-bridge", healthy=False, status_code=0, elapsed_ms=0,
                    skip_reason=(f"fixture missing: {_unresolved_adm!r}: the lifecycle that sets it found none on this "
                                 f"frame, so the tool was not called with a placeholder"),
                    fail_reason=None, has_explicit_contract=False, args_used={}, result_excerpt={},
                ))
                return _out
            pre_call_iso = datetime.now(timezone.utc).isoformat()
            ok_a, body_a, code_a = await _mcp_rpc_call_admin(
                target, tool_name, adm_args, jwt=dev_jwt, timeout=15,
            )
            elapsed_ms = int((time.time() - t0) * 1000)
            inner_a = _parse_rpc_result(body_a) if isinstance(body_a, dict) else {}
            # §MCPTEST-MCP10 — transport-timeout retry BEFORE classification.
            ok_a, body_a, code_a = await _retry_transport_timeout(
                _mcp_rpc_call_admin, target, tool_name, adm_args, dev_jwt,
                ok_a, body_a, code_a,
            )
            ok_eval, fail_eval = _evaluate_contract(
                tool, admin_default, ok_a, code_a, body_a, bag,
                has_explicit_contract=bool(admin_default.expect_keys),
            )
            # Phase C bug-finder: event + audit-row checks for admin tools
            if ok_eval:
                post_ok, post_fail = await _verify_post_call_assertions(
                    target, admin_default, tool_name, pre_call_iso,
                    jwt=dev_jwt, bag=bag,
                )
                if not post_ok:
                    ok_eval = False
                    fail_eval = post_fail
            tier_drift = False
            err_obj = body_a.get("error") if isinstance(body_a, dict) else None
            err_msg = (err_obj or {}).get("message", "") if isinstance(err_obj, dict) else ""
            # admin-bridge tier drift: server says agent/developer (not admin)?
            if not ok_eval and isinstance(err_msg, str):
                if "requires agent authentication" in err_msg:
                    tier_drift = True
                    fail_eval = f"tier drift: admin-bridge tool surfaced 'requires agent auth'"
                elif "requires developer authentication" in err_msg:
                    tier_drift = True
                    fail_eval = f"tier drift: admin-bridge tool surfaced 'requires developer auth'"
            contract_gap = (
                not ok_eval
                and fail_eval is not None
                and fail_eval.startswith("contract gap:")
            )
            _out.append(ContractOutcome(
                tool_name=tool_name,
                contract_tier="admin-bridge",
                healthy=ok_eval,
                status_code=int(code_a) if code_a.isdigit() else 0,
                elapsed_ms=elapsed_ms,
                skip_reason=None,
                fail_reason=fail_eval,
                # §MCPTEST30: an explicit contract decided this row (it said False for every one, the mirror of the
                # §FANCLAIM literal that once said True for every lifecycle row)
                has_explicit_contract=(tool_name in MCP_CONTRACTS),
                args_used={},
                result_excerpt=result_excerpt(inner_a, shape_only=admin_default.excerpt_shape_only),
                tier_drift=tier_drift,
                contract_gap=contract_gap,
            ))
            return _out

        # ── DRIVER: bounded-concurrent admin bridge sweep ───────────────
        async def _adm_progress(done, total):
            if done % 12 == 0 or done == total:
                await _mcp_record(
                    phase="Phase 6 · admin bridge sweep",
                    completed=done, total=total,
                )
        for _buck in await _bounded_sweep(
            admin_tools, _sweep_one_admin,
            concurrency=_sweep_concurrency(), on_progress=_adm_progress,
        ):
            outcomes.extend(_buck)
        # §MCPTEST30 (V0636): the admin lifecycles' rows that name no tool, and a real success measured where the tool's
        # contract pins a refusal, are kept beside the sweep's rows (kept_lifecycle_rows); they were dropped here.
        _adm_listed = {t.get("name") for t in admin_tools if isinstance(t, dict)}
        for _lname, _d in kept_lifecycle_rows(admin_lifecycle_outcomes, _adm_listed, {o.tool_name for o in outcomes},
                                              lambda n: bool(get_contract(n).override_coverage_fan)):
            outcomes.append(ContractOutcome(
                tool_name=_lname, contract_tier=_d.get("contract_tier") or "admin_effect",
                healthy=bool(_d.get("healthy")), status_code=int(_d.get("status_code") or 0),
                elapsed_ms=int(_d.get("elapsed_ms") or 0), skip_reason=_d.get("skip_reason"),
                fail_reason=_d.get("fail_reason"), has_explicit_contract=True,
                args_used={}, result_excerpt=_d.get("result_excerpt") or {},
            ))

        # ── Phase 6b · the ADMIN surface's wrong-tier matrix (§ADMINMATRIX) ──
        # The matrix above walks the PUBLIC tools/list. Every admin tool — the
        # teardowns, provisionCloudOperator, rotateRegistrySigningKey — was gate-
        # tested by nobody, and the five `never_probe_wrong_tier` declarations on
        # that surface were a declaration with no consumer.
        #
        # Four things measured on this tier before writing a single probe, because
        # a matrix that CALLS an admin tool is the same act it is testing for:
        #   1. the admin surface answers 401 `-32001 requires admin auth` to an
        #      empty AND to a garbage bearer, for a no-arg tool and for one with
        #      required args alike — so the gate runs BEFORE argument binding, and
        #      a refused probe never reaches a tool body;
        #   2. a tool with required args is refused at dispatch anyway
        #      (`-32602 Invalid params`, a TypeError on the call signature), so of
        #      321 admin tools only the 155 with no required args could reach a
        #      body even if their gate failed;
        #   3. a VALID non-admin developer JWT is refused by getAdminDashboard,
        #      getAdminDevelopers, getEnforcementPolicy — the sharp probe, not just
        #      the credential-less one;
        #   4. `invokeTool`, the gateway escape hatch, is REFUSED for a non-admin.
        #      Had it not been, every other gate here would be bypassable and this
        #      matrix would be measuring a fence with an open gate beside it.
        #
        # What is NOT a violation: the pre-dispatch catalog meta-tools. They are
        # handled before the admin dispatcher (doctrine says so — enableToolset /
        # disableToolset deliberately carry no audit row) and answer 200 to any
        # authenticated developer. They expose tool NAMES and SCHEMAS, which the
        # public MCP catalog documents anyway. Declared, not discovered each run.
        _ADMIN_MATRIX_EXPECTED_OPEN = {
            "theprotocol_listToolsets",
            "theprotocol_searchTools",
            "theprotocol_describeTools",
        }
        # …and the two that MUTATE per-credential state (a 24 h toolset selection)
        # are not probed at all: repeating them every run would churn the state of
        # whichever credential the probe borrowed.
        _ADMIN_MATRIX_NEVER_PROBE = {
            "theprotocol_enableToolset",
            "theprotocol_disableToolset",
        }


        # A SHARED cooldown, not a per-probe backoff. Measured: pacing alone still
        # met the bucket, and with a 20 s sleep PER throttled probe the phase would
        # have taken 20+ minutes for 281 probes — half of them waiting out the same
        # window separately. The bucket is shared, so the wait should be too: the
        # first 429 parks every worker until one window has passed, and afterwards
        # they continue rather than each paying their own.
        _admin_matrix_cooldown_until = 0.0
        _admin_matrix_deadline = 0.0        # set when the phase starts
        _admin_matrix_seed = 0              # the hourly probe-order seed, reported
        admin_matrix_budget_skipped: List[str] = []

        async def _admin_matrix_respect_cooldown():
            while True:
                wait = _admin_matrix_cooldown_until - time.time()
                if wait <= 0:
                    return
                await asyncio.sleep(min(wait, 2.0))

        admin_matrix_total = 0
        admin_matrix_violations = 0
        admin_matrix_inconclusive = 0
        admin_matrix_429_retries = 0        # how much of the wall time was backoff

        # §ADMINMATRIX-3 — CHOSEN ONCE, so the credential the guard proves is the
        # credential the probes use. Prefer the matrix's OWN principal: the
        # limiter buckets by principal, so sharing one credential with the
        # 617-probe public matrix is what left 80 of 281 probes unmeasured while
        # the time budget went unused. `developer_jwt_nonadmin` is the fallback
        # and `empty` the floor — an empty bearer proves only that the surface
        # wants a token, which is the weakest true thing this phase can say.
        admin_matrix_credential = ""          # which principal the phase probed WITH
        admin_matrix_credential_refused = None  # …and whether the surface refused it
        _sharpest = ("developer_jwt_nonadmin2" if _bad_jwts.get("developer_jwt_nonadmin2")
                     else "developer_jwt_nonadmin" if _bad_jwts.get("developer_jwt_nonadmin")
                     else "empty")
        admin_matrix_failed: List[str] = []
        admin_matrix_not_probed: List[str] = []
        admin_matrix_expected_open_seen: List[str] = []

        async def _sweep_one_admin_authmatrix(tool):
            nonlocal admin_matrix_total, admin_matrix_violations, admin_matrix_inconclusive
            nonlocal admin_matrix_429_retries
            nonlocal _admin_matrix_cooldown_until
            tool_name = tool.get("name") if isinstance(tool, dict) else None
            if not tool_name:
                return None
            if tool_name in _ADMIN_MATRIX_NEVER_PROBE:
                admin_matrix_not_probed.append(tool_name)
                return None
            contract = get_contract(tool_name)
            if contract.never_probe_wrong_tier:
                admin_matrix_not_probed.append(tool_name)
                return None
            if not _admin_probe_is_safe(tool):
                admin_matrix_not_probed.append(tool_name)
                return None
            if _admin_matrix_deadline and time.time() > _admin_matrix_deadline:
                # Out of budget. NOT the same fact as "not probed by policy", so it
                # gets its own list: this tool was never asked, and the run says so.
                admin_matrix_budget_skipped.append(tool_name)
                return None
            # ONE credential, not three. The public matrix sends three because each
            # contract declares which tiers must be rejected; the admin surface has a
            # SINGLE gate for all 321 tools, so three credentials re-measure the same
            # property at three times the cost — and the cost is the whole problem
            # (measured: 843 probes tripped the endpoint's rate limiter, 552 × 429).
            # `developer_jwt_nonadmin` is also the SHARPEST of the three: a valid
            # developer who is simply not an admin. An empty bearer proves only that
            # the surface wants a token.
            # Pace the probes so the matrix does not create the throttle it then has
            # to report as unmeasured. ~2.5 probes/sec against a 1000/minute bucket
            # leaves headroom for whatever else is talking to the node.
            await _admin_matrix_respect_cooldown()
            await asyncio.sleep(_ADMIN_MATRIX_PACE_SEC)
            for bad_tier_key in (_sharpest,):
                bad_jwt = _bad_jwts.get(bad_tier_key, "")
                admin_matrix_total += 1
                _ok, body, code = await _mcp_rpc_call_admin(
                    target, tool_name, {}, jwt=bad_jwt, timeout=10)
                status = int(code) if str(code).isdigit() else 0
                # A THROTTLED PROBE MEASURED NOTHING. 429 is neither a refusal nor an
                # accept, and scoring it as an accept is how the first run of this
                # matrix reported 548 "violations" that were 548 × 429 — the probe
                # observing its own pressure.
                #
                # The window is a MINUTE (`RATE_LIMIT_DEFAULT` and the route's own
                # limit). ⚠ THIS COMMENT USED TO SAY THE BUCKET IS KEYED BY ROLE.
                # It is not: `principal_rate_key` keys on
                # `request.state.rl_principal`, set once a signature has been
                # checked, so every distinct credential gets its own bucket. The
                # sharing was never structural — it was one credential used by
                # two matrices, which §ADMINMATRIX-3 splits. A 2 s retry is
                # therefore almost always still 429: measured, 251 of 281 probes came
                # back inconclusive with one. Back off on the window's scale instead,
                # once, and give up honestly after that.
                # §ADMINMATRIX-2 2026-09-06 — RETRY MORE THAN ONCE, because the
                # FULL pass proved time is not what is short. A deliberate run at
                # budget 2400 came back: 201 measured, 0 violations, 80
                # inconclusive, and `admin_matrix_budget_skipped: 0` — the budget
                # never bound. What bound was this 429, on a bucket shared with
                # the public matrix, and one backoff left 80 of 281 unmeasured.
                # A second and third attempt cost seconds out of a budget with
                # slack to spare; leaving a quarter of the admin surface
                # unmeasured costs the whole point of the matrix. Still bounded,
                # still honest when it gives up, and still never scored as an
                # accept.
                _tries = 0
                while status == 429 and _tries < _ADMIN_MATRIX_429_RETRIES:
                    _tries += 1
                    _admin_matrix_cooldown_until = max(
                        _admin_matrix_cooldown_until,
                        time.time() + _ADMIN_MATRIX_429_BACKOFF_SEC)
                    await _admin_matrix_respect_cooldown()
                    if _admin_matrix_deadline and time.time() > _admin_matrix_deadline:
                        break          # the budget is the one thing that still wins
                    _ok, body, code = await _mcp_rpc_call_admin(
                        target, tool_name, {}, jwt=bad_jwt, timeout=10)
                    status = int(code) if str(code).isdigit() else 0
                if _tries:
                    admin_matrix_429_retries += _tries
                if status == 429 or not (100 <= status <= 599):
                    # No HTTP answer, or only the limiter's answer: proves nothing in
                    # either direction and must never be scored as an accept.
                    admin_matrix_inconclusive += 1
                    admin_matrix_total -= 1
                    continue
                if _wrong_tier_rejected(status, body):
                    continue
                if tool_name in _ADMIN_MATRIX_EXPECTED_OPEN:
                    if tool_name not in admin_matrix_expected_open_seen:
                        admin_matrix_expected_open_seen.append(tool_name)
                    continue
                admin_matrix_violations += 1
                admin_matrix_failed.append(f"{tool_name}({bad_tier_key}→{status})")

        # The phase costs real wall time (≈280 probes at ~1/sec) because it must stay
        # under a rate bucket it shares with the public matrix. Skippable for anyone
        # who needs the fast path, and the skip SAYS so rather than reporting zero
        # violations over zero probes.
        _admin_matrix_on = (os.environ.get("MCP_TESTER_ADMIN_MATRIX", "on") or "on"
                            ).strip().lower() not in ("0", "off", "false", "no")
        if admin_tools and not _admin_matrix_on:
            logger.warning("[MCP-AdminAuthMatrix] DISABLED by MCP_TESTER_ADMIN_MATRIX — "
                           "the admin surface was NOT gate-probed this run")
        # §ADMINMATRIX-3 — PROVE THE PROBE CREDENTIAL IS ACTUALLY WRONG-TIER
        # BEFORE TRUSTING 321 VERDICTS BUILT ON IT. Every result here is "the
        # admin surface refused a caller who should be refused"; if the chosen
        # credential were an ADMIN (a seed flipped, the wrong fixture picked,
        # `developer@test.sandbox` promoted), every tool would answer normally
        # and the phase would report ~318 violations — which reads as a product
        # catastrophe and is a bad credential. One probe against a tool the
        # surface must refuse turns that into the truth. A credential that is
        # NOT refused disables the phase with the reason, because a matrix whose
        # premise is false measures nothing.
        if admin_tools and _admin_matrix_on and _sharpest != "empty":
            _guard_jwt = _bad_jwts.get(_sharpest, "")
            _g_ok, _g_body, _g_code = await _mcp_rpc_call_admin(
                target, "theprotocol_getAdminDashboard", {}, jwt=_guard_jwt, timeout=15)
            _g_status = int(_g_code) if str(_g_code).isdigit() else 0
            _guard_refused = _wrong_tier_rejected(_g_status, _g_body)
            admin_matrix_credential = _sharpest
            admin_matrix_credential_refused = _guard_refused
            if _g_status == 429:
                logger.warning("[MCP-AdminAuthMatrix] credential guard was THROTTLED "
                               "(429) — proceeding, the per-probe 429 handling covers it")
            elif not _guard_refused:
                _admin_matrix_on = False
                logger.error(
                    "[MCP-AdminAuthMatrix] DISABLED: the probe credential %r was NOT "
                    "refused by getAdminDashboard (HTTP %s) — it is not wrong-tier, so "
                    "every verdict this phase would produce is meaningless. Fix the "
                    "credential, do not read the numbers.", _sharpest, _g_status)

        if admin_tools and _admin_matrix_on:
            _admin_matrix_deadline = time.time() + _ADMIN_MATRIX_BUDGET_SEC
            # ROTATE THE ORDER. With a budget and a fixed list the phase would probe
            # the same first ~20 tools every run for ever: the rest would be
            # permanently unmeasured while the number on the report stayed reassuring
            # — a gate loudest about what it cannot see. Seeded by the hour so a run
            # is reproducible within it and the sample moves between them; the seed is
            # logged so any finding can be replayed on the same slice.
            _admin_matrix_seed = int(time.time()) // 3600
            _admin_order = list(admin_tools)
            random.Random(_admin_matrix_seed).shuffle(_admin_order)
            logger.info("[MCP-AdminAuthMatrix] probe order seed=%d (hourly) over %d tools",
                        _admin_matrix_seed, len(_admin_order))
            await _bounded_sweep(
                _admin_order, _sweep_one_admin_authmatrix,
                # Half the sweep's concurrency: this phase runs AFTER the admin bridge
                # sweep has already spent part of the endpoint's rate budget, and a
                # throttled probe is a lost measurement rather than a slow one.
                # Two at a time, paced: this phase shares the NON-admin rate bucket
                # with the public matrix, and a throttled probe is a lost
                # measurement rather than a slow one.
                concurrency=2,
            )
            await _mcp_record(
                phase="Phase 6b · admin wrong-tier auth matrix",
                completed=len(admin_tools), total=len(admin_tools),
            )
            logger.info(
                "Admin auth matrix: %d probes, %d violations, %d inconclusive, "
                "%d not probed (policy), %d unreached (budget %.0fs), "
                "%d expected-open seen",
                admin_matrix_total, admin_matrix_violations,
                admin_matrix_inconclusive, len(admin_matrix_not_probed),
                len(admin_matrix_budget_skipped), _ADMIN_MATRIX_BUDGET_SEC,
                len(admin_matrix_expected_open_seen))
            if admin_matrix_budget_skipped:
                logger.warning(
                    "[MCP-AdminAuthMatrix] %d admin tool(s) NOT reached inside the "
                    "%.0fs budget — coverage this run is partial, by design; raise "
                    "MCP_TESTER_ADMIN_MATRIX_BUDGET_SEC for a full pass",
                    len(admin_matrix_budget_skipped), _ADMIN_MATRIX_BUDGET_SEC)
            if admin_matrix_failed:
                logger.error("[MCP-AdminAuthMatrix] wrong-tier ACCEPTS: %s",
                             ", ".join(sorted(admin_matrix_failed)))
        else:
            # The admin list is fetched earlier and can legitimately be empty on a
            # node whose admin bridge is absent. Say so; never report 0 violations
            # over 0 probes as a clean matrix.
            logger.warning("[MCP-AdminAuthMatrix] admin tools/list is empty — "
                           "the admin surface was NOT gate-probed this run")




        # 4a2. PHASE 7 · §ENFPROP — the enforce REFUSAL branch. Runs AFTER both sweeps
        # on purpose: it suspends a sweep-owned agent, and doing that mid-sweep would
        # change results for every later tool that touches it. Fully self-contained —
        # it restores what it changed and reports the restore as its own row.
        try:
            _enf = await _phase7_enforcement_refusal(target, bag, dev_jwt)
            outcomes.extend(_enf)
            await _mcp_record(phase="Phase 7 · §ENFPROP refusal")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"phase-7 enforcement refusal raised (non-fatal): {e!r}")

        # 4b. PHASE 3 teardown — best-effort cleanup of fixture entities
        try:
            await _phase3_teardown(target, bag)
        except Exception as e:
            logger.warning(f"phase-3 teardown raised (non-fatal): {e!r}")

        # §TESTBED: a frame-seeded fixture this frame never had is a named skip, never a product red (_fixture_absent_reason)
        for o in outcomes:
            _absent = _fixture_absent_reason(o.tool_name, o.healthy, o.skip_reason, o.status_code, o.fail_reason)
            if _absent:
                o.skip_reason, o.fail_reason, o.healthy = _absent, None, False

        # 4c. §MCPTEST30 — the credential exposure census closes over every response of the run
        _census_summary = _credential_census_close(outcomes, _census_token)
        _shape_summary = _result_shape_close(outcomes, _shape_token)
        _words_summary = _wording_close(outcomes, _words_token, _listing_words_found)   # §MCPTEST30 W6
        # 4d. §MCPTEST30 — the target database's connections against their ceiling, with the pools at their fullest
        _db_headroom = await _db_headroom_close(outcomes)

        # 5. Shape outcomes into APITestBase results format
        for o in outcomes:
            results.append({
                "step": len(results) + 1,
                "name": f"MCP tool: {o.tool_name} (tier={o.contract_tier})",
                "path": "/mcp/rpc",
                "method": "POST",
                "authRequired": (
                    "none" if o.contract_tier in ("0", "1")
                    else "agent" if o.contract_tier == "2"
                    else "developer" if o.contract_tier == "3"
                    else "admin"
                ),
                "healthy": o.healthy,
                "statusCode": o.status_code,
                "responseData": {
                    "tool": o.tool_name,
                    "has_explicit_contract": o.has_explicit_contract,
                    "skip_reason": o.skip_reason,
                    # §MCPTEST30 (V0550): the switch this row was held to (mcp_switches.py), or None
                    "switched_off": (_swo.label() if (_swo := _switches.switched_off(o.tool_name)) else None),
                    # §MCPTEST30 (V0643): the by-design reason the router says if this row passes on a refusal alone
                    "declared_unmeasured": _refusal_reasons.declared(o.tool_name),
                    "result_excerpt": o.result_excerpt,
                    "elapsed_ms": o.elapsed_ms,
                    "tier_drift": o.tier_drift,
                    "contract_gap": o.contract_gap,
                },
                "error": o.fail_reason,
                "expected_failure": o.skip_reason is not None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        # 6. Summary stats — strict mode (2026-05-26): skips are NOT healthy.
        # Pass rate = healthy / total. Skips, tier drift, and contract gaps
        # are surfaced as separate columns so the operator can attribute
        # failures (real regression vs. coverage gap vs. drift).
        total = len(outcomes)
        # §MCPTEST-MCP9 (Commander-approved): separate POLICY-DENIED from SKIPPED.
        # The deny-list tools (provisioning, teardown, sim start/stop, api-tester
        # forks, canary pause) carry `healthy=True` AND a skip_reason, so they were
        # counted in BOTH `passed` and `skipped` — which is why 742 tools reported
        # 763 outcomes and why the headline read "29 skipped" when only 8 tools
        # were genuinely unexercised. They are not skipped for want of a fixture;
        # they are refused by a standing operating rule, and reporting them as the
        # same thing as "we could not test this" overstates the gap.
        # §MCPTEST30 (V0539): and in passed, until outcome_counts made the four classes disjoint
        _counted = outcome_counts(outcomes)
        policy_denied = _counted["policy_denied"]
        skipped = _counted["skipped"]
        passed = _counted["passed"]

        # §MCPTEST-MCP5 2026-08-08 — DUMP THE SKIP LIST.
        # `pass_pct = passed/tool_count` and skips count AGAINST it, so the
        # skipped set is the single biggest remaining block of non-passing
        # tools. The run record ships a skip COUNT with no list (the router's
        # predicate keys off `expected_failure`, which this flow never sets),
        # which makes those tools unactionable — you can see that 52 exist but
        # not which. Emit them here, where the reason is still attached to the
        # outcome, so the work list survives into the log.
        _skips = [(o.tool_name, (o.skip_reason or "")[:110])
                  for o in outcomes if o.skip_reason]
        logger.warning("[MCP-SkipList] %d skipped tools follow", len(_skips))
        for _t, _r in sorted(_skips):
            logger.warning("[MCP-Skip] %-46s %s", _t, _r)
        failed = _counted["failed"]
        tier_drift_n = sum(1 for o in outcomes if o.tier_drift)
        contract_gap_n = sum(1 for o in outcomes if o.contract_gap)
        # Strict pass percentage — only "healthy" counts as a pass. Skips
        # don't get a free ride (handover doctrine: a skip is a coverage
        # hole, not a victory).
        pass_pct = (passed * 100 / total) if total else 0

        # ── §pass73.2 task G — orphan sweep FINAL ─────────────────────────
        # Diff against baseline; report rows that accumulated during the sweep.
        try:
            orphan_final = await _snapshot_row_counts(_db_container_a)
            orphan_deltas = _diff_row_counts(orphan_baseline, orphan_final)
            logger.info(f"orphan deltas: {orphan_deltas}")
        except Exception as e:
            logger.warning(f"orphan final-snapshot failed (non-fatal): {e!r}")
            orphan_deltas = {}

        self.flow_values = {
            "tool_count": total,
            # §MCPTEST30 (V0550): what the target switched off, and the rows held to those switches' refusals
            **_central_switches,
            "switched_off_rows": sorted({o.tool_name for o in outcomes if _switches.switched_off(o.tool_name)}),
            "explicit_contracts": sum(1 for o in outcomes if o.has_explicit_contract),
            "default_contracts": sum(1 for o in outcomes if not o.has_explicit_contract),
            "passed": passed,
            "skipped": skipped,
            **skip_census(outcomes),
            "policy_denied": policy_denied,
            "failed": failed,
            "tier_drift": tier_drift_n,
            "contract_gap": contract_gap_n,
            "pass_pct": round(pass_pct, 2),
            "wall_s": round(time.time() - t_start, 1),
            # §EVTYPES5 — the posture this run measured, read from the node. The
            # central sweep states it too, otherwise the operator's readout has
            # nothing to be compared WITH, which was the whole point of adding it.
            "posture": _central_posture,
            "posture_complaints": _central_posture_notes,
            # §EVTYPES7 — which mechanism decided each row (they sum to the sweep's
            # public-tool count). `contract` is the only one where THIS tool's own
            # expect_keys / expect_error_message_contains were checked.
            "decided_by": _decided_by,
            # ── Phase F.1 — auth matrix totals (Gap-1) ────────────────
            "auth_matrix_total": auth_matrix_total,
            "auth_matrix_violations": auth_matrix_violations,
            # WHICH wrong-tier credentials this run actually had. A failed mint
            # degrades the matrix to an `empty` bearer — a real but much weaker
            # probe — and until now that showed up as one log line and no change
            # to any number on the report.
            "auth_matrix_credentials_available": sorted(
                k for k, v in _bad_jwts.items() if v),
            # §ADMINMATRIX — the admin surface's own matrix. `admin_matrix_total`
            # of 0 with a non-empty admin_tools means the sweep did not run, which
            # is a different fact from "no violations".
            "admin_matrix_total": admin_matrix_total,
            "admin_matrix_violations": admin_matrix_violations,
            "admin_matrix_inconclusive": admin_matrix_inconclusive,
            "admin_matrix_429_retries": admin_matrix_429_retries,
            # WHICH credential produced these verdicts, and whether it was PROVEN
            # wrong-tier first. Without both, "0 violations" is unreadable: it is
            # equally what a healthy surface and a mis-scoped probe would print.
            "admin_matrix_credential": admin_matrix_credential,
            "admin_matrix_credential_refused_probe": admin_matrix_credential_refused,
            "admin_matrix_failed_tools": sorted(admin_matrix_failed),
            "admin_matrix_not_probed": sorted(admin_matrix_not_probed),
            # Separate from `not_probed`: those were REFUSED a probe by policy, these
            # were simply never reached. Reporting them together would hide a
            # shrinking coverage behind a stable-looking number.
            "admin_matrix_unreached_budget": len(admin_matrix_budget_skipped),
            "admin_matrix_budget_sec": _ADMIN_MATRIX_BUDGET_SEC,
            # The slice this run happened to walk. Without it, a violation found on
            # one run could not be replayed on the same set.
            "admin_matrix_order_seed": _admin_matrix_seed,
            "admin_matrix_expected_open": sorted(admin_matrix_expected_open_seen),
            "auth_matrix_inconclusive": auth_matrix_inconclusive,
            "auth_matrix_before_gate": auth_matrix_before_gate,
            "auth_matrix_before_gate_tools": sorted(auth_matrix_before_gate_tools)[:80],
            "auth_matrix_not_probed": sorted(auth_matrix_not_probed),
            "auth_matrix_probed_tools": sorted(set(auth_matrix_probed)),
            "auth_matrix_failed_tools": auth_matrix_failed_tools[:50],  # cap surface
            # ── Phase F.4 — cross-frame parity (Gap-4) ─────────────────
            "cross_frame_probed": cross_frame.get("probed", 0),
            "cross_frame_drift": cross_frame.get("drifts", 0),
            "cross_frame_drift_details": cross_frame.get("drift_details", []),
            "cross_frame_a_unreachable": cross_frame.get("a_unreachable", 0),
            "cross_frame_b_unreachable": cross_frame.get("b_unreachable", 0),
            "cross_frame_timed_out": cross_frame.get("timed_out", 0),
            "cross_frame_compared": cross_frame.get("compared", 0),
            "cross_frame_compared_tools": cross_frame.get("compared_tools", []),
            # ── Phase F.3 — wrapper↔route: the request survey (§MCPTEST30 V0547) ────────────────
            **wrapper_drift_summary,
            # §MCPTEST30 (V0546): mutations whose read-after-write answered 2xx without any key its check reads, so the
            # check judged nothing (the mTLS toggle's class, found at run time instead of by reading the code)
            "unjudged_read_backs": sorted(t for t, o in lifecycle_outcomes.items()
                                          if isinstance(o, dict) and o.get("unjudged_read_back")),
            # ── §pass73.2 task G — orphan sweeper ──────────────────────
            # `orphans_by_table` is the per-table delta. Some tables (attestations,
            # reputation_bonds, bridge_transactions) accumulate by design — those
            # deltas are informational. The non-design-accumulating tables
            # (organizations, developer_api_keys, support_tickets etc.) should
            # ideally have delta=0 — non-zero indicates a lifecycle that creates
            # but doesn't delete.
            "orphans_by_table": orphan_deltas,
            "orphan_table_count": sum(1 for v in orphan_deltas.values() if v > 0),
            # §MCPTEST30 (V0638): what a throwaway agent held and the run could not return to the treasury, said
            "throwaway_balances_not_returned": list(getattr(bag, "throwaway_balances", None) or []),
        }
        self.flow_values["credential_exposure"] = {   # §MCPTEST30 (a console that passes it through will show it)
            "measured": bool(_census_summary.get("measured")),
            "responses_scanned": _census_summary.get("responses_scanned", 0),
            "unexpected": sorted(_census_summary.get("unexpected") or {}),
            "issuers_seen": len(_census_summary.get("issuer") or {}),
        }
        self.flow_values["db_headroom"] = _db_headroom   # §MCPTEST30: counts only
        self.flow_values["result_shape"] = {   # §MCPTEST30
            "measured": bool(_shape_summary.get("measured")),
            "responses_scanned": _shape_summary.get("responses_scanned", 0),
            "schema_checked": _shape_summary.get("schema_checked", 0),
            "tools_with_findings": sorted(_shape_summary.get("findings") or {}),
            "tools_with_reasonless_refusals": sorted(_shape_summary.get("reasonless_refusals") or {}),
        }
        self.flow_values["wording"] = {   # §MCPTEST30 W6: the critical words, counts and names only
            "listings_read": _words_summary["listings"]["listings_read"],
            "listing_findings": sum(len(v) for v in _words_summary["listings"]["findings"].values()),
            "old_names_listed": _words_summary["listings"]["old_names_listed"],
            "answers_with_a_word": _words_summary["answers"].get("tools_with_a_word", 0),
        }
        logger.info(f"MCP lifecycle sweep complete: {self.flow_values}")
        return self._summarize(results, failed == 0)

    def _summarize(self, results: List[Dict[str, Any]], success: bool, error: str = "") -> Dict[str, Any]:
        return {
            "flow_name": "flow_mcp_lifecycle_complete",
            "success": success,
            "total_steps": len(results),
            "successful_steps": sum(1 for r in results if r.get("healthy")),
            "error": error or None,
            "results": results,
            "flow_values": dict(self.flow_values),
        }

    # ──────────────────────────────────────────────────────────────────────
    # §pass73.3.3 — Option M sandbox cloud-op MCP coverage (Phase 1: lite)
    # ──────────────────────────────────────────────────────────────────────
    # Adds per-cloud-op MCP sweep flows that probe the cloud-op's own
    # /mcp/rpc + /mcp/admin/rpc surfaces. Reuses the contract resolver and
    # tier classifier from the central sweep but skips: lifecycles, phase-3
    # entity setup, F.1 auth matrix (no non-admin dev seeded on cloud-op),
    # F.3 wrapper drift (covered on central sandbox), F.4 cross-frame parity
    # (cloud-op is consumer of central EventStore, not a sovereign frame),
    # orphan sweep (no DB pattern match for cloud-op container names).
    #
    # Phase 2 (next session): bootstrap a synthetic agent on the cloud-op
    # via createAgent + fund from cloud-op TEG so tier-2 contracts run.

    async def test_mcp_lifecycle_cloudop_sandboxalpha_flow(
        self, developer_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run the cloud-op MCP sweep against sandboxalpha (frame-a child)."""
        return await self._run_cloudop_mcp_sweep("sandboxalpha")

    async def test_mcp_lifecycle_cloudop_sandboxdelta_flow(
        self, developer_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run the cloud-op MCP sweep against sandboxdelta (frame-b child)."""
        return await self._run_cloudop_mcp_sweep("sandboxdelta")

    async def _run_cloudop_mcp_sweep(self, operator_label: str) -> Dict[str, Any]:
        """Lite MCP-tester sweep against a sandbox cloud-op.

        Logs in as the cloud-op's admin developer, lists tools on both
        public + admin bridges, then walks each tool with default contract
        args + cloud-op-aware fixture skips. Tier-2 contracts skip cleanly
        (no sentinel agent on cloud-op in Phase 1). Returns the standard
        BFF-compatible flow shape with `flow_values.operator` set so the
        dashboard can attribute findings per cloud-op.
        """
        from types import SimpleNamespace
        from agentvault_registry.api_tests.multiframe_helpers import (
            get_operator_target,
        )

        # Resolve cloud-op target
        try:
            op = get_operator_target(operator_label)
        except ValueError as e:
            self.flow_values = {"error": str(e), "operator": operator_label}
            return {
                "flow_name": f"flow_mcp_lifecycle_cloudop_{operator_label}_complete",
                "success": False,
                "total_steps": 0,
                "successful_steps": 0,
                "error": str(e),
                "results": [],
                "flow_values": dict(self.flow_values),
            }

        logger.info("=" * 60)
        logger.info(f"MCP Lifecycle Cloud-Op Sweep — {op.label} ({op.parent_frame})")
        logger.info("=" * 60)

        # Build a TargetEndpoints-shaped proxy so the existing _mcp_rpc_*
        # helpers (which read target.a_registry_container) work unchanged.
        cloud_target = SimpleNamespace(
            label=f"cloud-op-{op.label}",
            a_registry_container=op.registry_container,
            b_registry_container="",  # cross-frame paths disabled on cloud-op
        )

        results: List[Dict[str, Any]] = []
        t_start = time.time()

        # 1. Login as cloud-op admin (skip the central sandbox commander —
        # cloud-op has its own admin@cloud-op-{label}.dev / SandboxOpAdmin2026!)
        rc, out = await asyncio.to_thread(
            exec_in_container, op.registry_container, [
                "sh", "-c",
                f"curl -sS -X POST "
                f"-H 'Content-Type: application/x-www-form-urlencoded' "
                f"--data-urlencode 'username={op.admin_email}' "
                f"--data-urlencode 'password={op.admin_password}' "
                f"-w '\\n{_HTTP_MARKER}%{{http_code}}--' "
                "http://localhost:8000/api/v1/auth/login",
            ], 15,
        )
        body, code = _split_http_body_code(out)
        if rc != 0 or not code.startswith("2"):
            return {
                "flow_name": f"flow_mcp_lifecycle_cloudop_{op.label}_complete",
                "success": False, "total_steps": 0, "successful_steps": 0,
                "error": f"cloud-op admin login failed: code={code} body={body[:200]}",
                "results": [], "flow_values": {"operator": op.label},
            }
        try:
            dev_jwt = json.loads(body)["access_token"]
        except Exception as e:
            return {
                "flow_name": f"flow_mcp_lifecycle_cloudop_{op.label}_complete",
                "success": False, "total_steps": 0, "successful_steps": 0,
                "error": f"cloud-op login response unparseable: {e!r}",
                "results": [], "flow_values": {"operator": op.label},
            }

        # §MCPTEST30 (V0550): hold this run to the operator's own switches (its env, never its parent's)
        _cop_switches = await _read_target_switches(op.registry_container)
        logger.info("cloud-op %s switches: %s; switched off here: %s"
                    % (op.label, _cop_switches["target_switches"], _cop_switches["target_switches_off"]))
        # §MCPTEST30 (V0637): who this run measured, read from the operator, not from the flow's key. The keys
        # (sandboxalpha, sandboxdelta) name operators retired in September; the run's container and its own card name
        # the operator that answers today (sbxalphaop under sbx-alpha, sbxbetaop under sbx-beta, on 2026-10-24).
        _op_identity = {"operator_slug": operator_slug(op.registry_container), "operator_name": ""}
        try:
            _ccode, _ctext = await _http_in_target(op.registry_container, "GET", "/.well-known/registry-card.json")
            _card = json.loads(_ctext) if _ccode == "200" and _ctext else {}
            _ident = _card.get("identity") if isinstance(_card, dict) else None
            _op_identity["operator_name"] = str((_ident or {}).get("registry_name") or "")
        except Exception:  # noqa: BLE001 — an unread card leaves the name empty, never a guess
            pass
        logger.info("cloud-op %s answers as %s (%r)"
                    % (op.label, _op_identity["operator_slug"], _op_identity["operator_name"]))

        # §MCPTEST30 (V0528): agents earlier runs of this phase left behind (oldest first, a few per run)
        async def _c_fx(tool, args):
            return await _mcp_rpc_call(cloud_target, tool, args, jwt=dev_jwt, timeout=20)

        async def _ca_fx(tool, args):
            return await _mcp_rpc_call_admin(cloud_target, tool, args, jwt=dev_jwt, timeout=25)
        _old_retired: Dict[str, Any] = {"asked": 0}
        try:
            _lc, _lt = await _http_in_target(op.registry_container, "GET",
                                             "/api/v1/developers/me/agents?q=cloudop-&limit=500", bearer=dev_jwt)
            _old = old_cloudop_fixtures(json.loads(_lt) if _lc == "200" else [], time.time(),
                                        active_orgs=await _active_org_names(_c_fx))
            if _old:
                _old_retired = await _retire_cloudop_agents(_c_fx, _ca_fx, _old)
            logger.info(f"cloud-op {op.label}: earlier runs' agents (listing HTTP {_lc}): {_old_retired}")
        except Exception as e:  # noqa: BLE001 — cleanup is never a finding
            _old_retired = {"asked": 0, "error": type(e).__name__}

        # 2. §pass73.3.19 Phase 2 — bootstrap a sentinel agent ON the cloud-op so
        # Tier-2 tools are reachable with a genuine agent JWT (was deferred in
        # Phase 1 lite → 83 tier-2 skips). createAgent → getAgentToken → fund from
        # the cloud-op's genesis treasury (each op got 100K AVT, §pass73.3.1).
        # Best-effort: any failure falls through with empty sentinel and the
        # Tier-2 no-sentinel skip path is preserved (no regression).
        # §CLOUDOPMCP 2026-09-04 — bootstrap TWO agents, not one. The fixture bag
        # below used to hardcode second_agent_did/jwt to "", so every contract
        # referencing ${second_agent_did} sent an EMPTY string and the tool answered
        # a perfectly correct "receiver_did is required" / "provider_did is required"
        # — which the sweep counted as a DEFECT. A two-party rail needs two parties;
        # one sentinel cannot test sending to somebody else. Measured on sbxalphaop:
        # smartSend and engageAgent, both failing for exactly this reason.
        # §EVTYPES5 2026-09-06 — the bootstrap MINTS client_id/client_secret and
        # then throws them away; getAgentToken's contract wants exactly those, so
        # it skipped for a fixture that existed one frame up the stack. Kept here
        # rather than widened into the return tuple, so both call sites are
        # untouched.
        _boot_creds: Dict[str, Dict[str, str]] = {}
        # §MCPTEST30 (V0639): the roles the run gave its own agents, said in the summary (run_roles)
        _run_roles: Dict[str, Any] = {}

        async def _bootstrap_cloudop_agent(_tag):
            """Create one agent on the cloud-op, mint its JWT, try to fund it.

            Returns (did, jwt, agent_id), or ("","","") on any failure so the
            pre-existing no-sentinel skip paths still apply unchanged.

            The funding call is best-effort and on a FRESH cloud-op it is a no-op:
            the operator treasury is 0 and cannot be seeded, because cross-TEG
            treasury funding refuses any frame whose SPIFFE id is not named
            /service/registry-* or /service/teg-* (backlog B8). Money-dependent
            fixtures are therefore unavailable BY DESIGN here, not by accident.
            """
            _did = _jwt = _aid = ""
            try:
                _okc, _cab, _cac = await _mcp_rpc_call(
                    cloud_target, "theprotocol_createAgent",
                    {"name": "cloudop-%s-%d-%s" % (_tag, int(time.time()), uuid.uuid4().hex[:6]),
                     "description": "MCP-tester Phase-2 %s (cloud-op tier-2 fixture)" % _tag},
                    jwt=dev_jwt, timeout=20)
                _ca = _parse_rpc_result(_cab) if isinstance(_cab, dict) else {}
                _cid, _csec = _ca.get("client_id"), _ca.get("client_secret")
                _did = _ca.get("did") or _ca.get("agent_did") or ""
                if _cid and _csec:
                    _boot_creds[_tag] = {"client_id": _cid, "client_secret": _csec}
                    _okt, _tb, _tc = await _mcp_rpc_call(
                        cloud_target, "theprotocol_getAgentToken",
                        {"client_id": _cid, "client_secret": _csec}, jwt=dev_jwt, timeout=20)
                    _tok = _parse_rpc_result(_tb) if isinstance(_tb, dict) else {}
                    _jwt = _tok.get("access_token") or ""
                if _jwt:
                    try:
                        _pl = _jwt.split(".")[1]
                        _pl += "=" * (-len(_pl) % 4)
                        _aid = str(json.loads(base64.urlsafe_b64decode(_pl)).get("agent_id") or "")
                    except Exception:
                        _aid = ""
                    if _did:
                        _fund_body = (
                            '{"target_agent_did":"' + _did + '","amount":"5000",'
                            '"reason":"mcp-tester phase-2 cloud-op ' + _tag + ' bootstrap"}'
                        )
                        await asyncio.to_thread(
                            exec_in_container, op.registry_container, [
                                "sh", "-c",
                                "curl -sS -X POST -H 'Authorization: Bearer " + dev_jwt + "' "
                                "-H 'Content-Type: application/json' "
                                "-d '" + _fund_body + "' "
                                "http://localhost:8000/api/v1/teg/treasury/fund-agent > /dev/null 2>&1",
                            ], 20)
                if _jwt and _did and _tag == "sentinel":
                    # §MCPTEST30 (V0639): the governance rules on an operator, not its posture. Under the operator's
                    # enforce posture the run's agent holds its birth roles (AGENT_RBAC_DEFAULT_ROLES, no gov.*), so
                    # castVote, tallyProposal and federationVoteProposal answered "Agent lacks required permission:
                    # gov.vote" and never reached the rule each row is for. The owner grants the sentinel `governor`
                    # for the run; the second agent keeps the posture's roles.
                    _run_roles["sentinel"] = await _grant_run_role(op.registry_container, dev_jwt, _did, "governor")
                    logger.info("cloud-op %s sentinel run role: %s" % (op.label, _run_roles["sentinel"]))
                # §CLOUDOPMCP 2026-09-04 — give the SENTINEL a stake and a
                # reputation bond. Two contracts assert on state that only exists
                # once the agent has actually done these things:
                #   estimateMyLockPayouts -> requires staked_amount / total_apy
                #   getMyReputationBondStatus -> 404 until a bond is posted
                # Funding alone is not enough; both were still failing with a
                # funded sentinel. Best-effort and non-fatal, exactly like the
                # funding above — if either refuses, the tool simply keeps failing
                # and says why, which is better than a fixture that pretends.
                if _jwt and _tag == "sentinel":
                    # §CLOUDOPMCP2 2026-09-05 — read the operator's OWN bond policy;
                    # the literal 50 that used to be passed below was refused with
                    # "The bond must be at least 250 SBXA (asked 50)", which left the
                    # sentinel unbonded and every bond-gated tool refusing it.
                    _bond_amt = await _required_bond_amount(op.registry_container)
                    if _bond_amt is None:
                        logger.warning("cloud-op %s reputation bond SKIPPED — bond policy "
                                       "unreadable; refusing to guess an amount", op.label)
                    _bond_steps = () if _bond_amt is None else (
                        ("theprotocol_depositReputationBond",
                         {"agent_jwt": _jwt, "amount": float(_bond_amt)},
                         f"reputation bond ({_bond_amt} from policy)"),
                    )
                    for _tool, _args, _what in ((
                        ("theprotocol_lockUnits",
                         {"agent_jwt": _jwt, "amount": "100"}, "stake"),
                        # ⚠ amount is REQUIRED by the wrapper (mcp/tools_agent.py:1401
                        # refuses a missing/zero amount), even though the REST route
                        # falls back to the policy amount when it is None. Omitting it
                        # here cost one measured 400 — and then hardcoding it cost
                        # another, from the opposite direction, once the policy moved.
                    ) + _bond_steps):
                        _swx = _switches.switched_off(_tool)
                        if _swx is not None:
                            # §MCPTEST30 (V0550): nothing to give the sentinel where the operator switched it off
                            logger.info("cloud-op %s sentinel %s: not asked, switched off here (%s)"
                                        % (op.label, _what, _swx.label()))
                            continue
                        try:
                            _ok_x, _bx, _cx = await _mcp_rpc_call(
                                cloud_target, _tool, _args, jwt=dev_jwt, timeout=20)
                            logger.info("cloud-op %s sentinel %s: http=%s"
                                        % (op.label, _what, _cx))
                        except Exception as _e:                          # noqa: BLE001
                            logger.warning("cloud-op %s sentinel %s failed "
                                           "(non-fatal): %r" % (op.label, _what, _e))
            except Exception as e:
                logger.warning(
                    "cloud-op %s %s bootstrap failed (non-fatal): %r" % (op.label, _tag, e))
                return "", "", ""
            return _did, _jwt, _aid

        sentinel_did, sentinel_jwt, sentinel_agent_id = await _bootstrap_cloudop_agent("sentinel")
        second_agent_did, second_agent_jwt, _second_aid = await _bootstrap_cloudop_agent("second")
        logger.info(
            "cloud-op %s sentinel bootstrap: did=%r jwt=%s agent_id=%r | second: did=%r jwt=%s"
            % (op.label, sentinel_did[:28], "yes" if sentinel_jwt else "NO", sentinel_agent_id,
               second_agent_did[:28], "yes" if second_agent_jwt else "NO"))

        # §CLOUDOPMCP 2026-09-04 — build an AGORA listing that exists HERE. The four
        # exchange READ contracts used to name a module constant
        # (_EXCHANGE_LISTING, from API_TEST_EXCHANGE_LISTING) which points at the
        # FRAME's listing, so on a cloud-op all four answered 404. They are fixtures
        # now; this supplies one. Chain is org -> listing -> ADMIN APPROVAL (the
        # wrapper's own docstring says "Awaits admin approval"), and every step is
        # best-effort: if any leg fails the fixture stays EMPTY and the contracts
        # skip as "fixture missing" rather than failing — an honest gap, not a
        # pretend pass.
        cloudop_listing = ""
        cloudop_org_id = ""
        cloudop_org_slug = ""
        cloudop_treasury_did = ""   # §MCPTEST30 (V0639): the listing's treasury agent, retired with the run's agents
        _cloudop_setup_rows: Dict[str, Dict[str, Any]] = {}   # §MCPTEST30 (V0641): the chain's own measured rows
        try:
            _oko, _ob, _oc = await _mcp_rpc_call(
                cloud_target, "theprotocol_createOrganization",
                {"name": "cloudop-fixture-%d" % int(time.time()),
                 "description": "MCP-tester AGORA fixture (cloud-op)"},
                jwt=dev_jwt, timeout=20)
            _org = _parse_rpc_result(_ob) if isinstance(_ob, dict) else {}
            _org_id = str(_org.get("id") or _org.get("organization_id") or "")
            # §EVTYPES5: this org was already being created and then dropped on the
            # floor — five org-read contracts skipped for `organization_id` while
            # the id sat in a local. Carry it out.
            cloudop_org_id = _org_id
            cloudop_org_slug = str(_org.get("slug") or _org.get("organization_slug") or "")
            _sym = "CO" + uuid.uuid4().hex[:4].upper()
            if _org_id and sentinel_did:
                _t_list = time.time()
                _okl, _lb, _lc = await _mcp_rpc_call(
                    cloud_target, "theprotocol_createAgoraListing",
                    {"organization_id": _org_id, "symbol": _sym,
                     "total_shares": 1000, "ipo_float": 100, "ipo_price": "1.0",
                     "funding_agent_did": sentinel_did,
                     "display_name": "Cloud-op fixture co"},
                    jwt=dev_jwt, timeout=25)
                # Approval is on the ADMIN bridge; without it the listing is not
                # readable and the reads would still 404.
                # ⚠ the arg is `listing_ref`, NOT `listing` (mcp/tools_admin.py:3357);
                # passing `listing` cost a measured 400 "listing_ref is required".
                # It accepts a listing id or $TICKER — prefer the id the create
                # returned, fall back to the ticker form.
                _lst = _parse_rpc_result(_lb) if isinstance(_lb, dict) else {}
                _cloudop_setup_rows["theprotocol_createAgoraListing"] = cloudop_listing_row(
                    _lc, _lst, int((time.time() - _t_list) * 1000))
                _ref = str(_lst.get("id") or _lst.get("listing_id") or ("$" + _sym))
                _oka, _ab, _ac = await _mcp_rpc_call_admin(
                    cloud_target, "theprotocol_adminAgoraApproveListing",
                    {"listing_ref": _ref}, jwt=dev_jwt, timeout=25)
                # Only claim the fixture when the listing is actually APPROVED —
                # an unapproved listing still 404s the reads, so reporting it here
                # would just move the failure somewhere less obvious.
                cloudop_treasury_did = str(_lst.get("treasury_agent_did") or "") if str(_lc).startswith("2") else ""
                cloudop_listing = _sym if (str(_lc).startswith("2")
                                           and str(_ac).startswith("2")) else ""
                logger.info("cloud-op %s AGORA fixture: org=%s symbol=%s "
                            "create=%s approve=%s -> listing=%r"
                            % (op.label, _org_id[:12], _sym, _lc, _ac, cloudop_listing))
            else:
                logger.warning("cloud-op %s AGORA fixture skipped: org_id=%r "
                               "sentinel=%r" % (op.label, _org_id, bool(sentinel_did)))
        except Exception as e:                                            # noqa: BLE001
            logger.warning("cloud-op %s AGORA fixture failed (non-fatal): %r"
                           % (op.label, e))
            cloudop_listing = ""

        # §CLOUDOPMCP 2026-09-04 — MEASURE the operator treasury; do not assume it.
        # Money-dependent contracts (transfer / stake / bond / exchange) cannot be
        # satisfied on an operator whose treasury is 0, and on a fresh cloud-op it IS
        # 0 because cross-TEG treasury funding is blocked (backlog B8: the receiving
        # TEG accepts only /service/teg-*, /service/registry-* or /operator/* SPIFFE
        # ids, and a provisioned frame has none of those). Marking these NOT
        # MEASURABLE with a named cause is honest; marking them FAILED is not, and
        # silently passing them would be worse. This is evidence-based and
        # self-healing: fund the treasury and they run again automatically.
        _op_treasury = None
        try:
            _rc_t, _out_t = await asyncio.to_thread(
                exec_in_container, op.registry_container, [
                    "sh", "-c",
                    "curl -sS -H 'Authorization: Bearer " + dev_jwt + "' "
                    "http://localhost:8000/api/v1/teg/treasury/balance",
                ], 20)
            if _rc_t == 0 and _out_t:
                _op_treasury = float(json.loads(_out_t).get("balance") or 0)
        except Exception as e:                                            # noqa: BLE001
            logger.warning("cloud-op %s treasury probe failed: %r" % (op.label, e))
        _treasury_empty = (_op_treasury is not None and _op_treasury <= 0)
        logger.info("cloud-op %s treasury=%s empty=%s"
                    % (op.label, _op_treasury, _treasury_empty))

        # Tools that cannot be satisfied without operator-side funds. Each was
        # MEASURED failing for exactly this reason on sbxalphaop/sbxbetaop.
        _MONEY_DEPENDENT_TOOLS = {
            "theprotocol_smartSend",                 # sender has 0 balance
            "theprotocol_estimateMyLockPayouts",  # nothing staked
            "theprotocol_getMyReputationBondStatus", # no bond can be posted
            "theprotocol_getAgoraListing",        # no listing: needs org+shares+funds
            "theprotocol_getAgoraOrderBook",
            "theprotocol_getAgoraTrades",
            "theprotocol_getAgoraCandles",
        }
        # Flag-gated on a cloud-op, and MATCHING PRODUCTION: A2A_DID_JWT_AUTOGEN is
        # unset on both cloud-op-sbxalphaop-registry AND prod agentvault_registry_a,
        # so an agent has no registered public key. The upstream body says so
        # verbatim; the MCP wrapper eats it (B6), hence the name-based set.
        _NO_AUTOGEN_TOOLS = {"theprotocol_getAgentPublicKey"}

        # Build the fixture bag. developer_id="1" because every provisioned
        # cloud-op seeds its admin as developer#1. A populated sentinel unblocks
        # Tier-2; if bootstrap failed, the empties keep the clean Phase-1 skips.
        bag = McpFixtureBag(
            sentinel_did=sentinel_did,
            sentinel_jwt=sentinel_jwt,
            sentinel_agent_id=sentinel_agent_id,
            second_agent_did=second_agent_did,
            second_agent_jwt=second_agent_jwt,
            # §CLOUDOPMCP 2026-09-04 — the OPERATOR's own admin, not the central
            # sandbox's. admin@test.sandbox does not exist on a cloud-op.
            admin_email=op.admin_email,
            admin_password=op.admin_password,
            # Empty when the fixture chain failed → the contracts skip as
            # "fixture missing" instead of asking for a listing that is not here.
            # NOTE: scratch_listing is deliberately NOT passed — it is not a
            # McpFixtureBag field (the write-side contracts that reference
            # ${scratch_listing} resolve it elsewhere and skip cleanly here).
            # Passing it raised McpFixtureBag.__init__() unexpected keyword.
            exchange_listing=cloudop_listing,
            developer_jwt=dev_jwt,
            developer_id="1",
            admin_jwt=dev_jwt,
            developer_jwt_nonadmin="",
            flow_values={},
        )
        _cloudop_fixtures: Dict[str, str] = {}
        # §GUILDDARK 2026-09-07 — subsystems that are OFF on this operator, measured
        # once per run rather than assumed. A fixture that cannot exist because the
        # feature is disabled is not a "fixture missing" — that message tells the next
        # reader to go build something the node will never accept.
        _cloudop_dark: Dict[str, str] = {}
        # §MCPTEST30 (V0545): a fixture the operator was ASKED for and does not hold, with the read that said so; a
        # tool waiting only on such fixtures skips as "unavailable: <why>", not as one somebody should go and build.
        _cloudop_unavailable: Dict[str, str] = {}

        # ── §EVTYPES5 2026-09-06 — publish the cloud-op's own fixtures ────────
        # WHY. 35 rows on this sweep skipped with "cloud-op fixture missing: [...]
        # (no sentinel agent — defer to Phase 2)". That parenthesis was STALE and
        # actively misleading: Phase 2 landed, the sentinel exists and holds a JWT
        # (the line above says so), and the real cause is that the cloud-op sweep
        # does not run phase-3 ENTITY setup at all. A message that names the wrong
        # cause is worse than none — it sends the next reader after a sentinel that
        # is already there. Same defect the phase-3 fixtures had this morning.
        #
        # Three of those fixtures needed no new call whatsoever: the sentinel's
        # client_id/secret were minted and discarded, and the organization was
        # created for the AGORA chain and left in a local. The rest here are
        # READ-ONLY harvests or free creates. Money-dependent fixtures are NOT
        # staged here. On 2026-09-04 the operator treasury was 0 and could not be
        # seeded (backlog B8); it is measured each run (`_treasury_empty` above),
        # and the guild's reason below says which cause holds on this run.
        try:
            if _boot_creds.get("sentinel"):
                _cloudop_fixtures["sentinel_client_id"] = _boot_creds["sentinel"]["client_id"]
                _cloudop_fixtures["sentinel_client_secret"] = _boot_creds["sentinel"]["client_secret"]
            if cloudop_org_id:
                _cloudop_fixtures["organization_id"] = cloudop_org_id
            if cloudop_org_slug:
                _cloudop_fixtures["organization_slug"] = cloudop_org_slug

            # §GUILDDARK: is the Guild even on here? MEASURED, not inferred from env
            # (a flag read is a claim about the carrier; the rail is the answer).
            # Frame sbx-alpha: 200 with real orders. Operator: 503 "The Guild is
            # disabled on this registry", GUILD_ENABLED unset. Six guild tools were
            # skipping as "fixture missing: ['guild_order_id']" — work nobody can do.
            _ok_g, _b_g, _ = await _mcp_rpc_call(
                cloud_target, "theprotocol_guildListOrders", {"limit": 1},
                jwt=dev_jwt, timeout=15)
            _g_txt = json.dumps(_b_g)[:400] if _b_g is not None else ""
            if "disabled on this registry" in _g_txt or "Guild is disabled" in _g_txt:
                _cloudop_dark["guild"] = (
                    "GUILD_ENABLED unset — The Guild is disabled on this registry "
                    "(MEASURED 503). The fixture cannot exist here at all; this is a "
                    "node-class difference, not missing setup.")
                logger.info("[MCP-CloudOp] guild subsystem DARK on %s (measured 503)", op.label)
            else:
                # ON, but that is not the same as usable: an operator's own order
                # table starts empty and `guildNetworkBoard` is a FEDERATED view, so
                # the ids it returns are other frames' — `GET /guild/orders/{id}`
                # answers 404 "Order not found" for them (measured 2026-09-07 on both
                # node classes). Publishing one would hand every guild contract an id
                # that cannot resolve, which is worse than the honest skip.
                _n_local = 0
                _gp = _parse_rpc_result(_b_g) if _ok_g else {}
                if isinstance(_gp, dict):
                    _n_local = len(_gp.get("orders") or [])
                if not _n_local:
                    # §MCPTEST30 (V0644): the cause named is the one this run measured. "The treasury cannot fund
                    # (B8)" was true on 2026-09-04 and stayed in the text after the operators' treasuries were
                    # funded (sbxalphaop read 292,937 on 2026-10-25), so the row blamed a cause that no longer held.
                    if _treasury_empty:
                        _why_none = "Posting one costs a bounty the operator treasury cannot fund (B8: it reads 0)"
                    else:
                        _why_none = ("this sweep stages no guild orders on an operator (a frame's phase-3 posts "
                                     "its own, each escrowing a bounty); the operator treasury reads "
                                     + ("unread" if _op_treasury is None else f"{_op_treasury:,.2f}")
                                     + ", so B8 is not the cause")
                    _cloudop_dark["guild"] = (
                        "the Guild is ENABLED here but this operator holds no orders of "
                        "its own (0 local), and network-board ids are federated — "
                        "`GET /guild/orders/{id}` answers 404 for them (measured). " + _why_none)

            # sample card: read-only harvest, exactly as phase-3 does centrally.
            _ok_lc, _b_lc, _ = await _mcp_rpc_call(
                cloud_target, "theprotocol_listAgentCards", {}, jwt=dev_jwt, timeout=15)
            _cards = _parse_rpc_result(_b_lc) if _ok_lc else {}
            _items = _cards.get("items", []) if isinstance(_cards, dict) else []
            if _items and isinstance(_items[0], dict) and _items[0].get("id"):
                _cid_card = str(_items[0]["id"])
                _cloudop_fixtures["sample_card_id"] = _cid_card
                _ok_c, _b_c, _ = await _mcp_rpc_call(
                    cloud_target, "theprotocol_getAgentCardById",
                    {"card_id": _cid_card}, jwt=dev_jwt, timeout=15)
                _full = _parse_rpc_result(_b_c) if _ok_c else {}
                _cd = _full.get("card_data") if isinstance(_full, dict) else None
                _hri = ((_cd.get("humanReadableId") or _cd.get("human_readable_id"))
                        if isinstance(_cd, dict) else None)
                if _hri:
                    _cloudop_fixtures["sample_card_hri"] = _hri
            # ⚠ the FIRST card is a lottery — on the run that added this block the
            # first card carried no humanReadableId and the fixture silently did
            # not publish. Walk a few until one yields an hri rather than trusting
            # the head of an unordered list.
            if "sample_card_hri" not in _cloudop_fixtures:
                for _cand in _items[1:5]:
                    if not (isinstance(_cand, dict) and _cand.get("id")):
                        continue
                    _ok_c2, _b_c2, _ = await _mcp_rpc_call(
                        cloud_target, "theprotocol_getAgentCardById",
                        {"card_id": str(_cand["id"])}, jwt=dev_jwt, timeout=15)
                    _f2 = _parse_rpc_result(_b_c2) if _ok_c2 else {}
                    _cd2 = _f2.get("card_data") if isinstance(_f2, dict) else None
                    _h2 = ((_cd2.get("humanReadableId") or _cd2.get("human_readable_id"))
                           if isinstance(_cd2, dict) else None)
                    if _h2:
                        _cloudop_fixtures["sample_card_hri"] = _h2
                        _cloudop_fixtures["sample_card_id"] = str(_cand["id"])
                        break

            # a webhook and two TEG policies: free creates, no money, and the same
            # shapes phase-3 makes centrally. FRESH policy codes per run — a fixed
            # code 409s forever once deleteTegPolicy soft-deletes it (measured on
            # the frame this morning; the operator would have inherited it).
            # §EVTYPES8 2026-09-06 — THE CREATE WAS COPIED FROM PHASE-3; THE CLEANUP
            # BESIDE IT WAS NOT. The backend caps a developer at 10 webhooks, every
            # sweep creates one, and nothing here ever deleted them — so the
            # operator's developer#1 filled up and `createWebhook` has been
            # answering 400 "Maximum 10 webhooks per developer" for an unknown
            # number of runs. `webhook_id` was therefore never published and
            # getWebhook / getWebhookDeliveries skipped as "fixture missing"
            # FOREVER, reported as a fixture gap rather than as the cap it is.
            # Measured directly on cloud-op-sbxalphaop before writing this.
            # Phase-3 has had exactly this cleanup since the frame hit the same
            # wall (see "0.5 Sandbox idempotency" above); this is that step,
            # ported. Best-effort and non-fatal: a failure to tidy must never
            # take down fixture publication.
            try:
                _ok_lw, _b_lw, _ = await _mcp_rpc_call(
                    cloud_target, "theprotocol_listDeveloperWebhooks", {},
                    jwt=dev_jwt, timeout=20)
                _lw = _parse_rpc_result(_b_lw) if _ok_lw else {}
                _existing = (_lw if isinstance(_lw, list)
                             else (_lw.get("webhooks") or _lw.get("items") or []))
                _swept = 0
                for _w in _existing if isinstance(_existing, list) else []:
                    _wid = _w.get("id") if isinstance(_w, dict) else None
                    if not _wid:
                        continue
                    _ok_d, _, _ = await _mcp_rpc_call(
                        cloud_target, "theprotocol_deleteWebhook",
                        {"webhook_id": str(_wid)}, jwt=dev_jwt, timeout=20)
                    _swept += 1 if _ok_d else 0
                logger.info("cloud-op %s webhook cleanup: %d existing, %d swept"
                            % (op.label, len(_existing) if isinstance(_existing, list) else 0, _swept))
            except Exception as e:                                    # noqa: BLE001
                logger.warning("cloud-op %s webhook cleanup raised (non-fatal): %r"
                               % (op.label, e))

            _ok_w, _b_w, _ = await _mcp_rpc_call(
                cloud_target, "theprotocol_createWebhook",
                # ⚠ the arg is `events`, not `event_types` — the schema says
                # required ["url", "events"], and the central phase-3 call above
                # uses the same shape. Checked against the schema before the
                # first call rather than after a measured 400.
                {"url": "https://webhook.example.test/cloudop-%d" % int(time.time()),
                 "events": ["agent.created", "agent.updated"],
                 "description": "MCP-tester cloud-op fixture"},
                jwt=dev_jwt, timeout=20)
            _wh = _parse_rpc_result(_b_w) if _ok_w else {}
            if isinstance(_wh, dict) and (_wh.get("id") or _wh.get("webhook_id")):
                _cloudop_fixtures["webhook_id"] = str(_wh.get("id") or _wh.get("webhook_id"))

            # a team under the org just created, a support ticket, an api key and
            # a bundle: all free, all shapes copied from the phase-3 setup that
            # already proves them on the frame. NOT copied: anything that needs a
            # balance (guild bounties, exchange orders, the a2a token, the
            # proposal's stake) — on this run the operator's stake answered 500
            # and its treasury is 0, so publishing those fixtures would convert
            # honest skips into failures, which is the worse trade.
            if cloudop_org_id:
                _ok_t, _b_t, _ = await _mcp_rpc_call(
                    cloud_target, "theprotocol_createOrganizationTeam",
                    {"org_id": cloudop_org_id, "name": "cloudop-team",
                     "description": "MCP-tester cloud-op team fixture"},
                    jwt=dev_jwt, timeout=20)
                _team = _parse_rpc_result(_b_t) if _ok_t else {}
                if isinstance(_team, dict) and _team.get("id"):
                    _cloudop_fixtures["team_id"] = str(_team["id"])

            _ok_s, _b_s, _ = await _mcp_rpc_call(
                cloud_target, "theprotocol_submitSupportTicket",
                {"subject": CLOUDOP_TICKET_SUBJECT,
                 "message": "Auto-created by the cloud-op MCP sweep. Ignore.",
                 "category": "general", "priority": "low"},
                jwt=dev_jwt, timeout=20)
            _tk = _parse_rpc_result(_b_s) if _ok_s else {}
            if isinstance(_tk, dict) and _tk.get("id"):
                _cloudop_fixtures["support_ticket_id"] = str(_tk["id"])

            # ⚠ the KEY itself is never stored — only its id. The plaintext is
            # shown once by design and a fixture has no business holding it.
            _ok_k, _b_k, _ = await _mcp_rpc_call(
                cloud_target, "theprotocol_createApiKey",
                {"key_name": CLOUDOP_KEY_NAME}, jwt=dev_jwt, timeout=20)
            _ak = _parse_rpc_result(_b_k) if _ok_k else {}
            if isinstance(_ak, dict) and (_ak.get("api_key_info") or {}).get("id"):
                _cloudop_fixtures["api_key_id"] = str(_ak["api_key_info"]["id"])

            if sentinel_did:
                _ok_b, _b_b, _ = await _mcp_rpc_call(
                    cloud_target, "theprotocol_createBundle",
                    {"bundle_data": {"agent_dids": [sentinel_did], "kind": "snapshot",
                                     "name": CLOUDOP_BUNDLE_NAME,
                                     "visibility": "private", "sign": True}},
                    jwt=dev_jwt, timeout=25)
                _bd = _parse_rpc_result(_b_b) if _ok_b else {}
                if isinstance(_bd, dict) and _bd.get("id"):
                    _cloudop_fixtures["bundle_id"] = str(_bd["id"])

            # templates are seeded, so this is a read-only pick.
            _ok_tp, _b_tp, _ = await _mcp_rpc_call(
                cloud_target, "theprotocol_listAgentTemplates", {}, jwt=dev_jwt, timeout=15)
            _tr = _parse_rpc_result(_b_tp) if _ok_tp else {}
            _tmpls = (_tr.get("templates") or _tr.get("items")) if isinstance(_tr, dict) else None
            if isinstance(_tmpls, list) and _tmpls and isinstance(_tmpls[0], dict):
                _tid = (_tmpls[0].get("template_id") or _tmpls[0].get("id")
                        or _tmpls[0].get("slug") or _tmpls[0].get("name"))
                if _tid:
                    _cloudop_fixtures["agent_template_id"] = str(_tid)

            # §MCPTEST30 (V0640): an active circuit for the attestation schedule lifecycle, read-only like the template
            _circ, _no_circ = await cloudop_pick_circuit(_mcp_rpc_call, cloud_target, dev_jwt)
            if _circ:
                _cloudop_fixtures["circuit_id"] = _circ
            elif _no_circ:
                _cloudop_unavailable["circuit_id"] = _no_circ

            # §MCPTEST30 (V0545): a proposal the operator already holds, a read-only pick like the template above
            _pid, _no_pid = await cloudop_pick_proposal(_mcp_rpc_call, cloud_target, dev_jwt)
            if _pid:
                _cloudop_fixtures["proposal_id"] = _pid
            elif _no_pid:
                _cloudop_unavailable["proposal_id"] = _no_pid
            # §MCPTEST30 (V0640): the vote and the premature tally on a proposal of the run's own, still open; the pick
            # stays the reads' fallback, and where none opens the governance lifecycle says why on both rows
            _own_pid, _own_why = await cloudop_open_own_proposal(op.registry_container, sentinel_jwt)
            if _own_pid:
                _cloudop_fixtures["proposal_id"] = _own_pid
                _cloudop_unavailable.pop("proposal_id", None)
            else:
                _cloudop_fixtures["proposal_vote_unavailable"] = _own_why

            # §MCPTEST30 (V0545): a staking distribution the operator already ran, read-only like the proposal
            async def _op_call(tool, args, jwt):
                _ok_x, _b_x, _ = await _mcp_rpc_call(cloud_target, tool, args, jwt=jwt, timeout=15)
                return _parse_rpc_result(_b_x) if _ok_x else {}
            _dist = await staking_distribution_pick(_op_call, dev_jwt)
            if _dist:
                _cloudop_fixtures["distribution_id"] = _dist

            # §MCPTEST30 (V0641): the read/update subject through createTegPolicy, the delete subject through
            # createTegPoliciesBatch (one policy), and each answer is its tool's row, as the AGORA chain's above
            for _slot, _code, _tool in (
                    ("teg_policy_id", "COR" + uuid.uuid4().hex[:4].upper(), "theprotocol_createTegPolicy"),
                    ("teg_policy_id_del", "COD" + uuid.uuid4().hex[:4].upper(), "theprotocol_createTegPoliciesBatch")):
                _one = teg_policy_batch_policy(_code, CLOUDOP_POLICY_NAME % _slot, "MCP-tester cloud-op throwaway policy")
                _t_pol = time.time()
                _ok_p, _b_p, _c_p = await _mcp_rpc_call(
                    cloud_target, _tool, {"policies": [_one]} if _tool.endswith("Batch") else _one,
                    jwt=dev_jwt, timeout=20)
                _pol = _parse_rpc_result(_b_p) if _ok_p else {}
                _cloudop_setup_rows[_tool] = cloudop_policy_row(_tool, _c_p, _pol, int((time.time() - _t_pol) * 1000))
                _pid = (teg_policy_batch_id(_pol) if _tool.endswith("Batch") else
                        str((_pol.get("policy_id") or _pol.get("id") or "") if isinstance(_pol, dict) else ""))
                if _pid:
                    _cloudop_fixtures[_slot] = _pid
        except Exception as e:                                            # noqa: BLE001
            logger.warning("cloud-op %s fixture publication raised (non-fatal): %r"
                           % (op.label, e))
        bag.flow_values.update(_cloudop_fixtures)
        logger.info("cloud-op %s published fixtures: %s"
                    % (op.label, sorted(_cloudop_fixtures)))

        # §MCPTEST30 (V0637): the earned lifecycles on the operator itself (BACKLOG_2026-10-19_MCP_REFUSAL_ONLY_PASSES.md,
        # the cloud-operator item). Until now this sweep ran no lifecycle at all, so a tool an earned lifecycle measures on
        # the frame read here only what its contract asks: a refusal on a made-up id, or a named skip. The earned
        # lifecycles make their own subjects through the two bridges and clear them away, so they run on an operator as on
        # a frame, given an operator's bag: its own admin bridge, a throwaway developer registered on it (with an invite
        # from its admin where it registers only with one), and no lifecycle that needs what an operator cannot give
        # (operator_lifecycles names it and why). Event checks are not made here: an operator's events land in its parent
        # frame's store, so bag.event_verifier stays unset.
        # §EVTYPES5 — say which posture this run measured, before it measures it. §MCPTEST30 (V0637): read before the
        # earned lifecycles and handed to them (bag.target_posture): a refusal that is the agent permission check's is
        # not measured where the operator does not enforce it (the sandbox operators set neither mode, 2026-10-24)
        _posture = await _read_posture(op.registry_container)
        _posture_notes = _posture_complaints(_posture)
        logger.info("cloud-op %s posture: %s" % (op.label, _posture))
        for _c in _posture_notes:
            logger.warning("cloud-op %s posture: %s" % (op.label, _c))
        bag.target_posture = dict(_posture)  # type: ignore[attr-defined]
        lifecycle_outcomes: Dict[str, Dict[str, Any]] = {}
        # §MCPTEST30 (V0641): the AGORA fixture chain's own measured rows decide their tools, as a lifecycle's do
        lifecycle_outcomes.update(_cloudop_setup_rows)
        _cop_lc_not_run: Dict[str, str] = {}
        _cop_lc_run: List[str] = []

        async def _rpc_cloudop_lc(tool: str, args: dict, jwt: str = "", timeout: int = 20):
            return await _mcp_rpc_call(cloud_target, tool, args, jwt=(jwt or dev_jwt), timeout=timeout)

        async def _rpc_admin_cloudop_lc(tool: str, args: dict, jwt: str = "", timeout: int = 20):
            return await _mcp_rpc_call_admin(cloud_target, tool, args, jwt=(jwt or dev_jwt), timeout=timeout)

        _cop_reg_cfg: Dict[str, Any] = {}
        try:
            _rcc, _rct = await _http_in_target(op.registry_container, "GET", "/api/v1/auth/registration-config")
            _cop_reg_cfg = json.loads(_rct) if _rcc == "200" and _rct else {}
        except Exception:  # noqa: BLE001 — an unread rule means no invite is asked for; the mint then says why
            _cop_reg_cfg = {}
        _cop_invite = None
        if isinstance(_cop_reg_cfg, dict) and _cop_reg_cfg.get("beta_invite_required"):
            async def _ask_operator_invite():
                return await cloudop_invite(_rpc_admin_cloudop_lc, dev_jwt)
            _cop_invite = _ask_operator_invite
        bag.rpc_admin = _rpc_admin_cloudop_lc  # type: ignore[assignment]
        bag.admin_lifecycle_rows = {}  # type: ignore[assignment]
        bag.http_in_target = functools.partial(_http_in_target, op.registry_container)  # type: ignore[assignment]
        bag.dev_login = functools.partial(_dev_login, op.registry_container)  # type: ignore[assignment]
        bag.mint_throwaway = functools.partial(  # type: ignore[assignment]
            _mint_throwaway_developer, op.registry_container, invite=_cop_invite)
        bag.registration_invite = _cop_invite  # type: ignore[attr-defined]   # a lifecycle's own authRegister
        # §MCPTEST30 (V0639): the account lifecycle_self_account_on_throwaway acts on (2FA, password change, logout,
        # deletion request and cancel, on an account the sweep owns, never the runner). The frame's bootstrap mints it
        # (_bootstrap_fixtures); the operator sweep built its bag without one, so on an operator those tools were NOT
        # MEASURED or passed on a refusal alone (authValidate2FA, authRecover2FA, verify2FA in the wide list). The
        # lifecycle ends with the account asking for its own deletion.
        if not (bag.self_subject or {}).get("access_token"):
            bag.self_subject = await _mint_throwaway_developer(op.registry_container, "self", invite=_cop_invite)
            if not bag.self_subject.get("access_token"):
                logger.warning("cloud-op %s self-account subject unavailable (%s); those tools stay NOT MEASURED"
                               % (op.label, bag.self_subject.get("why")))
        # §MCPTEST30 (V0641): the second owner the chat lifecycle needs (a knock takes two owners; the frame's bootstrap
        # logs in a second seeded developer, which an operator has not), a throwaway the sweep registers on the operator
        # and that asks for its own deletion after the lifecycles: sendChatMessage and respondChatRequest passed on a
        # made-up conversation alone on both operators (V0640's previews, 2026-10-24/25)
        _chat_owner: Dict[str, Any] = {}
        if not getattr(bag, "developer_jwt_nonadmin2", ""):
            _chat_owner = await _mint_throwaway_developer(op.registry_container, "chat", invite=_cop_invite)
            if _chat_owner.get("access_token"):
                bag.developer_jwt_nonadmin2 = _chat_owner["access_token"]  # type: ignore[attr-defined]
            else:
                logger.warning("cloud-op %s chat second owner unavailable (%s); the chat lifecycle says so"
                               % (op.label, _chat_owner.get("why")))
        # §MCPTEST30 (V0639): whether the OPERATOR mounts the sandbox webhook sink, asked of the operator itself (this
        # process's flag is the frame's): mcp_lifecycles._webhook_sink_url reads it
        bag.target_webhook_sink = await _probe_webhook_sink(op.registry_container)  # type: ignore[attr-defined]
        # §MCPTEST30 (V0638/V0639): mcp_lifecycles' own lifecycles too, not only the earned lists (the operators' 171
        # refusal-only passes per run were mostly tools they measure on the frames), but those that probe a tool acting
        # on the operator itself (cloudop_lifecycle_list). The operator's own database is asked in its database
        # container (bag.target_db), so the lifecycles that read the target's database run here too
        bag.rpc_raw = functools.partial(_mcp_rpc_raw, cloud_target)  # type: ignore[assignment]
        _cop_offers = set(CLOUDOP_OFFERS)
        if op.db_container:
            bag.target_db = functools.partial(_db_in_target, op.db_container)  # type: ignore[attr-defined]
        else:
            _cop_offers.discard("target_db")
        try:
            _cop_lcs, _cop_lc_not_run = operator_lifecycles(cloudop_lifecycle_list(), offers=_cop_offers)
        except Exception as e:  # noqa: BLE001
            _cop_lcs, _cop_lc_not_run = [], {"(all)": f"the earned lifecycles could not be loaded: {type(e).__name__}"}

        async def _run_cop_lifecycle(lc):
            try:
                await lc["runner"](_rpc_cloudop_lc, _parse_rpc_result, bag, lifecycle_outcomes)
                _cop_lc_run.append(str(lc.get("name")))
            except Exception as e:  # noqa: BLE001
                logger.warning(f"cloud-op {op.label} lifecycle {lc.get('name')} raised: {e!r}")
            return None
        await _bounded_sweep(_cop_lcs, _run_cop_lifecycle, concurrency=_lifecycle_concurrency())
        if _chat_owner.get("email") and _chat_owner.get("password"):
            # §MCPTEST30 (V0641): the chat lifecycle's second owner asks for its own deletion (its agents went with
            # the lifecycle, their balances back to the treasury first)
            from agentvault_registry.api_tests.contracts.mcp_lifecycles import _schedule_own_deletion
            await _schedule_own_deletion(_rpc_cloudop_lc, bag, _chat_owner["email"], _chat_owner["password"],
                                         "chat second owner")
        logger.info("cloud-op %s earned lifecycles: %d run, not run here: %s; %d rows, %d admin rows"
                    % (op.label, len(_cop_lc_run), _cop_lc_not_run, len(lifecycle_outcomes),
                       len(getattr(bag, "admin_lifecycle_rows", None) or {})))
        # the central sweep's re-mint after its lifecycle phase (§MCPTEST-MCP4), for the operator's admin: a lifecycle
        # that ends sessions must not leave the sweep below on a dead credential
        _rlc, _rlt = await _dev_login(op.registry_container, op.admin_email, op.admin_password)
        if str(_rlc).startswith("2") and _rlt.get("access_token"):
            dev_jwt = _rlt["access_token"]
            bag.developer_jwt = dev_jwt
            bag.admin_jwt = dev_jwt
        else:
            logger.error("cloud-op %s could not log its admin in again after the lifecycles (HTTP %s)"
                         % (op.label, _rlc))

        # §EVTYPES5: the posture this run measured was read above, before the earned lifecycles (§MCPTEST30 V0637)

        # 3. tools/list — public bridge
        ok_list, tools, code = await _mcp_rpc_list_tools(cloud_target, jwt=dev_jwt)
        if not ok_list:
            return {
                "flow_name": f"flow_mcp_lifecycle_cloudop_{op.label}_complete",
                "success": False, "total_steps": 0, "successful_steps": 0,
                "error": f"cloud-op tools/list failed: {code}",
                "results": [], "flow_values": {"operator": op.label},
            }
        logger.info(f"cloud-op {op.label} public tools/list: {len(tools)}")
        _listing_words_found: Dict[str, Any] = {"public": _listing_words(tools)}   # §MCPTEST30 W6

        # 4. Per-tool sweep (reduced — no lifecycle_outcomes, no setup_outcomes,
        # no F.1/F.3/F.4/F.5, no orphan sweep).
        outcomes: List[ContractOutcome] = []
        _census_token = credential_exposure.begin()   # §MCPTEST30: every response of this cloud-op run is scanned
        _shape_token = result_shape.begin()           # §MCPTEST30: and read for the protocol's shape
        _words_token = _words.begin()                 # §MCPTEST30 W6: and for the critical words
        async def _cloudop_one_public(tool):
            _out: List[ContractOutcome] = []
            tool_name = tool.get("name") if isinstance(tool, dict) else None
            if not tool_name:
                return _out

            # §MCPTEST30 (V0637): an earned lifecycle's row decides the tool, as in the central sweep, unless the
            # tool's contract pins a refusal (override_coverage_fan: the success is kept as `earned: <tool>` below)
            if tool_name in lifecycle_outcomes and not get_contract(tool_name).override_coverage_fan:
                d = _fan_row_verdict(lifecycle_outcomes[tool_name], tool_name)
                _out.append(ContractOutcome(
                    tool_name=d["tool_name"],
                    contract_tier=d["contract_tier"],
                    healthy=d["healthy"],
                    status_code=d["status_code"],
                    elapsed_ms=d["elapsed_ms"],
                    skip_reason=d["skip_reason"],
                    fail_reason=d["fail_reason"],
                    has_explicit_contract=(tool_name in MCP_CONTRACTS),
                    args_used=d.get("args_used") or {},
                    result_excerpt=d.get("result_excerpt") or {},
                ))
                return _out

            contract = get_contract(tool_name)
            has_explicit = (tool_name in MCP_CONTRACTS) or (tool_name in _autogen_keys())

            # PHASE 1 default-contract gate (same as central sweep)
            if not has_explicit:
                input_schema = tool.get("inputSchema") if isinstance(tool, dict) else None
                required_params = (input_schema or {}).get("required") if isinstance(input_schema, dict) else None
                if required_params:
                    contract = McpContract(
                        tier="1",
                        skip_reason=f"default contract: tool has required params {required_params!r} — add explicit contract",
                    )

            args = resolve_args(contract.arguments, bag)
            unresolved = unresolved_fixtures(args)
            if unresolved:
                contract = McpContract(
                    tier=contract.tier,
                    # §EVTYPES5: the old text said "no sentinel agent — defer to
                    # Phase 2". Phase 2 landed; the sentinel is bootstrapped a
                    # few hundred lines above and the log line proves it. Name
                    # the real cause instead: this sweep runs no phase-3 entity
                    # setup, and the money-dependent half of it CANNOT run while
                    # the operator treasury is 0 (backlog B8).
                    # §GUILDDARK: name the REAL cause when the subsystem is off. "fixture missing" implies someone
                    # should build one; on an operator with the Guild dark, no fixture can ever exist (V0545: nor
                    # one the operator was asked for and does not hold).
                    skip_reason=cloudop_fixture_skip(tool_name, unresolved, _cloudop_dark, _cloudop_unavailable),
                )

            # M Phase 1 lite cleanup (§pass73.3.3): tier-2 tools require an
            # agent JWT that cloud-op doesn't have until Phase 2 bootstrap.
            # Skip them cleanly instead of letting the 401 surface as a fail.
            if contract.tier == "2" and not bag.sentinel_jwt:
                contract = McpContract(
                    tier="2",
                    skip_reason="cloud-op tier-2 fixture missing: no sentinel JWT (Phase 2 — synthetic agent bootstrap)",
                )

            if contract.tier == "2":
                # Reachable only if Phase 2 lands a sentinel — inline-pass it.
                jwt_for_call = dev_jwt
                args.setdefault("agent_jwt", bag.sentinel_jwt)
            else:
                jwt_for_call = dev_jwt

            t0 = time.time()
            if contract.skip_reason:
                _out.append(ContractOutcome(
                    tool_name=tool_name,
                    contract_tier=contract.tier,
                    healthy=False,
                    status_code=0,
                    elapsed_ms=0,
                    skip_reason=contract.skip_reason,
                    fail_reason=None,
                    has_explicit_contract=has_explicit,
                    args_used=args,
                    result_excerpt={},
                ))
                return _out

            try:
                ok, body_r, code_r = await _mcp_rpc_call(
                    cloud_target, tool_name, args, jwt=jwt_for_call, timeout=15,
                )
            except Exception as e:
                _out.append(ContractOutcome(
                    tool_name=tool_name,
                    contract_tier=contract.tier,
                    healthy=False,
                    status_code=0,
                    elapsed_ms=int((time.time() - t0) * 1000),
                    skip_reason=None,
                    fail_reason=f"exception: {e!r}",
                    has_explicit_contract=has_explicit,
                    args_used=args,
                    result_excerpt={},
                ))
                return _out
            elapsed_ms = int((time.time() - t0) * 1000)
            # §MCPTEST-MCP10 — transport-timeout retry BEFORE classification.
            ok, body_r, code_r = await _retry_transport_timeout(
                _mcp_rpc_call, cloud_target, tool_name, args, jwt_for_call,
                ok, body_r, code_r,
            )
            ok_eval, fail_eval = _evaluate_contract(
                tool, contract, ok, code_r, body_r, bag,
                has_explicit_contract=has_explicit,
            )
            inner = _parse_rpc_result(body_r) if isinstance(body_r, dict) else {}
            _out.append(ContractOutcome(
                tool_name=tool_name,
                contract_tier=contract.tier,
                healthy=ok_eval,
                status_code=int(code_r) if code_r.isdigit() else 0,
                elapsed_ms=elapsed_ms,
                skip_reason=None,
                fail_reason=fail_eval,
                has_explicit_contract=has_explicit,
                args_used=args,
                result_excerpt=result_excerpt(inner),
            ))
            return _out

        for _buck in await _bounded_sweep(
            tools, _cloudop_one_public, concurrency=_cloudop_sweep_concurrency(),
        ):
            outcomes.extend(_buck)
        # §MCPTEST30 (V0637): the earned lifecycles' rows that name no tool (`refusal: `, `admin_effect: `) and a success
        # measured where the tool's contract pins a refusal (`earned: <tool>`), kept as the central sweep keeps them
        _cop_listed = {t.get("name") for t in tools if isinstance(t, dict)}
        for _lname, _d in kept_lifecycle_rows(lifecycle_outcomes, _cop_listed, {o.tool_name for o in outcomes},
                                              lambda n: bool(get_contract(n).override_coverage_fan)):
            outcomes.append(ContractOutcome(
                tool_name=_lname, contract_tier=_d.get("contract_tier") or "protocol",
                healthy=bool(_d.get("healthy")), status_code=int(_d.get("status_code") or 0),
                elapsed_ms=int(_d.get("elapsed_ms") or 0), skip_reason=_d.get("skip_reason"),
                fail_reason=_d.get("fail_reason"), has_explicit_contract=True,
                args_used={}, result_excerpt=_d.get("result_excerpt") or {},
            ))

        public_tool_total = len(tools)

        # 5. Admin bridge sweep — cloud-op admin has admin tier on its own
        # bridge (same auth model as central sandbox commander).
        ok_admin_list, admin_tools, admin_code = await _mcp_rpc_list_tools_admin(
            cloud_target, jwt=dev_jwt,
        )
        # §CLOUDOPMCP 2026-09-04 — retry once. MEASURED: this exec intermittently
        # returns rc=127 when issued straight after the 435-tool public sweep, while
        # the identical helper call standalone returns 321 tools every time. Treated
        # as a transient docker-exec failure under concurrency, not an empty surface.
        if not ok_admin_list:
            await asyncio.sleep(3)
            ok_admin_list, admin_tools, admin_code = await _mcp_rpc_list_tools_admin(
                cloud_target, jwt=dev_jwt,
            )
        if ok_admin_list:
            _listing_words_found["admin"] = _listing_words(admin_tools)   # §MCPTEST30 W6
        if not ok_admin_list:
            logger.warning(f"cloud-op {op.label} admin tools/list failed: {admin_code}")
            admin_tools = []
            # 🔴 Do NOT let this pass as "this operator has no admin surface". A
            # listing transport failure silently removed 321 of 756 tools (42%) from
            # the sweep while the flow still reported success — an instrument that
            # fails quietly and reports a smaller universe as if it were complete.
            # Record it as an explicit NOT-MEASURED failure so the number is honest.
            _admin_list_failed = True
        else:
            _admin_list_failed = False
            logger.info(f"cloud-op {op.label} admin tools/list: {len(admin_tools)}")

        # §pass73.3.21: run the admin lifecycles against the cloud-op ADMIN bridge so
        # the 302 admin tools get the SAME reachability coverage the central sweep gives
        # them (fake-id phase-6 sweep — registry-agnostic + side-effect-free). Cloud-op
        # previously skipped these as "admin contract_gap" (~169 skips); that was a
        # coverage gap vs central, NOT a stricter bar (central has no expect_keys for
        # them either — it covers them via these same lifecycles). Mirrors central ~L2196-2252.
        try:
            from agentvault_registry.api_tests.contracts.mcp_admin_lifecycles import (  # type: ignore
                ADMIN_LIFECYCLES as _CLOUDOP_ADMIN_LIFECYCLES,
            )
        except ImportError:
            _CLOUDOP_ADMIN_LIFECYCLES = []
        admin_lifecycle_outcomes: Dict[str, Dict[str, Any]] = {}
        # §MCPTEST30 (V0637): the admin rows the earned lifecycles recorded through bag.rpc_admin, first, as the central
        # sweep has them: the reachability probes below leave a tool already measured for real alone
        admin_lifecycle_outcomes.update(getattr(bag, "admin_lifecycle_rows", None) or {})

        def _rpc_admin_cloudop(tool: str, args: dict, jwt: str = "", timeout: int = 20):
            return _mcp_rpc_call_admin(cloud_target, tool, args, jwt=(jwt or dev_jwt), timeout=timeout)

        for _lc in _CLOUDOP_ADMIN_LIFECYCLES:
            try:
                await _lc["runner"](_rpc_admin_cloudop, _parse_rpc_result, bag, admin_lifecycle_outcomes)
            except Exception as e:
                logger.warning(f"cloud-op {op.label} admin lifecycle {_lc.get('name')} raised: {e!r}")
        logger.info(f"cloud-op {op.label} admin lifecycle outcomes: {len(admin_lifecycle_outcomes)}")

        async def _cloudop_one_admin(tool):
            _out: List[ContractOutcome] = []
            tool_name = tool.get("name") if isinstance(tool, dict) else None
            if not tool_name:
                return _out
            # §pass73.3.21: lifecycle outcome (reachability) takes priority over the
            # contract_gap skip below — exact parity with the central admin sweep.
            # §MCPTEST30 (2026-10-01): an override contract wins only where its fixture resolved on THIS operator (the
            # harvest publishes the ids the node has). Where it did not, the operator keeps its reachability row, and
            # a contract without a fan row is a named skip below, never a call with a literal `${fixture}`.
            _cop_ov = get_contract(tool_name)
            _cop_unres = unresolved_fixtures(resolve_args(_cop_ov.arguments, bag)) if _cop_ov.override_coverage_fan else []
            if tool_name in admin_lifecycle_outcomes and (not _cop_ov.override_coverage_fan or _cop_unres):
                _d = _fan_row_verdict(admin_lifecycle_outcomes[tool_name], tool_name)
                if _cop_unres and _d.get("skip_reason"):
                    _d["skip_reason"] = (
                        f"fixture missing on this operator: {_cop_unres!r}: it has no such row, so the success path is "
                        f"not measured here; the only call was a deliberately-invalid id (HTTP {_d['status_code']})")
                _out.append(ContractOutcome(
                    tool_name=_d["tool_name"],
                    contract_tier="admin-bridge",
                    healthy=_d["healthy"],
                    status_code=_d["status_code"],
                    elapsed_ms=_d["elapsed_ms"],
                    skip_reason=_d["skip_reason"],
                    fail_reason=_d["fail_reason"],
                    has_explicit_contract=(tool_name in MCP_CONTRACTS),   # §FANCLAIM
                    args_used=_d.get("args_used") or {},
                    result_excerpt=_d.get("result_excerpt") or {},
                ))
                return _out
            # §MCPADMSKIP-2 2026-09-07 — THE SECOND CONSUMER. The cloud-op flow has
            # its own admin sweep, so fixing the central one moved nothing here: this
            # path skips a tool with no expect_keys as a "contract gap" and CALLS
            # everything else, both without reading the contract's own skip_reason.
            # `getAdminFundingPending` is the case that proves it — a declared skip
            # ("no pagination, returns ALL pending", still true of the route) plus
            # expect_keys, so it was called on every cloud-op run. Same field, same
            # class, second consumer; a fix aimed at one copy of a duplicated sweep
            # looks exactly like a fix that did not work.
            _cop_contract = get_contract(tool_name)
            if _cop_contract.skip_reason:
                _out.append(ContractOutcome(
                    tool_name=tool_name,
                    contract_tier="admin-bridge",
                    healthy=False,
                    status_code=0,
                    elapsed_ms=0,
                    skip_reason=_cop_contract.skip_reason,
                    fail_reason=None,
                    has_explicit_contract=True,
                    args_used={},
                    result_excerpt={},
                ))
                return _out
            admin_default = (
                get_contract(tool_name)
                if tool_name in MCP_CONTRACTS or tool_name in _autogen_keys()
                else McpContract(tier="admin", expect_status="success")
            )
            if not admin_default.expect_keys:
                from agentvault_registry.api_tests.contracts.mcp_contracts import (  # type: ignore
                    _augment_contract_with_schema,
                )
                admin_default = _augment_contract_with_schema(admin_default, tool_name)
            adm_args = resolve_args(admin_default.arguments, bag)
            try:
                input_schema = tool.get("inputSchema") if isinstance(tool, dict) else None
                req_params = (input_schema or {}).get("required") or []
                for p in req_params:
                    if p in adm_args:
                        continue
                    # Cloud-op has no sentinel — best-effort defaults
                    if p in ("agent_did", "did"):
                        adm_args[p] = ""
                    elif p == "developer_id":
                        adm_args[p] = _resolve_developer_id_param(tool_name)
                    elif p == "event_type":
                        adm_args[p] = "TokensTransferred"
            except Exception:
                pass
            # §MCPTEST30 (2026-10-01): the central walk's rule (§TESTBED), which this walk never had: a `${fixture}`
            # still in the arguments is a named skip. A call with the literal measured the tester, not the operator.
            _cop_unres_args = unresolved_fixtures(adm_args)
            if _cop_unres_args:
                _out.append(ContractOutcome(
                    tool_name=tool_name, contract_tier="admin-bridge", healthy=False, status_code=0, elapsed_ms=0,
                    skip_reason=(f"fixture missing on this operator: {_cop_unres_args!r}: it has no such row, so the "
                                 f"tool was not called with a placeholder"),
                    fail_reason=None, has_explicit_contract=(tool_name in MCP_CONTRACTS), args_used={},
                    result_excerpt={},
                ))
                return _out

            # M Phase 1 lite cleanup (§pass73.3.3): if neither the explicit
            # contract nor the live outputSchema yields any expect_keys, this
            # is a true contract gap for cloud-op admin tier. Cloud-op admin
            # contract synthesis is Phase 2 work. Skip cleanly instead of
            # letting it surface as a hard fail.
            # §MCPTEST30 (V0551): a refusal pin is judged, never a gap (_cloudop_admin_contract_gap).
            if _cloudop_admin_contract_gap(admin_default):
                _out.append(ContractOutcome(
                    tool_name=tool_name,
                    contract_tier="admin-bridge",
                    healthy=False,
                    status_code=0,
                    elapsed_ms=0,
                    skip_reason="cloud-op admin contract_gap — no expect_keys nor outputSchema.required (Phase 2 — admin contract synthesis)",
                    fail_reason=None,
                    has_explicit_contract=False,
                    args_used=adm_args,
                    result_excerpt={},
                ))
                return _out

            t0 = time.time()
            ok_a, body_a, code_a = await _mcp_rpc_call_admin(
                cloud_target, tool_name, adm_args, jwt=dev_jwt, timeout=15,
            )
            elapsed_ms = int((time.time() - t0) * 1000)
            inner_a = _parse_rpc_result(body_a) if isinstance(body_a, dict) else {}
            # §MCPTEST-MCP10 — transport-timeout retry BEFORE classification.
            ok_a, body_a, code_a = await _retry_transport_timeout(
                _mcp_rpc_call_admin, cloud_target, tool_name, adm_args, dev_jwt,
                ok_a, body_a, code_a,
            )
            ok_eval, fail_eval = _evaluate_contract(
                tool, admin_default, ok_a, code_a, body_a, bag,
                has_explicit_contract=bool(admin_default.expect_keys),
            )
            _out.append(ContractOutcome(
                tool_name=tool_name,
                contract_tier="admin-bridge",
                healthy=ok_eval,
                status_code=int(code_a) if code_a.isdigit() else 0,
                elapsed_ms=elapsed_ms,
                skip_reason=None,
                fail_reason=fail_eval,
                has_explicit_contract=(tool_name in MCP_CONTRACTS),   # §MCPTEST30, as the central walk
                args_used=adm_args,
                result_excerpt=result_excerpt(inner_a, shape_only=admin_default.excerpt_shape_only),
            ))
            return _out

        for _buck in await _bounded_sweep(
            admin_tools, _cloudop_one_admin, concurrency=_cloudop_sweep_concurrency(),
        ):
            outcomes.extend(_buck)
        # §MCPTEST30 (V0637): and the admin lifecycle rows that name no tool, or a success where a pin refuses
        _cop_adm_listed = {t.get("name") for t in admin_tools if isinstance(t, dict)}
        for _lname, _d in kept_lifecycle_rows(admin_lifecycle_outcomes, _cop_adm_listed, {o.tool_name for o in outcomes},
                                              lambda n: bool(get_contract(n).override_coverage_fan)):
            outcomes.append(ContractOutcome(
                tool_name=_lname, contract_tier=_d.get("contract_tier") or "admin_effect",
                healthy=bool(_d.get("healthy")), status_code=int(_d.get("status_code") or 0),
                elapsed_ms=int(_d.get("elapsed_ms") or 0), skip_reason=_d.get("skip_reason"),
                fail_reason=_d.get("fail_reason"), has_explicit_contract=True,
                args_used={}, result_excerpt=_d.get("result_excerpt") or {},
            ))

        # §pass73.3.21: cloud-op tier-gating reclassification. A consumer cloud-op
        # legitimately LACKS sovereign-mainframe-only features (operator/frame/license
        # management, fiat onramp, bridge mint, treasury mint, cross-frame ES). Those
        # endpoints self-identify via a 503/404/403 whose body says "runs on sovereign
        # mainframes only" / "mainframe admins use" / "fiat onramp is mainframe" /
        # "is for cloud-ops only". Reclassify ONLY those self-identifying failures as
        # tier-gated SKIPs (not defects) — parity with how the central suite skips
        # cloud-op-only tools. A generic 5xx with NO self-identifying message stays a
        # FAIL (never blanket-tolerate 5xx — a real ES/TEG outage must still surface).
        # §MCPTEST30: the sentences that say a tool is mainframe-only BY CONSTRUCTION (module level since V0641)
        _BY_CONSTRUCTION_MARKERS = CLOUDOP_BY_CONSTRUCTION_MARKERS
        _verified_refusals = 0
        _GATE_MARKERS = CLOUDOP_GATE_MARKERS   # module level since V0524, so a test can hold the phrases
        # §CLOUDOPMCP 2026-09-04 — STILL LOAD-BEARING AFTER B6. Do not delete on the
        # strength of the OPEN-ITEMS line that says B6 made this readable: RE-MEASURED
        # 2026-09-05 on cloud-op-sbxalphaop, on the image that carries B6, both tools
        # still answer a bare swallowed envelope:
        #     getForgeStatus      /mcp/rpc        -> "Error: getForgeStatus returned HTTP 403"
        #     getDiagnosticConfig /mcp/admin/rpc  -> "Error: …/diagnostics/config/registry returned HTTP 404"
        # so no _GATE_MARKERS phrase can match, and deleting this set turns two
        # correctly-gated tools into false FAILs.
        # WHY B6 did not reach them — they are on two lanes it did not convert:
        #   · getForgeStatus is PUBLIC (tools_discovery._public_get). That helper DOES
        #     attach the RFC7807 body, but under the key `error`, so server.py's
        #     formatter renders isError+text and drops the rest. Exactly the B6 class,
        #     never fixed in the public lane.
        #   · getDiagnosticConfig is ADMIN, but tools_admin.py:803 still returns
        #     {"error": …, "detail": …} — one of the sites B6's `upstream_error`
        #     conversion (:308/:371/:534) missed.
        # DELETE THIS SET only after re-running scratchpad/cloudop/probe_b6.py and
        # seeing the gate phrase actually arrive. Probe, then delete — not the reverse.
        # ⚠ THE "MOVING TARGET" PARAGRAPH THAT STOOD HERE IS RESOLVED — see the
        # measurement immediately below. It predicted, before the image existed,
        # that on V0223 the Forge entries would become redundant while the
        # diagnostics one stayed load-bearing, and it warned the gating branch
        # might stop matching altogether. Measured 2026-09-06: the branch matches,
        # Forge is redundant, diagnostics is not. Both predictions correct; the
        # feared silent pass did not happen. Its full text is in the git history
        # of this file (before §EVTYPES5) and its reasoning is preserved in the
        # note below — nothing measured was dropped, only the open question.
        # §EVTYPES5 2026-09-06 — THE PROBE THE COMMENT ABOVE ASKED FOR, RUN.
        # It said: on the image where BOTH wrapper lanes return the
        # {status_code, upstream_error, body} envelope, check whether the marker
        # path starts matching and these entries become redundant — and it warned
        # that the branch might stop matching entirely, "a silently-passing gated
        # tool is worse than a false fail". Neither guess had been tested.
        #
        # MEASURED against the excerpts the sweep itself recorded on
        # cloud-op-sbxalphaop, by running _GATE_MARKERS over the same blob the
        # classifier builds (fail_reason + result_excerpt, lowered):
        #     getForgeStatus   403  hits ['is not enabled on this registry', ...]
        #     getForgeLineage  403  hits ['is not enabled on this registry', ...]
        #     getDiagnosticConfig 404  hits NONE
        # So the branch still matches (the feared silent pass did NOT happen), the
        # two Forge entries are now REDUNDANT and are removed, and the diagnostics
        # entry is STILL LOAD-BEARING — exactly as that comment predicted, which is
        # worth saying because it was written before the image existed.
        #
        # A name-based set is a hand-maintained roster, and those go stale while
        # sounding confident. It shrinks on evidence; it never grows on a guess.
        _FLAG_GATED_CLOUDOP_TOOLS = {
            # Diagnostics — a cloud-op has NO docker socket, so target discovery
            # finds nothing and GET /admin/diagnostics/targets returns
            # {"targets":[],"count":0} (measured on cloud-op-sbxalphaop-registry).
            # No target value can resolve, so every /diagnostics/config/{t} is a
            # correct 404 whose body says only "target '<x>' not found" — a true
            # sentence that names no gate, so no marker can ever match it. This
            # was never a B6 case and does not go away with an envelope change.
            "theprotocol_getDiagnosticConfig",
        }
        # §pass73.3.21: data-conditional keys legitimately absent on an empty/minimal
        # cloud-op data set. The central contract harvested these as "required" because
        # central had data; on a fresh cloud-op the tool returns a VALID 200 without
        # them (empty ES → no newest/oldest_event/last_refresh_ts; agent w/o endpoints
        # → no service_endpoints; empty tx history → no summary/source). The tool is
        # healthy; only the over-strict required-key set differs.
        _CONDITIONAL_KEYS = {
            "service_endpoints", "newest_event", "oldest_event",
            "last_refresh_ts", "summary", "source",
        }
        # §CLOUDOPMCP2 2026-09-05 — contracts written for the MAINFRAME sweep that
        # are INVERTED here. `mcp_contracts.py` pins operator-portal tools to the
        # 503 "cloud-ops only" guard, which is the correct answer ON A MAINFRAME
        # (pass73.3.19, when only that sweep existed). On a cloud-op the same tool
        # is running on the node it was built for, so a 2xx is the tool WORKING —
        # not a contract violation. Measured 2026-09-05 on cloud-op-sbxalphaop:
        # self-logs answers 200 once the mainframe URL resolves.
        # Keep this set TINY and named: it inverts an assertion, so a wrong entry
        # would mask a real failure rather than merely re-label it.
        _MAINFRAME_GUARD_CONTRACT_TOOLS = {
            "theprotocol_operatorPortalSelfLogs",
        }
        _redundant_gate_entries: set = set()
        # §EVTYPES7 — the 503 branch below tolerates ANY 503 without asking for a
        # gate phrase, while the paragraph above it promises "never blanket-tolerate
        # 5xx — a real ES/TEG outage must still surface". Both cannot be true. The
        # blanket is deliberate and mostly right (a 503 on a consumer cloud-op IS
        # usually structural), and tightening it would fail six tools that ARE gated
        # and simply cannot say so: their wrapper collapses the body to
        # "Error: <tool> returned HTTP 503" (the B6 class, agent/public lanes).
        # So the blanket stays and stops being invisible: every 503 tolerated with
        # NO explanation is named in the run. A handful is the known set below; a
        # jump is what an actual outage looks like, which is precisely what that
        # paragraph was worried about and had no way to see.
        _blanket_503: set = set()
        _tier_gated = 0
        _cond_shape = 0
        _guard_inverted = 0
        _regated: List[ContractOutcome] = []
        for o in outcomes:
            if (not o.healthy) and (not o.skip_reason):
                blob = (str(o.fail_reason or "") + " " + str(o.result_excerpt or {})).lower()
                # Inverted mainframe-guard contract (see the set above): a 2xx is
                # the pass. Anything non-2xx falls through to the normal rules, so
                # a real breakage on these tools still fails.
                if (o.tool_name in _MAINFRAME_GUARD_CONTRACT_TOOLS
                        and 200 <= int(o.status_code or 0) < 300):
                    o = ContractOutcome(
                        tool_name=o.tool_name,
                        contract_tier=o.contract_tier,
                        healthy=True,
                        status_code=o.status_code,
                        elapsed_ms=o.elapsed_ms,
                        skip_reason=None,
                        fail_reason=None,
                        has_explicit_contract=o.has_explicit_contract,
                        args_used=o.args_used,
                        result_excerpt=o.result_excerpt,
                    )
                    _regated.append(o)
                    _guard_inverted += 1
                    continue
                # §2026-06-01 — a 503 on a federated cloud-op is STRUCTURAL (no local
                # EventStore / not a genesis|fiat registry / not the fleet mainframe) =
                # correct behavior, so reclassify any 503 unconditionally. 403/404 still
                # require an explicit gate MARKER so a genuine auth/missing bug on a
                # route that a cloud-op SHOULD serve is never masked.
                # §CLOUDOPMCP 2026-09-04: 501 joins 403/404 as marker-gated (a
                # "not implemented / not enabled here" is structural on a consumer
                # cloud-op) — the MARKER is still required, so a bare 501 with no
                # explanation stays a FAIL. The flag-gated name set is the B6
                # workaround for tools whose detail the wrapper eats.
                _marker_hit = any(m in blob for m in _GATE_MARKERS)
                _is_gated = (o.status_code == 503) or (
                    o.status_code in (403, 404, 501) and _marker_hit
                ) or (
                    o.tool_name in _FLAG_GATED_CLOUDOP_TOOLS
                    and o.status_code in (403, 404, 501)
                )
                # §EVTYPES5 — the name set audits ITSELF. An entry exists only
                # because the wrapper ate the gate phrase; the moment the phrase
                # survives, the entry is dead weight that will outlive its reason
                # and read like knowledge. Two of them just did, for a day. This
                # says so in the run rather than waiting for someone to re-probe.
                if o.tool_name in _FLAG_GATED_CLOUDOP_TOOLS and _marker_hit:
                    _redundant_gate_entries.add(o.tool_name)
                if (o.status_code == 503 and not _marker_hit
                        and o.tool_name not in _FLAG_GATED_CLOUDOP_TOOLS):
                    _blanket_503.add(o.tool_name)
                # §CLOUDOPMCP 2026-09-04 — two NOT-MEASURABLE classes, each with a
                # named cause and each self-healing. Deliberately NOT folded into the
                # tier-gating reason above: "the operator refuses this route" and "we
                # could not set up the fixture" are different facts.
                _extra_skip = None
                if (not _is_gated) and _treasury_empty \
                        and o.tool_name in _MONEY_DEPENDENT_TOOLS:
                    _extra_skip = (
                        "cloud-op fixture unavailable: operator treasury measured at 0, "
                        "so no money-dependent fixture can be created. NOT a defect in "
                        "the tool, and NOT unfixable: the cross-TEG rail seeds it in one "
                        "call — POST /api/v1/teg/treasury/cross-teg-fund on the PARENT "
                        "with {target_registry: <op slug>, amount, reason: "
                        "'liquidity_provision'}, which is what the provisioner already "
                        "does best-effort at birth (cloud_operators.py:316). "
                        "⚠ THE OLD TEXT HERE BLAMED backlog B8 ('cross-TEG funding "
                        "refuses this frame's SPIFFE id') AND THAT IS NO LONGER TRUE: "
                        "R51 widened is_internal_service_identity to accept "
                        "'<name>-registry' (internal_auth.py:67), and §EVTYPES8 seeded "
                        "both sandbox operators through this exact rail, first call, "
                        "HTTP 200, Δ=0. A skip reason that names a fixed cause sends "
                        "the next reader to the wrong place."
                    )
                elif (not _is_gated) and o.tool_name == "theprotocol_adminReviewMessages" \
                        and o.status_code == 404 and "no such review grant" in blob:
                    # §CLOUDOPMCP2 2026-09-05 — the review grant is a FRAME-SEEDED
                    # fixture. MEASURED on V0223: sbx-alpha holds exactly 1 row in
                    # support_review_grants (the id in API_TEST_SUPPORT_GRANT_ID);
                    # cloud-op-sbxalphaop's own table holds 0. The sweep sends the
                    # frame's grant id to an operator whose DB never had it, so the
                    # 404 is structural — the same class as the treasury and autogen
                    # cases above, not a defect in the tool.
                    # Keyed on the upstream PHRASE, not merely tool+404: any other
                    # 404 on this tool (a revoked grant, a closed ticket, a broken
                    # route) still FAILS. That phrase only became visible at all
                    # because B6's envelope now carries the RFC7807 detail — before
                    # V0223 this row read "no message".
                    _extra_skip = (
                        "cloud-op fixture unavailable: the review grant in "
                        "API_TEST_SUPPORT_GRANT_ID is seeded on the FRAME "
                        "(1 row) and this operator's support_review_grants is "
                        "empty (0 rows, measured). Seed a grant on the operator "
                        "and this runs again. NOT a defect in the tool."
                    )
                elif (not _is_gated) and o.tool_name in _NO_AUTOGEN_TOOLS:
                    _extra_skip = (
                        "cloud-op flag-gated: A2A_DID_JWT_AUTOGEN unset, so agents carry "
                        "no registered public key. MEASURED unset on this operator AND on "
                        "production registry-a — the central sandbox is the outlier, so "
                        "this matches prod rather than diverging from it."
                    )
                if _extra_skip:
                    o = ContractOutcome(
                        tool_name=o.tool_name,
                        contract_tier=o.contract_tier,
                        healthy=False,
                        status_code=o.status_code,
                        elapsed_ms=o.elapsed_ms,
                        skip_reason=_extra_skip,
                        fail_reason=None,
                        has_explicit_contract=o.has_explicit_contract,
                        args_used=o.args_used,
                        result_excerpt=o.result_excerpt,
                    )
                    _regated.append(o)
                    _tier_gated += 1
                    continue
                if _is_gated:
                    # §MCPTEST30 (2026-10-01): three different facts used to share one skip. (1) A call sent with a
                    # literal `${fixture}` measured the TESTER, not the operator (getDiagnosticConfig's 404 named
                    # "target '${diagnostic_target_id}'"). (2) A refusal BY CONSTRUCTION, in the operator's own
                    # sentence ("runs on sovereign mainframes only", "fiat onramp is mainframe-only"), is the
                    # operator's contract MET: 56 of the 62 rows on 2026-09-30, counted NOT MEASURED. (3) A feature
                    # switched off here leaves its success path unmeasured on this node: a skip, naming the phrase.
                    _phrase = next((m for m in _BY_CONSTRUCTION_MARKERS if m in blob), None)
                    _flag = next((m for m in _GATE_MARKERS if m in blob), None)
                    _placeholders = sorted(set(re.findall(r"\$\{([a-z0-9_]+)\}", json.dumps(o.args_used, default=str) + " " + blob)))
                    if _placeholders:
                        _reason, _healthy = (
                            f"cloud-op fixture unresolved: {', '.join(_placeholders)} reached the operator as a literal "
                            f"placeholder (HTTP {o.status_code}); a fixture gap in the sweep, not a tier-gating answer", False)
                    elif _phrase:
                        # §MCPTEST30 (V0640): said on its own row, by design, in the operator's words. As a pass it was
                        # a pass on a refusal alone to the tester router, which gave it the generic refusal-only
                        # sentence (V0636), so about 45 mainframe-only admin tools per operator read like the gaps
                        # beside them (V0640's preview on V0638's operators, 2026-10-24 23:1xZ). Not measured either
                        # way; only the reason is new.
                        _reason, _healthy = cloudop_by_construction_reason(_phrase, o.status_code), False
                    else:
                        _reason, _healthy = (
                            cloudop_flag_gated_reason(_flag, o.status_code) if _flag else
                            (f"cloud-op tier-gating: HTTP {o.status_code} with no gate phrase the classifier knows; the "
                             f"operator's words: '{_refusal_words(o) or '(none)'}'; not measured"), False)
                    _ex = dict(o.result_excerpt or {})
                    _by_construction = bool(_phrase and not _placeholders)
                    if _by_construction:
                        _ex["verified_refusal"] = (f"refused by construction on a cloud-op: '{_phrase}' "
                                                   f"(HTTP {o.status_code}), the operator's contract for a mainframe-only tool")
                    o = ContractOutcome(
                        tool_name=o.tool_name,
                        contract_tier=o.contract_tier,
                        healthy=_healthy,
                        status_code=o.status_code,
                        elapsed_ms=o.elapsed_ms,
                        skip_reason=_reason,
                        fail_reason=None,
                        has_explicit_contract=o.has_explicit_contract,
                        args_used=o.args_used,
                        result_excerpt=_ex,
                    )
                    _tier_gated += 1
                    if _by_construction:
                        _verified_refusals += 1
                elif o.status_code == 200 and "missing keys: [" in str(o.fail_reason or ""):
                    _seg = str(o.fail_reason).split("missing keys: [", 1)[1].split("]", 1)[0]
                    _miss = {x.strip().strip("'\"") for x in _seg.split(",") if x.strip()}
                    if _miss and _miss <= _CONDITIONAL_KEYS:
                        o = ContractOutcome(
                            tool_name=o.tool_name,
                            contract_tier=o.contract_tier,
                            healthy=True,
                            status_code=o.status_code,
                            elapsed_ms=o.elapsed_ms,
                            skip_reason=None,
                            fail_reason=None,
                            has_explicit_contract=o.has_explicit_contract,
                            args_used=o.args_used,
                            result_excerpt=o.result_excerpt,
                        )
                        _cond_shape += 1
            else:
                # §MCPTEST30 (V0641): a mainframe-only tool that PASSED its own contract on the operator's refusal is
                # said by design too, where the operator's words say by construction (cloudop_by_design_refusal), and
                # one switched off here is not measured, where its words say so (cloudop_switched_off_refusal)
                _bd = cloudop_by_design_refusal(o)
                if _bd is not None:
                    o = _bd
                    _verified_refusals += 1
                else:
                    _so = cloudop_switched_off_refusal(o)
                    if _so is not None:
                        o = _so
                        _tier_gated += 1
            _regated.append(o)
        outcomes = _regated
        logger.info(
            f"cloud-op {op.label} tier-gated skips: {_tier_gated}, "
            f"conditional-shape passes: {_cond_shape}, "
            f"inverted mainframe-guard contracts: {_guard_inverted}"
        )
        if _blanket_503:
            logger.warning(
                "cloud-op %s: %d tool(s) answered 503 with NO gate phrase and were "
                "tolerated by the unconditional 503 branch — each is gated but its "
                "wrapper ate the sentence (B6 class). Known and expected; a JUMP in "
                "this number is what a real outage looks like, so read the list, not "
                "just the pass rate: %s",
                op.label, len(_blanket_503), sorted(
                    t.replace("theprotocol_", "") for t in _blanket_503))
        if _redundant_gate_entries:
            logger.warning(
                "cloud-op %s: %d entr%s in _FLAG_GATED_CLOUDOP_TOOLS %s now "
                "REDUNDANT — the gate phrase reaches the caller and the marker "
                "matches on its own, so the name entry no longer does any work: "
                "%s. Remove it (probe first, then delete — never the reverse).",
                op.label, len(_redundant_gate_entries),
                "y" if len(_redundant_gate_entries) == 1 else "ies",
                "is" if len(_redundant_gate_entries) == 1 else "are",
                sorted(_redundant_gate_entries))

        # ── §EVTYPES8 2026-09-06 — THE CLOUD-OP WRONG-TIER MATRIX ────────────
        # 435 public tools x 2 operator nodes had NEVER verified that a wrong-tier
        # credential is refused: `F1_auth_matrix` sat in `skip_axes_disabled` with
        # the recorded blocker "no non-admin dev seeded on cloud-op". That blocker
        # was smaller than it read — the matrix degrades gracefully on a missing
        # non-admin JWT (it falls through to the `empty` case) — and the two real
        # reasons to hesitate were measured away before this was written:
        #
        #   1. "the operator runs an unenforced posture (IRONKEY off), so a
        #      violation might be a posture artefact." It cannot be: this matrix
        #      tests the TIER gate — does a developer-tier route accept an agent
        #      JWT — which is a FastAPI dependency check. IRONKEY governs per-agent
        #      PERMISSIONS after authentication. Orthogonal.
        #   2. "a tool whose gate does not fire gets called with {} args." True,
        #      and it is why the dangerous tail was probed FIRST: the eight tools
        #      whose contracts say they act on the CALLER and take no arguments
        #      (logoutSession, authRefresh, setup2FA, disable2FASelf,
        #      regenerateBackupCodes, requestAccountDeletion,
        #      flareCelebrationAcknowledge, requestSelfRevocation) were sent both
        #      wrong-tier credentials on cloud-op-sbxalphaop by hand. All sixteen
        #      probes refused; zero open gates. The six whose open gate would
        #      destroy something rather than refuse still opt out via
        #      `never_probe_wrong_tier`.
        #
        # Same predicate as the central matrix by construction — `_wrong_tier_rejected`
        # is one function with two callers, because two implementations of "was this
        # refused?" drift and each keeps reporting zero for its own reasons.
        # `auto_tier_rejections` is imported LOCALLY by the central matrix, so its
        # name never reached this method — the first cloud-op probe raised NameError
        # and the flow returned a 500 instead of a matrix. Same import, same alias.
        from agentvault_registry.api_tests.contracts.mcp_contracts import (
            auto_tier_rejections as _auto_tier_rejections,
        )

        _op_matrix_total = 0
        _op_matrix_violations = 0
        _op_matrix_inconclusive = 0
        _op_matrix_before_gate = 0
        _op_matrix_failed: List[str] = []
        _op_matrix_not_probed: List[str] = []
        _op_matrix_probed: List[str] = []   # §MCPTEST30 (V0541): the tools a wrong-tier credential reached the gate of
        _op_bad_jwts: Dict[str, str] = {
            "empty": "",
            "agent_jwt": bag.sentinel_jwt or "",
            "developer_jwt": dev_jwt or "",
            # the operator seeds no non-admin developer; the rejection logic treats
            # an empty bearer exactly as the `empty` case, so this degrades into a
            # duplicate probe rather than a false violation (its own comment in the
            # central matrix says so).
            "developer_jwt_nonadmin": "",
        }

        async def _cloudop_authmatrix(tool):
            nonlocal _op_matrix_total, _op_matrix_violations, _op_matrix_inconclusive, _op_matrix_before_gate
            tool_name = tool.get("name") if isinstance(tool, dict) else None
            if not tool_name:
                return None
            contract = get_contract(tool_name)
            if contract.never_probe_wrong_tier:
                _op_matrix_not_probed.append(tool_name)
                return None
            rejections = list(contract.expect_tier_rejections) or _auto_tier_rejections(contract.tier)
            for bad_tier_key in rejections:
                bad_jwt = _op_bad_jwts.get(bad_tier_key, "")
                _op_matrix_total += 1
                _, body, code = await _mcp_rpc_call(
                    cloud_target, tool_name, {}, jwt=bad_jwt, timeout=10)
                status = int(code) if code.isdigit() else 0
                # §MCPTEST-MCP10: a probe with no HTTP answer proves nothing in
                # either direction and must never be scored as an accept.
                if not (100 <= status <= 599):
                    _op_matrix_inconclusive += 1
                    _op_matrix_total -= 1
                    continue
                if _wrong_tier_refused_before_gate(body):
                    _op_matrix_before_gate += 1
                    _op_matrix_total -= 1
                    continue
                if not _wrong_tier_rejected(status, body):
                    _op_matrix_violations += 1
                    _op_matrix_failed.append(f"{tool_name}({bad_tier_key}→{status})")
                _op_matrix_probed.append(tool_name)

        await _bounded_sweep(tools, _cloudop_authmatrix, concurrency=_sweep_concurrency())
        if _op_matrix_violations:
            logger.error(
                "[MCP-AuthMatrix] cloud-op %s: %d WRONG-TIER ACCEPT(S) — a credential "
                "of the wrong tier was not refused: %s",
                op.label, _op_matrix_violations, _op_matrix_failed[:20])
        logger.info(
            "cloud-op %s auth matrix: %d probes, %d violations, %d inconclusive, "
            "%d refused before the gate (not measured), %d not probed by contract",
            op.label, _op_matrix_total, _op_matrix_violations,
            _op_matrix_inconclusive, _op_matrix_before_gate, len(_op_matrix_not_probed))

        # 5c. §MCPTEST30 — the credential exposure census closes over every response of this cloud-op run
        _census_summary = _credential_census_close(outcomes, _census_token)
        _shape_summary = _result_shape_close(outcomes, _shape_token)
        _words_summary = _wording_close(outcomes, _words_token, _listing_words_found)   # §MCPTEST30 W6

        # 6. Format outcomes into APITestBase result shape (an outcome appended after this loop is formatted where it is
        # appended: the console shows `results`, the summary counts `outcomes`)
        for o in outcomes:
            results.append(_cloudop_result_row(op.label, o, len(results) + 1))

        # §MCPTEST30 (2026-10-01): the operator's AGORA fixture (organization + listing) at the end of its life; until now
        # it stayed, one per run (58 on sbxalphaop, 25 on sbxbetaop by 2026-10-01)
        _retired = "no fixture"
        if cloudop_org_id:
            async def _c_op(tool, args):
                return await _mcp_rpc_call(cloud_target, tool, args, jwt=dev_jwt, timeout=20)

            async def _ca_op(tool, args):
                return await _mcp_rpc_call_admin(cloud_target, tool, args, jwt=dev_jwt, timeout=25)
            _retired = await _retire_scratch_org(op.registry_container, _c_op, _ca_op, cloudop_org_id,
                                                 cloudop_listing, dev_jwt, str(sentinel_did or ""))
            logger.info(f"cloud-op {op.label}: the AGORA fixture: {_retired}")
        # §MCPTEST30 (V0528): this run's own agents, after the AGORA fixture (its treasury sweep pays the sentinel);
        # V0639: with the listing's treasury agent once its organization is deleted (before, one stayed active per run)
        _org_gone = bool(re.search(r"organization delete HTTP 2\d\d$", _retired))
        _own_retired = await _retire_cloudop_agents(
            _c_fx, _ca_fx, [d for d in ((cloudop_treasury_did if _org_gone else ""), sentinel_did, second_agent_did)
                            if d])
        logger.info(f"cloud-op {op.label}: this run's agents: {_own_retired}")
        # §MCPTEST30 (V0639): the createOrganization contract's probe orgs (an operator run has no orphan sweep)
        _probe_orgs = await _retire_probe_orgs(_c_fx, bag.developer_id)
        logger.info(f"cloud-op {op.label}: the contract's probe orgs: {_probe_orgs}")
        # §MCPTEST30 (V0639): the run's free fixtures (API key, ticket, bundle, TEG policy) and earlier runs' ones
        _fixtures_retired = await _retire_run_fixtures(_c_fx, _ca_fx, _cloudop_fixtures, bag.developer_id, time.time())
        logger.info(f"cloud-op {op.label}: the run's free fixtures: {_fixtures_retired}")

        # §MCPTEST30 (V0529, 2026-10-01): the operator admin's own token must not authenticate at its parent frame. A
        # signing secret the two registries shared would make operator developer 1 the frame's developer 1: its admin.
        # Measured by hand first, both sandbox operators, both directions: refused (REST 401, MCP -32001).
        _scope_outcome = await token_scope_row(op, dev_jwt)
        outcomes.append(_scope_outcome)
        results.append(_cloudop_result_row(op.label, _scope_outcome, len(results) + 1))   # V0536: counted AND shown

        # 7. Summary — strict accounting per cloud-op (V0539: four disjoint classes, outcome_counts)
        total = len(outcomes)
        _counted = outcome_counts(outcomes)
        policy_denied = _counted["policy_denied"]
        skipped = _counted["skipped"]
        passed = _counted["passed"]
        failed = _counted["failed"]
        pass_pct = (passed * 100 / total) if total else 0

        self.flow_values = {
            "operator": op.label,
            "parent_frame": op.parent_frame,
            # §MCPTEST30 (V0637): the operator that answered (its stack label and its card's name), and the earned
            # lifecycles this run took to it, with the ones it could not and why
            **_op_identity,
            "earned_lifecycles_run": sorted(_cop_lc_run),
            "earned_lifecycles_not_run": dict(sorted(_cop_lc_not_run.items())),
            "event_checks": "not made: an operator's events land in its parent frame's store",
            # §MCPTEST30 (V0550): what the operator switched off, and the rows held to those switches' refusals
            **_cop_switches,
            "switched_off_rows": sorted({o.tool_name for o in outcomes if _switches.switched_off(o.tool_name)}),
            "public_tools": public_tool_total,
            "admin_tools": len(admin_tools),
            # §CLOUDOPMCP 2026-09-04 — when the admin listing failed, admin_tools is 0
            # because we could not ASK, not because the operator has no admin surface.
            # Those are different facts and must never collapse into the same number.
            "admin_surface_measured": not _admin_list_failed,
            "admin_list_error": (admin_code if _admin_list_failed else None),
            # §MCPTEST30 — mainframe-only tools the operator refused in its own sentence: measured refusals, each said NOT
            # MEASURED (by design) on its own row since V0640, as the tester router counted them since V0636
            "verified_refusals": _verified_refusals,
            "fixture_retired": _retired,   # §MCPTEST30: the AGORA fixture's end (delist, sweep, delete)
            "agents_retired": _own_retired,          # §MCPTEST30 V0528: this run's sentinel + second (V0639: + its
                                                     # listing's treasury agent), returned + revoked
            "earlier_agents_retired": _old_retired,  # §MCPTEST30 V0528: earlier runs' leftovers, a few per run
            "run_roles": _run_roles,                 # §MCPTEST30 V0639: the role the sentinel held for the run
            "probe_orgs_retired": _probe_orgs,       # §MCPTEST30 V0639: the createOrganization contract's orgs
            "run_fixtures_retired": _fixtures_retired,   # §MCPTEST30 V0639: the run's key, ticket, bundle, policy
            "webhook_sink": list(getattr(bag, "target_webhook_sink", None) or ()),   # V0639: (on, why), asked there
            # §MCPTEST30 (V0638): what a throwaway agent held and the run could not return to the treasury, said
            "throwaway_balances_not_returned": list(getattr(bag, "throwaway_balances", None) or []),
            # §MCPTEST30 — the credential exposure census of this cloud-op run
            "credential_exposure": {
                "measured": bool(_census_summary.get("measured")),
                "responses_scanned": _census_summary.get("responses_scanned", 0),
                "unexpected": sorted(_census_summary.get("unexpected") or {}),
                "issuers_seen": len(_census_summary.get("issuer") or {}),
            },
            # §MCPTEST30 — the result shape census of this cloud-op run
            "result_shape": {
                "measured": bool(_shape_summary.get("measured")),
                "responses_scanned": _shape_summary.get("responses_scanned", 0),
                "schema_checked": _shape_summary.get("schema_checked", 0),
                "tools_with_findings": sorted(_shape_summary.get("findings") or {}),
                "tools_with_reasonless_refusals": sorted(_shape_summary.get("reasonless_refusals") or {}),
            },
            # §MCPTEST30 W6 — the critical words of this cloud-op run, counts and names only
            "wording": {
                "listings_read": _words_summary["listings"]["listings_read"],
                "listing_findings": sum(len(v) for v in _words_summary["listings"]["findings"].values()),
                "old_names_listed": _words_summary["listings"]["old_names_listed"],
                "answers_with_a_word": _words_summary["answers"].get("tools_with_a_word", 0),
            },
            "tool_count": total,
            "passed": passed,
            "skipped": skipped,
            **skip_census(outcomes),
            "policy_denied": policy_denied,
            "failed": failed,
            "pass_pct": round(pass_pct, 2),
            "wall_s": round(time.time() - t_start, 1),
            # §EVTYPES5 — the posture this run actually measured, read from the
            # node rather than assumed. `posture_complaints` is non-empty when
            # IRONKEY is off or the two flags disagree (PART 14's pairing rule).
            "posture": _posture,
            "posture_complaints": _posture_notes,
            "skip_axes_disabled": [
                # §EVTYPES8: F1_auth_matrix is no longer here — the cloud-op sweep
                # runs it (see the block above the result formatting).
                # §MCPTEST30 (V0637/V0638): the lifecycles run here now (cloudop_lifecycle_list: mcp_lifecycles'
                # own and the earned lists, those the operator can give everything to); phase-3 setup does not
                "phase3_setup",
                "F3_wrapper_drift", "F4_cross_frame_parity",
                "F5_eventual_consistency", "orphan_sweep",
                # §SKIPCENSUS 2026-09-06 — DECLARED, not newly disabled. The
                # operator sweep runs the PUBLIC wrong-tier matrix (above) and has
                # never run the ADMIN one; only the flagship does. The absence was
                # implied by a missing key, and a missing key is not a statement —
                # the same reason `admin_surface_measured` exists two fields up
                # ("could not ask" and "has no admin surface" are different facts).
                # Turning it on is a COST decision, not an oversight: the flagship's
                # full admin pass is 321 tools at ~2 s pacing, and two operators
                # would add roughly that again, twice, to every run.
                "F6_admin_auth_matrix",
            ],
            "auth_matrix_total": _op_matrix_total,
            "auth_matrix_violations": _op_matrix_violations,
            "auth_matrix_inconclusive": _op_matrix_inconclusive,
            "auth_matrix_before_gate": _op_matrix_before_gate,
            "auth_matrix_failed_tools": _op_matrix_failed[:50],
            "auth_matrix_not_probed": sorted(_op_matrix_not_probed),
            "auth_matrix_probed_tools": sorted(set(_op_matrix_probed)),
        }
        logger.info(
            f"cloud-op {op.label} MCP sweep complete: "
            f"passed={passed} skipped={skipped} failed={failed} "
            f"pass_pct={round(pass_pct, 2)} wall={round(time.time() - t_start, 1)}s"
        )
        return {
            "flow_name": f"flow_mcp_lifecycle_cloudop_{op.label}_complete",
            "success": failed == 0,
            "total_steps": len(results),
            "successful_steps": passed,
            "error": None,
            "results": results,
            "flow_values": dict(self.flow_values),
        }
