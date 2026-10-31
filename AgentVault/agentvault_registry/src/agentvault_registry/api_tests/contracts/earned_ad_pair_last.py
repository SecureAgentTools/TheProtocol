"""§MCPTEST30 (V0650, tester batch 1 items 1c and 1d, agentvault2-d3, 2026-10-31, Guild order
gwo_2015b757c94ce69138500df6): the tools that change the frame itself, run LAST, and only where the target is torn down
after its run (MCP_TESTER_EPHEMERAL_TARGET: the nightly and proof pairs).

They run in PHASE 8 of flow_mcp_lifecycle_complete (run_last below), after both sweeps and phase 7, one at a time; on a
pair the lifecycle flow itself runs after the federation suite (scripts/nightly/nightly_suites.py runs its suites in
order). So nothing of the run or of the pair's suites still uses the operator or reads the card when they change. They
are in no LIFECYCLES list, so a cloud operator's sweep never runs them. On a standing frame every row is NOT MEASURED with
the reason, and the sweep's pinned refusals still measure each route's refusal.

  the registry's own card (item 1d)
    uploadRegistryCardIcon       a 1x1 PNG of the run's own (a text chunk names the run, so no two runs upload the same
                                 bytes): the answer and the admin card name its digest and size, the served file is its
                                 bytes, and the public card carries its digest. Then the icon the card held before goes
                                 back and its digest is read again. Where the card held one the run cannot read whole, the
                                 run uploads nothing (it could not put it back); where the card held none, the run's stays
                                 (no route removes an icon, and the pair is torn down).
  the pair's own operators (item 1c), only where the target mails nobody (GET /admin/email/senders: smtp_configured
  false): a frame request is mailed to the network's commander address, and the operator routes mail the operator and
  the admins
    requestFrame                 a request of the run's own (no account made), read back pending in Frame Management
    rejectOperatorApplication    an application of the run's own (the public form's route: no MCP tool submits one),
                                 rejected; read back rejected, with the reason as its notes
    adminDownloadOperatorBundle  the pair's operator's bundle: status, content type, size and whether the answer gives a
                                 digest; never a byte of it (the row keeps no excerpt of the answer), and an answer that
                                 carries the bundle's first bytes is a finding
    rotateOperatorPullToken      the application's pull-token prefix and issue time move; the token the answer carries
                                 is in no row
    suspendOperator              suspended, read back; then reinstateOperator, read back approved
    revokeOperatorAccess         last: revoked, read back, and the application's pull token cleared with it
  Not run: setCanaryMaintenance. No route makes a canary path and a pair holds none, so the call could only answer
  updated_paths 0, which shows nothing; it stays out of every lifecycle (mcp_admin_lifecycles' never-invoke guard).
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import re
import secrets
import struct
import time
import zlib
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from agentvault_registry.api_tests.contracts.earned_ad_ephemeral import EPHEMERAL_ENV, ephemeral_target
from agentvault_registry.api_tests.contracts.earned_fixtures import (
    REFUSAL, bare, effect, effect_name, effect_unmeasured, lc, said, step, tool_row,
)

ICON = "theprotocol_uploadRegistryCardIcon"
CARD = "theprotocol_getAdminRegistryCard"
PUBLIC_CARD = "theprotocol_getWellKnownRegistryCard"
REQUEST_FRAME = "theprotocol_requestFrame"
REJECT = "theprotocol_rejectOperatorApplication"
BUNDLE = "theprotocol_adminDownloadOperatorBundle"
ROTATE = "theprotocol_rotateOperatorPullToken"
SUSPEND = "theprotocol_suspendOperator"
REINSTATE = "theprotocol_reinstateOperator"
REVOKE = "theprotocol_revokeOperatorAccess"
APPLICATION = "theprotocol_getAdminOperatorApplication"
APPLICATIONS = "theprotocol_listAdminOperatorApplications"
ADMIN_REQUEST = "theprotocol_adminRequest"
# the pair's own operator, in the order they run: revokeOperatorAccess ends it, so it is last
OPERATOR_TOOLS = (BUNDLE, ROTATE, SUSPEND, REINSTATE, REVOKE)
OWN_TOOLS = (REQUEST_FRAME, REJECT)
# every row of this phase is an `admin_effect: ` row (requestFrame's too: the runner files a request of its own and an
# admin read in Frame Management shows it) or a `refusal: ` row, never a tool's own name, which the sweep has written
PHASE8_PREFIXES = ("admin_effect: ", REFUSAL)

SUSPEND_REASON = "The MCP tester suspends the pair's own operator, then reinstates it (Phase 8, the pair only)."
REVOKE_REASON = "The MCP tester revokes the pair's own operator as its very last step (Phase 8, the pair only)."
REJECT_REASON = "The MCP tester rejects an application of its own (Phase 8, the pair only)."
NOT_EPHEMERAL = (f"the run changes the frame itself (its card's icon, its operators) only where its target is torn "
                 f"down after the run ({EPHEMERAL_ENV}=true: the nightly and proof pairs), and there last (Phase 8)")
MAILS = ("a frame request is mailed to the network's commander address and the operator routes mail the operator and "
         "the admins, so the run makes them only where the target mails nobody")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


# ── the icon (item 1d) ──────────────────────────────────────────────────────────────────────────────────────────────
def run_png(tag: str) -> bytes:
    """A 1x1 PNG of the run's own: one opaque pixel and a tEXt chunk naming the run."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)          # 1x1, 8-bit RGBA
    text = b"Comment\x00" + f"MCP tester {tag}".encode()
    idat = zlib.compress(b"\x00\x1f\x8f\xd6\xff")                  # filter byte, then one RGBA pixel
    return PNG_SIGNATURE + chunk(b"IHDR", ihdr) + chunk(b"tEXt", text) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def icon_etag(raw: bytes) -> str:
    """The digest the icon route stores for `raw` (routers/admin_registry_card.upload_registry_card_icon)."""
    return f"sha256:{hashlib.sha256(raw).hexdigest()[:32]}"


def _path_of(url: str) -> Optional[str]:
    """The path of a card's icon_url (relative as stored, absolute once a peer resolved it); None for anything else."""
    m = re.match(r"^(?:https?://[^/]+)?(/[A-Za-z0-9._~/%+-]+)$", str(url or ""))
    return m.group(1) if m else None


def _visual(card: Any) -> Dict[str, Any]:
    v = card.get("visual") if isinstance(card, dict) else None
    return v if isinstance(v, dict) else {}


async def _admin(bag: Any, parse: Any, tool: str, args: Dict[str, Any]) -> Tuple[bool, Any, str]:
    """An admin read, set-up or put-back that records no row: (ok, the answer as parsed, the code)."""
    ok, body, code = await bag.rpc_admin(tool, args, jwt=bag.developer_jwt, timeout=60)
    return bool(ok), (parse(body) if isinstance(body, dict) else {}), str(code)


async def _rest(bag: Any, parse: Any, method: str, endpoint: str, body: Optional[Dict[str, Any]] = None
                ) -> Tuple[int, Any]:
    """One REST call through the admin bridge's adminRequest, as the runner: (HTTP status, the route's answer)."""
    ok, got, code = await _admin(bag, parse, ADMIN_REQUEST, {"method": method, "endpoint": endpoint, "body": body or {}})
    got = got if isinstance(got, dict) else {}
    try:
        st = int(got.get("status_code"))
    except (TypeError, ValueError):
        st = int(code) if str(code).isdigit() else 0
    return st, (got.get("response") if "response" in got else got)


async def _served(bag: Any, path: str) -> Optional[bytes]:
    """The bytes the target serves at `path`, read inside its own container; None when they could not be read."""
    st, b64 = await bag.http_b64_in_target(path)
    if st != "200":
        return None
    try:
        return base64.b64decode((b64 or "").strip(), validate=True)
    except (binascii.Error, ValueError):
        return None


async def lifecycle_last_registry_icon(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    """The registry's own icon: the run's, read back three ways, then the one it held back (the module docstring)."""
    if not ephemeral_target():
        return effect_unmeasured(outcomes, ICON, NOT_EPHEMERAL)
    if getattr(bag, "rpc_admin", None) is None:
        return effect_unmeasured(outcomes, ICON, "this flow carries no admin bridge (bag.rpc_admin)")
    if getattr(bag, "http_b64_in_target", None) is None:
        return effect_unmeasured(outcomes, ICON, "this flow carries no transport for a file's bytes from inside the "
                                                 "target (bag.http_b64_in_target), so the icon the card holds could "
                                                 "not be read, nor put back")
    ok, card, code = await _admin(bag, parse, CARD, {})
    if not (ok and isinstance(card, dict)):
        return effect_unmeasured(outcomes, ICON, f"the admin card could not be read (HTTP {code})")
    # The card names its icon by icon_url alone: v0.4 strips icon_etag and icon_size_bytes from the visual block at
    # serve time (registry_card_builder, "move to HTTP headers"), on the admin card too, so the icon is read by its
    # bytes, as served (V0650 trial nt261031x3: a read of visual.icon_etag found None after a sound upload).
    held_url = _visual(card).get("icon_url")
    held: Optional[Tuple[bytes, str]] = None
    if held_url:
        path = _path_of(held_url)
        raw0 = await _served(bag, path) if path else None
        fmt0 = ("image/png" if raw0 and raw0.startswith(PNG_SIGNATURE)
                else "image/jpeg" if raw0 and raw0[:3] == b"\xff\xd8\xff" else None)
        if not (raw0 and fmt0):
            return effect_unmeasured(outcomes, ICON, f"the icon the card holds ({held_url}) could not be read whole, so "
                                                     f"the run could not put it back and uploads nothing")
        held = (raw0, fmt0)
    tag = f"{int(time.time())}-{secrets.token_hex(3)}"
    png = run_png(tag)
    want = icon_etag(png)

    def _answer(a: dict) -> Optional[str]:
        if a.get("icon_etag") != want or a.get("icon_size_bytes") != len(png):
            return (f"the answer names icon_etag={a.get('icon_etag')!r} and icon_size_bytes={a.get('icon_size_bytes')!r}"
                    f", not the run's ({want}, {len(png)})")
        return None
    name = effect_name(ICON)
    try:
        ok, _ans = await effect(bag, parse, ICON, {"icon_b64": base64.b64encode(png).decode(), "content_type": "image/png"},
                               outcomes, check=_answer)
        if not ok:
            return
        why = None
        ok_c, card1, code1 = await _admin(bag, parse, CARD, {})
        v1 = _visual(card1) if ok_c else {}
        path1 = _path_of(v1.get("icon_url") or "") if ok_c else None
        if not ok_c:
            why = f"the admin card could not be read afterwards (HTTP {code1})"
        elif not path1:
            why = f"the admin card names no icon afterwards (icon_url={v1.get('icon_url')!r})"
        else:
            got = await _served(bag, path1)
            if got != png:
                why = (f"the admin card's icon_url ({v1.get('icon_url')!r}) serves "
                       + ("nothing readable" if got is None else f"{len(got)} other bytes") + ", not the run's icon")
        if why is None:
            # the signed public card names the icon that serves the run's bytes (a serve rebuilds it; read a few times).
            # A public tool still goes with the run's developer token: the MCP endpoint answers 401 to a call without
            # one (mcp/server.py, the OAuth prompt), which the trial pair nt261031x4 read as "names the icon at None".
            seen = None
            for attempt in range(3):
                if attempt:
                    await asyncio.sleep(2)
                okp, body, _cp = await rpc(PUBLIC_CARD, {}, jwt=bag.developer_jwt, timeout=30)
                pub = parse(body) if okp and isinstance(body, dict) else {}
                seen = _path_of(_visual(pub).get("icon_url") or "")
                if seen == path1:
                    break
            if seen != path1:
                why = (f"the public registry card names the icon at {seen!r}, not {path1!r}, the address that serves "
                       f"the run's icon")
        if why:
            lc()._bugfind(outcomes, name, "admin_effect", f"uploadRegistryCardIcon: {why}")
    finally:
        if held is not None:
            raw0, fmt0 = held
            okr, back, coder = await _admin(bag, parse, ICON, {"icon_b64": base64.b64encode(raw0).decode(),
                                                                "content_type": fmt0})
            ok_c2, card2, _c2 = await _admin(bag, parse, CARD, {})
            path2 = _path_of(_visual(card2).get("icon_url") or "") if ok_c2 else None
            now = await _served(bag, path2) if path2 else None
            if not (okr and now == raw0):
                lc()._bugfind(outcomes, name, "admin_effect",
                              f"uploadRegistryCardIcon: the icon the card held before did not come back (the put-back "
                              f"answered HTTP {coder}; the card's icon_url {path2!r} serves "
                              + ("nothing readable" if now is None else f"{len(now)} bytes, not the {len(raw0)} it held")
                              + ")")
        elif name in outcomes and outcomes[name].get("healthy"):
            row = outcomes[name]
            row["result_excerpt"] = {**(row.get("result_excerpt") or {}),
                                     "put_back": "none: the card held no icon before, and no route removes one"}


# ── the pair's own operators (item 1c) ──────────────────────────────────────────────────────────────────────────────
def _status_is(want: str) -> Callable[[dict], Optional[str]]:
    def check(a: dict) -> Optional[str]:
        got = a.get("status") if isinstance(a, dict) else None
        return None if str(got or "").lower() == want else f"the answer reads status={got!r}, not {want!r}"
    return check


def pick_operator(listing: Any) -> Optional[Dict[str, Any]]:
    """The pair's own operator: an approved, cloud-hosted application not torn down, the oldest such (a pair has one per
    frame). None when the listing names none."""
    rows = listing.get("applications") if isinstance(listing, dict) else listing
    rows = [r for r in (rows or []) if isinstance(r, dict) and str(r.get("status") or "") == "approved"
            and r.get("cloud_hosted") and not r.get("cloud_torn_down_at") and r.get("id")]
    rows.sort(key=lambda r: str(r.get("created_at") or ""))
    return rows[0] if rows else None


async def _application(bag: Any, parse: Any, aid: str) -> Tuple[bool, Dict[str, Any], str]:
    ok, a, code = await _admin(bag, parse, APPLICATION, {"application_id": aid})
    return ok and isinstance(a, dict), (a if isinstance(a, dict) else {}), code


async def _read_back(bag: Any, parse: Any, outcomes: Dict[str, dict], tool: str, aid: str,
                     judge: Callable[[Dict[str, Any]], Optional[str]]) -> None:
    """The application must show what `tool` answered it did; anything else downgrades its row."""
    name = effect_name(tool)
    row = outcomes.get(name)
    if not (row and row.get("healthy")):
        return
    ok, a, code = await _application(bag, parse, aid)
    why = f"getAdminOperatorApplication answered HTTP {code} afterwards" if not ok else judge(a)
    if why:
        lc()._bugfind(outcomes, name, "admin_effect", f"{bare(tool)}: {why}")


async def _request_frame(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict], tag: str) -> None:
    name = effect_name(REQUEST_FRAME)
    email = f"mcp-earn-frame-{tag}@tester.theprotocol.cloud"
    scratch: Dict[str, dict] = {}
    ok, ans = await step(rpc, parse, REQUEST_FRAME, "3", {"request_data": {
        "accept_terms": True, "organization": "The MCP tester", "contact_name": "MCP tester",
        "email": email, "use_case": "The MCP tester's own frame request, on a pair that is torn down after its run.",
        "create_account": False}}, bag.developer_jwt, scratch)
    row = scratch.get(REQUEST_FRAME) or lc()._not_measured(name, "3", "NOT MEASURED: the step recorded no answer")
    row.update(tool_name=name, contract_tier="admin_effect")
    outcomes[name] = row
    rid = str(ans.get("request_id") or "") if ok and isinstance(ans, dict) else ""
    if not (ok and row.get("healthy")):
        return
    why = None
    if not (ans.get("submitted") is True and rid):
        why = "the answer says no submitted request (submitted, request_id)"
    elif ans.get("account_created"):
        why = "the request made an account though create_account was false"
    else:
        st, fr = await _rest(bag, parse, "GET", f"/api/v1/admin/frame-requests/{rid}")
        if st != 200 or not isinstance(fr, dict):
            why = f"Frame Management answered HTTP {st} for the request afterwards"
        elif str(fr.get("status")) != "pending" or str(fr.get("contact_email") or "").lower() != email:
            why = (f"Frame Management reads status={fr.get('status')!r}, contact_email={fr.get('contact_email')!r}, "
                   f"not the run's pending request")
    if why:
        lc()._bugfind(outcomes, name, "admin_effect", f"requestFrame: {why}")


async def _reject_own_application(bag: Any, parse: Any, outcomes: Dict[str, dict], tag: str) -> None:
    st, made = await _rest(bag, parse, "POST", "/api/v1/operator-applications", {
        "name": f"mcp-earn-op-{tag}", "email": f"mcp-earn-op-{tag}@tester.theprotocol.cloud",
        "organization": "The MCP tester", "use_case": "An application of the MCP tester's own, rejected at once.",
        "accept_operator_terms": True})
    aid = str(made.get("id") or "") if st in (200, 201) and isinstance(made, dict) else ""
    if not aid or str(made.get("status")) != "pending":
        return effect_unmeasured(outcomes, REJECT, f"no application of the run's own could be made (the form's route "
                                                   f"answered HTTP {st}: {said(made)})")
    await effect(bag, parse, REJECT, {"application_id": aid, "reason": REJECT_REASON}, outcomes,
                 check=_status_is("rejected"))
    await _read_back(bag, parse, outcomes, REJECT, aid, lambda a: None
                     if str(a.get("status")) == "rejected" and a.get("review_notes") == REJECT_REASON
                     else f"the application reads status={a.get('status')!r}, review_notes="
                          f"{'the reason' if a.get('review_notes') == REJECT_REASON else repr(a.get('review_notes'))}")


async def _bundle(bag: Any, parse: Any, outcomes: Dict[str, dict], aid: str) -> None:
    """The bundle's answer is read here and nowhere else: its row is written by hand (tool_row), from four facts."""
    name = effect_name(BUNDLE)
    t0 = time.monotonic()
    ok, ans, code = await _admin(bag, parse, BUNDLE, {"application_id": aid})
    ms = int((time.monotonic() - t0) * 1000)
    ans = ans if isinstance(ans, dict) else {}
    ctype, size = str(ans.get("content_type") or ""), ans.get("size_bytes")
    digest = ans.get("sha256")
    fail = None
    if not ok:
        fail = f"adminDownloadOperatorBundle answered HTTP {code} for the pair's own operator"
    elif "gzip" not in ctype or not isinstance(size, int) or size <= 0:
        fail = f"BUG-FIND: adminDownloadOperatorBundle: the answer names content_type={ctype!r}, size_bytes={size!r}"
    elif "encoded_preview_hex" in ans:
        fail = ("BUG-FIND: adminDownloadOperatorBundle: the answer carries the bundle's first bytes "
                "(encoded_preview_hex), a piece of an operator's credentials in every caller's transcript")
    elif not (isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)):
        fail = "BUG-FIND: adminDownloadOperatorBundle: the answer gives no sha256 of the bundle"
    del ans
    tool_row(name, outcomes, "admin_effect", ok and fail is None, code, ms, fail,
             {"content_type": ctype, "size_bytes": size if isinstance(size, int) else None,
              "digest_given": isinstance(digest, str), "bytes_kept": "none"})
    outcomes[name]["contract_tier"] = "admin_effect"


async def _rotate(bag: Any, parse: Any, outcomes: Dict[str, dict], aid: str) -> None:
    """The answer carries the new token (shown once): it is compared by its first eight characters in this process and
    kept nowhere; the row is written by hand (tool_row)."""
    name = effect_name(ROTATE)
    ok0, a0, code0 = await _application(bag, parse, aid)
    if not ok0:
        return effect_unmeasured(outcomes, ROTATE, f"the pair's operator's application could not be read before the "
                                                   f"rotation (HTTP {code0})")
    prefix0, issued0 = a0.get("docker_pull_token_prefix"), a0.get("docker_pull_token_issued_at")
    t0 = time.monotonic()
    ok, ans, code = await _admin(bag, parse, ROTATE, {"application_id": aid})
    ms = int((time.monotonic() - t0) * 1000)
    token = ans.get("pull_token") if ok and isinstance(ans, dict) else None
    new_prefix = token[:8] if isinstance(token, str) and token.startswith("dpt_") and len(token) >= 40 else None
    del token, ans   # never kept past this line
    fail = None
    moved = {"prefix_moved": False, "issued_at_moved": False}
    if not ok:
        fail = f"rotateOperatorPullToken answered HTTP {code} for the pair's own operator"
    elif new_prefix is None:
        fail = "BUG-FIND: rotateOperatorPullToken: the answer carries no new pull token (dpt_)"
    else:
        ok1, a1, code1 = await _application(bag, parse, aid)
        moved = {"prefix_moved": ok1 and a1.get("docker_pull_token_prefix") == new_prefix != prefix0,
                 "issued_at_moved": ok1 and a1.get("docker_pull_token_issued_at") not in (None, issued0)}
        if not ok1:
            fail = f"rotateOperatorPullToken: the application could not be read afterwards (HTTP {code1})"
        elif not all(moved.values()):
            fail = ("BUG-FIND: rotateOperatorPullToken: the application's pull token "
                    + ("prefix did not move to the new token's" if not moved["prefix_moved"] else "issue time did not move"))
    tool_row(name, outcomes, "admin_effect", ok and fail is None, code, ms, fail, {**moved, "token_kept": "none"})
    outcomes[name]["contract_tier"] = "admin_effect"


async def lifecycle_last_pair_operators(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    """A frame request and an application of the run's own, then the pair's own operator, revoked last (the module
    docstring)."""
    def _none(why: str) -> None:
        for tool in OWN_TOOLS + OPERATOR_TOOLS:
            effect_unmeasured(outcomes, tool, why)
    if not ephemeral_target():
        return _none(NOT_EPHEMERAL)
    if getattr(bag, "rpc_admin", None) is None:
        return _none("this flow carries no admin bridge (bag.rpc_admin)")
    st, senders = await _rest(bag, parse, "GET", "/api/v1/admin/email/senders")
    smtp = senders.get("smtp_configured") if st == 200 and isinstance(senders, dict) else None
    if smtp is not False:
        return _none(f"{MAILS}, and " + ("this target sends mail (smtp_configured true)" if smtp is True else
                                         f"whether this target sends mail could not be read (HTTP {st})"))
    tag = f"{int(time.time())}-{secrets.token_hex(3)}"
    await _request_frame(rpc, parse, bag, outcomes, tag)
    await _reject_own_application(bag, parse, outcomes, tag)

    ok, listing, code = await _admin(bag, parse, APPLICATIONS, {"status": "approved"})
    op = pick_operator(listing) if ok else None
    if op is None:
        why = (f"the operator applications could not be listed (HTTP {code})" if not ok else
               "the target holds no approved cloud-hosted operator of its own")
        for tool in OPERATOR_TOOLS:
            effect_unmeasured(outcomes, tool, why)
        return
    aid = str(op["id"])
    await _bundle(bag, parse, outcomes, aid)
    await _rotate(bag, parse, outcomes, aid)
    await effect(bag, parse, SUSPEND, {"application_id": aid, "reason": SUSPEND_REASON}, outcomes,
                 check=_status_is("suspended"))
    await _read_back(bag, parse, outcomes, SUSPEND, aid, lambda a: None if str(a.get("status")) == "suspended"
                     else f"the application reads status={a.get('status')!r} afterwards, not 'suspended'")
    # whether the operator IS suspended decides the reinstatement, whatever the suspension's checks found
    ok_r, now, code_r = await _application(bag, parse, aid)
    if ok_r and str(now.get("status")) == "suspended":
        await effect(bag, parse, REINSTATE, {"application_id": aid}, outcomes, check=_status_is("approved"))
        await _read_back(bag, parse, outcomes, REINSTATE, aid, lambda a: None if str(a.get("status")) == "approved"
                         else f"the application reads status={a.get('status')!r} afterwards, not 'approved'")
    else:
        state = now.get("status") if ok_r else f"unread (HTTP {code_r})"
        effect_unmeasured(outcomes, REINSTATE, f"the pair's operator reads status={state} after the suspension, so "
                                               f"there was no suspended operator to reinstate")
    # the very last step of the run on this frame: it ends the pair's operator (the pair's teardown removes it)
    await effect(bag, parse, REVOKE, {"application_id": aid, "reason": REVOKE_REASON}, outcomes,
                 check=_status_is("revoked"))
    await _read_back(bag, parse, outcomes, REVOKE, aid, lambda a: None
                     if str(a.get("status")) == "revoked" and a.get("docker_pull_token_prefix") is None
                     else f"the application reads status={a.get('status')!r}, pull token "
                          f"{'cleared' if a.get('docker_pull_token_prefix') is None else 'still set'} afterwards")


# ── Phase 8 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
LAST_LIFECYCLES: List[Dict[str, Any]] = [
    {"name": "last_registry_icon", "runner": lifecycle_last_registry_icon},
    {"name": "last_pair_operators", "runner": lifecycle_last_pair_operators},   # revokeOperatorAccess is its last step
]


async def run_last(rpc: Any, parse: Any, bag: Any) -> Dict[str, dict]:
    """PHASE 8: each lifecycle in its order, one at a time. A lifecycle that raised says so on a row of its own."""
    rows: Dict[str, dict] = {}
    for item in LAST_LIFECYCLES:
        try:
            await item["runner"](rpc, parse, bag, rows)
        except Exception as e:                                         # noqa: BLE001
            name = f"admin_effect: phase8 {item['name']}"
            rows[name] = lc()._make_outcome(name, "admin_effect", False, "0", 0,
                                            f"the Phase 8 lifecycle {item['name']} raised {type(e).__name__}", {})
    return rows


def phase8_rows(rows: Dict[str, dict], present: Set[str]) -> List[Tuple[str, Dict[str, Any]]]:
    """Phase 8's rows as the run keeps them, as (row name, row): each under its own name, once, after the sweeps, so a
    name the run has already emitted is skipped. A row named for a tool itself (none should be: the sweep wrote that
    name) is filed as that tool's `admin_effect: ` row, so it never vanishes."""
    out: List[Tuple[str, Dict[str, Any]]] = []
    seen = set(present)
    for name in sorted(rows):
        d = rows[name]
        if not isinstance(d, dict):
            continue
        row_name = name if name.startswith(PHASE8_PREFIXES) else effect_name(name)
        if row_name in seen:
            continue
        seen.add(row_name)
        out.append((row_name, d))
    return out
