"""§MCPTEST30 (V0652, agentvault2-d3, 2026-11-01): a support ticket played through on a pair, every notice counted.

His ask in the sessions' room, seq 301: "can someone test to raise a support ticket? ... and play it thru to find bugs?";
session-tester's run on EU found six defects (sessionlogs2026/FINDINGS_2026-10-31_SUPPORT_TICKET_EU.md) and order (ai)
gwo_b13813d486f28d456a324293 fixed them in V0652. This lifecycle holds the fixes on a pair, the way a person meets them:
a throwaway developer files a ticket (submitSupportTicket) and the run's own admin developer is the desk.

  - the desk is told durably: a support.desk entry in the desk's notification feed names the ticket and opens the chat
    desk (#/admin/chatdesk?ticket=N); before, a ticket filed at night waited for an open console
  - one notice to the requester per desk act (the desk's reply, then the resolve), in words: never two or three, never a
    raw support.* key, each carrying its message's first words; before, a reply was three notices, one of them the raw
    "support.in_progress" (V0653's tester: the resolve's too, the desk's closing message riding the status change in one
    call since V0652, so the one notice left is the only place the requester is told it)
  - the requester's reply reopens the resolved ticket: the ticket reads open and its thread holds a support.open row
    authored by the requester; before, the reopen left no row
  - the desk is told of the reopen

Pairs only (MCP_TESTER_EPHEMERAL_TARGET): a desk notice reaches every admin and support holder, and on a standing frame
those are people. The requester closes its ticket and is deleted (Throwaways). Nothing moves money."""
from __future__ import annotations

import re
import secrets
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.contracts.earned_ad_ephemeral import EPHEMERAL_ENV, ephemeral_target
from agentvault_registry.api_tests.contracts.earned_fixtures import Throwaways, lc, said, unmeasured

# filed under the runner's "chat: " rows (a ticket lives in the chat; an unknown prefix is dropped unread)
DESK_NEW = "chat: the support desk is told of a new ticket"
ONE_PER_ACT = "chat: one support notice to the requester per desk act, in words"
REOPEN_ROW = "chat: a requester's reply reopens a resolved support ticket, with its status row"
DESK_REOPEN = "chat: the support desk is told of the reopen"
ROWS = {DESK_NEW: "admin", ONE_PER_ACT: "3", REOPEN_ROW: "3", DESK_REOPEN: "admin"}
NOT_EPHEMERAL = (f"a desk notice reaches every admin and support holder of the target, and on a standing frame those are "
                 f"people: the ticket is played through only where the target is torn down after the run "
                 f"({EPHEMERAL_ENV}=true: the nightly and proof pairs)")
RAW_KEY = re.compile(r"\bsupport\.[a-z_]+\b")
WAIT_S = 12.0      # a notice is written inside the request (routers/support.py awaits notify): this is slack
SETTLE_S = 2.5     # and this catches a second or third notice for the same act


def _nm(outcomes: Dict[str, dict], why: str) -> None:
    for name, tier in ROWS.items():
        unmeasured(outcomes, name, tier, why)


def _row(outcomes: Dict[str, dict], name: str, ok: bool, t0: float, fail: Optional[str], data: Dict[str, Any]) -> None:
    outcomes[name] = lc()._make_outcome(name, ROWS[name], ok, "200" if ok else "0", int((time.time() - t0) * 1000),
                                        None if ok else fail, data, expect_status="success")


async def _call(rpc: Any, parse: Any, tool: str, args: Dict[str, Any], jwt: str) -> Tuple[bool, Dict[str, Any], str]:
    """A setup or read-back call, recorded nowhere."""
    ok, body, code = await rpc(tool, args, jwt=jwt, timeout=60)
    inner = parse(body) if isinstance(body, dict) else {}
    return bool(ok), inner if isinstance(inner, dict) else {}, str(code)


async def _rest(bag: Any, parse: Any, method: str, endpoint: str, as_jwt: str, body: Optional[Dict[str, Any]] = None,
                params: Optional[Dict[str, Any]] = None) -> Tuple[int, Any]:
    """One REST call sent with `as_jwt`, through the admin bridge's adminRequest; (0, {}) when it cannot be made."""
    rpc_admin = getattr(bag, "rpc_admin", None)
    if rpc_admin is None:
        return 0, {}
    args: Dict[str, Any] = {"method": method, "endpoint": endpoint, "developer_jwt": as_jwt}
    if body is not None:
        args["body"] = body
    if params:
        args["params"] = params
    try:
        _ok, raw, code = await rpc_admin("theprotocol_adminRequest", args, jwt=bag.developer_jwt, timeout=60)
    except Exception:                                                  # noqa: BLE001
        return 0, {}
    got = parse(raw) if isinstance(raw, dict) else {}
    got = got if isinstance(got, dict) else {}
    try:
        st = int(got.get("status_code"))
    except (TypeError, ValueError):
        st = int(code) if str(code).isdigit() else 0
    return st, (got.get("response") if "response" in got else got)


async def _feed(bag: Any, parse: Any, jwt: str) -> Optional[List[Dict[str, Any]]]:
    """The developer's in-app feed (GET /api/v1/notifications/feed, newest first), or None when it cannot be read."""
    st, a = await _rest(bag, parse, "GET", "/api/v1/notifications/feed", jwt, params={"limit": 50})
    if st != 200 or not isinstance(a, dict) or a.get("available") is False:
        return None
    return [e for e in (a.get("entries") or []) if isinstance(e, dict)]


def _id(e: Dict[str, Any]) -> int:
    try:
        return int(e.get("id"))
    except (TypeError, ValueError):
        return 0


def newest_id(feed: List[Dict[str, Any]]) -> int:
    """The feed's newest entry id (0 for an empty feed). Pure."""
    return max([_id(e) for e in feed] or [0])


def raw_keys(entries: List[Dict[str, Any]]) -> List[str]:
    """The raw support.* keys a person would read in these entries' words (title and body). Pure."""
    return sorted({k for e in entries for k in RAW_KEY.findall(f"{e.get('title') or ''} {e.get('body') or ''}")})


async def _arrivals(bag: Any, parse: Any, jwt: str, after: int, want: Callable[[Dict[str, Any]], bool]
                    ) -> List[Dict[str, Any]]:
    """Every entry newer than `after`, read once one that `want` accepts has arrived (or WAIT_S passed), and again
    SETTLE_S later, so a second notice for the same act is counted too."""
    import asyncio
    t_end = time.time() + WAIT_S
    new: List[Dict[str, Any]] = []
    while time.time() < t_end:
        feed = await _feed(bag, parse, jwt) or []
        new = [e for e in feed if _id(e) > after]
        if any(want(e) for e in new):
            break
        await asyncio.sleep(1.0)
    await asyncio.sleep(SETTLE_S)
    feed = await _feed(bag, parse, jwt) or []
    return [e for e in feed if _id(e) > after]


def _brief(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"type_key": e.get("type_key"), "title": str(e.get("title") or "")[:80],
             "click": str(e.get("click") or "")[:80]} for e in entries]


def desk_entry_for(entries: List[Dict[str, Any]], tid: int, title_has: str) -> Optional[Dict[str, Any]]:
    """The support.desk entry that names ticket `tid` and says `title_has`, or None. Pure."""
    for e in entries:
        if (e.get("type_key") == "support.desk" and f"ticket={tid}" in str(e.get("click") or "")
                and title_has.lower() in str(e.get("title") or "").lower()):
            return e
    return None


def one_notice_verdict(act: str, new: List[Dict[str, Any]], words: Optional[str] = None) -> Optional[str]:
    """None when a desk act left the requester exactly one support.reply notice in words (carrying `words` where
    given); else the sentence of what the feed read. Pure."""
    if len(new) != 1:
        raw = raw_keys(new)
        return (f"the {act} left the requester {len(new)} new notice(s), not one"
                + (f", showing the raw key(s) {raw}" if raw else "") + f": {_brief(new)}")
    e = new[0]
    if e.get("type_key") != "support.reply":
        return f"the {act}'s notice is a {e.get('type_key')!r}, not a support.reply: {_brief(new)}"
    raw = raw_keys(new)
    if raw:
        return f"the {act}'s notice shows the raw key(s) {raw} to the requester: {_brief(new)}"
    if words and words.lower() not in f"{e.get('title') or ''} {e.get('body') or ''}".lower():
        return f"the {act}'s notice does not carry its first words ({words!r}): {_brief(new)}"
    return None


def reopen_row_verdict(messages: List[Dict[str, Any]], requester_id: int, after_seq: int) -> Optional[str]:
    """None when the thread holds a support.open row after `after_seq`, authored by the requester; else why not. Pure."""
    rows = [m for m in messages if isinstance(m, dict) and m.get("kind") == "system"
            and str(m.get("body") or "") == "support.open" and int(m.get("seq") or 0) > after_seq]
    if not rows:
        bodies = [str(m.get("body") or "")[:40] for m in messages if isinstance(m, dict) and m.get("kind") == "system"]
        return f"the reopened ticket's thread holds no support.open row after seq {after_seq} (its system rows: {bodies[-6:]})"
    mine = [m for m in rows if m.get("sender_ptype") == "developer" and str(m.get("sender_id")) == str(requester_id)]
    if not mine:
        return (f"the support.open row is authored by {rows[-1].get('sender_ptype')}:{rows[-1].get('sender_id')}, not by "
                f"the requester (developer {requester_id})")
    return None


def thread_of(click: Any) -> Optional[str]:
    """The conversation id a support notice opens (/ui#/pocket/ourchat/<id>), or None. Pure."""
    m = re.search(r"/ourchat/([0-9A-Za-z_-]{8,})", str(click or ""))
    return m.group(1) if m else None


async def _play(rpc: Any, parse: Any, bag: Any, t: Throwaways, tag: str, outcomes: Dict[str, dict],
                held: Dict[str, Any]) -> None:
    desk = bag.developer_jwt
    r = await t.developer("support-requester")
    rjwt = r.get("access_token")
    if not rjwt:
        return _nm(outcomes, f"NOT MEASURED: no requester could be made ({r.get('why')})")
    held["rjwt"] = rjwt
    rid = int(r["developer_id"])
    d_feed, r_feed = await _feed(bag, parse, desk), await _feed(bag, parse, rjwt)
    if d_feed is None or r_feed is None:
        return _nm(outcomes, "NOT MEASURED: the notification feed (GET /api/v1/notifications/feed) could not be read")
    d0, r0 = newest_id(d_feed), newest_id(r_feed)

    t0 = time.time()
    ok, made, code = await _call(rpc, parse, "theprotocol_submitSupportTicket",
                                 {"subject": f"MCP tester {tag}: a ticket played through",
                                  "message": f"MCP tester {tag}: the requester asks the desk", "category": "question",
                                  "priority": "low"}, rjwt)
    tid = made.get("id")
    if not ok or not isinstance(tid, int):
        return _nm(outcomes, f"NOT MEASURED: the requester's ticket was refused (HTTP {code}: {said(made)})")
    held["tid"] = tid
    new = await _arrivals(bag, parse, desk, d0, lambda e: e.get("type_key") == "support.desk")
    hit = desk_entry_for(new, tid, f"#{tid}")
    _row(outcomes, DESK_NEW, hit is not None, t0,
         f"BUG-FIND: support: the desk's feed holds no support.desk entry for ticket #{tid} (new entries: {_brief(new)})",
         {"ticket": tid, "entry": _brief([hit]) if hit else None})
    d0 = max([d0] + [_id(e) for e in new])

    # the desk's two acts, each its one notice to the requester (counted from here: a notice about the filing itself
    # is not one of them)
    r0 = max([r0] + [_id(e) for e in (await _feed(bag, parse, rjwt) or [])])
    t1 = time.time()
    words = f"MCP tester {tag} desk reply"
    verdicts: List[Optional[str]] = []
    ok_r, ans_r, code_r = await _call(bag.rpc_admin, parse, "theprotocol_supportReplyTicket",
                                      {"ticket_id": tid, "message": f"{words}: we are on it."}, desk)
    if not ok_r:
        return _row(outcomes, ONE_PER_ACT, False, t1, f"the desk's reply was refused (HTTP {code_r}: {said(ans_r)})", {})
    new = await _arrivals(bag, parse, rjwt, r0, lambda e: e.get("type_key") == "support.reply")
    verdicts.append(one_notice_verdict("desk's reply", new, words))
    thread = next((thread_of(e.get("click")) for e in new if thread_of(e.get("click"))), None)
    r0 = max([r0] + [_id(e) for e in new])
    close_words = f"MCP tester {tag} desk close"
    ok_c, ans_c, code_c = await _call(bag.rpc_admin, parse, "theprotocol_supportCloseTicket",
                                      {"ticket_id": tid, "status": "resolved",
                                       "message": f"{close_words}: resolved on our side."}, desk)
    if not ok_c:
        return _row(outcomes, ONE_PER_ACT, False, t1, f"the desk's resolve was refused (HTTP {code_c}: {said(ans_c)})", {})
    new = await _arrivals(bag, parse, rjwt, r0, lambda e: e.get("type_key") == "support.reply")
    verdicts.append(one_notice_verdict("desk's resolve", new, close_words))
    r0 = max([r0] + [_id(e) for e in new])
    bad = [v for v in verdicts if v]
    _row(outcomes, ONE_PER_ACT, not bad, t1, ("BUG-FIND: support: " + "; ".join(bad)) if bad else None,
         {"acts": 2, "notices_each": 1 if not bad else None})

    # the requester's reply reopens it
    t2 = time.time()
    seq0 = 0
    if thread:
        st_m, msgs = await _rest(bag, parse, "GET", f"/api/v1/chat/conversations/{thread}/messages", rjwt,
                                 params={"limit": 50})
        if st_m == 200 and isinstance(msgs, dict):
            seq0 = max([int(m.get("seq") or 0) for m in (msgs.get("messages") or []) if isinstance(m, dict)] or [0])
    ok_p, ans_p, code_p = await _call(rpc, parse, "theprotocol_replySupportTicket",
                                      {"ticket_id": str(tid), "message": f"MCP tester {tag}: not solved yet"}, rjwt)
    if not ok_p:
        why = f"the requester's reply was refused (HTTP {code_p}: {said(ans_p)})"
        _row(outcomes, REOPEN_ROW, False, t2, why, {})
        return _row(outcomes, DESK_REOPEN, False, t2, why, {})
    ok_d, det, _code = await _call(rpc, parse, "theprotocol_getSupportTicketDetail", {"ticket_id": str(tid)}, rjwt)
    status = str(det.get("status") or "")
    why = None if status == "open" else f"the ticket reads status={status!r} after the requester's reply, not open"
    if why is None and not thread:
        why = "the desk's notice named no thread (its click opens no /ourchat/<id>), so the status row cannot be read"
    if why is None:
        st_m, msgs = await _rest(bag, parse, "GET", f"/api/v1/chat/conversations/{thread}/messages", rjwt,
                                 params={"limit": 50})
        rows = (msgs.get("messages") or []) if st_m == 200 and isinstance(msgs, dict) else []
        why = reopen_row_verdict(rows, rid, seq0) if rows else f"the thread's messages could not be read (HTTP {st_m})"
    _row(outcomes, REOPEN_ROW, why is None, t2, (f"BUG-FIND: support: {why}") if why else None,
         {"status": status, "thread": bool(thread)})
    new = await _arrivals(bag, parse, desk, d0, lambda e: e.get("type_key") == "support.desk")
    hit = desk_entry_for(new, tid, "reopened")
    _row(outcomes, DESK_REOPEN, hit is not None, t2,
         f"BUG-FIND: support: the desk's feed holds no support.desk entry for the reopen of #{tid} (new: {_brief(new)})",
         {"entry": _brief([hit]) if hit else None})


async def lifecycle_earn_support_played(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    """A support ticket played through on a pair (the module docstring)."""
    if not ephemeral_target():
        return _nm(outcomes, NOT_EPHEMERAL)
    if getattr(bag, "rpc_admin", None) is None:
        return _nm(outcomes, "NOT MEASURED: this flow carries no admin bridge (bag.rpc_admin): the notification feed and "
                             "the thread are read through it")
    tag = f"{int(time.time())}-{secrets.token_hex(2)}"
    t = Throwaways(rpc, parse, bag, "support-played")
    held: Dict[str, Any] = {}
    try:
        await _play(rpc, parse, bag, t, tag, outcomes, held)
    except Exception as e:                                             # noqa: BLE001 - the lifecycle's crash, named
        lc()._bugfind(outcomes, ONE_PER_ACT, "3", f"support: the played-through lifecycle stopped: {type(e).__name__}: "
                                                  f"{str(e)[:200]}")
    finally:
        if held.get("tid") and held.get("rjwt"):   # the requester closes its own ticket: none is left open
            await _rest(bag, parse, "POST", f"/api/v1/support/tickets/{held['tid']}/status", held["rjwt"],
                        body={"status": "closed"})
        await t.close()


LIFECYCLES: List[Dict[str, Any]] = [
    {"name": "earn_support_played_v0652", "runner": lifecycle_earn_support_played},
]
