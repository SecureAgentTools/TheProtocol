"""§MCPTEST30 (2026-10-01) — is a paginated feed a partition? Two pages against one page of twice the size.

A list ordered on a non-unique key is not a partition under LIMIT/OFFSET: the planner may arrange rows that share the key
differently per plan, so page 1 and page 2 can return the same row twice and another never, while two IDENTICAL calls
agree with each other (so it reads as stable). The errors are symmetric, so a count cannot see them (§DIRFEED-2: 95
active cards on EU shared 68 instants of `updated_at`). Every MCP tool that takes `limit` with `offset` is asked, read
only, four times: one page of 2n, page 1 and page 2 of n, and the page of 2n again. The two big pages must agree (or the
list moved during the probe: NOT MEASURED); the two small pages must then hold exactly the big page's rows, none twice,
none missing, nothing from outside. Rows keep counts, never an id or a value.

§MCPTEST30 (V0545, round 11): a list of 2 to n rows has no second page of n, so it was NOT MEASURED, which left a short
history (a fresh agent's three staking rows) unjudged on every run. Such a list is asked again with the page halved to
fit it (pages of len//2 against one of 2*(len//2)); the row records the page it was measured at and the one it was
first asked at. A list of 0 or 1 rows holds no second page at any size and stays NOT MEASURED.

A second page that repeats the first was read as "`offset` ignored", but at a page of one row it is also what two rows
sharing the sort key look like (the tied row lands on both pages): the four reads cannot tell the two apart, and the
sentence named a cause it had not measured. One more read, far past any list here, tells them apart: an honored offset
answers it with no rows (the repeat is a tie), an ignored one with the first page again. Both are BUG-FINDs; the row
says which, or that it could not tell.

§MCPTEST30 (V0556): a list that moved during the four reads (the sandbox's sim registers agents: listAgentCards read NOT
MEASURED on the 2026-10-03 nightly) is read again, up to MOVED_RETRIES times a second apart, and judged on the first
quiet window; the row records how many times it asked. A list that keeps moving stays NOT MEASURED and says so.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

PAGE = 3                       # n: two pages of 3 against one of 6
MIN_SHORT_ROWS = 2             # a list of 2..PAGE rows is asked again at pages of len//2 (V0545)
FAR_OFFSET = 100000            # far past any list here: an honored offset answers it with no rows (V0545)
MOVED_RETRIES = 2              # a list that moved during the four reads is read again, up to twice (V0556)
MOVED_PAUSE_S = 1.0            # ... a second apart
_UNASKED = object()            # the far read was not made
PREFIX = "pagination: "
BOUNDS_PREFIX = "bounds: "
# §MCPTEST30 (2026-10-01): the page bounds a route must check before its SQL does (Postgres refuses a negative LIMIT or
# OFFSET with an error, which an unchecked route answers as a 500), and a page size far above any cap.
BOUND_CASES: Tuple[Tuple[str, Dict[str, int]], ...] = (
    ("limit=0", {"limit": 0, "offset": 0}),
    ("limit=-1", {"limit": -1, "offset": 0}),
    ("offset=-1", {"limit": PAGE, "offset": -1}),
    ("limit=5000", {"limit": 5000, "offset": 0}),
)
UNCAPPED_ROWS = 1000           # more rows than this for one page of 5000: the route caps nothing (recorded, not failed)
_HTTP = re.compile(r"\b(?:HTTP|returned)\s+(\d{3})\b")   # §MCPTEST30 (V0523): "<route> returned 500" too

# the paged public tools (census of the tool schemas 2026-10-01: `limit` with `offset`), the tier each is called at, and
# the arguments it needs besides the paging pair (a ${fixture} is read from the bag). The two MCP audit logs and the
# federation card feed page by cursor / since (their tools sent an `offset` the routes never read, fixed in V0511).
PAGED_PUBLIC: Tuple[Tuple[str, str, Dict[str, str]], ...] = (
    ("theprotocol_discoverAgents", "1", {}),
    ("theprotocol_listAgentCards", "1", {}),
    ("theprotocol_getMyIncome", "2", {}),
    ("theprotocol_getMyLockHistory", "2", {}),
    ("theprotocol_getMyTegTransactions", "2", {}),
    ("theprotocol_getTegAdvancedTransactions", "2", {}),
    ("theprotocol_getMyAgentBundles", "3", {}),
    ("theprotocol_getMySupportTickets", "3", {}),
    ("theprotocol_getMyDisputes", "3", {}),
    ("theprotocol_listMyAttestations", "3", {}),
    ("theprotocol_getMyAgentLogs", "3", {"agent_did": "${sentinel_did}"}),
    ("theprotocol_getFederationDisputeSettlements", "3", {}),
)
PAGED_ADMIN: Tuple[Tuple[str, str, Dict[str, Any]], ...] = (
    ("theprotocol_getAdminAgents", "admin", {}),
    ("theprotocol_getAdminDevelopers", "admin", {}),
    ("theprotocol_getAgentCardDriftList", "admin", {}),
    ("theprotocol_getInviteCodes", "admin", {}),
    # §MCPTEST30 (V0545): the audit log reads newest first and every MCP call writes a row (mcp_tool_invoked, the caller's
    # actor), so the probe's own four reads moved the list and the row read NOT MEASURED on every run. Filtered to the
    # system actor, whose rows no MCP caller writes (sbx-alpha 2026-10-02: 29 a day), the window holds still.
    # §MCPTEST30 V0614 (2026-10-14): over 720 hours, not the route's default 24, so a quiet day (the sandbox sim stopped,
    # its breaker trips are the system actor's only rows) no longer leaves too few rows to page.
    ("theprotocol_getAdminAuditLogs", "admin", {"actor_type": "system", "since_hours": 720}),
    ("theprotocol_getAdminFiatPurchases", "admin", {}),
)

_LIST_KEYS = ("agents", "items", "cards", "agent_cards", "results", "transactions", "bundles", "tickets", "disputes",
              "logs", "entries", "attestations", "settlements", "history", "earnings", "records", "developers", "codes",
              "invite_codes", "events", "purchases", "drifts", "audit_logs", "rows", "data")
_ID_KEYS = ("id", "did", "agent_did", "transaction_id", "tx_id", "dispute_id", "ticket_id", "bundle_id", "log_id",
            "attestation_id", "settlement_id", "event_id", "uuid", "purchase_id", "code")


def rows_of(answer: Any) -> Optional[List[Dict[str, Any]]]:
    """The list of row objects an answer carries (a bare list, or the one list under a known key), or None."""
    def _rows(v: Any) -> bool:
        return isinstance(v, list) and all(isinstance(r, dict) for r in v)
    if _rows(answer):
        return answer
    if isinstance(answer, dict):
        for k in _LIST_KEYS:
            if _rows(answer.get(k)):
                return answer[k]
        lists = [v for v in answer.values() if _rows(v)]
        if len(lists) == 1:
            return lists[0]
    return None


def identity(row: Dict[str, Any]) -> str:
    for k in _ID_KEYS:
        if row.get(k) not in (None, ""):
            return f"{k}={row[k]}"
    return "row=" + json.dumps(row, sort_keys=True, default=str)


def repeat_cause(p1: List[str], far: Any = _UNASKED) -> str:
    """Why a second page repeats the first, as far as one read far past the list can say (V0545). `far`: that read's
    identity list, None when it carried no list, _UNASKED when it was not made."""
    either = "`offset` ignored, or rows that share the sort key with no unique tiebreak"
    if far is _UNASKED:
        return either + " (the reads cannot tell which)"
    if far is None:
        return either + ": a read far past the list answered nothing this probe can read, so it cannot tell which"
    if not far:
        return ("rows that share the sort key with no unique tiebreak (§DIRFEED-2): `offset` is honored, a read far "
                "past the list came back empty")
    if far == p1:
        return "`offset` ignored: a read far past the list returned the first page again"
    return either + ": a read far past the list returned other rows, so it cannot tell which"


def verdict(big: List[str], big_again: List[str], p1: List[str], p2: List[str], n: int = PAGE, far: Any = _UNASKED
            ) -> Tuple[Optional[bool], str, Dict[str, Any]]:
    """(healthy | None for NOT MEASURED, the sentence, counts) for one tool's four reads, as identity lists; `far` is
    the read far past the list, made only when the second page repeats the first."""
    ev: Dict[str, Any] = {"page": n, "rows_in_one_page_of_2n": len(big), "page1": len(p1), "page2": len(p2)}
    if len(p1) > n or len(p2) > n or len(big) > 2 * n:
        return False, (f"BUG-FIND: pagination: `limit` not honored: a page of {n} returned {max(len(p1), len(p2))} rows, "
                       f"a page of {2 * n} returned {len(big)}"), ev
    if big != big_again:
        moved = "a row came or went" if set(big) != set(big_again) else "the same rows came back in another order"
        return None, (f"NOT MEASURED: the list moved between two identical reads ({moved} during the probe), so two "
                      "pages cannot be compared with one"), ev
    if len(big) <= n:
        return None, f"NOT MEASURED: {len(big)} row(s), no second page of {n} to compare", ev
    if p2 and p2 == p1:
        ev["second_page_repeats_first"] = True
        if far is not _UNASKED:
            ev["rows_far_past_the_list"] = None if far is None else len(far)
        return False, "BUG-FIND: pagination: the second page repeats the first: " + repeat_cause(p1, far), ev
    both, union = set(p1) & set(p2), set(p1) | set(p2)
    neither, outside = set(big) - union, union - set(big)
    ev.update(on_both=len(both), on_neither=len(neither), outside=len(outside), order_differs=(p1 + p2) != big)
    if both or neither or outside:
        return False, (f"BUG-FIND: pagination: two pages of {n} are not a partition of one page of {2 * n}: "
                       f"{len(both)} row(s) on both pages, {len(neither)} on neither, {len(outside)} from outside it "
                       f"(the list has no unique order: no ORDER BY, or one without a unique tiebreak, §DIRFEED-2)"), ev
    return True, "a partition" + (" (the order within the pages differs from the single read)"
                                  if ev["order_differs"] else ""), ev


def args_for(tier: str, extra: Dict[str, str], bag: Any) -> Tuple[Dict[str, Any], str, Optional[str]]:
    """(arguments, the JWT to call with, NOT MEASURED reason or None) for one paged tool: a ${fixture} is read from the
    bag, a tier-2 tool is called as the sentinel agent."""
    args: Dict[str, Any] = {}
    missing = []
    for k, v in extra.items():
        if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
            key = v[2:-1]
            val = bag.get(key) if hasattr(bag, "get") else None
            if val in (None, "") and hasattr(bag, key):
                val = getattr(bag, key)
            if val in (None, "") or str(val).startswith("${"):
                missing.append(key)
            args[k] = val
        else:
            args[k] = v
    if missing:
        return args, "", f"NOT MEASURED: fixture missing: {missing!r}"
    jwt = getattr(bag, "developer_jwt", "") or ""
    if tier == "2":
        if not getattr(bag, "sentinel_jwt", None):
            return args, jwt, "NOT MEASURED: no sentinel agent token"
        args["agent_jwt"] = bag.sentinel_jwt
    return args, jwt, None


def bound_answer(ok: bool, inner: Any, code: Any, answered: Callable) -> Tuple[str, Optional[int], Optional[int]]:
    """(kind, the HTTP status the tool reported or None, rows) for one bounds read. kind: `rows` (an answer), `refused`
    (the tool or its route said no, below 500), `server_error` (a 5xx, or the words of one), `no_answer` (no result
    came back at all: the bound cannot be judged from it).

    §MCPTEST30 (round 7): the sweep's transport hands back a tool's OWN refusal with its wrapped status as the code
    ("422", "500"), so a non-2xx code is a refusal to classify, never a lost call: reading it as `no_answer` hid
    transferUnits' 500 on NaN. Only an empty result is no answer. A failure the admin and public GET helpers return
    without an `error` key ({status_code, upstream_error}) is read as the refusal it is."""
    if inner in (None, {}, []) and not str(code or "").startswith("2"):
        return "no_answer", None, None
    if answered(ok, inner, code):
        st0 = inner.get("status_code") if isinstance(inner, dict) else None
        if isinstance(inner, dict) and ("upstream_error" in inner or (isinstance(st0, int) and st0 >= 400)):
            st0 = st0 if isinstance(st0, int) else None
            return ("server_error" if (st0 or 0) >= 500 else "refused"), st0, None
        rows = rows_of(inner)
        return "rows", None, (len(rows) if rows is not None else None)
    t = inner.get("_text") if isinstance(inner, dict) else None
    text = t if isinstance(t, str) else json.dumps(inner, default=str)
    m = _HTTP.search(text or "")
    wrapped = str(code or "")   # the sweep's transport puts a tool's own non-2xx status here (a 2xx is the transport's)
    st = int(m.group(1)) if m else (int(wrapped) if wrapped.isdigit() and not wrapped.startswith("2") else None)
    if (st is not None and st >= 500) or "Internal Server Error" in (text or ""):
        return "server_error", st, None
    return "refused", st, None


def bounds_verdict(answers: Dict[str, Tuple[str, Optional[int], Optional[int]]]
                   ) -> Tuple[Optional[bool], Optional[str], Dict[str, Any]]:
    """(healthy | None for NOT MEASURED, the failure or skip sentence, per-case evidence). Only a server error is a
    finding: a refusal or a clamped page both keep the route's SQL from the bound. A page of 5000 that returns more than
    UNCAPPED_ROWS rows is recorded (`uncapped`), not failed: no route here documents a cap to hold it to."""
    ev: Dict[str, Any] = {}
    for case, (kind, st, rows) in answers.items():
        ev[case] = (f"{rows} rows" if kind == "rows" and rows is not None else "answered, no list" if kind == "rows"
                    else f"{kind} HTTP {st}" if st else kind)
    errs = [case for case, (kind, _st, _rows) in answers.items() if kind == "server_error"]
    if errs:
        return False, (f"BUG-FIND: bounds: a page bound the route does not check answered a server error "
                       f"({', '.join(errs)}): the bound reached the SQL"), ev
    big = answers.get("limit=5000")
    if big and big[0] == "rows" and big[2] is not None and big[2] > UNCAPPED_ROWS:
        ev["uncapped"] = True
    if all(kind == "no_answer" for kind, _st, _rows in answers.values()):
        return None, "NOT MEASURED: no bounds read came back over MCP", ev
    return True, None, ev


async def run_bounds(rpc: Callable, parse: Callable, bag: Any, outcomes: Dict[str, dict],
                     paged: Tuple[Tuple[str, str, Dict[str, str]], ...], make_outcome: Callable,
                     answered: Callable) -> None:
    """Four read-only calls per paged tool, one per BOUND_CASES entry; one `bounds: <tool>` row each."""
    for tool, tier, extra in paged:
        t0 = time.time()
        name = BOUNDS_PREFIX + tool.replace("theprotocol_", "")
        args, jwt, unmet = args_for(tier, extra, bag)
        if unmet:
            outcomes[name] = make_outcome(name, "bounds", False, "0", 0, None, {}, expect_status="any", skip_reason=unmet)
            continue
        answers: Dict[str, Tuple[str, Optional[int], Optional[int]]] = {}
        last_code: Any = 0
        for case, page in BOUND_CASES:
            ok, body, code = await rpc(tool, {**args, **page}, jwt=jwt, timeout=30)
            answers[case], last_code = bound_answer(ok, parse(body), code, answered), code
        healthy, sentence, ev = bounds_verdict(answers)
        outcomes[name] = make_outcome(name, "bounds", bool(healthy), str(last_code or "0"),
                                      int((time.time() - t0) * 1000), sentence if healthy is False else None, {},
                                      expect_status="any", skip_reason=sentence if healthy is None else None)
        outcomes[name]["result_excerpt"] = ev   # per-case kinds and counts, never a row


async def run_paged(rpc: Callable, parse: Callable, bag: Any, outcomes: Dict[str, dict],
                    paged: Tuple[Tuple[str, str, Dict[str, str]], ...], make_outcome: Callable,
                    answered: Callable) -> None:
    """Four read-only calls per tool (eight when a short list is asked again at a smaller page); one
    `pagination: <tool>` row each."""
    def _row(tool: str, tier: str, ok: bool, code: Any, t0: float, fail: Optional[str] = None,
             skip: Optional[str] = None, ev: Optional[Dict[str, Any]] = None) -> None:
        name = PREFIX + tool.replace("theprotocol_", "")
        outcomes[name] = make_outcome(name, "pagination", bool(ok) and not skip, str(code or "0"),
                                      int((time.time() - t0) * 1000), None if ok else fail, {},
                                      expect_status="success", skip_reason=skip)
        outcomes[name]["result_excerpt"] = dict(ev or {})   # counts only, kept whole (the excerpt keeps five keys)

    async def _four_reads(tool: str, args: Dict[str, Any], jwt: str, n: int
                          ) -> Tuple[Optional[List[List[str]]], Any]:
        """(the four identity lists: one page of 2n, page 1 and page 2 of n, the page of 2n again, or None when a read
        carried no list, the last code)."""
        reads: List[List[str]] = []
        last_code: Any = 0
        for limit, offset in ((2 * n, 0), (n, 0), (n, n), (2 * n, 0)):
            ok, body, code = await rpc(tool, {**args, "limit": limit, "offset": offset}, jwt=jwt, timeout=30)
            inner, last_code = parse(body), code
            rows = rows_of(inner) if answered(ok, inner, code) else None
            if rows is None:
                return None, last_code
            reads.append([identity(r) for r in rows])
        return reads, last_code

    async def _settled_reads(tool: str, args: Dict[str, Any], jwt: str, n: int
                             ) -> Tuple[Optional[List[List[str]]], Any, int]:
        """The four reads, again while the two big pages disagree (the list moved), up to MOVED_RETRIES times; returns the
        last reads, the last code and how many times it asked again."""
        tries = 0
        reads, code = await _four_reads(tool, args, jwt, n)
        while reads is not None and reads[0] != reads[3] and tries < MOVED_RETRIES:
            tries += 1
            await asyncio.sleep(MOVED_PAUSE_S)
            reads, code = await _four_reads(tool, args, jwt, n)
        return reads, code, tries

    async def _judge(tool: str, args: Dict[str, Any], jwt: str, reads: List[List[str]], n: int
                     ) -> Tuple[Optional[bool], str, Dict[str, Any]]:
        """The verdict on four reads at page n; a second page that repeats the first earns one read far past the list,
        which tells an ignored offset from tied rows."""
        big, p1, p2, big_again = reads
        healthy, sentence, ev = verdict(big, big_again, p1, p2, n=n)
        if ev.get("second_page_repeats_first"):
            ok, body, code = await rpc(tool, {**args, "limit": n, "offset": FAR_OFFSET}, jwt=jwt, timeout=30)
            inner = parse(body)
            rows = rows_of(inner) if answered(ok, inner, code) else None
            healthy, sentence, ev = verdict(big, big_again, p1, p2, n=n,
                                            far=None if rows is None else [identity(r) for r in rows])
        return healthy, sentence, ev

    for tool, tier, extra in paged:
        t0 = time.time()
        args, jwt, unmet = args_for(tier, extra, bag)
        if unmet:
            _row(tool, tier, False, 0, t0, skip=unmet)
            continue
        reads, last_code, tries = await _settled_reads(tool, args, jwt, PAGE)
        if reads is None:
            _row(tool, tier, False, last_code, t0, skip=(
                f"NOT MEASURED: a read answered HTTP {last_code} or carried no list of rows this probe can read"))
            continue
        big, _p1, _p2, big_again = reads
        healthy, sentence, ev = await _judge(tool, args, jwt, reads, PAGE)
        if tries:
            ev["moved_retries"] = tries
            if big != big_again:
                sentence = f"{sentence} (asked {1 + tries} times, {MOVED_PAUSE_S:g} s apart)"
        if healthy is None and big == big_again and MIN_SHORT_ROWS <= len(big) <= PAGE:
            # a short list: ask again with pages that fit it, so the history is judged rather than skipped
            small = len(big) // 2
            again, last_code, tries2 = await _settled_reads(tool, args, jwt, small)
            if again is None:
                _row(tool, tier, False, last_code, t0, skip=(
                    f"NOT MEASURED: {len(big)} row(s); asked again at pages of {small}, a read answered HTTP "
                    f"{last_code} or carried no list of rows this probe can read"), ev=ev)
                continue
            healthy, sentence, ev = await _judge(tool, args, jwt, again, small)
            ev["first_asked_at_page"] = PAGE
            if tries2:
                ev["moved_retries"] = tries2
                if again[0] != again[3]:
                    sentence = f"{sentence} (asked {1 + tries2} times, {MOVED_PAUSE_S:g} s apart)"
        if healthy is None:
            _row(tool, tier, False, last_code, t0, skip=sentence, ev=ev)
        else:
            _row(tool, tier, healthy, last_code, t0, fail=None if healthy else sentence, ev={**ev, "verdict": sentence})
