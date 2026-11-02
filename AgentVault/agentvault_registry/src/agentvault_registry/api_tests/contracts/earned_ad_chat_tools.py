"""§MCPTEST30 (V0652, tester batch 4, Guild order gwo_39e726e914785352bfdc9557, agentvault2-d3, 2026-11-01): the ten chat
tools V0652 adds, earned on an organization room of the run's own (session-release's ask in the sessions' room, seq 429;
(w)'s acceptance: each tool's earned path on the pairs, as earned_ad_chat_approvals did for (l)).

Only where the target is torn down after its run (MCP_TESTER_EPHEMERAL_TARGET: the nightly and proof pairs): the run
makes an organization and opens its room, which stays after the organization is deleted. Elsewhere every row below is
NOT MEASURED with the reason; the sweep's contracts (mcp_contracts.py) still pin each tool's refusal of a room that is not
the caller's.

The room: D, a throwaway developer, owns an organization; its agent A is assigned; M, a second throwaway developer, joins
as a plain member (invited by D, accepted by M); S, a third, is a stranger to it. The room opens for D, A and M.
  (w) the phone set
    getChatUnreadCount        D's count, read before A writes one line in the room; after it, the count is higher
    markChatRead              D marks the room read to A's line: D's count falls back
    getChatAttachment         D shares a text file in the room (the upload route, multipart, from inside the target);
                              A reads it back, the same text; S is refused ("not a participant in this conversation")
    listChatApprovals         A asks an approval in the room: D's list names it with can_decide true; M's names it with
                              can_decide false (any member reads, only deciders decide)
    listWaitingChatApprovals  D's waiting list names it; M's (a member, not a decider) does not; A's token is refused
    enum: listChatApprovals   (V0653, batch 4's finding) its status filter in the room, which holds the request above
                              pending and a second one decided at once (denied): pending names the pending one alone,
                              decided the decided one alone, all both, no status the pending one (the documented
                              default); a value the tool advertises and this check does not know is red. Recorded under
                              the sweep's own row name and marked measured_in, which the sweep's enum probe keeps (it asks
                              with no room of the caller's, so its own row read NOT MEASURED)
  (aa) the progress card
    postChatProgress          A posts a progress card (running, two steps)
    updateChatProgress        A moves its steps on: changed, and getChatCardHistory holds the revision
    getChatCardHistory        (that read-back)
                              refused: D updating A's card ("only whoever posted this card updates it"); after A closes
                              it (passed), any update ("this card is closed")
  (ac) the room's status board
    getChatBoard              D reads it: can_edit true; M's read: can_edit false
    updateChatBoard           D writes it against the revision read: the next read shows the text at the next revision
                              refused: a write against the replaced revision ("the board changed since you read it"),
                              the board still D's text; M, whom the owner did not name ("keeps its status board")
The approvals are denied (deny never asks a phone); the organization is deleted after; the developers and the agent are
removed (Throwaways). Nothing moves money."""
from __future__ import annotations

import json
import secrets
import time
from typing import Any, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.contracts.earned_ad_ephemeral import EPHEMERAL_ENV, ephemeral_target
from agentvault_registry.api_tests.contracts.enum_filter import PREFIX as ENUM_PREFIX
from agentvault_registry.api_tests.contracts.earned_fixtures import (
    Throwaways, lc, refusal_step, said, step, unmeasured,
)

UNREAD = "theprotocol_getChatUnreadCount"
MARK = "theprotocol_markChatRead"
ATTACH = "theprotocol_getChatAttachment"
LISTA = "theprotocol_listChatApprovals"
WAITING = "theprotocol_listWaitingChatApprovals"
POSTP = "theprotocol_postChatProgress"
UPDP = "theprotocol_updateChatProgress"
HIST = "theprotocol_getChatCardHistory"
BOARD = "theprotocol_getChatBoard"
WBOARD = "theprotocol_updateChatBoard"
TIERS = {UNREAD: "2", MARK: "2", ATTACH: "2", LISTA: "2", WAITING: "3", POSTP: "2", UPDP: "2", HIST: "2", BOARD: "2",
         WBOARD: "2"}
# V0653: the sweep's enum row for listChatApprovals, measured in the run's own room (the module docstring)
ENUM_ROW = ENUM_PREFIX + "listChatApprovals"
STATUS_WANT = ("pending", "decided", "all")          # the vocabulary this check knows: pending is the default
MEMBER_LIST_ROW = "chat: a member who is not a decider reads a room's requests, can_decide false"
MEMBER_WAIT_ROW = "chat: a member who is not a decider waits on none of a room's requests"
MEMBER_BOARD_ROW = "chat: a member the owner did not name reads the board, can_edit false"
ROWS = {MEMBER_LIST_ROW: "3", MEMBER_WAIT_ROW: "3", MEMBER_BOARD_ROW: "3"}
NOT_EPHEMERAL = (f"the run opens an organization room of its own only where its target is torn down after the run "
                 f"({EPHEMERAL_ENV}=true: the nightly and proof pairs); a room stays after its organization is deleted")
FILE_TEXT = "The MCP tester's shared file.\nSecond line: read back word for word.\n"


def _nm(outcomes: Dict[str, dict], why: str, tools: Optional[List[str]] = None) -> None:
    for tool in (tools if tools is not None else list(TIERS) + list(ROWS)):
        unmeasured(outcomes, tool, TIERS.get(tool) or ROWS.get(tool, "3"), why)


def _bug(outcomes: Dict[str, dict], tool: str, why: str) -> None:
    lc()._bugfind(outcomes, tool, TIERS[tool], f"{tool.replace('theprotocol_', '')}: {why}")


def _row(outcomes: Dict[str, dict], name: str, ok: bool, code: Any, t0: float, fail: Optional[str],
         data: Dict[str, Any]) -> None:
    outcomes[name] = lc()._make_outcome(name, ROWS[name], ok, str(code), int((time.time() - t0) * 1000),
                                        None if ok else fail, data, expect_status="success")


async def _call(rpc: Any, parse: Any, tool: str, args: Dict[str, Any], jwt: str) -> Tuple[bool, Dict[str, Any], str]:
    """A setup or read-back call, recorded nowhere."""
    ok, body, code = await rpc(tool, args, jwt=jwt, timeout=60)
    inner = parse(body) if isinstance(body, dict) else {}
    return bool(ok), inner if isinstance(inner, dict) else {}, str(code)


async def _rest(bag: Any, parse: Any, method: str, endpoint: str, as_jwt: str,
                body: Optional[Dict[str, Any]] = None) -> Tuple[int, Dict[str, Any]]:
    """One REST call sent with `as_jwt`, through the admin bridge's adminRequest; (0, {}) when it cannot be made."""
    rpc_admin = getattr(bag, "rpc_admin", None)
    if rpc_admin is None:
        return 0, {}
    try:
        _ok, raw, code = await rpc_admin("theprotocol_adminRequest", {"method": method, "endpoint": endpoint,
                                                                      "body": body or {}, "developer_jwt": as_jwt},
                                         jwt=bag.developer_jwt, timeout=60)
    except Exception:                                                  # noqa: BLE001
        return 0, {}
    got = parse(raw) if isinstance(raw, dict) else {}
    got = got if isinstance(got, dict) else {}
    try:
        st = int(got.get("status_code"))
    except (TypeError, ValueError):
        st = int(code) if str(code).isdigit() else 0
    inner = got.get("response") if "response" in got else got
    return st, inner if isinstance(inner, dict) else {}


def multipart(field: str, filename: str, mime: str, data: bytes) -> Tuple[bytes, str]:
    """One file as a multipart/form-data body, and its content type. Pure."""
    boundary = "mcptester" + secrets.token_hex(12)
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {mime}\r\n\r\n").encode()
    return head + data + f"\r\n--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


def count_of(answer: Dict[str, Any]) -> Optional[int]:
    """getChatUnreadCount's message count, or None when the answer carries none. Pure."""
    for k in ("messages", "unread", "count"):
        v = answer.get(k)
        if isinstance(v, int) and not isinstance(v, bool):
            return v
    return None


def names_request(answer: Dict[str, Any], aid: str) -> bool:
    items = answer.get("items") if isinstance(answer.get("items"), list) else []
    return any(isinstance(i, dict) and str(i.get("id")) == aid for i in items)


def message_of(answer: Dict[str, Any]) -> Dict[str, Any]:
    m = answer.get("message") if isinstance(answer.get("message"), dict) else answer
    return m if isinstance(m, dict) else {}


def steps_of(*states: str) -> List[Dict[str, str]]:
    return [{"label": f"step {i + 1}", "state": s} for i, s in enumerate(states)]


async def _room(rpc: Any, parse: Any, bag: Any, t: Throwaways, tag: str, outcomes: Dict[str, dict]
                ) -> Optional[Dict[str, Any]]:
    """D, its agent A, the member M and the stranger S, D's organization with A assigned and M joined, its room open for
    D, A and M. None, with every row NOT MEASURED and the reason, when a step of it fails."""
    d = await t.developer("chat-tools-owner")
    if d.get("why"):
        return _nm(outcomes, f"no developer of the run's own: {d.get('why')}")
    a = await t.agent(d)
    if a.get("why"):
        return _nm(outcomes, f"no agent of the run's own: {a.get('why')}")
    m = await t.developer("chat-tools-member")
    s = await t.developer("chat-tools-stranger")
    if m.get("why") or s.get("why"):
        return _nm(outcomes, f"no second and third developer of the run's own: {m.get('why') or s.get('why')}")
    djwt, ajwt, mjwt, sjwt = d["access_token"], a["agent_jwt"], m["access_token"], s["access_token"]
    ok, org, code = await _call(rpc, parse, "theprotocol_createOrganization", {
        "name": f"mcp-earn-chat-tools-{tag}", "description": "The MCP tester's organization: deleted after its run."}, djwt)
    oid = str(org.get("id")) if ok and org.get("id") else None
    if not oid:
        return _nm(outcomes, f"no organization of the run's own could be made (HTTP {code}: {said(org)})")
    room = {"djwt": djwt, "ajwt": ajwt, "mjwt": mjwt, "sjwt": sjwt, "did": a["did"], "oid": oid}
    ok, _x, code = await _call(rpc, parse, "theprotocol_assignAgentToOrg", {"org_id": oid, "agent_did": a["did"]}, djwt)
    if not ok:
        _nm(outcomes, f"the run's agent could not join its organization (HTTP {code})")
        return {**room, "conv": None}
    ok, inv, code = await _call(rpc, parse, "theprotocol_inviteOrganizationMember",
                                {"org_id": oid, "email": m["email"], "role": "member"}, djwt)
    token = str(inv.get("token") or "") if ok else ""
    ok2, _y, code2 = (await _call(rpc, parse, "theprotocol_acceptOrgInvitation", {"token": token}, mjwt)
                      if token else (False, {}, code))
    if not ok2:
        _nm(outcomes, f"the run's member could not join its organization (invite HTTP {code}, accept HTTP {code2})")
        return {**room, "conv": None}
    st, opened = await _rest(bag, parse, "POST", f"/api/v1/chat/org-rooms/{oid}/open", djwt)
    conv = str(opened.get("conversation_id") or "")
    st_a, _o = await _rest(bag, parse, "POST", f"/api/v1/chat/org-rooms/{oid}/open", ajwt)
    st_m, _o = await _rest(bag, parse, "POST", f"/api/v1/chat/org-rooms/{oid}/open", mjwt)
    if not conv or not (200 <= st_a < 300) or not (200 <= st_m < 300):
        _nm(outcomes, f"the organization room did not open for all three (HTTP {st}, {st_a} and {st_m})")
        return {**room, "conv": None}
    return {**room, "conv": conv}


async def _phone_set(rpc: Any, parse: Any, bag: Any, r: Dict[str, Any], tag: str, outcomes: Dict[str, dict]) -> None:
    """(w): the unread count and the read mark, a shared file, a room's requests and the requests waiting on me."""
    conv, djwt, ajwt, mjwt, sjwt = r["conv"], r["djwt"], r["ajwt"], r["mjwt"], r["sjwt"]
    # the unread count follows the room; the read mark brings it back
    ok, before = await step(rpc, parse, UNREAD, "2", {}, djwt, outcomes)
    n0 = count_of(before) if ok else None
    okm, sent, code = await _call(rpc, parse, "theprotocol_sendChatMessage", {
        "agent_jwt": ajwt, "conversation_id": conv, "body": f"MCP tester, a line to read {tag}",
        "client_ref": f"mcp-earn-unread-{tag}"}, ajwt)
    seq = message_of(sent).get("seq") if okm else None
    if not okm or not isinstance(seq, int):
        unmeasured(outcomes, MARK, "2", f"the run's agent could not write the line to mark read (HTTP {code}: "
                                        f"{said(sent)})")
    else:
        _ok, mid, _c = await _call(rpc, parse, UNREAD, {}, djwt)
        n1 = count_of(mid)
        if ok and n0 is not None and (n1 is None or n1 <= n0):
            _bug(outcomes, UNREAD, f"the count did not grow after a new line in a room of the caller's ({n0} -> {n1})")
        okr, _m = await step(rpc, parse, MARK, "2", {"conversation_id": conv, "seq": seq}, djwt, outcomes)
        if okr:
            _ok, after, _c = await _call(rpc, parse, UNREAD, {}, djwt)
            n2 = count_of(after)
            if n1 is None or n2 is None or n2 >= n1:
                _bug(outcomes, MARK, f"after the room was marked read to seq {seq} the unread count did not fall "
                                     f"({n1} -> {n2})")
    # a shared file
    http_in = getattr(bag, "http_in_target", None)
    if http_in is None:
        unmeasured(outcomes, ATTACH, "2", "this flow carries no transport into the target (bag.http_in_target): the "
                                          "file is shared through the multipart upload route, which no MCP tool wraps")
    else:
        body, ctype = multipart("file", f"mcp-tester-{tag}.txt", "text/plain", FILE_TEXT.encode())
        hcode, htext = await http_in("POST", f"/api/v1/chat/conversations/{conv}/attachments", body=body,
                                     content_type=ctype, bearer=djwt)
        try:
            up = json.loads(htext or "{}")
        except ValueError:
            up = {}
        att = str(up.get("attachment_id") or "") if isinstance(up, dict) else ""
        if not att:
            unmeasured(outcomes, ATTACH, "2", f"the run's file could not be shared in its room (HTTP {hcode or 'none'})")
        else:
            okf, got = await step(rpc, parse, ATTACH, "2", {"attachment_id": att}, ajwt, outcomes)
            if okf and got.get("text") != FILE_TEXT:
                _bug(outcomes, ATTACH, f"a member read the shared text file back as {str(got.get('text'))[:80]!r}, not "
                                       f"the text shared")
            await refusal_step(rpc, parse, ATTACH, "2", {"attachment_id": att}, sjwt, outcomes,
                               "a file in a room the caller is not in", codes=(403,),
                               text="not a participant in this conversation")
    # a room's requests, and the requests waiting on me
    ok, asked, code = await _call(rpc, parse, "theprotocol_requestChatApproval", {
        "agent_jwt": ajwt, "conversation_id": conv, "title": f"MCP tester request {tag}",
        "client_ref": f"mcp-earn-tools-{tag}", "reason": "The MCP tester asks, to read the lists.",
        "expires_in_seconds": 600}, ajwt)
    a1 = asked.get("approval") if isinstance(asked.get("approval"), dict) else asked
    aid = str((a1 or {}).get("id") or "") if ok else ""
    if not aid:
        return _nm(outcomes, f"no approval request of the run's own to list (requestChatApproval HTTP {code}: "
                             f"{said(asked)})", [LISTA, WAITING, MEMBER_LIST_ROW, MEMBER_WAIT_ROW])
    r["aid"] = aid
    okl, mine = await step(rpc, parse, LISTA, "2", {"conversation_id": conv, "status": "pending"}, djwt, outcomes)
    if okl and not (names_request(mine, aid) and mine.get("can_decide") is True):
        _bug(outcomes, LISTA, f"the owner's list of the room's requests names {aid}: {names_request(mine, aid)}, "
                              f"can_decide: {mine.get('can_decide')!r} (want both true)")
    t0 = time.time()
    okm, theirs, code = await _call(rpc, parse, LISTA, {"conversation_id": conv, "status": "pending"}, mjwt)
    ok_m = okm and names_request(theirs, aid) and theirs.get("can_decide") is False
    _row(outcomes, MEMBER_LIST_ROW, ok_m, code, t0,
         f"a member's list of the room's requests (HTTP {code}) names {aid}: {names_request(theirs, aid)}, can_decide: "
         f"{theirs.get('can_decide')!r} (want named, false)", {"named": names_request(theirs, aid)})
    okw, waiting = await step(rpc, parse, WAITING, "3", {}, djwt, outcomes)
    if okw and not names_request(waiting, aid):
        _bug(outcomes, WAITING, f"the owner's waiting list does not name the room's pending request {aid}")
    t0 = time.time()
    okm, theirs, code = await _call(rpc, parse, WAITING, {}, mjwt)
    ok_w = okm and not names_request(theirs, aid)
    _row(outcomes, MEMBER_WAIT_ROW, ok_w, code, t0,
         f"a member who is not a decider (HTTP {code}) " + ("waits on the room's request" if okm else "was refused: "
                                                            + said(theirs)), {"named": names_request(theirs, aid)})
    await refusal_step(rpc, parse, WAITING, "3", {}, ajwt, outcomes, "an agent's own token",
                       text=("agents never decide approvals", "requires developer authentication"))
    await _enum_in_room(rpc, parse, r, tag, outcomes)


def _status_vocabulary() -> List[str]:
    """listChatApprovals' advertised status values, from the tool's own schema (STATUS_WANT when it cannot be read)."""
    try:
        from agentvault_registry.mcp import server as S
        t = next((x for x in S.ALL_TOOL_SCHEMAS if (x or {}).get("name") == LISTA), None)
        props = ((t or {}).get("inputSchema") or {}).get("properties") or {}
        return [str(v) for v in (props.get("status") or {}).get("enum") or []] or list(STATUS_WANT)
    except Exception:                                                  # noqa: BLE001 - the schema unreadable here
        return list(STATUS_WANT)


async def _enum_in_room(rpc: Any, parse: Any, r: Dict[str, Any], tag: str, outcomes: Dict[str, dict]) -> None:
    """listChatApprovals' status filter in the run's own room: r["aid"] pending, a second request decided at once (deny
    never asks a phone). pending names the pending one alone, decided the decided one alone, all both, and no status the
    pending one (the documented default). Written under the sweep's own row name, marked measured_in."""
    conv, djwt, ajwt, aid = r["conv"], r["djwt"], r["ajwt"], str(r.get("aid") or "")
    if not aid:
        return                       # the list rows said why: the sweep's own row stands
    t0 = time.time()

    def row(ok: bool, why: Optional[str], seen: Dict[str, Any], skip: Optional[str] = None) -> None:
        out = lc()._make_outcome(ENUM_ROW, "enum", ok, "0", int((time.time() - t0) * 1000), None if ok else why, {},
                                 expect_status="any", skip_reason=skip)
        out["result_excerpt"] = seen
        out["measured_in"] = "earn_chat_tools_v0652: an organization room of the run's own"
        outcomes[ENUM_ROW] = out

    vocab = _status_vocabulary()
    ok, asked, code = await _call(rpc, parse, "theprotocol_requestChatApproval", {
        "agent_jwt": ajwt, "conversation_id": conv, "title": f"MCP tester request {tag} (decided at once)",
        "client_ref": f"mcp-earn-enum-{tag}", "reason": "The MCP tester asks, to read the status filter.",
        "expires_in_seconds": 600}, ajwt)
    a1 = asked.get("approval") if isinstance(asked.get("approval"), dict) else asked
    a2 = str((a1 or {}).get("id") or "") if ok else ""
    if not a2:
        return row(False, None, {}, skip=f"NOT MEASURED: no second request of the run's own (requestChatApproval HTTP "
                                         f"{code}: {said(asked)})")
    okd, decided, coded = await _call(rpc, parse, "theprotocol_decideChatApproval", {
        "conversation_id": conv, "decision": "deny", "approval_ids": [a2],
        "note": "the MCP tester's own request, decided at once to read the status filter"}, djwt)
    if not okd:
        return row(False, None, {}, skip=f"NOT MEASURED: the second request could not be decided (HTTP {coded}: "
                                         f"{said(decided)})")
    want = {"pending": [aid], "decided": [a2], "all": sorted([aid, a2]), "(none)": [aid]}
    seen: Dict[str, Any] = {"pending request": aid, "decided request": a2}
    bad: List[str] = []
    for v in ("pending", "decided", "all", None):
        key = v or "(none)"
        okv, ans, codev = await _call(rpc, parse, LISTA, {"conversation_id": conv, **({"status": v} if v else {})}, djwt)
        if not okv:
            seen[key] = f"HTTP {codev}"
            bad.append(f"{key}: refused (HTTP {codev}: {said(ans)})")
            continue
        items = ans.get("items") if isinstance(ans.get("items"), list) else []
        ids = sorted({str(i.get("id")) for i in items if isinstance(i, dict)} & {aid, a2})
        seen[key] = ids
        if ids != sorted(want[key]):
            bad.append(f"{key}: {ids or 'none'} (want {sorted(want[key])})")
    unknown = sorted(set(vocab) - set(STATUS_WANT))
    if unknown:
        bad.append(f"the tool advertises {', '.join(unknown)}, which this check does not know: add its expectation")
    row(not bad, ("BUG-FIND: enum: listChatApprovals' status filter does not name the room's requests as its vocabulary "
                  "says: " + "; ".join(bad)) if bad else None, seen)


async def _progress(rpc: Any, parse: Any, r: Dict[str, Any], tag: str, outcomes: Dict[str, dict]) -> None:
    """(aa): a progress card posted, moved on, its history read, refused to a non-author and once closed."""
    conv, djwt, ajwt = r["conv"], r["djwt"], r["ajwt"]
    title = f"MCP tester progress {tag}"
    okp, posted = await step(rpc, parse, POSTP, "2", {
        "agent_jwt": ajwt, "conversation_id": conv, "title": title, "state": "running",
        "steps": steps_of("running", "pending"), "client_ref": f"mcp-earn-progress-{tag}"}, ajwt, outcomes)
    mid = str(message_of(posted).get("id") or "") if okp else ""
    if not mid:
        return _nm(outcomes, f"no progress card of the run's own (postChatProgress: {said(posted)})", [UPDP, HIST])
    base = {"agent_jwt": ajwt, "conversation_id": conv, "message_id": mid, "title": title}
    oku, upd = await step(rpc, parse, UPDP, "2", {**base, "state": "running", "steps": steps_of("done", "running")},
                          ajwt, outcomes)
    if oku and upd.get("changed") is not True:
        _bug(outcomes, UPDP, f"moving a step on answered changed: {upd.get('changed')!r}")
    okh, hist = await step(rpc, parse, HIST, "2", {"conversation_id": conv, "message_id": mid}, djwt, outcomes)
    updates = hist.get("updates") if isinstance(hist.get("updates"), list) else []
    if okh and oku and (len(updates) < 1 or int(hist.get("card_rev") or 0) < 1):
        _bug(outcomes, HIST, f"after one update the card's history holds {len(updates)} update(s) at revision "
                             f"{hist.get('card_rev')!r}")
    await refusal_step(rpc, parse, UPDP, "2", {**base, "agent_jwt": "", "state": "running",
                                                "steps": steps_of("done", "done")}, djwt,
                       outcomes, "a card someone else posted", codes=(403,),
                       text="only whoever posted this card updates it")
    okc, _c, code = await _call(rpc, parse, UPDP, {**base, "state": "passed", "steps": steps_of("done", "done")}, ajwt)
    if not okc:
        unmeasured(outcomes, f"refusal: {UPDP.replace('theprotocol_', '')} a closed card", "2",
                   f"the run's card could not be closed with its verdict (HTTP {code})")
    else:
        await refusal_step(rpc, parse, UPDP, "2", {**base, "state": "running", "steps": steps_of("done", "running")},
                           ajwt, outcomes, "a closed card", codes=(409,), text="this card is closed")


async def _board(rpc: Any, parse: Any, r: Dict[str, Any], tag: str, outcomes: Dict[str, dict]) -> None:
    """(ac): the board read, written against its revision, refused stale and to a member the owner did not name."""
    conv, djwt, mjwt = r["conv"], r["djwt"], r["mjwt"]
    okb, board = await step(rpc, parse, BOARD, "2", {"conversation_id": conv}, djwt, outcomes)
    rev0 = board.get("rev") if okb else None
    if okb and board.get("can_edit") is not True:
        _bug(outcomes, BOARD, f"the room's owner reads can_edit {board.get('can_edit')!r}")
    t0 = time.time()
    okm, theirs, code = await _call(rpc, parse, BOARD, {"conversation_id": conv}, mjwt)
    _row(outcomes, MEMBER_BOARD_ROW, okm and theirs.get("can_edit") is False, code, t0,
         f"a member the owner did not name (HTTP {code}) reads can_edit {theirs.get('can_edit')!r}",
         {"can_edit": theirs.get("can_edit")})
    if not isinstance(rev0, int):
        return _nm(outcomes, f"the board answered no revision to write against ({said(board)})", [WBOARD])
    text = f"MCP tester board {tag}: one line the next read must show"
    okw, wrote = await step(rpc, parse, WBOARD, "2", {"conversation_id": conv, "text": text, "base_rev": rev0}, djwt,
                            outcomes)
    if okw:
        _ok, now, _c = await _call(rpc, parse, BOARD, {"conversation_id": conv}, djwt)
        if now.get("text") != text or now.get("rev") != rev0 + 1:
            _bug(outcomes, WBOARD, f"after the write the board reads revision {now.get('rev')!r} with "
                                   f"{str(now.get('text'))[:60]!r}, not revision {rev0 + 1} with the text written")
    await refusal_step(rpc, parse, WBOARD, "2", {"conversation_id": conv, "text": "a stale write", "base_rev": rev0},
                       djwt, outcomes, "a write against a revision already replaced", codes=(409,),
                       text="the board changed since you read it")
    if okw:
        _ok, now, _c = await _call(rpc, parse, BOARD, {"conversation_id": conv}, djwt)
        if now.get("text") != text:
            _bug(outcomes, WBOARD, f"a stale write was refused but the board now reads {str(now.get('text'))[:60]!r}")
    await refusal_step(rpc, parse, WBOARD, "2", {"conversation_id": conv, "text": "not mine to write",
                                                 "base_rev": rev0 + 1 if okw else rev0}, mjwt, outcomes,
                       "a member the owner did not name", codes=(403,), text="keeps its status board")


async def lifecycle_earn_chat_tools(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    """The ten V0652 chat tools in an organization room of the run's own (the module docstring)."""
    if not ephemeral_target():
        return _nm(outcomes, NOT_EPHEMERAL)
    if getattr(bag, "rpc_admin", None) is None:
        return _nm(outcomes, "this flow carries no admin bridge (bag.rpc_admin): the organization room opens through "
                             "a route no MCP tool wraps")
    tag = f"{int(time.time())}-{secrets.token_hex(2)}"
    t = Throwaways(rpc, parse, bag, "chat-tools")
    r: Optional[Dict[str, Any]] = None
    try:
        r = await _room(rpc, parse, bag, t, tag, outcomes)
        if not r or not r.get("conv"):
            return None
        for part in (_phone_set(rpc, parse, bag, r, tag, outcomes), _progress(rpc, parse, r, tag, outcomes),
                     _board(rpc, parse, r, tag, outcomes)):
            try:
                await part
            except Exception as e:                                     # noqa: BLE001 - one part's crash, named
                lc()._bugfind(outcomes, f"chat: the V0652 tools' lifecycle part {getattr(part, '__name__', '?')}", "2",
                              f"{type(e).__name__}: {str(e)[:200]}")
    finally:
        if r and r.get("aid"):
            await _call(rpc, parse, "theprotocol_decideChatApproval",
                        {"conversation_id": r["conv"], "decision": "deny", "approval_ids": [r["aid"]],
                         "note": "the MCP tester's own request, closed after its run"}, r["djwt"])
        if r and r.get("oid"):
            await _call(rpc, parse, "theprotocol_deleteOrganization", {"org_id": r["oid"]}, r["djwt"])
        await t.close()


LIFECYCLES: List[Dict[str, Any]] = [
    {"name": "earn_chat_tools_v0652", "runner": lifecycle_earn_chat_tools},
]
