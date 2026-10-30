"""§MCPTEST30 (2026-10-01) — does every id a list tool advertises resolve at its detail tool?

Two routes that serve the same objects can serve different POPULATIONS: the list may include rows (mirrored, federated,
inactive, another tier's) that the detail never searches, and an id the caller was just shown then answers 404. Round 5
of the MCP tester found one by luck of fixture order: the compliance overview listed every peer row (§FRAMEKIT P3.1)
while the per-operator detail searched only the diagnostics targets (fixed in V0513). This probe asks the question on
purpose, for every list tool with a detail tool: up to three rows (the first, the middle, the last) of one list read,
each looked up at the detail, which must answer and name the same object. Read only. Rows keep counts and statuses,
never an id or a value.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

PREFIX = "list_detail: "
GONE = "gone_from_list"   # V0649: the id was no longer listed on a re-read after its detail answered 404
_HTTP = re.compile(r"\b(?:HTTP|returned)\s+(\d{3})\b")   # §MCPTEST30 (V0523): "<route> returned 500" too


@dataclass(frozen=True)
class Pair:
    list_tool: str                 # theprotocol_<name>
    tier: str                      # "1" public, "2" agent (the sentinel), "3" developer, "admin" (the admin bridge)
    rows_keys: Tuple[str, ...]     # where the rows are in the list result (a bare list when empty)
    row_id: str                    # the field of a row that the detail takes
    detail_tool: str
    detail_arg: str                # the detail tool's argument for that id
    detail_id: str                 # the field of the detail result naming the same object (dotted for nesting)
    list_args: Dict[str, Any] = field(default_factory=dict)
    detail_args: Dict[str, Any] = field(default_factory=dict)
    detail_tier: Optional[str] = None   # when it differs from the list's
    row_where: Tuple[Tuple[str, Any], ...] = ()   # only rows whose fields equal these (the population the detail serves)
    row_max: Tuple[Tuple[str, int], ...] = ()     # skip rows above these (a detail whose cost grows with the row)
    designed: Tuple[str, ...] = ()               # detail answers that are a designed step, not a missing object
    note: str = ""


def rows_of(answer: Any, keys: Tuple[str, ...]) -> Optional[List[Dict[str, Any]]]:
    def _rows(v: Any) -> bool:
        return isinstance(v, list) and all(isinstance(r, dict) for r in v)
    if not keys:
        return answer if _rows(answer) else None
    if isinstance(answer, dict):
        for k in keys:
            if _rows(answer.get(k)):
                return answer[k]
    return None


def dig(obj: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj


def failed_answer(inner: Any) -> Optional[int]:
    """The status of a failure a tool returned WITHOUT an `error` key (the admin and public GET helpers answer a non-2xx
    with {status_code, upstream_error, ...}, which the dispatcher does not mark isError), or None."""
    if not isinstance(inner, dict):
        return None
    st = inner.get("status_code")
    if "upstream_error" in inner or (isinstance(st, int) and st >= 400):
        return st if isinstance(st, int) else 0
    return None


def pick(rows: List[Dict[str, Any]], row_id: str, where: Tuple[Tuple[str, Any], ...] = (),
         most: Tuple[Tuple[str, int], ...] = ()) -> List[Any]:
    """The ids of the first, the middle and the last row that carry one (and pass the pair's filters), without repeats."""
    def _keep(r: Dict[str, Any]) -> bool:
        if any(r.get(k) != v for k, v in where):
            return False
        for k, n in most:
            v = r.get(k)
            if isinstance(v, (int, float)) and v > n:
                return False
        return True
    ids = [r.get(row_id) for r in rows if _keep(r) and r.get(row_id) not in (None, "")]
    if not ids:
        return []
    chosen = [ids[0], ids[len(ids) // 2], ids[-1]]
    out: List[Any] = []
    for i in chosen:
        if i not in out:
            out.append(i)
    return out


def same_id(a: Any, b: Any) -> bool:
    return a is not None and b is not None and str(a).strip().lower() == str(b).strip().lower()


def detail_kind(ok: bool, inner: Any, code: Any, answered: Callable, expect_id: Any, detail_id: str) -> str:
    """`same`, `other` (answered, names another object), `no_id` (answered, carries no id to compare), `refused NNN`,
    `server_error NNN`, or `no_answer` (no result came back at all).

    §MCPTEST30 (round 7): the sweep's transport hands back a tool's OWN refusal with its wrapped status as the code, so
    a non-2xx code with a result is a refusal to classify: reading it as `no_answer` hid two circuits whose detail
    failed. Only an empty result is no answer."""
    if inner in (None, {}, []) and not str(code or "").startswith("2"):
        return "no_answer"
    if answered(ok, inner, code):
        st = failed_answer(inner)
        if st is not None:
            return f"server_error {st}" if st >= 500 else f"refused {st or '?'}"
        got = dig(inner, detail_id) if isinstance(inner, dict) else None
        if got is None:
            return "no_id"
        return "same" if same_id(got, expect_id) else "other"
    t = inner.get("_text") if isinstance(inner, dict) else None
    text = t if isinstance(t, str) else json.dumps(inner, default=str)
    m = _HTTP.search(text or "")
    wrapped = str(code or "")   # the sweep's transport puts a tool's own non-2xx status here (a 2xx is the transport's)
    st = int(m.group(1)) if m else (int(wrapped) if wrapped.isdigit() and not wrapped.startswith("2") else 0)
    if st >= 500 or "Internal Server Error" in (text or ""):
        return f"server_error {st or ''}".strip()
    return f"refused {st or '?'}"


def verdict(kinds: List[str], designed: Tuple[str, ...] = ()) -> Tuple[Optional[bool], Optional[str]]:
    """(healthy | None for NOT MEASURED, the failure or skip sentence) for one pair's detail answers. A kind the pair
    declares `designed` (a consent step such as a join confirmation) is neither a pass nor a finding: it is counted.

    §MCPTEST30 (V0545): "the list returned no row carrying an id" stood for three different states: an empty list, rows
    without the id key, and ids asked whose every answer was a designed step. The runner names the first two before it
    asks; this names the third."""
    asked = list(kinds)
    gone = [k for k in asked if k == GONE]
    kinds = [k for k in kinds if k not in designed and k != GONE]
    if not kinds:
        if gone:
            return None, (f"NOT MEASURED: {len(gone)} of {len(asked)} id(s) the list advertised were gone from it on a "
                          f"re-read (deleted between the list read and the detail read, as another lifecycle's "
                          f"cleanup does)")
        if asked:
            return None, (f"NOT MEASURED: every detail answer was a designed step ({', '.join(sorted(set(asked)))}), so "
                          f"none showed the row")
        return None, "NOT MEASURED: no detail was asked"
    if all(k == "no_answer" for k in kinds):
        return None, "NOT MEASURED: no detail call came back over MCP"
    bad = [k for k in kinds if k.startswith(("refused", "server_error")) or k == "other"]
    if bad:
        return False, (f"BUG-FIND: list/detail: {len(bad)} of {len(kinds)} id(s) the list advertised did not resolve at "
                       f"the detail ({', '.join(sorted(set(bad)))}): the two routes serve different populations")
    if all(k == "no_id" for k in kinds):
        return None, "NOT MEASURED: the detail answered without the field that names its object"
    return True, None


async def recheck_refused(p: Pair, list_rpc: Callable, detail_rpc: Callable, parse: Callable, answered: Callable,
                          bag: Any, args: Dict[str, Any], jwt: str, ids: List[Any], kinds: List[str]) -> List[str]:
    """V0649 (agentvault2-13): another lifecycle can delete a row between this probe's list read and its detail read.
    pair_proof_v0645's first attempt went red on getMyWebhooks -> getWebhook that way: the owner-scoping lifecycle
    deleted its webhook 62 ms after the probe listed it and 35 ms before the detail asked (frame a's log, 2026-10-27
    05:27:47Z); the two routes serve one population. On a detail 404 the list is read once more: an id it no longer
    carries was deleted in between (GONE, NOT MEASURED for that id, never a finding); an id it still carries is asked
    again, and only a second refusal stays a BUG-FIND. A re-read that fails leaves the answers as they were."""
    ok, body, code = await list_rpc(p.list_tool, args, jwt=jwt, timeout=30)
    inner = parse(body)
    if not answered(ok, inner, code) or failed_answer(inner) is not None:
        return kinds
    rows = rows_of(inner, p.rows_keys)
    if rows is None:
        return kinds
    listed = {str(r.get(p.row_id)).strip().lower() for r in rows if isinstance(r, dict) and r.get(p.row_id) is not None}
    out = list(kinds)
    for n, (i, k) in enumerate(zip(ids, kinds)):
        if k != "refused 404":
            continue
        if str(i).strip().lower() not in listed:
            out[n] = GONE
            continue
        dargs = {**p.detail_args, p.detail_arg: i}
        if (p.detail_tier or p.tier) == "2":
            dargs["agent_jwt"] = bag.sentinel_jwt
        dok, dbody, dcode = await detail_rpc(p.detail_tool, dargs, jwt=jwt, timeout=30)
        out[n] = detail_kind(dok, parse(dbody), dcode, answered, i, p.detail_id)
    return out


async def run_pairs(rpc_for: Callable[[str], Optional[Callable]], parse: Callable, bag: Any, outcomes: Dict[str, dict],
                    pairs: Tuple[Pair, ...], make_outcome: Callable, answered: Callable) -> None:
    """One `list_detail: <list tool>` row per pair. `rpc_for(tier)` gives the transport for a tier (None: unavailable)."""
    for p in pairs:
        t0 = time.time()
        name = PREFIX + p.list_tool.replace("theprotocol_", "") + " -> " + p.detail_tool.replace("theprotocol_", "")

        def _row(ok: bool, code: Any, fail: Optional[str] = None, skip: Optional[str] = None,
                 ev: Optional[Dict[str, Any]] = None) -> None:
            outcomes[name] = make_outcome(name, "list_detail", ok and not skip, str(code or "0"),
                                          int((time.time() - t0) * 1000), fail, {}, expect_status="success",
                                          skip_reason=skip)
            outcomes[name]["result_excerpt"] = dict(ev or {})
        list_rpc, detail_rpc = rpc_for(p.tier), rpc_for(p.detail_tier or p.tier)
        if list_rpc is None or detail_rpc is None:
            _row(False, 0, skip=f"NOT MEASURED: no transport for tier {p.tier}")
            continue
        args = dict(p.list_args)
        jwt = getattr(bag, "developer_jwt", "") or ""
        if "2" in (p.tier, p.detail_tier):
            if not getattr(bag, "sentinel_jwt", None):
                _row(False, 0, skip="NOT MEASURED: no sentinel agent token")
                continue
        if p.tier == "2":
            args["agent_jwt"] = bag.sentinel_jwt
        ok, body, code = await list_rpc(p.list_tool, args, jwt=jwt, timeout=30)
        inner = parse(body)
        if not answered(ok, inner, code) or failed_answer(inner) is not None:
            _row(False, code, skip=f"NOT MEASURED: the list refused or did not answer (HTTP {failed_answer(inner) or code})")
            continue
        rows = rows_of(inner, p.rows_keys)
        if rows is None:
            _row(False, code, skip="NOT MEASURED: the list carried no rows this probe can read")
            continue
        if not rows:
            _row(False, code, skip="NOT MEASURED: the list is empty (0 rows), so no detail can be asked",
                 ev={"rows": 0, "asked": 0, "answers": []})
            continue
        ids = pick(rows, p.row_id, p.row_where, p.row_max)
        if not ids:
            _row(False, code, skip=(f"NOT MEASURED: {len(rows)} row(s), none carrying `{p.row_id}`"
                                    + (" among those the pair's row filters admit" if (p.row_where or p.row_max) else "")),
                 ev={"rows": len(rows), "asked": 0, "answers": []})
            continue
        kinds: List[str] = []
        last_code: Any = code
        for i in ids:
            dargs = {**p.detail_args, p.detail_arg: i}
            if (p.detail_tier or p.tier) == "2":
                dargs["agent_jwt"] = bag.sentinel_jwt
            dok, dbody, dcode = await detail_rpc(p.detail_tool, dargs, jwt=jwt, timeout=30)
            kinds.append(detail_kind(dok, parse(dbody), dcode, answered, i, p.detail_id))
            last_code = dcode
        if "refused 404" in kinds:
            kinds = await recheck_refused(p, list_rpc, detail_rpc, parse, answered, bag, args, jwt, ids, kinds)
        healthy, sentence = verdict(kinds, p.designed)
        ev = {"rows": len(rows), "asked": len(ids), "answers": kinds}
        if healthy is None:
            _row(False, last_code, skip=sentence, ev=ev)
        else:
            _row(healthy, last_code, fail=sentence, ev=ev)


# The pairs, from a census of the tools and their routes (2026-10-01). A pair is measurable only where its list has rows;
# an empty list is NOT MEASURED, never a pass. Admin pairs need the admin bridge's raw transport.
PAIRS: Tuple[Pair, ...] = (
    Pair("theprotocol_getAdminAgents", "admin", ("agents",), "did", "theprotocol_getAdminAgentDetail", "agent_did", "did",
         list_args={"limit": 30}),
    Pair("theprotocol_getAdminDevelopers", "admin", ("developers",), "id", "theprotocol_getAdminDeveloperDetail",
         "developer_id", "id", list_args={"limit": 30}, row_max=(("agent_count", 50),),
         note="the detail lists every owned agent: developers with many agents are skipped to keep the answers small"),
    Pair("theprotocol_getMyAgents", "3", ("agents",), "did", "theprotocol_getAgentProfile", "agent_did", "did",
         detail_tier="1"),
    Pair("theprotocol_listAgentCards", "1", ("items",), "id", "theprotocol_getAgentCardById", "card_id", "id",
         list_args={"limit": 30}),
    Pair("theprotocol_discoverAgents", "1", ("agents",), "did", "theprotocol_getAgentProfile", "agent_did", "did",
         list_args={"limit": 20}, note="the list appends the federated half to every page; the profile reads by DID"),
    Pair("theprotocol_getMyOrganizations", "3", ("organizations",), "id", "theprotocol_getOrganization", "org_id", "id"),
    Pair("theprotocol_getMyWebhooks", "3", ("webhooks",), "id", "theprotocol_getWebhook", "webhook_id", "id"),
    Pair("theprotocol_getAgoraListings", "1", ("listings",), "id", "theprotocol_getAgoraListing", "listing", "id"),
    Pair("theprotocol_guildListOrders", "1", ("orders",), "id", "theprotocol_guildGetOrder", "order_id", "order.id"),
    Pair("theprotocol_listArenaMatches", "1", ("matches",), "match_id", "theprotocol_getArenaMatch", "match_id",
         "state.match_id"),
    Pair("theprotocol_getGovernanceProposals", "1", ("proposals",), "id", "theprotocol_getProposalDetail", "proposal_id",
         "id", list_args={"status": "all", "limit": 30}, detail_tier="3"),
    Pair("theprotocol_getMyDisputes", "3", ("disputes",), "id", "theprotocol_getDisputeById", "dispute_id", "id",
         list_args={"limit": 30}),
    Pair("theprotocol_getMySupportTickets", "3", ("tickets",), "id", "theprotocol_getSupportTicketDetail", "ticket_id",
         "id", list_args={"limit": 30}),
    Pair("theprotocol_listFederationLicenses", "admin", (), "id", "theprotocol_getFederationLicenseDetail", "license_id",
         "id"),
    Pair("theprotocol_getAllFederationPeersAdmin", "admin", ("items",), "id", "theprotocol_getFederationPeerByID",
         "peer_id", "id", detail_tier="3", row_where=(("status", "ACTIVE"),),
         note="the public detail serves ACTIVE peers only, by design: the admin list's other rows are not asked"),
    Pair("theprotocol_getFederationComplianceOverview", "admin", ("peers",), "peer_registry_id",
         "theprotocol_getFederationCompliancePeerByID", "peer_id", "peer_registry_id"),
    Pair("theprotocol_getFederationComplianceOverview", "admin", ("peers",), "operator_id",
         "theprotocol_getFederationCompliancePeerByOperator", "operator_id", "operator_id",
         note="round 5's find: the detail searched only the diagnostics targets (V0513)"),
    Pair("theprotocol_listAdminOperatorApplications", "admin", ("applications",), "id",
         "theprotocol_getAdminOperatorApplication", "application_id", "id"),
    Pair("theprotocol_getCircuits", "1", ("circuits",), "circuit_id", "theprotocol_getCircuitACIR", "circuit_id",
         "circuit_id", row_where=(("acir_available", True),),
         note="the detail echoes its input: what is measured is that it answers. Round 8: two listed circuits were never "
              "compiled and answered 500; V0525 lists `acir_available` and answers 404 for them, so only those that "
              "carry bytecode are asked"),
    Pair("theprotocol_listMyAttestations", "3", ("items",), "id", "theprotocol_getAttestationDetail", "attestation_id",
         "id", list_args={"limit": 30}),
    Pair("theprotocol_getAdminBroadcasts", "admin", (), "id", "theprotocol_getBroadcastStats", "broadcast_id",
         "broadcast_id"),
    Pair("theprotocol_listTransparentOrganizations", "1", ("organizations",), "org_id", "theprotocol_getOrgPublicFeed",
         "org_id", "org_id", list_args={"limit": 20}),
    # the developer's inbox (no agent token) against the thread read; join=false, so a read never announces the reader to
    # another registry, and its 409 asking for that consent is a designed step
    Pair("theprotocol_listConversations", "3", ("conversations",), "id", "theprotocol_readThread", "conversation_id",
         "conversation_id", list_args={"limit": 20}, detail_args={"join": False, "limit": 1},
         designed=("refused 409",), note="the inbox includes org rooms reached through the developer's own agents"),
)
