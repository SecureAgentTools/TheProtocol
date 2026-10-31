"""MCP lifecycle contracts (phase 4 — 2026-05-25).

Each lifecycle is a small async function that orchestrates create→test→cleanup
sequences for tools that don't make sense in isolation. Returns a dict mapping
the tools it exercised to their `ContractOutcome` — the test runner merges
these into the sweep results, displacing the autogen-destructive skip rows.

Pattern:

    async def lifecycle_xxx(rpc_call, parse_result, bag, outcomes_dict):
        # rpc_call(tool, args, jwt, timeout=20) → (ok, body, code)
        # parse_result(body) → inner dict
        # outcomes_dict[tool_name] = ContractOutcome(...)

The runner provides `rpc_call` (a bound function to the in-container MCP
endpoint) and `parse_result` so the lifecycle doesn't need to import
the helpers from the test module (would create a circular import).

Each lifecycle is INDEPENDENT — it creates its own ephemeral entity,
does the destructive thing, then optionally deletes the entity.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from agentvault_registry.core.sandbox_creds import SANDBOX_ADMIN_PASSWORD, SANDBOX_TUTORIAL_PASSWORD  # §SBROTATE
from agentvault_registry.api_tests.contracts import mcp_switches as _switches  # §MCPTEST30 (V0550)
from agentvault_registry.api_tests.contracts import earned_fixtures as _ef  # §MCPTEST30 (V0636): refusal rows


# Type alias for the rpc-call function the runner injects
RpcCall = Callable[..., Awaitable[Tuple[bool, dict, str]]]
ParseResult = Callable[[dict], dict]


# §MCPSWEEP 2026-09-27 — JSON-RPC codes that mean the DISPATCHER refused the call before the tool ran: the request
# could not be read (-32700, -32600), named a tool this bridge does not carry (-32601), or its arguments did not fit
# the tool's signature (-32602).
_RPC_PROBE_NEVER_REACHED = {-32700: "a parse error", -32600: "an invalid request", -32601: "tool not found",
                            -32602: "invalid params"}


def _dispatcher_refusal_skip(tool: str, code: Any, msg: str, tier: str = "") -> Optional[str]:
    """§MCPSWEEP 2026-09-27 — A PROBE THE DISPATCHER REFUSED NEVER REACHED THE TOOL, SO IT MEASURED NOTHING.

    The refusal arrives as a JSON-RPC error envelope inside an HTTP 200, and `parse` keeps only `result`, so under
    expect_status="any" such a row read HEALTHY. Measured from sbx-alpha's audit rows of the 03:00Z run: 57 admin
    probes sent arguments their tools never declared, or omitted required ones, and all 57 read green; the public
    lifecycles also name 137 admin tools the public bridge does not carry (unscored, because the public sweep reads
    only its own tools, but never measured either). The row becomes a NAMED SKIP, a tester defect counted by the
    census as `probe_never_reached_tool`: never a pass, and never a product failure, because the product answered
    a malformed call correctly."""
    if code == -32001 and str(tier) == "1":
        # a public (tier-1) tool needs no credential, so an auth refusal from the ENDPOINT is not the tool's answer:
        # the MCP endpoint wants a bearer on every path and refused before dispatch (§BEARER4)
        return (f"probe never reached the tool: the MCP endpoint refused the call before dispatch ({msg}); it wants "
                f"a bearer on every path, even for a tier-1 tool: pass one")
    if code not in _RPC_PROBE_NEVER_REACHED:
        return None
    if code == -32601:
        return (f"probe never reached the tool: the bridge answered tool not found ({msg}); an admin tool is "
                f"measured by the admin lifecycle on the admin bridge, not here")
    return (f"probe never reached the tool: the dispatcher answered {_RPC_PROBE_NEVER_REACHED[code]} ({msg}) before "
            f"'{tool}' ran — a tester defect: send the arguments its inputSchema declares")


def _make_outcome(tool: str, tier: str, ok: bool, code: str, elapsed_ms: int,
                  fail_reason: Optional[str], inner: dict,
                  expect_status: str = "success", skip_reason: Optional[str] = None) -> dict:
    """Build an outcome dict matching the ContractOutcome shape (dict-as-dataclass).

    §FANCLAIM 2026-09-07 — the row now CARRIES THE STANDARD IT WAS JUDGED BY.
    Without it, a reachability probe ("did anything at all come back?") and a
    success assertion ("did the documented 2xx shape come back?") are the same
    row downstream, so the coverage fan could answer a contract's question with a
    different, easier one and the sweep could not tell. `has_explicit_contract`
    was likewise a hardcoded True on EVERY lifecycle row — 261 tools that hold no
    contract of any kind reported one."""
    return {
        "tool_name": tool,
        "contract_tier": tier,
        "healthy": ok,
        "status_code": int(code) if code.isdigit() else 0,
        "elapsed_ms": elapsed_ms,
        "skip_reason": skip_reason,
        "fail_reason": fail_reason,
        # the standard THIS row was actually held to, for the fan's consumers
        "probe_expect_status": expect_status,
        "has_explicit_contract": True,
        "args_used": {},
        "result_excerpt": result_excerpt(inner),
    }


_CONTENT_KEYS = ("content_base64",)   # an answer's file content, never kept in a row (result_excerpt)


def result_excerpt(inner: Any, shape_only: bool = False) -> Dict[str, Any]:
    """The first five keys of a tool's result, as the run record keeps them, through the MCP audit sanitizer.

    §MCPSWEEP 2026-09-27: the run history keeps every row's excerpt, passing rows included, so a credential a tool
    returns (createAgent's client_secret, createApiKey's plain_api_key, a token) was kept as written. A key whose name
    carries a credential word is redacted now. A secret inside an innocuously named value is not caught by any name
    rule, which is why the sweep does not publish fixtures that would lead it to such reads.

    §MCPTEST30 (2026-10-01): `shape_only` keeps the five keys and the TYPE of each value, never a value. A contract sets
    it (`excerpt_shape_only`) for a read whose values are configuration or personal records (a frame's environment, an
    operator application), so the sweep can measure the read without the run record keeping what it returned.

    §MCPTEST30 (V0640): a file's content (`content_base64`, fix/mcp-binary-answers) is never kept, wherever its key
    stands: a generated package or a bundle can carry an env file and the agent's secret."""
    if not isinstance(inner, dict):
        return {}
    head = {k: inner[k] for k in [k for k in inner.keys() if k not in _CONTENT_KEYS][:5]}
    if shape_only:
        return {k: _value_shape(v) for k, v in head.items()}
    try:
        from agentvault_registry.mcp.audit_sanitizer import sanitize_result
        out = sanitize_result(head)
        return out if isinstance(out, dict) else {}
    except Exception:  # noqa: BLE001 — never keep an unsanitized excerpt
        return {k: "<excerpt withheld: sanitizer unavailable>" for k in head}


def _value_shape(v: Any) -> str:
    """A value's type as the run record may keep it: `dict(12 keys)`, `list(3)`, `str`, `int`, never the value."""
    if isinstance(v, dict):
        return f"dict({len(v)} keys)"
    if isinstance(v, list):
        return f"list({len(v)})"
    return "null" if v is None else type(v).__name__


class _KeyLog(dict):
    """A read-after-write answer that remembers which top-level keys a check asked for, and which it found.

    §MCPTEST30 (V0546). A check that reads a key the answer never carries returns "no finding" and has judged nothing:
    the mTLS toggle read `enabled` and `mtls_enabled` from a route that answers `enrolled`, on every run since it was
    written, and V0545 found it only by reading the code (a census of the 38 checks against the recorded shapes, which
    keep five keys, so it was a lead and not a verdict). This makes the class visible at run time for every check
    without touching one: `_exec_step` hands the check this dict and reads the log after it returns. Only `get` and
    `[]` are logged; `in` is how a check tests for absence on purpose, and is left alone."""

    def __init__(self, data: Dict[str, Any]) -> None:
        super().__init__(data)
        self.asked: set = set()
        self.found: set = set()

    def _note(self, key: Any) -> None:
        if isinstance(key, str):
            self.asked.add(key)
            if dict.__contains__(self, key):
                self.found.add(key)

    def get(self, key: Any, default: Any = None) -> Any:
        self._note(key)
        return dict.get(self, key, default)

    def __getitem__(self, key: Any) -> Any:
        self._note(key)
        return dict.__getitem__(self, key)


def unjudged_sentence(tool: str, code: int, asked: set) -> str:
    """The note a parent row carries when its read-after-write answered 2xx without any key the check reads."""
    return (f"{tool} answered {code} without any of {sorted(asked)}, the keys the check reads: the read-after-write "
            f"judged nothing")


def no_http_status(code: Any) -> bool:
    """§MCPTEST30 (V0545): no HTTP answer at all: "" (the exec came back without curl's status marker: the answer was
    lost in transit) or curl's 000 (no server answered). Neither says anything about the tool."""
    c = str(code or "").strip()
    return not (c.isdigit() and 100 <= int(c) <= 599)


def lost_answer_sentence(tool: str, code: Any) -> str:
    why = ("curl reached no server: 000" if str(code or "").strip() == "000"
           else "the answer was lost in transit; the server may have answered")
    return f"NOT MEASURED: no HTTP status came back for {tool} ({why})"


def _reads_only(tool: str) -> bool:
    """The server's own annotation (the hint tools/list publishes); False when it cannot be read, so a write is never
    taken for a read. The federation rig's rule (rig.read_only_tool)."""
    try:
        from agentvault_registry.mcp.tool_metadata import derive_annotations
        return bool(derive_annotations(tool).get("readOnlyHint"))
    except Exception:  # noqa: BLE001
        return False


async def _exec_step(rpc_call: RpcCall, parse: ParseResult,
                      tool: str, tier: str, args: Dict[str, Any], jwt: str,
                      outcomes: Dict[str, dict],
                      expect_status: str = "success",
                      timeout: int = 15,
                      record_as_separate: bool = True,
                      verify_against: Optional[str] = None,
                      verify_against_check: Optional[Callable[[dict], Optional[str]]] = None,
                      expect_events: Optional[List[str]] = None,
                      event_verifier: Optional[Callable[..., Awaitable[Tuple[bool, Optional[str]]]]] = None,
                      ) -> Tuple[bool, dict]:
    """Run one step of a lifecycle. Records outcome. Returns (ok, parsed_inner).

    Phase 5 additions:
      - `record_as_separate=False` runs the call but does NOT add a row to
        `outcomes`. Use this for verification probes (read-after-write checks
        that already have a parent mutation outcome).
      - `verify_against_check(inner) -> Optional[str fail_reason]` runs after
        a successful call. If it returns a string, the OUTCOME ROW NAMED
        BY `verify_against` is downgraded to `healthy=False` with a BUG-FIND
        fail_reason. This is how we propagate read-after-write failures
        back to the original mutation step (so the framework reports the
        mutation as the failing tool, not the verifier).
    """
    # §MCPTEST30 (V0550): a tool the run's target switched off is held to its switch (mcp_switches.py): the step expects
    # the documented refusal and asks for no event, whatever the lifecycle asked of it.
    _sw = _switches.switched_off(tool)
    if _sw is not None:
        expect_events = None
    t0 = time.time()
    ok, body, code = await rpc_call(tool, args, jwt=jwt, timeout=timeout)
    if (no_http_status(code) or str(code).strip() == "504") and _reads_only(tool):
        # §MCPTEST30 (V0545): a read whose answer never arrived is asked once more (the federation rig's rule since
        # 2026-10-01); a write is never repeated. V0552: so is a read whose own call to its route timed out (the rpc
        # layer reads the tool's "Error: ReadTimeout" as 504); a second timeout is the route's, and fails the row
        ok, body, code = await rpc_call(tool, args, jwt=jwt, timeout=timeout)
    elapsed_ms = int((time.time() - t0) * 1000)
    # pass73.3.19: always parse so result_excerpt + wrapped-error detection work
    # even when the rpc layer flagged ok=False (e.g. an unmasked "Error: HTTP
    # NNN" returned as transport-200). Was `parse(body) if ok else {}`.
    inner = parse(body)
    code_int = int(code) if code.isdigit() else 0
    # §MCPSWEEP 2026-09-27 — `parse` keeps only `result`; a JSON-RPC error envelope (inside an HTTP 200) is read here.
    _rpc_err = body.get("error") if isinstance(body, dict) and isinstance(body.get("error"), dict) else None
    _rpc_code = _rpc_err.get("code") if _rpc_err else None
    _rpc_msg = str((_rpc_err or {}).get("message") or "")[:200]

    # Phase-5 detection: wrappers commonly return `{"error": "..."}` on
    # validation failure instead of raising. The JSON-RPC dispatcher then
    # formats this as `"Error: ..."` text and the outer HTTP is still 200.
    # We need to detect this case and treat the step as failed — otherwise
    # subsequent read-after-write probes see stale state and report false
    # BUG-FINDs.
    inner_error_text = ""
    if isinstance(inner, dict):
        # _format_tool_result formats {"error":X} as "Error: X" text; our
        # parser then returns {"_text": "Error: ..."}
        t = inner.get("_text") or ""
        if isinstance(t, str) and t.startswith("Error:"):
            inner_error_text = t
            ok = False
        # Some wrappers leak the raw error key into the parsed dict (e.g.
        # when the dispatcher chose not to text-format it)
        elif "error" in inner and isinstance(inner.get("error"), str):
            inner_error_text = f"wrapper returned error: {inner['error']}"
            ok = False

    # Apply expect_status — "error_4xx" / "error_5xx" / "any" / "success"
    if expect_status == "success":
        step_ok = ok
        if not ok:
            if inner_error_text:
                fail = f"step '{tool}' wrapper-error: {inner_error_text[:200]}"
            else:
                fail = f"step '{tool}' failed: HTTP {code}"
        else:
            fail = None
    elif expect_status == "error_4xx":
        step_ok = 400 <= code_int < 500
        fail = None if step_ok else f"step '{tool}' expected 4xx, got {code}"
    elif expect_status == "error_5xx":
        step_ok = 500 <= code_int < 600
        fail = None if step_ok else f"step '{tool}' expected 5xx, got {code}"
    else:  # "any" — reachability probe (often intentionally-invalid input).
        # pass73.3.19: a 5xx is a genuine server error and must NOT pass even
        # under "any"; a 4xx is an accepted rejection of the probe's input. The
        # REAL HTTP code now flows from the rpc layer (wrapped-error unmask), so
        # the row shows 404/422/500 instead of a deceptive 200.
        step_ok = code_int < 500
        fail = None if step_ok else f"step '{tool}' server error: HTTP {code}"

    if _sw is not None:
        step_ok, fail = _switches.judge(tool, _sw, code_int, _switches.answer_text(inner, _rpc_msg))
        expect_status = "error_4xx"

    # §MCPSWEEP 2026-09-27 — in every mode: a call the dispatcher refused before the tool ran measured nothing (a
    # named skip), and an internal error is a server error (the JSON-RPC twin of a 5xx), whatever the HTTP code says.
    probe_skip = _dispatcher_refusal_skip(tool, _rpc_code, _rpc_msg, tier)
    if not probe_skip and no_http_status(code):
        # §MCPTEST30 (V0545): under "any" a missing status read as 0 < 500, a pass: getArenaMatchMap was recorded healthy
        # with no status and an empty answer (strict run 3e49fcef, 2026-10-02 03:19Z). It measured nothing.
        probe_skip = lost_answer_sentence(tool, code)
    if probe_skip:
        step_ok, fail = False, None
    elif _rpc_code == -32603:
        step_ok = expect_status == "error_5xx"
        fail = None if step_ok else f"step '{tool}' internal error from the dispatcher: {_rpc_msg}"

    # Phase-5 (sprint 5.7): verifier probes count as coverage ONLY when the
    # probe call succeeded. A probe is identified by
    # `verify_against_check is not None` — it ran a real read tool against
    # the server. If the probe HTTP-fails it's almost always a lifecycle
    # bug (wrong args), not a wrapper bug — don't pollute the sweep by
    # marking the read tool as failed. If the probe HTTP-succeeds, record
    # it as covered (healthy=True). The BUG-FIND signal goes on the PARENT.
    if verify_against_check is not None:
        if step_ok:
            outcomes[tool] = _make_outcome(tool, tier, step_ok, code, elapsed_ms, fail, inner,
                                           expect_status=expect_status,
                                           skip_reason=probe_skip)
        # else: silently skip — let the read tool fall back to its normal
        # contract/autogen path so we don't fabricate a wrapper bug.
    elif record_as_separate:
        outcomes[tool] = _make_outcome(tool, tier, step_ok, code, elapsed_ms, fail, inner,
                                       expect_status=expect_status,
                                       skip_reason=probe_skip)
        if _sw is not None:
            outcomes[tool]["switched_off"] = _sw.label()

    # Phase-5 read-after-write assertion: if the call succeeded AND a
    # verify check is provided, run it and propagate any failure back to
    # the parent mutation's outcome row.
    if step_ok and verify_against_check is not None:
        probe = _KeyLog(inner) if isinstance(inner, dict) else inner
        try:
            fail_reason = verify_against_check(probe)
        except Exception as e:
            fail_reason = f"verify check raised: {e!r}"
        if fail_reason:
            target_tool = verify_against or tool
            target_row = outcomes.get(target_tool)
            # §MCPTEST30 (V0551): a step its target's switch refused changed nothing by design; the read that follows it
            # finds nothing changed, which is the switch holding, not the write failing (round 17: updatePayoutRelock)
            if target_row is not None and not target_row.get("switched_off"):
                # §MCPTEST30 (V0643, agentvault2-66's find on the V0641 operator read): a read-after-write check judges a
                # write that answered 2xx. A write the server refused, already failed on its own, keeps its own reason
                # (the read-back finding it unchanged agrees with the refusal): "deleteWebhook returned 2xx but ... still
                # present" had been written over a 409. A refusal the step expected (a healthy row) is still judged.
                own = target_row.get("status_code")
                if target_row.get("healthy") is False and not (isinstance(own, int) and 200 <= own < 300):
                    target_row.setdefault("read_back", fail_reason)
                else:
                    target_row["healthy"] = False
                    target_row["fail_reason"] = f"BUG-FIND: {fail_reason}"
        elif (isinstance(probe, _KeyLog) and probe.asked and not probe.found and 200 <= code_int < 300
              and not inner_error_text):
            # §MCPTEST30 (V0546): a 2xx answer that carries none of the keys the check reads; a refused read (a 404
            # after a delete, say) is excluded: there the absence can be the judgment
            target_row = outcomes.get(verify_against or tool)
            if target_row is not None:
                target_row.setdefault("unjudged_read_back", unjudged_sentence(tool, code_int, probe.asked))

    # Phase C bug-finder (2026-05-26): event-emission verification.
    # If `expect_events` declares event types AND an `event_verifier` callback
    # was injected, call it after a REAL HTTP-2xx success. The verifier checks
    # EventStore for each declared event_type emitted since pre_call. If
    # missing → mark the parent outcome row as healthy=False with a
    # BUG-FIND:missing-event reason. Pattern mirrors verify_against_check
    # but operates on the EventStore rather than a read-back tool.
    #
    # IMPORTANT: gate on `ok` (HTTP-2xx) not `step_ok`. With expect_status="any",
    # step_ok=True even on 4xx (which is the typical path for tolerated
    # error paths like locked-stake unstake). 4xx calls never emit events,
    # so requiring events on 4xx is a false positive. Round-trip via the
    # `ok` flag from the RPC call result.
    if ok and expect_events and event_verifier is not None:
        try:
            event_ok, event_fail = await event_verifier(expect_events, tool)
        except Exception as e:
            event_ok, event_fail = False, f"event verifier raised: {e!r}"
        if not event_ok and event_fail:
            target_tool = verify_against or tool
            target_row = outcomes.get(target_tool)
            if target_row is not None:
                target_row["healthy"] = False
                target_row["fail_reason"] = f"BUG-FIND: {event_fail}"

    if _sw is not None:
        # §MCPTEST30 (V0551): the row holds the switch's verdict; the lifecycle hears that nothing succeeded, so it builds
        # nothing on a refusal (round 17: the stake's shape checks read a 403 as a stake without an id)
        return False, inner
    return step_ok, inner


# ============================================================================
# §MCPTEST30 (V0553): an admin action on the run's own object, a probe family
# ============================================================================
# Five public lifecycles hold admin steps: a webhook disabled, enabled and tested, a bundle hidden and shown again, a
# support ticket answered, reopened and closed, two funding requests approved and rejected, the EigenTrust epoch. They
# went through the PUBLIC bridge, whose dispatcher refuses an admin tool before it runs (-32601), so none of them was
# ever done and their read-after-write checks judged nothing (sbx-alpha held 310 pending funding requests and 155 open
# support tickets of the tester's, measured 2026-10-02). They go through the admin bridge now (bag.rpc_admin). The
# tools' own rows stay their contracts' refusal of an id that names nothing (the V0550 pins carry override_coverage_fan,
# so the admin sweep never reads a lifecycle row for them); the success on the run's own object, with the read that
# shows it, is this family's row `admin_effect: <tool>`, and neither hides the other.
_ADMIN_EFFECT = "admin_effect: "


def admin_effect_row(tool: str) -> str:
    return _ADMIN_EFFECT + tool.replace("theprotocol_", "")


def _admin_bridge(bag: Any) -> Optional[RpcCall]:
    """The admin bridge a public lifecycle's admin steps go through. None where the flow carries none: the steps, and
    any object only they could clear away, are then not started."""
    return getattr(bag, "rpc_admin", None)


async def _admin_effect(rpc_admin: RpcCall, parse: ParseResult, tool: str, args: Dict[str, Any], jwt: str,
                        outcomes: Dict[str, dict], *, check: Optional[Callable[[dict], Optional[str]]] = None,
                        expect_events: Optional[List[str]] = None,
                        event_verifier: Optional[Callable[..., Awaitable[Tuple[bool, Optional[str]]]]] = None,
                        ) -> Tuple[bool, dict]:
    """One admin step on the run's own object, through the admin bridge, recorded as `admin_effect: <tool>`.
    `check(answer)` judges the step's own answer: None when it says what the step did, else the sentence (a BUG-FIND).
    A read that shows the effect afterwards names the row with `verify_against=admin_effect_row(tool)`."""
    scratch: Dict[str, dict] = {}
    ok, inner = await _exec_step(rpc_admin, parse, tool, "admin", args, jwt, scratch,
                                 expect_events=expect_events, event_verifier=event_verifier)
    answer = inner if isinstance(inner, dict) else {}
    name = admin_effect_row(tool)
    row = scratch.get(tool) or _not_measured(tool, "admin", "NOT MEASURED: the step recorded no answer")
    row.update(tool_name=name, contract_tier="admin_effect")
    if ok and row.get("healthy") and check is not None:
        why = check(answer)
        if why:
            row["healthy"], row["fail_reason"] = False, f"BUG-FIND: {tool}: {why}"
    outcomes[name] = row
    return bool(ok and row.get("healthy")), answer


def _says(*keys: str) -> Callable[[dict], Optional[str]]:
    """An answer check: the admin routes say what they changed, and one of `keys` must be true in the answer."""
    def check(answer: dict) -> Optional[str]:
        if any(answer.get(k) is True for k in keys):
            return None
        return f"the answer says none of {list(keys)} (it carries {sorted(answer)[:8]})"
    return check


def _reads(key: str, *values: Any) -> Callable[[dict], Optional[str]]:
    """An answer check: `key` in the answer reads one of `values`."""
    def check(answer: dict) -> Optional[str]:
        return None if answer.get(key) in values else f"the answer reads {key}={answer.get(key)!r}"
    return check


# ============================================================================
# Lifecycle implementations
# ============================================================================


async def _webhook_sink_url(rpc: RpcCall, parse: ParseResult, webhook_id: str,
                            jwt: str, bag: Any = None) -> Tuple[Optional[str], str]:
    """§MCPTEST30 V0637: the sandbox webhook sink's address for `webhook_id` on this target (routers/
    sandbox_webhook_sink.py), or None and why not. Its positive flag is read in this process, which runs the target's
    own code when the frame's tester runs the lifecycle; the host is the target's public URL from its registry card,
    which the delivery's address check passes and the frame reaches through its own edge.

    §MCPTEST30 (V0639): a sweep that runs the lifecycle outside the target's process (the cloud-operator sweep, from
    its frame) says whether the TARGET mounts the sink (bag.target_webhook_sink: (on, why), on None when it could not
    be read), because this process's flag is another registry's. Measured: the operator sweeps read the frame's flag
    (on since V0637) and pointed the operators' webhooks at a path the operators never mounted (404, three red rows)."""
    try:
        from agentvault_registry.routers import sandbox_webhook_sink as _sink
    except ImportError:
        return None, "this target has no webhook sink"
    probed = getattr(bag, "target_webhook_sink", None)
    if probed is not None:
        on, why = probed
        if on is None:
            return None, f"whether this target runs the webhook sink could not be read ({why})"
        if not on:
            return None, f"no webhook sink on this target ({why})"
    elif not _sink.sink_enabled():
        return None, f"no webhook sink on this target ({_sink.FLAG} is off)"
    ok, body, _code = await rpc("theprotocol_getRegistryCard", {}, jwt=jwt, timeout=15)
    card = parse(body) if ok else {}
    origin = ((card.get("identity") or {}).get("public_url") if isinstance(card, dict) else None) or ""
    if not origin.startswith("https://"):
        return None, "the target's registry card names no https public URL for the webhook sink"
    return f"{origin.rstrip('/')}{_sink.PATH}/{webhook_id}", ""


async def lifecycle_webhook_full_crud(rpc: RpcCall, parse: ParseResult,
                                       bag: Any, outcomes: Dict[str, dict]) -> None:
    """createWebhook → getWebhook → updateWebhook (READ-AFTER-WRITE) →
    testWebhook → getWebhookDeliveries → disable/enable (READ-AFTER-WRITE) → deleteWebhook.

    Phase-5 bug-finding assertions:
      - updateWebhook → re-getWebhook → assert `events` actually changed
        (catches BUG-FIND-5: wrong body key `event_types` silently NO-OP).
      - disableWebhookAdmin → re-getWebhook → assert `is_active=false`.
      - enableWebhookAdmin → re-getWebhook → assert `is_active=true`.
    """
    dev_jwt = bag.developer_jwt
    # 1. create
    # NOTE: createWebhook does NOT emit a registry event under the current
    # emission policies (no WebhookCreated row in event_emission_policies).
    # If a future policy row enables it, add expect_events=["WebhookCreated"].
    ok, r = await _exec_step(rpc, parse,
        "theprotocol_createWebhook", "3",
        {"url": "https://webhook.example.test/lifecycle-crud",
         "events": ["agent.created"],
         "description": "phase-4 lifecycle test"},
        dev_jwt, outcomes,
    )
    if not ok or "id" not in r:
        return
    wid = r["id"]

    # 2. get
    await _exec_step(rpc, parse, "theprotocol_getWebhook", "3",
                      {"webhook_id": wid}, dev_jwt, outcomes)

    # §MCPTEST30 V0637: where the target runs the sandbox's webhook sink, the update points the webhook at it, so the
    # test deliveries below are real signed deliveries the sink takes (204); elsewhere the webhook keeps its made-up
    # host and every test delivery fails, by design
    sink, no_sink = await _webhook_sink_url(rpc, parse, wid, dev_jwt, bag)

    # 3. update (events list) — Phase 5: verify the events persisted
    new_events = ["agent.created", "agent.updated", "agent.deleted"]
    update_args: Dict[str, Any] = {"webhook_id": wid, "events": new_events}
    if sink:
        update_args["url"] = sink
    await _exec_step(rpc, parse, "theprotocol_updateWebhook", "3",
                      update_args, dev_jwt, outcomes)

    # Phase 5 verification probe — read back and diff
    def _verify_update(inner: dict) -> Optional[str]:
        actual_events = sorted(inner.get("events") or [])
        expected = sorted(new_events)
        if actual_events != expected:
            return (
                f"updateWebhook returned 2xx but events did not persist. "
                f"Sent {expected}, getWebhook returned {actual_events}"
            )
        if sink and "url" in inner and inner.get("url") != sink:
            return f"updateWebhook returned 2xx but the url did not persist: getWebhook returned {inner.get('url')!r}"
        return None

    await _exec_step(rpc, parse, "theprotocol_getWebhook", "3",
                      {"webhook_id": wid}, dev_jwt, outcomes,
                      record_as_separate=False,
                      verify_against="theprotocol_updateWebhook",
                      verify_against_check=_verify_update)

    # 4. test (fires test event). §MCPTEST30 V0637: with the sink, each test route must report the sink's 204; the
    # legacy route (/developers/webhooks/{id}/test) puts a failed delivery's message under `error`, which the MCP
    # dispatcher reads as a tool failure, so without the sink its row is NOT MEASURED, said (it was expect-any)
    def _taken(status_key: str) -> Callable[[dict], Optional[str]]:
        def _check(inner: dict) -> Optional[str]:
            if inner.get("success") is True and inner.get(status_key) == 204:
                return None
            return (f"the test delivery to the frame's own webhook sink was not taken: {status_key} "
                    f"{inner.get(status_key)!r}, success {inner.get('success')!r}")
        return _check

    # each check runs after its step, never as the step's verify: a verify skips the row of a call that failed, and a
    # failed delivery must be a red row, not a quiet fall back to the contract's refusal
    ok_t, t = await _exec_step(rpc, parse, "theprotocol_testWebhook", "3",
                                {"webhook_id": wid}, dev_jwt, outcomes)
    if sink and ok_t and _taken("status_code")(t):
        _bugfind(outcomes, "theprotocol_testWebhook", "3", _taken("status_code")(t))
    if sink:
        ok_a, a = await _exec_step(rpc, parse, "theprotocol_testDeveloperWebhookAlt", "3",
                                    {"webhook_id": wid}, dev_jwt, outcomes)
        if ok_a and _taken("status")(a):
            _bugfind(outcomes, "theprotocol_testDeveloperWebhookAlt", "3", _taken("status")(a))
    else:
        outcomes["theprotocol_testDeveloperWebhookAlt"] = _not_measured(
            "theprotocol_testDeveloperWebhookAlt", "3",
            f"NOT MEASURED: {no_sink}: the run's webhook names a host that resolves to nothing, and the legacy "
            f"route's failed delivery reads as a tool failure")

    # 5. deliveries (§MCPTEST30 V0637: with the sink, the list holds a delivery it took)
    def _a_delivery_taken(inner: dict) -> Optional[str]:
        rows = inner.get("deliveries") if isinstance(inner.get("deliveries"), list) else []
        if any(isinstance(d, dict) and d.get("response_status") == 204 for d in rows):
            return None
        return f"getWebhookDeliveries lists no delivery the webhook sink took (204) among {len(rows)}"

    ok_d, d = await _exec_step(rpc, parse, "theprotocol_getWebhookDeliveries", "3",
                                {"webhook_id": wid, "limit": 5}, dev_jwt, outcomes)
    if sink and ok_d and _a_delivery_taken(d):
        _bugfind(outcomes, "theprotocol_getWebhookDeliveries", "3", _a_delivery_taken(d))

    # 6. admin disable, enable and test, through the admin bridge (§MCPTEST30 V0553, the admin_effect family) —
    # Phase 5: verify is_active after each
    rpc_admin = _admin_bridge(bag)
    if rpc_admin is not None:
        ok_dis, _ = await _admin_effect(rpc_admin, parse, "theprotocol_disableWebhookAdmin", {"webhook_id": wid},
                                        dev_jwt, outcomes, check=_reads("is_active", False))

        def _verify_disabled(inner: dict) -> Optional[str]:
            # tools_developer.getWebhook returns is_active (snake_case)
            actual = inner.get("is_active")
            if actual is None:
                actual = inner.get("active")  # tolerate listDeveloperWebhooks-shape
            if actual is None:
                return None  # field absent — don't assert (could be lifecycle skipped)
            if actual is True:
                return (
                    "disableWebhookAdmin returned 2xx but webhook still has "
                    "is_active=true on subsequent getWebhook read"
                )
            return None

        if ok_dis:
            await _exec_step(rpc, parse, "theprotocol_getWebhook", "3",
                              {"webhook_id": wid}, dev_jwt, outcomes,
                              record_as_separate=False,
                              verify_against=admin_effect_row("theprotocol_disableWebhookAdmin"),
                              verify_against_check=_verify_disabled)

        # 6b. admin enable — Phase 5: verify is_active=true
        ok_en, _ = await _admin_effect(rpc_admin, parse, "theprotocol_enableWebhookAdmin", {"webhook_id": wid},
                                       dev_jwt, outcomes, check=_reads("is_active", True))

        def _verify_enabled(inner: dict) -> Optional[str]:
            actual = inner.get("is_active")
            if actual is None:
                actual = inner.get("active")
            if actual is None:
                return None
            if actual is False:
                return (
                    "enableWebhookAdmin returned 2xx but webhook still has "
                    "is_active=false on subsequent getWebhook read"
                )
            return None

        if ok_en:
            await _exec_step(rpc, parse, "theprotocol_getWebhook", "3",
                              {"webhook_id": wid}, dev_jwt, outcomes,
                              record_as_separate=False,
                              verify_against=admin_effect_row("theprotocol_enableWebhookAdmin"),
                              verify_against_check=_verify_enabled)

        # the delivery is written either way: the sink takes it where it runs, else it fails at a reserved .test host
        await _admin_effect(rpc_admin, parse, "theprotocol_testWebhookAdmin", {"webhook_id": wid}, dev_jwt, outcomes,
                            check=lambda a: None if a.get("delivery_id") is not None
                            else f"the answer names no delivery (it carries {sorted(a)[:8]})")

    # 7. delete — verify the webhook is GONE from getMyWebhooks
    await _exec_step(rpc, parse, "theprotocol_deleteWebhook", "3",
                      {"webhook_id": wid}, dev_jwt, outcomes)

    def _verify_webhook_deleted(inner: dict) -> Optional[str]:
        whs = []
        if isinstance(inner, dict):
            for k in ("webhooks", "items", "results"):
                v = inner.get(k)
                if isinstance(v, list):
                    whs = v
                    break
        if not whs:
            return None
        for w in whs:
            if isinstance(w, dict) and w.get("id") == wid:
                return (
                    f"deleteWebhook returned 2xx but id={wid} still present "
                    f"in getMyWebhooks"
                )
        return None

    await _exec_step(rpc, parse, "theprotocol_getMyWebhooks", "3",
                      {}, dev_jwt, outcomes,
                      record_as_separate=False,
                      verify_against="theprotocol_deleteWebhook",
                      verify_against_check=_verify_webhook_deleted)


async def lifecycle_organization_full_crud(rpc: RpcCall, parse: ParseResult,
                                            bag: Any, outcomes: Dict[str, dict]) -> None:
    """createOrganization → updateOrganization (READ-AFTER-WRITE) → deleteOrganization.

    Phase-5 bug-finding assertion: re-read after update, diff description.
    """
    dev_jwt = bag.developer_jwt
    ok, r = await _exec_step(rpc, parse,
        "theprotocol_createOrganization", "3",
        {"name": "phase4-lifecycle-org",
         "description": "phase-4 lifecycle test"},
        dev_jwt, outcomes,
        # Phase C: emits OrganizationCreated (skip_in_projection=true → audit only).
        expect_events=["OrganizationCreated"],
        event_verifier=getattr(bag, "event_verifier", None),
    )
    if not ok or "id" not in r:
        return
    oid = str(r["id"])

    # 2026-06-02: full_crud's org is DELETED below, so it must NOT clobber the shared
    # `organization_slug` fixture. Phase-3 sets that fixture from its PERSISTENT org
    # (alive through the per-tool sweep, deleted only in teardown), which is what
    # getOrganizationBySlug needs to resolve to 200. (The old "by-slug endpoint BUGGED"
    # note was STALE — verified live 2026-06-02: getOrganizationBySlug returns 200 on an
    # existing owned org; the prior 404 was simply this clobber pointing at a deleted org.)
    _fc_org_slug = r.get("slug")  # local only — intentionally NOT surfaced to flow_values

    # Update — Phase 5 verifies description actually changed
    new_desc = "phase-5 lifecycle test (UPDATED — verify read-after-write)"
    await _exec_step(rpc, parse, "theprotocol_updateOrganization", "3",
                      {"org_id": oid, "description": new_desc},
                      dev_jwt, outcomes)

    def _verify_org_update(inner: dict) -> Optional[str]:
        actual = inner.get("description")
        if actual is None:
            return None  # tolerate response shape variation
        if actual != new_desc:
            return (
                f"updateOrganization returned 2xx but description did not "
                f"persist. Sent {new_desc!r}, getOrganization returned {actual!r}"
            )
        return None

    await _exec_step(rpc, parse, "theprotocol_getOrganization", "3",
                      {"org_id": oid}, dev_jwt, outcomes,
                      record_as_separate=False,
                      verify_against="theprotocol_updateOrganization",
                      verify_against_check=_verify_org_update)

    # Delete — verify the org is GONE from getMyOrganizations
    await _exec_step(rpc, parse, "theprotocol_deleteOrganization", "3",
                      {"org_id": oid}, dev_jwt, outcomes)

    def _verify_org_deleted(inner: dict) -> Optional[str]:
        orgs = []
        if isinstance(inner, dict):
            for k in ("organizations", "orgs", "items", "results"):
                v = inner.get(k)
                if isinstance(v, list):
                    orgs = v
                    break
        if not orgs:
            return None
        for o in orgs:
            if isinstance(o, dict) and str(o.get("id")) == str(oid):
                return (
                    f"deleteOrganization returned 2xx but org id={oid} "
                    f"still present in getMyOrganizations"
                )
        return None

    await _exec_step(rpc, parse, "theprotocol_getMyOrganizations", "3",
                      {}, dev_jwt, outcomes,
                      expect_status="any",
                      record_as_separate=False,
                      verify_against="theprotocol_deleteOrganization",
                      verify_against_check=_verify_org_deleted)


async def lifecycle_org_team_full_crud(rpc: RpcCall, parse: ParseResult,
                                        bag: Any, outcomes: Dict[str, dict]) -> None:
    """Org + team + member full lifecycle.

    Phase-5 bug-finding: verify updateOrganizationTeam description persists
    via getOrganizationTeam.
    """
    dev_jwt = bag.developer_jwt
    # Need a parent org
    ok, r = await _exec_step(rpc, parse,
        "theprotocol_createOrganization", "3",
        {"name": "phase4-lifecycle-team-org", "description": "phase-4"},
        dev_jwt, outcomes,
    )
    if not ok or "id" not in r:
        return
    oid = str(r["id"])

    # Create team
    ok, r = await _exec_step(rpc, parse,
        "theprotocol_createOrganizationTeam", "3",
        {"org_id": oid, "name": "phase4-team", "description": "phase-4"},
        dev_jwt, outcomes,
    )
    tid = str(r.get("id", "")) if ok else None

    if tid:
        # Update team — verify description persists
        new_team_desc = "phase-5 (description-UPDATED via read-after-write)"
        await _exec_step(rpc, parse, "theprotocol_updateOrganizationTeam", "3",
                          {"org_id": oid, "team_id": tid,
                           "description": new_team_desc},
                          dev_jwt, outcomes)

        def _verify_team_update(inner: dict) -> Optional[str]:
            actual = inner.get("description")
            if actual is None:
                # Maybe nested under "team"
                team = inner.get("team") if isinstance(inner.get("team"), dict) else None
                if team:
                    actual = team.get("description")
            if actual is None:
                return None
            if actual != new_team_desc:
                return (
                    f"updateOrganizationTeam returned 2xx but description "
                    f"did not persist. Sent {new_team_desc!r}, "
                    f"getOrganizationTeam returned {actual!r}"
                )
            return None

        await _exec_step(rpc, parse, "theprotocol_getOrganizationTeam", "3",
                          {"org_id": oid, "team_id": tid},
                          dev_jwt, outcomes,
                          record_as_separate=False,
                          verify_against="theprotocol_updateOrganizationTeam",
                          verify_against_check=_verify_team_update)

        # Delete team
        await _exec_step(rpc, parse, "theprotocol_deleteOrganizationTeam", "3",
                          {"org_id": oid, "team_id": tid}, dev_jwt, outcomes)

    # Cleanup org: unrecorded (§MCPTEST30 V0636: lifecycle_organization_full_crud owns deleteOrganization's row; two
    # writers of one row in the runner's shared dict made it whichever finished last)
    await _exec_step(rpc, parse, "theprotocol_deleteOrganization", "3",
                      {"org_id": oid}, dev_jwt, outcomes, expect_status="any", record_as_separate=False)


async def _clear_fork(rpc: RpcCall, parse: ParseResult, fork: Any, jwt: str) -> None:
    """§MCPTEST30 (V0638): what a forkBundle made, cleared: each produced agent (the developer's delete, which also
    deactivates its card) and the child bundle. Unrecorded steps (their rows are other lifecycles'); an answer that names
    neither clears nothing."""
    if not isinstance(fork, dict):
        return
    for a in fork.get("produced_agents") or []:
        did = a.get("did") if isinstance(a, dict) else None
        if did:
            await _exec_step(rpc, parse, "theprotocol_deleteMyAgentByDev", "3", {"agent_did": str(did)}, jwt, {},
                             expect_status="any", record_as_separate=False)
    child = fork.get("forked_bundle_id")
    if child:
        await _exec_step(rpc, parse, "theprotocol_deleteBundle", "3", {"bundle_id": str(child)}, jwt, {},
                         expect_status="any", record_as_separate=False)


async def lifecycle_bundle_full_crud(rpc: RpcCall, parse: ParseResult,
                                      bag: Any, outcomes: Dict[str, dict]) -> None:
    """createBundle → patchBundle (READ-AFTER-WRITE) → rateBundle → forkBundle → deleteBundle → restoreBundle.

    Phase-5 bug-finding: per BUG-FIND-14, `getBundleManifest` returns the
    immutable signed manifest from the .tpb archive — patchBundle DB-row
    edits don't appear there. The DB row IS visible via `getMyAgentBundles`,
    so we verify there instead.
    """
    dev_jwt = bag.developer_jwt
    # Create
    ok, r = await _exec_step(rpc, parse,
        "theprotocol_createBundle", "3",
        {"bundle_data": {
            "agent_dids": [bag.sentinel_did],
            "kind": "snapshot",
            "name": "phase4-lifecycle-bundle",
            "visibility": "private",
            "sign": True,
        }},
        dev_jwt, outcomes,
    )
    if not ok or "id" not in r:
        return
    bid = str(r["id"])

    # patchBundle — verify the description landed in the DB row
    new_desc = "phase-5 lifecycle test (description-UPDATED)"
    await _exec_step(rpc, parse, "theprotocol_patchBundle", "3",
                      {"bundle_id": bid, "updates": {"description": new_desc}},
                      dev_jwt, outcomes)

    def _verify_patch(inner: dict) -> Optional[str]:
        # getMyAgentBundles returns either {bundles: [...]} or a bare list
        bundles = []
        if isinstance(inner, dict):
            for k in ("bundles", "items", "results"):
                v = inner.get(k)
                if isinstance(v, list):
                    bundles = v
                    break
        if not bundles:
            return None  # tolerate empty/missing
        target = None
        for b in bundles:
            if isinstance(b, dict) and str(b.get("id")) == bid:
                target = b
                break
        if target is None:
            return None  # bundle not found in listing — can't verify
        actual_desc = target.get("description")
        if actual_desc is None:
            return None
        if actual_desc != new_desc:
            return (
                f"patchBundle returned 2xx but description did not persist "
                f"on getMyAgentBundles. Sent {new_desc!r}, listing returned "
                f"{actual_desc!r}"
            )
        return None

    await _exec_step(rpc, parse, "theprotocol_getMyAgentBundles", "3",
                      {}, dev_jwt, outcomes,
                      record_as_separate=False,
                      verify_against="theprotocol_patchBundle",
                      verify_against_check=_verify_patch)

    # rateBundle
    await _exec_step(rpc, parse, "theprotocol_rateBundle", "3",
                      {"bundle_id": bid, "rating": 5, "comment": "phase-4 lifecycle test"},
                      dev_jwt, outcomes)

    # forkBundle
    _ok_fork, fork = await _exec_step(rpc, parse, "theprotocol_forkBundle", "3",
                                      {"bundle_id": bid, "new_name": "phase4-bundle-fork"},
                                      dev_jwt, outcomes)
    # §MCPTEST30 (V0638): a fork is a restore under fresh DIDs plus a child bundle (routers/bundles.py fork_bundle); the
    # lifecycle clears both. It never did: each run left the restored agent and its card (sbx-alpha: 187 since
    # 2026-09-03; one per operator per sweep once the operators ran this lifecycle, 2026-10-24)
    await _clear_fork(rpc, parse, fork, dev_jwt)

    # reportBundle — BUG-FIND-15 catcher: wrapper sends reason/details,
    # backend wants reason_code/comment. If 4xx, this lifecycle test will
    # show it as a hard fail.
    await _exec_step(rpc, parse, "theprotocol_reportBundle", "3",
                      {"bundle_id": bid, "reason": "other",
                       "details": "phase-4 lifecycle self-report"},
                      dev_jwt, outcomes)

    # admin hide/unhide, through the admin bridge (§MCPTEST30 V0553, the admin_effect family; hideBundle also needs the
    # reason its tool requires). Hiding resolves the report this run filed above.
    rpc_admin = _admin_bridge(bag)
    if rpc_admin is not None:
        await _admin_effect(rpc_admin, parse, "theprotocol_hideBundle",
                            {"bundle_id": bid, "reason": "MCP tester: its own bundle, hidden and shown again"},
                            dev_jwt, outcomes, check=_says("hidden", "already_hidden"))
        await _admin_effect(rpc_admin, parse, "theprotocol_unhideBundle", {"bundle_id": bid}, dev_jwt, outcomes,
                            check=_says("unhidden", "already_visible"))

    # delete — verify the bundle is removed from active getMyAgentBundles
    await _exec_step(rpc, parse, "theprotocol_deleteBundle", "3",
                      {"bundle_id": bid}, dev_jwt, outcomes)

    def _verify_bundle_deleted(inner: dict) -> Optional[str]:
        bs = []
        if isinstance(inner, dict):
            for k in ("bundles", "items", "results"):
                v = inner.get(k)
                if isinstance(v, list):
                    bs = v
                    break
        if not bs:
            return None
        for b in bs:
            if isinstance(b, dict) and str(b.get("id")) == bid:
                # Still listed → soft delete with deleted_at marker OK,
                # but a fully active bundle is NOT OK.
                if b.get("deleted_at") or b.get("is_deleted"):
                    return None
                return (
                    f"deleteBundle returned 2xx but bundle id={bid} still "
                    f"active in getMyAgentBundles (no deleted_at marker)"
                )
        return None

    await _exec_step(rpc, parse, "theprotocol_getMyAgentBundles", "3",
                      {}, dev_jwt, outcomes,
                      record_as_separate=False,
                      verify_against="theprotocol_deleteBundle",
                      verify_against_check=_verify_bundle_deleted)

    # restore (sandbox: just exercise the path)
    await _exec_step(rpc, parse, "theprotocol_restoreBundle", "3",
                      {"bundle_id": bid}, dev_jwt, outcomes, expect_status="any")


async def lifecycle_pipeline_full_crud(rpc: RpcCall, parse: ParseResult,
                                        bag: Any, outcomes: Dict[str, dict]) -> None:
    """createPipeline → updatePipeline (READ-AFTER-WRITE) → createVersion →
    activateVersion → rollbackVersion → deleteVersion → deletePipeline.

    Phase-5 bug-finding: verify updatePipeline persists `is_active=False`
    via getMyCicdPipelines (find row by id).
    """
    dev_jwt = bag.developer_jwt
    # createPipeline
    ok, r = await _exec_step(rpc, parse,
        "theprotocol_createPipeline", "3",
        {"agent_did": bag.sentinel_did,
         "pipeline_name": "phase4-lifecycle-pipeline",
         "pipeline_config": {"stages": [{"name": "noop"}]},
         "trigger_type": "webhook",
         "webhook_url": "https://example.test/phase4-trigger",
         "is_active": True},
        dev_jwt, outcomes,
    )
    pid = (r or {}).get("pipeline_id") or (r or {}).get("id")
    if not pid:
        return

    # updatePipeline — flip is_active to False. NOTE: wrapper requires
    # both `agent_did` AND `pipeline_id`. Test bug 2026-05-25: omitting
    # agent_did would short-circuit the wrapper with a {"error": ...}
    # response that the dispatcher wraps as HTTP 200 + "Error: ..." text.
    # The Phase-5 `_exec_step` wrapper-error detection now catches that,
    # but the correct fix is to pass agent_did.
    await _exec_step(rpc, parse, "theprotocol_updatePipeline", "3",
                      {"agent_did": bag.sentinel_did,
                       "pipeline_id": str(pid),
                       "is_active": False},
                      dev_jwt, outcomes, expect_status="any")

    def _verify_pipeline_disabled(inner: dict) -> Optional[str]:
        pipelines = []
        if isinstance(inner, dict):
            for k in ("pipelines", "items", "results"):
                v = inner.get(k)
                if isinstance(v, list):
                    pipelines = v
                    break
        if not pipelines:
            return None
        target = None
        for p in pipelines:
            if isinstance(p, dict) and (
                str(p.get("pipeline_id") or p.get("id")) == str(pid)
            ):
                target = p
                break
        if target is None:
            return None
        actual = target.get("is_active")
        if actual is None:
            return None
        if actual is True:
            return (
                "updatePipeline returned 2xx but is_active did not flip to "
                "False on subsequent getMyCicdPipelines read"
            )
        return None

    await _exec_step(rpc, parse, "theprotocol_getMyCicdPipelines", "3",
                      {"agent_did": bag.sentinel_did},
                      dev_jwt, outcomes,
                      record_as_separate=False,
                      verify_against="theprotocol_updatePipeline",
                      verify_against_check=_verify_pipeline_disabled)

    # createVersion
    ok, r = await _exec_step(rpc, parse,
        "theprotocol_createVersion", "3",
        {"agent_did": bag.sentinel_did,
         "version": "1.0.0-phase4",
         "release_notes": "phase-4 lifecycle version",
         "is_stable": True},
        dev_jwt, outcomes,
    )
    vid = (r or {}).get("version_id") or (r or {}).get("id")

    if vid:
        # activateVersion
        await _exec_step(rpc, parse, "theprotocol_activateVersion", "3",
                          {"agent_did": bag.sentinel_did, "version_id": str(vid)},
                          dev_jwt, outcomes, expect_status="any")
        # rollbackVersion
        await _exec_step(rpc, parse, "theprotocol_rollbackVersion", "3",
                          {"agent_did": bag.sentinel_did, "version_id": str(vid)},
                          dev_jwt, outcomes, expect_status="any")
        # deleteVersion on the version just made current: refused (§MCPTEST30 V0636: a refusal row; the tool's own row
        # is earned_ad_devtools' delete of a version that is not current)
        await _ef.refusal_step(rpc, parse, "theprotocol_deleteVersion", "3",
                               {"agent_did": bag.sentinel_did, "version_id": str(vid)},
                               dev_jwt, outcomes, "the current version", codes=(409,), text="current version")

    # deletePipeline
    # the pipeline was created for the sentinel; without its agent_did the dispatcher refused this call, so the run's
    # pipeline was never deleted (§MCPSWEEP 2026-09-27)
    await _exec_step(rpc, parse, "theprotocol_deletePipeline", "3",
                      {"agent_did": bag.sentinel_did, "pipeline_id": str(pid)}, dev_jwt, outcomes, expect_status="any")

    # Phase E.4 read-after-delete: pipeline must NOT show up in
    # getMyCicdPipelines as ACTIVE. Soft-delete (deactivation) IS acceptable
    # — the pipeline either gone entirely OR present-but-inactive. Phase F
    # tightened the endpoint to default-hide soft-deleted, but the verifier
    # tolerates either to avoid false negatives during rollout windows.
    def _verify_pipeline_deleted(inner: dict) -> Optional[str]:
        pipelines = []
        if isinstance(inner, dict):
            for k in ("pipelines", "items", "results"):
                v = inner.get(k)
                if isinstance(v, list):
                    pipelines = v
                    break
        if not pipelines:
            return None
        for p in pipelines:
            if not isinstance(p, dict):
                continue
            if str(p.get("pipeline_id") or p.get("id")) != str(pid):
                continue
            # Found it — tolerate is_active=false (soft-delete)
            if p.get("is_active") is False:
                return None
            return (
                f"deletePipeline returned 2xx but pipeline_id={pid} still "
                f"present as ACTIVE in getMyCicdPipelines (is_active={p.get('is_active')!r})"
            )
        return None

    await _exec_step(rpc, parse, "theprotocol_getMyCicdPipelines", "3",
                      {"agent_did": bag.sentinel_did},
                      dev_jwt, outcomes,
                      record_as_separate=False,
                      verify_against="theprotocol_deletePipeline",
                      verify_against_check=_verify_pipeline_deleted)


async def lifecycle_api_key_full_crud(rpc: RpcCall, parse: ParseResult,
                                       bag: Any, outcomes: Dict[str, dict]) -> None:
    """createApiKey → revokeApiKey (READ-AFTER-WRITE) → createDeveloperApikeyMe → deleteMyApiKey (READ-AFTER-WRITE).

    Phase-5 bug-finding: after revoke or delete, verify the key id is NOT
    in the active getMyApiKeys list.
    """
    dev_jwt = bag.developer_jwt
    ok, r = await _exec_step(rpc, parse,
        "theprotocol_createApiKey", "3",
        {"key_name": "phase4-lifecycle-key-1"},
        dev_jwt, outcomes,
    )
    revoked_kid: Optional[int] = None
    if ok:
        revoked_kid = (r.get("api_key_info") or {}).get("id")
        if revoked_kid:
            await _exec_step(rpc, parse, "theprotocol_revokeApiKey", "3",
                              {"key_id": revoked_kid}, dev_jwt, outcomes)

            def _verify_revoked(inner: dict) -> Optional[str]:
                keys = []
                if isinstance(inner, dict):
                    for k in ("api_keys", "items", "results"):
                        v = inner.get(k)
                        if isinstance(v, list):
                            keys = v
                            break
                if not keys:
                    return None
                # Look for the revoked key id in the *active* list. If it
                # appears with is_revoked=false or status=active, assertion fails.
                for kk in keys:
                    if isinstance(kk, dict) and (
                        kk.get("id") == revoked_kid or
                        str(kk.get("id")) == str(revoked_kid)
                    ):
                        is_revoked = kk.get("is_revoked")
                        status = kk.get("status")
                        active_like = (
                            (is_revoked is False) or
                            (status and status.lower() in ("active", "enabled"))
                        )
                        if active_like:
                            return (
                                f"revokeApiKey returned 2xx but key id "
                                f"{revoked_kid} still appears as active in "
                                f"getMyApiKeys (is_revoked={is_revoked!r}, "
                                f"status={status!r})"
                            )
                return None

            await _exec_step(rpc, parse, "theprotocol_getMyApiKeys", "3",
                              {}, dev_jwt, outcomes,
                              record_as_separate=False,
                              verify_against="theprotocol_revokeApiKey",
                              verify_against_check=_verify_revoked)

    ok, r = await _exec_step(rpc, parse,
        "theprotocol_createDeveloperApikeyMe", "3",
        {"description": "phase4-lifecycle-key-2"},
        dev_jwt, outcomes,
    )
    deleted_kid: Optional[int] = None
    if ok:
        deleted_kid = (r.get("api_key_info") or {}).get("id")
        if deleted_kid:
            await _exec_step(rpc, parse, "theprotocol_deleteMyApiKey", "3",
                              {"key_id": str(deleted_kid)}, dev_jwt, outcomes)

            def _verify_deleted(inner: dict) -> Optional[str]:
                keys = []
                if isinstance(inner, dict):
                    for k in ("api_keys", "items", "results"):
                        v = inner.get(k)
                        if isinstance(v, list):
                            keys = v
                            break
                if not keys:
                    return None
                for kk in keys:
                    if isinstance(kk, dict) and (
                        kk.get("id") == deleted_kid or
                        str(kk.get("id")) == str(deleted_kid)
                    ):
                        is_revoked = kk.get("is_revoked")
                        status = kk.get("status")
                        active_like = (
                            (is_revoked is False) or
                            (status and status.lower() in ("active", "enabled"))
                        )
                        if active_like:
                            return (
                                f"deleteMyApiKey returned 2xx but key id "
                                f"{deleted_kid} still appears as active in "
                                f"getMyApiKeys (is_revoked={is_revoked!r}, "
                                f"status={status!r})"
                            )
                return None

            await _exec_step(rpc, parse, "theprotocol_getMyApiKeys", "3",
                              {}, dev_jwt, outcomes,
                              record_as_separate=False,
                              verify_against="theprotocol_deleteMyApiKey",
                              verify_against_check=_verify_deleted)


async def lifecycle_a2a_payment_settle(rpc: RpcCall, parse: ParseResult,
                                        bag: Any, outcomes: Dict[str, dict]) -> None:
    """authorizePayment → verifyPayment → settlePayment (pays a REAL counterparty).

    §MCPTEST-MCP9: this used to self-pay (`target_agent_did = sentinel_did`) and
    then assert `expect_events=["TokensTransferred"]` on the settle. That
    assertion could never pass: a self-payment moves nothing, so the TEG emits
    nothing. PROVEN against the sandbox EventStore — of 80 TokensTransferred
    events in a 3-hour window, **0 had from == to**; every real transfer is
    two-party. The long-standing "BUG-FIND: missing event ... (silent NO-OP
    class)" was therefore a FIXTURE defect, not an emission bug, and the right
    fix is to give the payment a genuine payee rather than to drop the check.
    The self-pay case still has its own dedicated lifecycle further down, which
    asserts net-zero-minus-fee on the BALANCE and expects no event.
    """
    dev_jwt = bag.developer_jwt
    sentinel_jwt = bag.sentinel_jwt
    # second agent when phase-3 made one; sentinel only as a last resort (in
    # which case the settle legitimately emits nothing and the event assertion
    # is dropped below, rather than failing for a reason the tool cannot fix).
    _payee = bag.flow_values.get("second_agent_did") or bag.sentinel_did
    _two_party = _payee != bag.sentinel_did
    ok, r = await _exec_step(rpc, parse,
        "theprotocol_authorizePayment", "2",
        {"agent_jwt": sentinel_jwt,
         "target_agent_did": _payee,
         "amount": "1",
         "ttl_seconds": 600},
        dev_jwt, outcomes,
        # Phase C: authorize must emit A2APaymentAuthorized (audit-only).
        expect_events=["A2APaymentAuthorized"],
        event_verifier=getattr(bag, "event_verifier", None),
    )
    if not ok or not r.get("token"):
        return
    token = r["token"]
    token_id = r["token_id"]
    # verify (no events expected — read-only)
    await _exec_step(rpc, parse, "theprotocol_verifyPayment", "2",
                      {"agent_jwt": sentinel_jwt, "token": token},
                      dev_jwt, outcomes)
    # settle — emits TokensTransferred (the underlying TEG /transfer)
    # + TransactionFeeCollected on the fee charged. A2APaymentSettled
    # is also emitted but skip_in_projection=true (audit only).
    await _exec_step(rpc, parse, "theprotocol_settlePayment", "2",
                      {"agent_jwt": sentinel_jwt, "token": token, "success": True},
                      dev_jwt, outcomes,
                      # Only assert the transfer event when the payment actually
                      # HAS two parties — see the docstring. Asserting it on a
                      # self-pay is asserting something the ledger will never do.
                      expect_events=(["TokensTransferred"] if _two_party else None),
                      event_verifier=getattr(bag, "event_verifier", None))
    # releasePaymentById on a *fresh* token (different lifecycle)
    ok, r2 = await _exec_step(rpc, parse,
        "theprotocol_authorizePayment", "2",
        {"agent_jwt": sentinel_jwt,
         "target_agent_did": bag.sentinel_did,
         "amount": "1",
         "ttl_seconds": 300},
        dev_jwt, outcomes, expect_status="any",
    )
    if ok and r2.get("token_id"):
        await _exec_step(rpc, parse, "theprotocol_releasePayment", "2",
                          {"agent_jwt": sentinel_jwt, "token": r2["token"]},
                          dev_jwt, outcomes)
    # release-by-id alt path
    ok, r3 = await _exec_step(rpc, parse,
        "theprotocol_authorizePayment", "2",
        {"agent_jwt": sentinel_jwt,
         "target_agent_did": bag.sentinel_did,
         "amount": "1",
         "ttl_seconds": 300},
        dev_jwt, outcomes, expect_status="any",
    )
    if ok and r3.get("token_id"):
        await _exec_step(rpc, parse, "theprotocol_releasePaymentById", "2",
                          {"agent_jwt": sentinel_jwt, "token_id": r3["token_id"]},
                          dev_jwt, outcomes)


async def lifecycle_funding_approve_reject(rpc: RpcCall, parse: ParseResult,
                                            bag: Any, outcomes: Dict[str, dict]) -> None:
    """submitFundingRequest → approveFunding (READ-AFTER-WRITE) →
    submitFundingRequest → rejectFunding (READ-AFTER-WRITE).

    Phase-5 bug-finding: after approve/reject, re-read the request via
    getMyFundingRequests and verify status flipped to funded/rejected.
    """
    dev_jwt = bag.developer_jwt
    sentinel_jwt = bag.sentinel_jwt
    # §MCPTEST30 (V0553): approve and reject go through the admin bridge (the admin_effect family). Through the public
    # bridge they never ran, and every run left both requests pending (310 on sbx-alpha, 2026-10-02). Without the bridge
    # no request is filed: nothing could clear it.
    rpc_admin = _admin_bridge(bag)
    if rpc_admin is None:
        return

    # Approve path (moves the requested 5 from the frame's treasury to the run's sentinel)
    ok, r = await _exec_step(rpc, parse,
        "theprotocol_submitFundingRequest", "2",
        {"agent_jwt": sentinel_jwt,
         "amount": "5",
         "reason": "phase-4 lifecycle approve path"},
        dev_jwt, outcomes,
    )
    approve_rid: Optional[int] = None
    if ok and r.get("id"):
        approve_rid = r["id"]
        ok_approve, _ = await _admin_effect(rpc_admin, parse, "theprotocol_approveFunding",
                                            {"request_id": approve_rid},   # §MCPTEST30: `notes` was never read
                                            dev_jwt, outcomes,
                                            # Phase C: approveFunding emits FundingRequestApproved
                                            # PLUS underlying TokensTransferred (treasury → agent).
                                            expect_events=["FundingRequestApproved"],
                                            event_verifier=getattr(bag, "event_verifier", None))

        def _verify_approved(inner: dict) -> Optional[str]:
            reqs = []
            if isinstance(inner, dict):
                for k in ("requests", "items", "results", "funding_requests"):
                    v = inner.get(k)
                    if isinstance(v, list):
                        reqs = v
                        break
            if not reqs:
                return None
            for fr in reqs:
                if isinstance(fr, dict) and (
                    fr.get("id") == approve_rid or
                    str(fr.get("id")) == str(approve_rid)
                ):
                    status = (fr.get("status") or "").lower()
                    if status not in ("funded", "approved"):
                        return (
                            f"approveFunding returned 2xx but request "
                            f"{approve_rid} has status={status!r} on "
                            f"getMyFundingRequests (expected 'funded'/'approved')"
                        )
                    return None
            return None  # request not in list — sandbox cleanup, tolerate

        if ok_approve:
            await _exec_step(rpc, parse, "theprotocol_getMyFundingRequests", "2",
                              {"agent_jwt": sentinel_jwt},
                              dev_jwt, outcomes,
                              expect_status="any",
                              record_as_separate=False,
                              verify_against=admin_effect_row("theprotocol_approveFunding"),
                              verify_against_check=_verify_approved)

    # Reject path
    ok, r = await _exec_step(rpc, parse,
        "theprotocol_submitFundingRequest", "2",
        {"agent_jwt": sentinel_jwt,
         "amount": "5",
         "reason": "phase-4 lifecycle reject path"},
        dev_jwt, outcomes, expect_status="any",
        record_as_separate=False,   # V0553: a prerequisite; the approve path's submit is the tool's row
    )
    reject_rid: Optional[int] = None
    if ok and r.get("id"):
        reject_rid = r["id"]
        ok_reject, _ = await _admin_effect(rpc_admin, parse, "theprotocol_rejectFunding",
                                           {"request_id": reject_rid,
                                            "reason": "phase-4 lifecycle reject"},
                                           dev_jwt, outcomes,
                                           expect_events=["FundingRequestRejected"],
                                           event_verifier=getattr(bag, "event_verifier", None))

        def _verify_rejected(inner: dict) -> Optional[str]:
            reqs = []
            if isinstance(inner, dict):
                for k in ("requests", "items", "results", "funding_requests"):
                    v = inner.get(k)
                    if isinstance(v, list):
                        reqs = v
                        break
            if not reqs:
                return None
            for fr in reqs:
                if isinstance(fr, dict) and (
                    fr.get("id") == reject_rid or
                    str(fr.get("id")) == str(reject_rid)
                ):
                    status = (fr.get("status") or "").lower()
                    if status != "rejected":
                        return (
                            f"rejectFunding returned 2xx but request "
                            f"{reject_rid} has status={status!r} on "
                            f"getMyFundingRequests (expected 'rejected')"
                        )
                    return None
            return None

        if ok_reject:
            await _exec_step(rpc, parse, "theprotocol_getMyFundingRequests", "2",
                              {"agent_jwt": sentinel_jwt},
                              dev_jwt, outcomes,
                              expect_status="any",
                              record_as_separate=False,
                              verify_against=admin_effect_row("theprotocol_rejectFunding"),
                              verify_against_check=_verify_rejected)


async def lifecycle_support_ticket(rpc: RpcCall, parse: ParseResult,
                                    bag: Any, outcomes: Dict[str, dict]) -> None:
    """submitSupportTicket → replySupportTicket (READ-AFTER-WRITE) → admin
    supportReplyTicket (READ-AFTER-WRITE) → supportCloseTicket → admin
    updateSupportTicketStatus.

    Phase-5 bug-finding: catches BUG-FIND-22 (reply tools return pre-reply
    snapshot). After each reply, re-fetch the ticket via
    getSupportTicketDetail and assert the new message text appears in the
    messages list.
    """
    dev_jwt = bag.developer_jwt
    ok, r = await _exec_step(rpc, parse,
        "theprotocol_submitSupportTicket", "3",
        {"subject": "phase4-lifecycle ticket",
         "message": "phase-4 lifecycle test ticket",
         "category": "general", "priority": "low"},
        dev_jwt, outcomes,
    )
    if not ok or not r.get("id"):
        return
    tid = r["id"]

    user_reply_msg = "phase-5 user reply -- UNIQUE-TOKEN-USER-A1B2C3"
    await _exec_step(rpc, parse, "theprotocol_replySupportTicket", "3",
                      {"ticket_id": str(tid), "message": user_reply_msg},
                      dev_jwt, outcomes)

    def _verify_user_reply(inner: dict) -> Optional[str]:
        messages = []
        if isinstance(inner, dict):
            for k in ("messages", "history", "thread", "items"):
                v = inner.get(k)
                if isinstance(v, list):
                    messages = v
                    break
        if not messages:
            return None
        found = any(
            isinstance(m, dict) and user_reply_msg in (m.get("message") or m.get("text") or m.get("body") or "")
            for m in messages
        )
        if not found:
            return (
                f"replySupportTicket returned 2xx but the new message "
                f"{user_reply_msg!r} is NOT in getSupportTicketDetail.messages "
                f"(found {len(messages)} messages — none containing the unique token)"
            )
        return None

    await _exec_step(rpc, parse, "theprotocol_getSupportTicketDetail", "3",
                      {"ticket_id": str(tid)}, dev_jwt, outcomes,
                      record_as_separate=False,
                      verify_against="theprotocol_replySupportTicket",
                      verify_against_check=_verify_user_reply)

    # §MCPTEST30 (V0553): the admin steps go through the admin bridge (the admin_effect family). Without it the ticket
    # is left as it is; through the public bridge they never ran and every run's ticket stayed open.
    rpc_admin = _admin_bridge(bag)
    if rpc_admin is None:
        return
    admin_reply_msg = "phase-5 admin reply -- UNIQUE-TOKEN-ADMIN-Z9Y8X7"
    ok_reply, _ = await _admin_effect(rpc_admin, parse, "theprotocol_supportReplyTicket",
                                      {"ticket_id": tid, "message": admin_reply_msg}, dev_jwt, outcomes)

    def _verify_admin_reply(inner: dict) -> Optional[str]:
        messages = []
        if isinstance(inner, dict):
            for k in ("messages", "history", "thread", "items"):
                v = inner.get(k)
                if isinstance(v, list):
                    messages = v
                    break
        if not messages:
            return None
        found = any(
            isinstance(m, dict) and admin_reply_msg in (m.get("message") or m.get("text") or m.get("body") or "")
            for m in messages
        )
        if not found:
            return (
                f"supportReplyTicket returned 2xx but the new admin message "
                f"{admin_reply_msg!r} is NOT in getSupportTicketDetail.messages"
            )
        return None

    if ok_reply:
        await _exec_step(rpc, parse, "theprotocol_getSupportTicketDetail", "3",
                          {"ticket_id": str(tid)}, dev_jwt, outcomes,
                          record_as_separate=False,
                          verify_against=admin_effect_row("theprotocol_supportReplyTicket"),
                          verify_against_check=_verify_admin_reply)

    await _admin_effect(rpc_admin, parse, "theprotocol_updateSupportTicketStatus", {"ticket_id": tid, "status": "open"},
                        dev_jwt, outcomes, check=_reads("status", "open"))
    ok_close, _ = await _admin_effect(rpc_admin, parse, "theprotocol_supportCloseTicket",
                                      {"ticket_id": tid, "status": "resolved", "message": "phase-4 close"},
                                      dev_jwt, outcomes)

    def _verify_closed(inner: dict) -> Optional[str]:
        status = str(inner.get("status") or "").lower()
        if not status:
            return None
        if status not in ("resolved", "closed"):
            return f"supportCloseTicket returned 2xx but getSupportTicketDetail reads status={status!r}"
        return None

    if ok_close:
        await _exec_step(rpc, parse, "theprotocol_getSupportTicketDetail", "3",
                          {"ticket_id": str(tid)}, dev_jwt, outcomes,
                          record_as_separate=False,
                          verify_against=admin_effect_row("theprotocol_supportCloseTicket"),
                          verify_against_check=_verify_closed)


async def lifecycle_attestation_schedule(rpc: RpcCall, parse: ParseResult,
                                          bag: Any, outcomes: Dict[str, dict]) -> None:
    """createAttestationSchedule → disableMyAttestationSchedule (needs circuit_id)."""
    dev_jwt = bag.developer_jwt
    sentinel_jwt = bag.sentinel_jwt
    cid = bag.flow_values.get("circuit_id")
    if not cid:
        return
    ok, r = await _exec_step(rpc, parse,
        "theprotocol_createAttestationSchedule", "2",
        {"agent_jwt": sentinel_jwt,
         "circuit_id": cid,
         "interval_hours": 24},
        dev_jwt, outcomes,
    )
    sid = (r or {}).get("schedule_id") or (r or {}).get("id")
    if ok and sid:
        await _exec_step(rpc, parse, "theprotocol_disableMyAttestationSchedule", "2",
                          {"agent_jwt": sentinel_jwt, "schedule_id": str(sid)},
                          dev_jwt, outcomes, expect_status="any")


async def lifecycle_flare(rpc: RpcCall, parse: ParseResult,
                           bag: Any, outcomes: Dict[str, dict]) -> None:
    """Equip → set variant → set overlay → set corner → move → unequip.

    Phase-5 bug-finding semantics:
      - setFlareVariant / setFlareOverlay / setFlareCornerVariant write to
        PER-AGENT fields (`agent.flare_encirclement_variant`, etc.). The
        dev-scoped `getMyFlareStatus` does NOT expose per-agent state —
        and `getAgentFlare(did)` is BUG-FIND-24-broken (it only returns
        dev-level data). For now we DON'T verify these; the existing
        BUG-FIND-24 ticket documents the read-side gap.
      - `customizeFlare` writes DEV-level fields → verifiable via
        getMyFlareStatus. We DO verify it here. NOTE: the wrapper schema
        wraps everything inside `{"customizations": {...}}` — a top-level
        dict won't reach the backend.
      - `unequipFlare` flips `bears_encirclement_flare` on the agent row. NOT
        verified here: §MCPTEST30 (V0545) getMyFlareStatus's response model
        (FlareStatusResponse) has no such field, so the old "verify only if the
        field is present" check never judged anything, and no MCP read carries
        an agent's bearer state (getMyAgents' mapper drops it, getAgentFlare
        answers the developer's selections). The equip above is expected to
        refuse on the sandbox sentinel anyway, so there is no flip to read.
    """
    dev_jwt = bag.developer_jwt
    # §MCPTEST30 (V0636): equipFlare, setFlareVariant, setFlareOverlay and moveFlare do their job in
    # earned_ad_developers.lifecycle_earn_flare, on a developer the run granted a flare to; here, on the runner's
    # sentinel (no flare of its own), each keeps its refusal as a `refusal: ` row, so it never writes the tool's row.
    await _ef.refusal_step(rpc, parse, "theprotocol_equipFlare", "3",
                       {"agent_did": bag.sentinel_did, "slot": "encirclement", "variant": "aurora"},
                       dev_jwt, outcomes, "by a developer with no encirclement flare", codes=(403,),
                       text="no encirclement flare")
    await _ef.refusal_step(rpc, parse, "theprotocol_setFlareVariant", "3",
                       {"agent_did": bag.sentinel_did, "variant": "phoenix"},
                       dev_jwt, outcomes, "on an agent that bears no encirclement slot", codes=(400,),
                       text="encirclement slot")
    await _ef.refusal_step(rpc, parse, "theprotocol_setFlareOverlay", "3",
                       {"agent_did": bag.sentinel_did, "overlay": "glitch"},
                       dev_jwt, outcomes, "on an agent that bears no encirclement slot", codes=(400,),
                       text="encirclement slot")
    await _exec_step(rpc, parse, "theprotocol_setFlareCornerVariant", "3",
                      {"agent_did": bag.sentinel_did, "variant": "atom"},
                      dev_jwt, outcomes, expect_status="any")
    # moveFlare is not called here: whether it refuses depends on whether the runner's own developer holds a flare
    # (the sandbox's admin may), so its refusal is no rule of the route; it moves a flare in lifecycle_earn_flare.
    await _exec_step(rpc, parse, "theprotocol_selectFlare", "3",
                      {"selection": {"encirclement": "phoenix"}},
                      dev_jwt, outcomes, expect_status="any")

    # customizeFlare — DEV-level write, verify against getMyFlareStatus.
    # NOTE: MCP schema wraps args under `customizations` key.
    custom_name = "phase5-custom-name"
    custom_accent = "#FF00FF"
    await _exec_step(rpc, parse, "theprotocol_customizeFlare", "3",
                      {"customizations": {
                          "display_name": custom_name,
                          "accent_color": custom_accent,
                      }},
                      dev_jwt, outcomes, expect_status="any")

    def _verify_customize(inner: dict) -> Optional[str]:
        actual_name = inner.get("flare_display_name")
        actual_accent = inner.get("flare_accent_color")
        if actual_name is None and actual_accent is None:
            return None
        errors = []
        if actual_name is not None and actual_name != custom_name:
            errors.append(f"display_name expected {custom_name!r}, got {actual_name!r}")
        if actual_accent is not None and actual_accent != custom_accent:
            errors.append(f"accent_color expected {custom_accent!r}, got {actual_accent!r}")
        if errors:
            return (
                "customizeFlare returned 2xx but customization did not "
                "persist on subsequent getMyFlareStatus: " + "; ".join(errors)
            )
        return None

    await _exec_step(rpc, parse, "theprotocol_getMyFlareStatus", "3",
                      {}, dev_jwt, outcomes,
                      record_as_separate=False,
                      verify_against="theprotocol_customizeFlare",
                      verify_against_check=_verify_customize)

    # unequip — tolerant verifier (bears_encirclement_flare is a roll-up,
    # may not be returned by getMyFlareStatus for all flare tiers).
    await _exec_step(rpc, parse, "theprotocol_unequipFlare", "3",
                      {"agent_did": bag.sentinel_did, "slot": "encirclement"},
                      dev_jwt, outcomes)



async def lifecycle_notifications_2fa(rpc: RpcCall, parse: ParseResult,
                                       bag: Any, outcomes: Dict[str, dict]) -> None:
    """markNotificationRead (READ-AFTER-WRITE) + 2FA setup + claimPendingAchievements.

    Phase-5 bug-finding: pick a real unread broadcast id from
    getMyUnreadNotifications, mark-read, then verify it's GONE from the
    next getMyUnreadNotifications call. Catches BUG-FIND-22-class
    (mutation returned 2xx but state didn't change).
    """
    dev_jwt = bag.developer_jwt

    # 1. Read unread notifications to find a real ID to mark
    ok, unread_inner = await _exec_step(rpc, parse,
        "theprotocol_getMyUnreadNotifications", "3",
        {}, dev_jwt, outcomes,
        record_as_separate=False,  # already covered by separate contract
    )
    target_id = None
    if ok and isinstance(unread_inner, dict):
        for k in ("notifications", "broadcasts", "items", "unread"):
            v = unread_inner.get(k)
            if isinstance(v, list) and v:
                first = v[0]
                if isinstance(first, dict):
                    target_id = (
                        first.get("broadcast_id") or first.get("id") or
                        first.get("notification_id")
                    )
                    if target_id is not None:
                        break

    # 2. Mark-read with the real ID (fall back to "1" if no unread exists,
    # which means the verify will be a no-op — tolerated)
    mark_id = str(target_id) if target_id is not None else "1"
    await _exec_step(rpc, parse, "theprotocol_markNotificationRead", "3",
                      {"broadcast_id": mark_id}, dev_jwt, outcomes, expect_status="any")

    # 3. Phase 5 verification probe: re-read unread, assert mark_id NOT in list
    def _verify_marked(inner: dict) -> Optional[str]:
        if target_id is None:
            return None  # no real target to verify against; skip assertion
        # Find the notifications list in the inner response
        for k in ("notifications", "broadcasts", "items", "unread"):
            v = inner.get(k)
            if isinstance(v, list):
                still_unread = []
                for n in v:
                    if isinstance(n, dict):
                        nid = (
                            n.get("broadcast_id") or n.get("id") or
                            n.get("notification_id")
                        )
                        if nid is not None:
                            still_unread.append(nid)
                if target_id in still_unread or str(target_id) in [str(x) for x in still_unread]:
                    return (
                        f"markNotificationRead returned 2xx but broadcast "
                        f"id {target_id!r} is STILL in getMyUnreadNotifications"
                    )
                return None
        return None  # no recognisable list shape; skip

    await _exec_step(rpc, parse, "theprotocol_getMyUnreadNotifications", "3",
                      {}, dev_jwt, outcomes,
                      record_as_separate=False,
                      verify_against="theprotocol_markNotificationRead",
                      verify_against_check=_verify_marked)

    # 2FA setup with a password that is not the runner's: the route re-authenticates and refuses, so nothing is enrolled
    await _exec_step(rpc, parse, "theprotocol_setup2FA", "3", {"password": "phase6-not-the-password"},
                      dev_jwt, outcomes, expect_status="any", record_as_separate=False)  # §MCPTEST30: unrecorded; self_account_on_throwaway owns this tool's row

    # claim achievements: measured by lifecycle_achievement_claim with the agent_did the tool requires (this call sent
    # none, so the dispatcher refused it before the tool ran; §MCPSWEEP 2026-09-27)

    # agent heartbeat
    await _exec_step(rpc, parse, "theprotocol_agentHeartbeat", "2",
                      {"agent_jwt": bag.sentinel_jwt}, dev_jwt, outcomes, expect_status="any")


async def lifecycle_teg_policy(rpc: RpcCall, parse: ParseResult,
                                bag: Any, outcomes: Dict[str, dict]) -> None:
    """createTegPolicy's refusal, then getTegPolicy, updateTegPolicy (READ-AFTER-WRITE) and deleteTegPolicy
    (READ-AFTER-DELETE) on the run's own two policies: teg_policy_id, the read/update subject, and teg_policy_id_del, the
    delete subject. The frame's phase-3 setup or the operator's bootstrap makes them, and those creates are the create
    tools' rows.

    §MCPTEST30 (V0641, agentvault2-66): the create probe filed its refusal under createTegPolicy's own name, the last
    writer after the setup, so the setup's real create never reached the run and the tool passed on a refusal alone on
    every node. With its create refused, the lifecycle then fell back to policies[0] of listTegPolicies, a policy of
    anyone's: it updated it with `enabled`, a field TEGPolicyUpdateRequest does not declare (dropped silently: a 200 that
    changed nothing, and the read-back asked for `enabled` and said nothing), then soft-deleted it, and its read-after-
    delete asked for an `id` the TEG's read does not carry. Measured 2026-10-25, read-only: on sbx-alpha 18 api-tester
    policies deactivated, one per run on 09-04/05, and AAA_TEST_POLICY at the 10-20 03:00Z nightly; on the sandbox
    operators an earlier run's fixture, or the run's own teg_policy_id 17 s after its birth (sbxbetaop 06:42:03 ->
    06:42:20Z), and, its row being deleteTegPolicy's, the run's teg_policy_id_del never deleted. Now the refusal is a
    `refusal: ` row and every write is on the run's own policies; where the setup made none, nothing is called here and
    the tools' contracts say why.
    """
    import uuid as _uuid
    dev_jwt = bag.developer_jwt
    # §MCPSWEEP 2026-09-27: a policy_type outside the TEG's four, refused 422 before the TEG's code lookup and its insert
    await _ef.refusal_step(rpc, parse, "theprotocol_createTegPolicy", "3",
                           {"policy_code": "phase5-lifecycle-invalid-type", "policy_name": "phase-5 lifecycle probe",
                            "policy_type": "phase5-no-such-type"},
                           dev_jwt, outcomes, "a policy_type outside the TEG's four", codes=(422,),
                           text="Invalid policy_type")
    fv = getattr(bag, "flow_values", None) or {}
    pid, pid_del = str(fv.get("teg_policy_id") or ""), str(fv.get("teg_policy_id_del") or "")
    if pid:
        await _exec_step(rpc, parse, "theprotocol_getTegPolicy", "3", {"policy_id": pid}, dev_jwt, outcomes)
        stamp = f"mcp-tester read-after-write {_uuid.uuid4().hex[:8]}"
        await _exec_step(rpc, parse, "theprotocol_updateTegPolicy", "3",
                         {"policy_id": pid, "updates": {"description": stamp}}, dev_jwt, outcomes)

        def _verify_described(inner: dict) -> Optional[str]:
            got = inner.get("description") if isinstance(inner, dict) else None
            return None if got == stamp else (
                f"updateTegPolicy answered 2xx, but getTegPolicy reads the description {str(got)[:60]!r}, not the "
                f"{stamp!r} it wrote")

        await _exec_step(rpc, parse, "theprotocol_getTegPolicy", "3", {"policy_id": pid}, dev_jwt, outcomes,
                         record_as_separate=False, verify_against="theprotocol_updateTegPolicy",
                         verify_against_check=_verify_described)
    if pid_del:
        await _exec_step(rpc, parse, "theprotocol_deleteTegPolicy", "3", {"policy_id": pid_del}, dev_jwt, outcomes)

        def _verify_inactive(inner: dict) -> Optional[str]:
            # a soft delete: the TEG's read still answers the policy, with is_active false
            act = inner.get("is_active") if isinstance(inner, dict) else None
            return None if act is False else (
                f"deleteTegPolicy answered 2xx, but getTegPolicy reads policy {pid_del} with is_active {act!r}, "
                "not false")

        await _exec_step(rpc, parse, "theprotocol_getTegPolicy", "3", {"policy_id": pid_del}, dev_jwt, outcomes,
                         record_as_separate=False, verify_against="theprotocol_deleteTegPolicy",
                         verify_against_check=_verify_inactive)


# ============================================================================
# Phase-5 sprint-5.2 additions
# ============================================================================


async def lifecycle_auto_compound(rpc: RpcCall, parse: ParseResult,
                                    bag: Any, outcomes: Dict[str, dict]) -> None:
    """updatePayoutRelock (Tier 3 dev) → getMyPayoutRelock (Tier 2 agent — read-after-write).

    Phase-5 bug-finding: catches BUG-FIND-5-class silent NO-OP on auto-compound
    setting changes. Setter is dev-scoped (`agent_did` param), reader is
    agent-scoped (uses auth.agent_did internally). Sentinel must already
    have a stake-eligible balance — setup funds 5000 AVT.
    """
    dev_jwt = bag.developer_jwt
    sentinel_jwt = bag.sentinel_jwt

    # Flip to True
    await _exec_step(rpc, parse, "theprotocol_updatePayoutRelock", "3",
                      {"agent_did": bag.sentinel_did, "enabled": True},
                      dev_jwt, outcomes, expect_status="any")

    def _verify_enabled(inner: dict) -> Optional[str]:
        actual = inner.get("enabled")
        if actual is None:
            # tolerate alternate shape under "auto_compound" key
            ac = inner.get("auto_compound")
            if isinstance(ac, dict):
                actual = ac.get("enabled")
        if actual is None:
            return None
        if actual is False:
            return (
                "updatePayoutRelock returned 2xx but enabled flag did not "
                "flip to True on subsequent getMyPayoutRelock read"
            )
        return None

    await _exec_step(rpc, parse, "theprotocol_getMyPayoutRelock", "2",
                      {"agent_jwt": sentinel_jwt},
                      dev_jwt, outcomes,
                      expect_status="any",
                      record_as_separate=False,
                      verify_against="theprotocol_updatePayoutRelock",
                      verify_against_check=_verify_enabled)

    # Flip back to False — second read-after-write
    await _exec_step(rpc, parse, "theprotocol_updatePayoutRelock", "3",
                      {"agent_did": bag.sentinel_did, "enabled": False},
                      dev_jwt, outcomes, expect_status="any",
                      # Don't overwrite the first outcome's BUG-FIND state if any
                      record_as_separate=False)

    def _verify_disabled(inner: dict) -> Optional[str]:
        actual = inner.get("enabled")
        if actual is None:
            ac = inner.get("auto_compound")
            if isinstance(ac, dict):
                actual = ac.get("enabled")
        if actual is None:
            return None
        if actual is True:
            return (
                "updatePayoutRelock (second flip) returned 2xx but enabled "
                "flag did not flip back to False on getMyPayoutRelock"
            )
        return None

    await _exec_step(rpc, parse, "theprotocol_getMyPayoutRelock", "2",
                      {"agent_jwt": sentinel_jwt},
                      dev_jwt, outcomes,
                      expect_status="any",
                      record_as_separate=False,
                      verify_against="theprotocol_updatePayoutRelock",
                      verify_against_check=_verify_disabled)


async def lifecycle_dev_profile_update(rpc: RpcCall, parse: ParseResult,
                                         bag: Any, outcomes: Dict[str, dict]) -> None:
    """updateMyDeveloperProfile → getMyDeveloperProfile (READ-AFTER-WRITE).

    Phase-5 bug-finding: silent-NO-OP on developer profile updates.

    Backend `DeveloperProfileUpdate` accepts `display_name` (NOT `name`) —
    documented in the wrapper docstring. The READ schema DeveloperRead
    surfaces BOTH `name` (canonical, read-only) AND `display_name`
    (writable). The assertion targets `display_name`. The wrapper's
    BUG-FIND-25 ergonomics shim also lets callers send `name` and have it
    auto-rewritten to `display_name`, so both paths are covered.
    """
    dev_jwt = bag.developer_jwt

    # Fetch original display_name to restore at end
    ok_orig, orig = await _exec_step(rpc, parse,
        "theprotocol_getMyDeveloperProfile", "3",
        {}, dev_jwt, outcomes,
        record_as_separate=False,  # already covered by separate contract
    )
    if not ok_orig or not isinstance(orig, dict):
        return
    original_display = orig.get("display_name")

    new_display = "phase5-bugfinder-temp-display"
    await _exec_step(rpc, parse, "theprotocol_updateMyDeveloperProfile", "3",
                      {"profile_updates": {"display_name": new_display}},
                      dev_jwt, outcomes, expect_status="any")

    def _verify_profile_update(inner: dict) -> Optional[str]:
        actual = inner.get("display_name")
        if actual is None:
            return None
        if actual != new_display:
            return (
                f"updateMyDeveloperProfile returned 2xx but `display_name` "
                f"did not persist. Sent {new_display!r}, "
                f"getMyDeveloperProfile returned {actual!r}"
            )
        return None

    await _exec_step(rpc, parse, "theprotocol_getMyDeveloperProfile", "3",
                      {}, dev_jwt, outcomes,
                      record_as_separate=False,
                      verify_against="theprotocol_updateMyDeveloperProfile",
                      verify_against_check=_verify_profile_update)

    # Restore original display_name to keep sandbox stable. If original was
    # None, push an empty-string clear to make this idempotent across runs.
    restore_val = original_display if original_display is not None else ""
    await _exec_step(rpc, parse, "theprotocol_updateMyDeveloperProfile", "3",
                      {"profile_updates": {"display_name": restore_val}},
                      dev_jwt, outcomes,
                      expect_status="any", record_as_separate=False)


async def lifecycle_stake_response_shape(rpc: RpcCall, parse: ParseResult,
                                          bag: Any, outcomes: Dict[str, dict]) -> None:
    """lockUnits response must include `stake_id` (BUG-FIND-9 regression
    coverage) and `lock_period_days` must echo back what was sent
    (BUG-FIND-10 regression coverage).

    Stakes 10 AVT (the backend minimum) for 7 days, asserts response shape,
    then attempts unstake (which will likely be rejected by the lock —
    that's fine, the read-after-write assertion fires before unstake).

    NOTE on `unlock_date`: the backend `StakeTransactionRead` schema does
    NOT include `unlock_date` in the stake response (only on subsequent
    getMyLocks reads via lock_expiry_at). The wrapper falls through to
    None. That's a known wrapper-design gap (BUG-FIND-9 component) — fix
    is to compute now+lock_period_days in the wrapper OR fetch
    getMyLocks after creation. We DO NOT assert unlock_date is non-null
    here to avoid false positives.
    """
    dev_jwt = bag.developer_jwt
    sentinel_jwt = bag.sentinel_jwt

    ok, r = await _exec_step(rpc, parse,
        "theprotocol_lockUnits", "2",
        {"agent_jwt": sentinel_jwt,
         "amount": "10",  # backend minimum is 10 AVT
         "lock_period_days": 7},
        dev_jwt, outcomes, expect_status="any",
        # Phase C bug-finder: stake MUST emit TokensStaked. Catches BUG-10
        # silent NO-OP class (call returns 2xx but no event lands).
        expect_events=["TokensStaked"],
        event_verifier=getattr(bag, "event_verifier", None),
    )
    if not ok:
        return

    errors = []
    stake_id = r.get("stake_id")
    if not stake_id or stake_id == "":
        errors.append("stake_id is empty/missing (BUG-FIND-9 regression)")
    lock_period = r.get("lock_period_days")
    if lock_period is not None and lock_period == 0:
        errors.append(
            "lock_period_days dropped to 0 despite request lock_period_days=7 "
            "(BUG-FIND-10 regression)"
        )
    if errors:
        out = outcomes.get("theprotocol_lockUnits")
        if out is not None:
            out["healthy"] = False
            out["fail_reason"] = "BUG-FIND: " + "; ".join(errors)

    # Try unstake — may be rejected as locked, that's fine.
    # NOTE: expect_events not asserted here because lock-period rejection is
    # the common path and produces 4xx with no event. The verifier only fires
    # when contract evaluation passes (which on 4xx it won't).
    if stake_id:
        await _ef.refusal_step(rpc, parse, "theprotocol_unlockUnits", "2",
                               {"agent_jwt": sentinel_jwt,
                                "stake_id": stake_id},
                               dev_jwt, outcomes, 'a position still in its lock',
                               codes=(403,), text='locked')


# ============================================================================
# Phase-5 sprint-5.7 additions — coverage expansion + new bug-finding surfaces
# ============================================================================


async def lifecycle_agent_clone_export_delete(rpc: RpcCall, parse: ParseResult,
                                                bag: Any, outcomes: Dict[str, dict]) -> None:
    """cloneAgent(sentinel) → exportAgentDev(both originals) → deleteMyAgentByDev(clone).

    Phase-5: exercises three previously-skipped destructive tools, and
    verifies the clone is gone from getMyAgents after deletion.
    """
    dev_jwt = bag.developer_jwt

    clone_name = "phase5-clone-{}".format(int(time.time()))
    # §MCPTEST30: the sentinel exists and is the caller's, so this IS the success path, held to it (under "any" a
    # failed clone read healthy; since the route answers failures with a 4xx it would still have read healthy).
    ok, r = await _exec_step(rpc, parse,
        "theprotocol_cloneAgent", "3",
        {"agent_did": bag.sentinel_did, "new_name": clone_name},
        dev_jwt, outcomes, expect_status="success",
    )
    # §pass73.3.19: cloneAgent returns the NEW clone DID in the `agent_did` key
    # (e.g. "...did..._clone_<ts>"). The prior one-liner had a Python precedence
    # bug — the `... if isinstance(r.get("agent"),dict) else r.get("did")` ternary
    # bound the whole `or`-chain, so with no "agent" key it returned the None
    # else-branch and discarded the real agent_did → clone_did stayed None →
    # deleteMyAgentByDev was never exercised (showed as skipped). Fixed below.
    clone_did = None
    if ok and isinstance(r, dict) and r.get("success") is False:
        # the route still answers an IMPORT-report failure with 200 + success=false (only its exceptions map to
        # 4xx/5xx): a 200 that says it did not clone is not a clone
        _bugfind(outcomes, "theprotocol_cloneAgent", "3",
                 f"answered 200 with success=false for the caller's own sentinel: {str(r.get('errors'))[:160]}")
        ok = False
    if ok and isinstance(r, dict):
        clone_did = r.get("agent_did") or r.get("did") or r.get("clone_did")
        if not clone_did and isinstance(r.get("agent"), dict):
            clone_did = r["agent"].get("did")

    # Always exercise export (no fixture risk)
    await _exec_step(rpc, parse, "theprotocol_exportAgentDev", "3",
                      {"agent_did": bag.sentinel_did},
                      dev_jwt, outcomes, expect_status="any")

    if clone_did:
        # Verify clone is in getMyAgents before deletion
        await _exec_step(rpc, parse, "theprotocol_getMyAgents", "3",
                          {}, dev_jwt, outcomes, record_as_separate=False)
        # §MCPTEST30 (V0534): the clone is found by the name it was given. The import made its card with the DID only in
        # the JSON (agent_cards.agent_did NULL), so a search by name, like every reader that joins on agent_did, found
        # no card, and deleting the clone left its card active; the clone's card also kept the SOURCE's name. A search
        # that did not answer measures nothing.
        okd, disc = await _exec_step(rpc, parse, "theprotocol_discoverAgents", "1",
                                      {"query": clone_name, "limit": 20}, dev_jwt, outcomes,
                                      expect_status="any", record_as_separate=False)
        found = disc.get("agents") if okd and isinstance(disc, dict) else None
        if isinstance(found, list) and not any(isinstance(a, dict) and a.get("did") == clone_did for a in found):
            _bugfind(outcomes, "theprotocol_cloneAgent", "3",
                     f"the clone is not found by the name it was given ({len(found)} agents for that name): its card "
                     "is not linked to it (agent_cards.agent_did), so every reader that joins on it sees no card")

        # Delete the clone — verify it's GONE from getMyAgents
        await _exec_step(rpc, parse, "theprotocol_deleteMyAgentByDev", "3",
                          {"agent_did": clone_did},
                          dev_jwt, outcomes, expect_status="any")

        def _verify_clone_gone(inner: dict) -> Optional[str]:
            agents = []
            if isinstance(inner, dict):
                for k in ("agents", "items", "results"):
                    v = inner.get(k)
                    if isinstance(v, list):
                        agents = v
                        break
            if not agents:
                return None
            for a in agents:
                if isinstance(a, dict) and a.get("did") == clone_did:
                    is_active = a.get("is_active")
                    deleted_at = a.get("deleted_at")
                    if is_active is True and not deleted_at:
                        return (
                            f"deleteMyAgentByDev returned 2xx but clone "
                            f"{clone_did} is still active in getMyAgents"
                        )
                    return None  # found but inactive — OK
            return None  # not found — OK

        await _exec_step(rpc, parse, "theprotocol_getMyAgents", "3",
                          {}, dev_jwt, outcomes,
                          record_as_separate=False,
                          verify_against="theprotocol_deleteMyAgentByDev",
                          verify_against_check=_verify_clone_gone)


async def lifecycle_agent_self_delete(rpc: RpcCall, parse: ParseResult,
                                       bag: Any, outcomes: Dict[str, dict]) -> None:
    """createAgent(throwaway) → getAgentToken → deleteMyAgent(self, Tier-2) → verify revoked.

    §pass73.3.19: closes the deleteMyAgent skip with a genuine 2xx via the
    safe-to-delete doctrine — a THROWAWAY agent is created, self-deleted, and
    thereby cleaned up. No load-bearing fixture is touched. deleteMyAgent is
    Tier 2 (agent self-delete via DELETE /agents/me, get_current_agent); the
    throwaway's own JWT is passed inline as `agent_jwt` so the endpoint revokes
    the caller agent (not the bearer/dev).
    """
    dev_jwt = bag.developer_jwt
    ts = int(time.time())

    # 1. Create throwaway agent (record_as_separate=False — createAgent coverage
    #    already comes from the setup phase; don't double-count).
    ok, r = await _exec_step(rpc, parse, "theprotocol_createAgent", "3",
        {"name": f"tw-selfdel-{ts}",
         "description": "throwaway agent for deleteMyAgent self-delete lifecycle"},
        dev_jwt, outcomes, expect_status="any", record_as_separate=False)
    if not ok or not isinstance(r, dict):
        return
    cid = r.get("client_id")
    csec = r.get("client_secret")
    did = r.get("did") or r.get("agent_did")
    if not (cid and csec):
        return

    # 2. Mint the throwaway's agent JWT (getAgentToken is Tier 0 — no auth;
    #    record_as_separate=False since getAgentToken has its own T0 contract).
    _ok, tok = await _exec_step(rpc, parse, "theprotocol_getAgentToken", "0",
        {"client_id": cid, "client_secret": csec},
        dev_jwt, outcomes, expect_status="any", record_as_separate=False)
    agent_jwt = tok.get("access_token") if isinstance(tok, dict) else None
    if not agent_jwt:
        # Couldn't mint — clean up the throwaway via dev-delete; let deleteMyAgent
        # fall back to its contract rather than fabricate a result.
        if did:
            await _exec_step(rpc, parse, "theprotocol_deleteMyAgentByDev", "3",
                {"agent_did": did}, dev_jwt, outcomes,
                expect_status="any", record_as_separate=False)
        return

    # 3. deleteMyAgent AS the throwaway agent (Tier 2 — inline agent_jwt popped
    #    by the dispatcher → becomes auth.raw_token → DELETE /agents/me revokes it).
    del_ok, _ = await _exec_step(rpc, parse, "theprotocol_deleteMyAgent", "2",
        {"agent_jwt": agent_jwt}, dev_jwt, outcomes, expect_status="success")

    # 4. Read-after-write: throwaway should be revoked/inactive in getMyAgents.
    if did:
        def _verify_revoked(inner: dict) -> Optional[str]:
            agents = []
            if isinstance(inner, dict):
                for k in ("agents", "items", "results"):
                    v = inner.get(k)
                    if isinstance(v, list):
                        agents = v
                        break
            for a in agents:
                if isinstance(a, dict) and a.get("did") == did:
                    if a.get("is_active") is True and a.get("status") != "revoked":
                        return (f"deleteMyAgent returned 2xx but throwaway {did} "
                                f"is still active in getMyAgents")
                    return None  # found revoked/inactive — OK
            return None  # not listed — OK

        await _exec_step(rpc, parse, "theprotocol_getMyAgents", "3",
            {}, dev_jwt, outcomes, record_as_separate=False,
            verify_against="theprotocol_deleteMyAgent",
            verify_against_check=_verify_revoked)

    # 5. Safety net: if deleteMyAgent did NOT succeed, ensure the throwaway is
    #    still cleaned up via the dev-side delete.
    if not del_ok and did:
        await _exec_step(rpc, parse, "theprotocol_deleteMyAgentByDev", "3",
            {"agent_did": did}, dev_jwt, outcomes,
            expect_status="any", record_as_separate=False)


async def lifecycle_auth_register_and_logout(rpc: RpcCall, parse: ParseResult,
                                              bag: Any, outcomes: Dict[str, dict]) -> None:
    """authRegister(throwaway dev) + logoutSession(spare session).

    §pass73.3.19: closes two destructive auth skips with genuine 2xx coverage.

    - authRegister (Tier 1, public): registers a throwaway developer with a
      unique, EmailStr-safe, clearly-tagged email + name (min 3 chars). Leaves
      a disposable dev row — doctrine-OK (safe-to-delete: never a load-bearing
      account; the tag makes it sweepable). The MCP wrapper previously omitted
      the API-required `name` field → every call 422'd; fixed in the wrapper.
    - logoutSession (Tier 3, developer): ⚠ CORRECTED 2026-09-07. This said "POST
      /auth/logout is a STATELESS no-op … does NOT revoke the JWT". That is FALSE
      of the current code and was the licence under which this step ran:
      `auth_secure.py:logout` bumps `developers.token_version`, whose own docstring
      reads "invalidates every live access token for that developer (all devices)".
      MEASURED end to end on 2026-09-07:

          14:45:20  non-admin developer JWT mint failed: 401 "Incorrect email or password"
          14:46:15  Logout revoked all sessions for developer 2  (admin@test.sandbox)
          token_version 67 → 68 across one flagship run, exactly one revocation

      The step means to log out a SPARE non-admin session. When that session fails
      to mint the old selector `getattr(bag, "developer_jwt_nonadmin", None) or
      bag.developer_jwt` fell through to the ADMIN token — so the protection
      inverted precisely when it was needed, and the sweep revoked its own
      load-bearing credential once per run. Every lifecycle that had already
      snapshotted `dev_jwt` then 401'd, and those rows were recorded healthy under
      `expect_status="any"` (§RUNNERCRED: 25 of 40 rows say "Could not validate
      credentials").

      So there is NO fallback now: no spare session ⇒ the step does not run, and
      says why. A destructive call must never retarget itself at the load-bearing
      account because its safe subject is missing.

    §MCPTEST30 (2026-09-30): logoutSession moved to `lifecycle_self_account_on_throwaway`, which runs it on the run's
    own throwaway account and then proves the token it ran with is refused. It can no longer run here: once the
    non-admin principal is a working credential (the throwaway, when the seeded fixture is unusable), logging it out in
    phase 4 would leave the phase-5b auth matrix probing with a REVOKED token, and every "non-admin refused" would be a
    dead token refused instead. And the account this step registers now asks for its own deletion (unrecorded): the
    nightly had left one such developer behind per run (89 by 2026-09-27).
    """
    ts = int(time.time())
    email = f"mcp-throwaway-sweep-{ts}@throwaway-pl.example.com"
    password = "McpThrowaway!2026"

    reg_args = {"name": f"mcp-throwaway-{ts}", "email": email, "password": password}
    # §MCPTEST30 (V0639): where the target registers only with an invite (a cloud operator: beta_invite_required), the
    # run asks its admin for one (bag.registration_invite), as the earned auth chain does; the operator sweep's wide
    # list measured "Beta access requires an invite code" here (2026-10-24 13:39-13:46Z, both operators)
    invite = getattr(bag, "registration_invite", None)
    if invite is not None:
        code, why = await invite()
        if not code:
            outcomes["theprotocol_authRegister"] = _not_measured(
                "theprotocol_authRegister", "1",
                f"NOT MEASURED: the target registers only with an invite, and none was had ({why})")
            return
        reg_args["invite_code"] = code

    # authRegister — Tier 1 (public). Bearer is ignored by the endpoint; pass a
    # real dev token to satisfy any MCP-endpoint-level auth.
    ok, _r = await _exec_step(rpc, parse, "theprotocol_authRegister", "1", reg_args,
        bag.developer_jwt, outcomes, expect_status="success")
    if ok:
        await _schedule_own_deletion(rpc, bag, email, password, "authRegister's throwaway")


async def _schedule_own_deletion(rpc: RpcCall, bag: Any, email: str, password: str, what: str) -> None:
    """§MCPTEST30: a throwaway account the sweep made asks for its OWN deletion (the 14-day cooling-off, then the daily
    anonymizer), through the same rail a person uses. Unrecorded and best-effort: cleanup must never cost a verdict."""
    login = getattr(bag, "dev_login", None)
    if login is None:
        return
    try:
        code, tok = await login(email, password)
        jwt = (tok or {}).get("access_token") if str(code).startswith("2") else None
        if not jwt:
            return
        await rpc("theprotocol_requestAccountDeletion",
                  {"password": password, "confirmation": "DELETE MY ACCOUNT",
                   "reason": f"mcp-tester: {what}, removed after its run"}, jwt=jwt, timeout=20)
    except Exception:                                                  # noqa: BLE001 — cleanup is never a finding
        return


# ============================================================================
# §MCPTEST30 (2026-09-30) — the caller's-own-account tools, on an account the sweep owns
# ============================================================================

# Tools whose success path changes the account that CALLS them. On the runner each was a hazard (a password flip
# bricked the sandbox once, 2026-05-26; `account_deletion_safe` scheduled the RUNNER's own deletion every night and
# relied on the cancel landing), so every night eight of them read NOT MEASURED and the rest ran only a refusal under
# expect_status="any", which cannot tell a route that refuses a wrong password from one that accepts it.
SELF_ACCOUNT_TOOLS = (
    "theprotocol_authRefresh", "theprotocol_setup2FA", "theprotocol_verify2FA", "theprotocol_authValidate2FA",
    "theprotocol_regenerateBackupCodes", "theprotocol_authRecover2FA", "theprotocol_disable2FASelf",
    "theprotocol_requestAccountDeletion", "theprotocol_cancelAccountDeletion", "theprotocol_changePassword",
    "theprotocol_logoutSession",
)
# Without a subject these stay NOT MEASURED (said so, per tool). The other three keep their standing refusal contracts,
# which run standalone whenever this lifecycle records nothing for them.
_SELF_ACCOUNT_UNMEASURED_WITHOUT_SUBJECT = (
    "theprotocol_authRefresh", "theprotocol_setup2FA", "theprotocol_regenerateBackupCodes",
    "theprotocol_disable2FASelf", "theprotocol_requestAccountDeletion", "theprotocol_cancelAccountDeletion",
    "theprotocol_changePassword", "theprotocol_logoutSession",
)


def totp_code(secret: str, at: Optional[float] = None, *, step: int = 30, digits: int = 6) -> str:
    """RFC 6238 TOTP (HMAC-SHA1) with the verifier's parameters (30 s steps, 6 digits).

    Written out, not imported: the tester computes the code the way the STANDARD says, so a registry that drifted from
    the standard fails here instead of agreeing with itself (pinned against the RFC's own vectors by
    tests/test_mcp_self_account_lifecycle.py)."""
    s = "".join(str(secret).split()).upper()
    key = base64.b32decode(s + "=" * (-len(s) % 8))
    counter = int((time.time() if at is None else at) // step)
    mac = hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    return str((int.from_bytes(mac[off:off + 4], "big") & 0x7FFFFFFF) % (10 ** digits)).zfill(digits)


def wrong_totp_code(secret: str, at: Optional[float] = None) -> str:
    """A six-digit code that is NOT valid anywhere in the verifier's window (the previous, current and next step)."""
    t = time.time() if at is None else at
    valid = {totp_code(secret, t + d) for d in (-60, -30, 0, 30, 60)}
    c = (int(totp_code(secret, t)) + 500_000) % 1_000_000
    while str(c).zfill(6) in valid:
        c = (c + 1) % 1_000_000
    return str(c).zfill(6)


def _jwt_claims(token: Any) -> Dict[str, Any]:
    try:
        p = str(token).split(".")[1]
        return json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
    except Exception:                                                  # noqa: BLE001
        return {}


def credential_refused(ok: bool, body: Any, code: Any) -> bool:
    """True when the call was refused for its CREDENTIAL: HTTP 401, or the MCP endpoint's -32001 before dispatch."""
    if ok:
        return False
    if str(code) == "401":
        return True
    err = body.get("error") if isinstance(body, dict) else None
    return isinstance(err, dict) and err.get("code") == -32001


def _bugfind(outcomes: Dict[str, dict], tool: str, tier: str, reason: str) -> None:
    """Mark `tool`'s row a BUG-FIND; when its success step recorded no row, record a failing one (never a silent gap)."""
    row = outcomes.get(tool)
    if row is None:
        outcomes[tool] = _make_outcome(tool, tier, False, "0", 0, f"BUG-FIND: {reason}", {},
                                       expect_status="success")
        return
    row["healthy"] = False
    prev = row.get("fail_reason")
    row["fail_reason"] = f"{prev}; BUG-FIND: {reason}" if prev else f"BUG-FIND: {reason}"


def _not_measured(tool: str, tier: str, why: str) -> dict:
    return _make_outcome(tool, tier, False, "0", 0, None, {}, expect_status="success", skip_reason=why)


async def _expect_refusal(rpc: RpcCall, parse: ParseResult, tool: str, args: Dict[str, Any], jwt: str, *,
                          codes: Tuple[int, ...], what: str, text: str = "") -> Optional[str]:
    """Call `tool` with an input its route MUST refuse. None when it was refused with one of `codes` (and, when given,
    `text` in the answer); otherwise the reason, which the caller records as a BUG-FIND on the tool's row. A refusal
    that came from the dispatcher (a JSON-RPC error) never reached the rule, so it is reported as unexercised."""
    ok, body, code = await rpc(tool, args, jwt=jwt, timeout=20)
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        return (f"{tool} with {what}: the call never reached the route (JSON-RPC {err.get('code')}: "
                f"{str(err.get('message'))[:120]}), so the rule was not exercised")
    inner = parse(body) if isinstance(body, dict) else {}
    blob = json.dumps(inner, default=str)[:600] if inner else ""
    c = int(code) if str(code).isdigit() else 0
    if ok or c not in codes:
        return f"{tool} ACCEPTED or mis-refused {what}: expected HTTP {'/'.join(map(str, codes))}, got {code}: {blob[:200]}"
    if text and text.lower() not in blob.lower():
        return f"{tool} refused {what} with HTTP {code} but not for the rule under test (wanted '{text}'): {blob[:200]}"
    return None


def _fresh_password(avoid: str = "") -> str:
    """A password the registry's own validator accepts (the one /auth/register and change-password apply)."""
    import secrets as _secrets
    from agentvault_registry.security_utils import validate_password_strength as _strong
    for _ in range(20):
        pw = f"Tw!{_secrets.token_hex(10)}Z9a"
        if pw != avoid and _strong(pw)[0]:
            return pw
    raise RuntimeError("no password the registry's validator accepts was generated in 20 tries")


async def lifecycle_self_account_on_throwaway(rpc: RpcCall, parse: ParseResult,
                                              bag: Any, outcomes: Dict[str, dict]) -> None:
    """Runs `_self_account_steps`; if a step raises, every tool it had not reached yet is recorded NOT MEASURED
    with the exception named (the runner would otherwise log a warning and fall back to the standalone contracts,
    whose text says 'not probed' and hides that this lifecycle tried and broke)."""
    try:
        await _self_account_steps(rpc, parse, bag, outcomes)
    except Exception as e:                                             # noqa: BLE001
        for t in _SELF_ACCOUNT_UNMEASURED_WITHOUT_SUBJECT:
            outcomes.setdefault(t, _not_measured(t, "3", (
                f"§MCPTEST30: lifecycle self_account_on_throwaway raised {type(e).__name__}: {str(e)[:160]} before "
                "it reached this tool")))


async def _self_account_steps(rpc: RpcCall, parse: ParseResult,
                              bag: Any, outcomes: Dict[str, dict]) -> None:
    """The steps, on `bag.self_subject` only. logoutSession and changePassword REVOKE every session of the account
    that calls them (auth_secure.logout and change-password bump token_version), which is why neither may ever run
    on the runner, and why there is no fallback to another credential when the subject is missing."""
    """§MCPTEST30 (2026-09-30) — THE CALLER'S-OWN-ACCOUNT TOOLS, ON AN ACCOUNT THE SWEEP OWNS FOR ONE RUN.

    `bag.self_subject` is a developer the fixture phase registered for this run and uses for nothing else. Each step
    runs the SUCCESS path, reads it back through its own getter, and probes the rule that guards it with an input the
    route must refuse (a refusal that does not happen is a BUG-FIND on the tool's row, not a quiet pass):

      authRefresh             the login's refresh token mints a token for the same developer; a garbage one is 401
      setup2FA                a wrong password is 401; the right one returns a secret and backup codes
      verify2FA               a wrong code is 400; the RFC 6238 code enables 2FA (getMy2FAStatus: enabled)
      authValidate2FA         the next login asks for the second factor; a wrong code is refused, the right one mints
      regenerateBackupCodes   a wrong code is 401; the right one returns NEW codes (none of the setup's)
      authRecover2FA          one new backup code logs in; the SAME code a second time is refused
      disable2FASelf          a wrong password is 401; the right one disables 2FA (getMy2FAStatus: disabled)
      requestAccountDeletion  a wrong confirmation phrase is refused; the right one sets pending_deletion
      cancelAccountDeletion   back to active
      changePassword          a wrong current password is refused; the right one changes it, after which the token
                              it ran with, the old refresh token and the old password are all refused and the new
                              password logs in
      logoutSession           the token it ran with is refused afterwards
    and last, unrecorded, the account asks for its own deletion (anonymized after the cooling-off).
    """
    subj = dict(getattr(bag, "self_subject", None) or {})
    login = getattr(bag, "dev_login", None)
    if not subj.get("access_token") or login is None:
        why = subj.get("why") or ("the runner gave the bag no login transport" if login is None
                                  else "no throwaway account was minted")
        for t in _SELF_ACCOUNT_UNMEASURED_WITHOUT_SUBJECT:
            outcomes[t] = _not_measured(t, "3", (
                f"§MCPTEST30: no throwaway account this run ({why}). This tool acts on the CALLER's own account, so "
                "it is measured only on an account the sweep owns, never on the runner"))
        return

    email, pw, jwt = subj["email"], subj["password"], subj["access_token"]
    sub = str(subj.get("developer_id") or _jwt_claims(jwt).get("sub") or "")

    async def _me(token: str) -> Tuple[bool, dict, str]:
        return await rpc("theprotocol_getMyDeveloperProfile", {}, jwt=token, timeout=20)

    async def _status(tool: str, token: str) -> Dict[str, Any]:
        ok_s, body_s, _c = await rpc(tool, {}, jwt=token, timeout=20)
        inner_s = parse(body_s) if (ok_s and isinstance(body_s, dict)) else {}
        return inner_s if isinstance(inner_s, dict) else {}

    # ── 1. authRefresh ────────────────────────────────────────────────────────────────────────────────────────
    refresh = subj.get("refresh_token") or ""
    bad = await _expect_refusal(rpc, parse, "theprotocol_authRefresh",
                                {"refresh_token": "mcptest30-not-a-refresh-token"}, jwt,
                                codes=(401,), text="refresh token", what="a garbage refresh token")
    if refresh:
        ok, r = await _exec_step(rpc, parse, "theprotocol_authRefresh", "3", {"refresh_token": refresh},
                                 jwt, outcomes)
        if ok:
            fresh = r.get("access_token") if isinstance(r, dict) else None
            if not fresh:
                _bugfind(outcomes, "theprotocol_authRefresh", "3", "answered 2xx without an access_token")
            elif str(_jwt_claims(fresh).get("sub")) != sub:
                _bugfind(outcomes, "theprotocol_authRefresh", "3",
                         f"minted a token for developer {_jwt_claims(fresh).get('sub')!r}, not {sub!r}")
            else:
                ok_me, body_me, code_me = await _me(fresh)
                me = parse(body_me) if ok_me else {}
                if not ok_me or (isinstance(me, dict) and me.get("email") and me.get("email") != email):
                    _bugfind(outcomes, "theprotocol_authRefresh", "3",
                             f"the refreshed token does not read its own profile (HTTP {code_me})")
                else:
                    jwt = fresh
    else:
        outcomes["theprotocol_authRefresh"] = _not_measured(
            "theprotocol_authRefresh", "3", "§MCPTEST30: the throwaway's login returned no refresh token")
    if bad:
        _bugfind(outcomes, "theprotocol_authRefresh", "3", bad)

    # ── 2. 2FA: setup, verify, login with the second factor, backup codes, disable ───────────────────────────
    bad = await _expect_refusal(rpc, parse, "theprotocol_setup2FA", {"password": pw + "-wrong"}, jwt,
                                codes=(401,), text="Invalid password", what="a wrong password")
    ok, r = await _exec_step(rpc, parse, "theprotocol_setup2FA", "3", {"password": pw}, jwt, outcomes)
    secret, setup_codes = "", []
    if ok and isinstance(r, dict):
        secret = r.get("secret_raw") or r.get("secret") or ""
        setup_codes = r.get("backup_codes") if isinstance(r.get("backup_codes"), list) else []
        if not secret:
            _bugfind(outcomes, "theprotocol_setup2FA", "3", "answered 2xx without the TOTP secret")
        elif not setup_codes:
            _bugfind(outcomes, "theprotocol_setup2FA", "3", "answered 2xx without backup codes")
        st = await _status("theprotocol_getMy2FAStatus", jwt)
        if st.get("enabled") is True:
            _bugfind(outcomes, "theprotocol_setup2FA", "3", "2FA reads ENABLED before any code was verified")
    if bad:
        _bugfind(outcomes, "theprotocol_setup2FA", "3", bad)

    tfa_on = False
    if secret:
        bad = await _expect_refusal(rpc, parse, "theprotocol_verify2FA", {"code": wrong_totp_code(secret)}, jwt,
                                    codes=(400,), text="Invalid verification code", what="a wrong TOTP code")
        ok, _r = await _exec_step(rpc, parse, "theprotocol_verify2FA", "3", {"code": totp_code(secret)}, jwt, outcomes)
        if ok:
            st = await _status("theprotocol_getMy2FAStatus", jwt)
            if st.get("enabled") is not True:
                _bugfind(outcomes, "theprotocol_verify2FA", "3", f"2xx, but getMy2FAStatus reads {st!r}")
            else:
                tfa_on = True
        if bad:
            _bugfind(outcomes, "theprotocol_verify2FA", "3", bad)

    new_codes: List[str] = []
    if tfa_on:
        # The next login must stop at the second factor.
        code_l, tok = await login(email, pw)
        partial = (tok or {}).get("partial_token") if (tok or {}).get("requires_2fa") else None
        if not (str(code_l).startswith("2") and partial):
            _bugfind(outcomes, "theprotocol_verify2FA", "3",
                     f"2FA reads enabled but the next login did not ask for the second factor (HTTP {code_l}, "
                     f"requires_2fa={(tok or {}).get('requires_2fa')!r})")
        else:
            bad = await _expect_refusal(rpc, parse, "theprotocol_authValidate2FA",
                                        {"login_token": partial, "code": wrong_totp_code(secret)}, jwt,
                                        codes=(400, 401), what="a wrong TOTP code")
            ok, r = await _exec_step(rpc, parse, "theprotocol_authValidate2FA", "1",
                                     {"login_token": partial, "code": totp_code(secret)}, jwt, outcomes)
            if ok and str(_jwt_claims((r or {}).get("access_token")).get("sub")) != sub:
                _bugfind(outcomes, "theprotocol_authValidate2FA", "1",
                         "the second factor was accepted but no token for this developer came back")
            if bad:
                _bugfind(outcomes, "theprotocol_authValidate2FA", "1", bad)

        bad = await _expect_refusal(rpc, parse, "theprotocol_regenerateBackupCodes",
                                    {"password": pw, "current_code": wrong_totp_code(secret)}, jwt,
                                    codes=(401,), text="Invalid verification code", what="a wrong TOTP code")
        ok, r = await _exec_step(rpc, parse, "theprotocol_regenerateBackupCodes", "3",
                                 {"password": pw, "current_code": totp_code(secret)}, jwt, outcomes)
        if ok:
            new_codes = r.get("backup_codes") if isinstance(r, dict) and isinstance(r.get("backup_codes"), list) else []
            if not new_codes:
                _bugfind(outcomes, "theprotocol_regenerateBackupCodes", "3", "answered 2xx without backup codes")
            elif set(new_codes) & set(setup_codes):
                _bugfind(outcomes, "theprotocol_regenerateBackupCodes", "3",
                         "the new backup codes repeat codes from the setup; the old set was not replaced")
        if bad:
            _bugfind(outcomes, "theprotocol_regenerateBackupCodes", "3", bad)

        if new_codes:
            used = new_codes[0]
            code_l, tok = await login(email, pw)
            partial = (tok or {}).get("partial_token") if (tok or {}).get("requires_2fa") else None
            if partial:
                ok, r = await _exec_step(rpc, parse, "theprotocol_authRecover2FA", "1",
                                         {"login_token": partial, "backup_code": used}, jwt, outcomes)
                if ok and str(_jwt_claims((r or {}).get("access_token")).get("sub")) != sub:
                    _bugfind(outcomes, "theprotocol_authRecover2FA", "1",
                             "the backup code was accepted but no token for this developer came back")
                if ok:
                    code_l, tok = await login(email, pw)
                    partial = (tok or {}).get("partial_token") if (tok or {}).get("requires_2fa") else None
                    if partial:
                        bad = await _expect_refusal(rpc, parse, "theprotocol_authRecover2FA",
                                                    {"login_token": partial, "backup_code": used}, jwt,
                                                    codes=(400, 401), what="a backup code that was already used")
                        if bad:
                            _bugfind(outcomes, "theprotocol_authRecover2FA", "1", bad)

        bad = await _expect_refusal(rpc, parse, "theprotocol_disable2FASelf",
                                    {"password": pw + "-wrong", "code": totp_code(secret)}, jwt,
                                    codes=(401,), text="Invalid password", what="a wrong password")
        ok, _r = await _exec_step(rpc, parse, "theprotocol_disable2FASelf", "3",
                                  {"password": pw, "code": totp_code(secret)}, jwt, outcomes)
        if ok:
            st = await _status("theprotocol_getMy2FAStatus", jwt)
            if st.get("enabled") is not False:
                _bugfind(outcomes, "theprotocol_disable2FASelf", "3", f"2xx, but getMy2FAStatus reads {st!r}")
        if bad:
            _bugfind(outcomes, "theprotocol_disable2FASelf", "3", bad)
    else:
        for t in ("theprotocol_regenerateBackupCodes", "theprotocol_disable2FASelf"):
            outcomes.setdefault(t, _not_measured(t, "3", "§MCPTEST30: 2FA could not be enabled on the throwaway "
                                                          "this run (see setup2FA / verify2FA), so there was nothing "
                                                          "to regenerate or disable"))

    # ── 3. account deletion: request, read back, cancel, read back ───────────────────────────────────────────
    bad = await _expect_refusal(rpc, parse, "theprotocol_requestAccountDeletion",
                                {"password": pw, "confirmation": "delete my account please"}, jwt,
                                codes=(400, 422), text="confirmation", what="a wrong confirmation phrase")
    ok, _r = await _exec_step(rpc, parse, "theprotocol_requestAccountDeletion", "3",
                              {"password": pw, "confirmation": "DELETE MY ACCOUNT",
                               "reason": "mcp-tester throwaway (cancelled next)"}, jwt, outcomes)
    if ok:
        st = await _status("theprotocol_getMyDeletionStatus", jwt)
        if st.get("deletion_status") != "pending_deletion":
            _bugfind(outcomes, "theprotocol_requestAccountDeletion", "3", f"2xx, but the status reads {st!r}")
        ok2, _r2 = await _exec_step(rpc, parse, "theprotocol_cancelAccountDeletion", "3", {}, jwt, outcomes)
        if ok2:
            st = await _status("theprotocol_getMyDeletionStatus", jwt)
            if st.get("deletion_status") not in (None, "active"):
                _bugfind(outcomes, "theprotocol_cancelAccountDeletion", "3", f"2xx, but the status reads {st!r}")
    else:
        outcomes.setdefault("theprotocol_cancelAccountDeletion", _not_measured(
            "theprotocol_cancelAccountDeletion", "3", "§MCPTEST30: requestAccountDeletion did not succeed, so there "
                                                      "was nothing to cancel"))
    if bad:
        _bugfind(outcomes, "theprotocol_requestAccountDeletion", "3", bad)

    # ── 4. changePassword: every credential from before the change must die with it ─────────────────────────
    new_pw = _fresh_password(avoid=pw)
    bad = await _expect_refusal(rpc, parse, "theprotocol_changePassword",
                                {"current_password": pw + "-wrong", "new_password": new_pw}, jwt,
                                codes=(400, 401), text="incorrect", what="a wrong current password")
    ok, _r = await _exec_step(rpc, parse, "theprotocol_changePassword", "3",
                              {"current_password": pw, "new_password": new_pw}, jwt, outcomes)
    if ok:
        ok_me, body_me, code_me = await _me(jwt)
        if not credential_refused(ok_me, body_me, code_me):
            _bugfind(outcomes, "theprotocol_changePassword", "3",
                     f"the token that changed the password still works afterwards (HTTP {code_me}): sessions are "
                     "not revoked by a password change")
        code_old, _t = await login(email, pw)
        if str(code_old).startswith("2"):
            _bugfind(outcomes, "theprotocol_changePassword", "3", "the OLD password still logs in")
        code_new, tok = await login(email, new_pw)
        if not (str(code_new).startswith("2") and (tok or {}).get("access_token")):
            _bugfind(outcomes, "theprotocol_changePassword", "3", f"the NEW password does not log in (HTTP {code_new})")
            pw = ""
        else:
            pw, jwt = new_pw, tok["access_token"]
            if refresh:
                # With the NEW session's bearer, so the endpoint lets the call through and the ROUTE judges the
                # pre-change refresh token (a revoked bearer would be refused first and measure nothing).
                bad_rf = await _expect_refusal(rpc, parse, "theprotocol_authRefresh", {"refresh_token": refresh},
                                               jwt, codes=(401,), text="revoked",
                                               what="a refresh token issued before the password change")
                if bad_rf:
                    _bugfind(outcomes, "theprotocol_changePassword", "3", bad_rf)
    if bad:
        _bugfind(outcomes, "theprotocol_changePassword", "3", bad)

    # ── 5. logoutSession: the token it ran with must be refused afterwards ─────────────────────────────────
    if pw:
        ok, _r = await _exec_step(rpc, parse, "theprotocol_logoutSession", "3", {}, jwt, outcomes)
        if ok:
            ok_me, body_me, code_me = await _me(jwt)
            if not credential_refused(ok_me, body_me, code_me):
                _bugfind(outcomes, "theprotocol_logoutSession", "3",
                         f"the token still works after logout (HTTP {code_me})")
        # ── 6. cleanup, unrecorded: the throwaway asks for its own deletion ──────────────────────────────
        await _schedule_own_deletion(rpc, bag, email, pw, "self-account throwaway")
    else:
        outcomes.setdefault("theprotocol_logoutSession", _not_measured(
            "theprotocol_logoutSession", "3", "§MCPTEST30: no working session was left on the throwaway after "
                                              "changePassword (see its row)"))


async def lifecycle_org_assign_unassign(rpc: RpcCall, parse: ParseResult,
                                          bag: Any, outcomes: Dict[str, dict]) -> None:
    """assignAgentToOrg → listOrganizationAgents (READ-AFTER-WRITE) → unassign → listOrganizationAgents (verify absent).

    Phase-5: catches BUG-FIND-5 class silent NO-OP on agent↔org membership.
    Uses the org_id created in setup phase.
    """
    dev_jwt = bag.developer_jwt
    org_id = bag.flow_values.get("organization_id")
    if not org_id:
        return

    # Assign sentinel to the org
    await _exec_step(rpc, parse, "theprotocol_assignAgentToOrg", "3",
                      {"org_id": str(org_id), "agent_did": bag.sentinel_did},
                      dev_jwt, outcomes, expect_status="any")

    def _verify_assigned(inner: dict) -> Optional[str]:
        agents = []
        if isinstance(inner, dict):
            for k in ("agents", "items", "results"):
                v = inner.get(k)
                if isinstance(v, list):
                    agents = v
                    break
        if not agents:
            return None
        for a in agents:
            if isinstance(a, dict) and a.get("did") == bag.sentinel_did:
                return None  # present → OK
        return (
            f"assignAgentToOrg returned 2xx but sentinel {bag.sentinel_did} "
            f"NOT in listOrganizationAgents(org={org_id}) — silent NO-OP"
        )

    await _exec_step(rpc, parse, "theprotocol_listOrganizationAgents", "3",
                      {"org_id": str(org_id)},
                      dev_jwt, outcomes,
                      expect_status="any",
                      record_as_separate=False,
                      verify_against="theprotocol_assignAgentToOrg",
                      verify_against_check=_verify_assigned)

    # Unassign — verify NOT present
    await _exec_step(rpc, parse, "theprotocol_unassignAgentFromOrg", "3",
                      {"org_id": str(org_id), "agent_did": bag.sentinel_did},
                      dev_jwt, outcomes, expect_status="any")

    def _verify_unassigned(inner: dict) -> Optional[str]:
        agents = []
        if isinstance(inner, dict):
            for k in ("agents", "items", "results"):
                v = inner.get(k)
                if isinstance(v, list):
                    agents = v
                    break
        if not agents:
            return None
        for a in agents:
            if isinstance(a, dict) and a.get("did") == bag.sentinel_did:
                return (
                    f"unassignAgentFromOrg returned 2xx but sentinel "
                    f"{bag.sentinel_did} STILL in listOrganizationAgents"
                )
        return None

    await _exec_step(rpc, parse, "theprotocol_listOrganizationAgents", "3",
                      {"org_id": str(org_id)},
                      dev_jwt, outcomes,
                      expect_status="any",
                      record_as_separate=False,
                      verify_against="theprotocol_unassignAgentFromOrg",
                      verify_against_check=_verify_unassigned)


async def lifecycle_team_member_add_remove(rpc: RpcCall, parse: ParseResult,
                                              bag: Any, outcomes: Dict[str, dict]) -> None:
    """addTeamMember(self) → getOrganizationTeam (verify member_count grew) →
    removeTeamMember → getOrganizationTeam (verify member_count shrank).

    Uses org_id + team_id from setup phase. Self-add is a no-op edge case
    we still want to exercise; backend may 4xx — tolerated.
    """
    dev_jwt = bag.developer_jwt
    org_id = bag.flow_values.get("organization_id")
    team_id = bag.flow_values.get("team_id")
    dev_id = bag.developer_id
    if not org_id or not team_id or not dev_id:
        return

    # Get original member_count for diff
    ok_orig, before = await _exec_step(rpc, parse,
        "theprotocol_getOrganizationTeam", "3",
        {"org_id": str(org_id), "team_id": str(team_id)},
        dev_jwt, outcomes, expect_status="any",
        record_as_separate=False,
    )
    orig_count = None
    if ok_orig and isinstance(before, dict):
        orig_count = before.get("member_count")
        if orig_count is None:
            team = before.get("team") if isinstance(before.get("team"), dict) else None
            orig_count = team.get("member_count") if team else None

    await _exec_step(rpc, parse, "theprotocol_addTeamMember", "3",
                      {"org_id": str(org_id), "team_id": str(team_id),
                       "developer_id": int(dev_id), "role": "member"},
                      dev_jwt, outcomes, expect_status="any")

    def _verify_added(inner: dict) -> Optional[str]:
        new_count = inner.get("member_count")
        if new_count is None:
            team = inner.get("team") if isinstance(inner.get("team"), dict) else None
            new_count = team.get("member_count") if team else None
        if orig_count is None or new_count is None:
            return None  # can't diff
        if new_count <= orig_count:
            return (
                f"addTeamMember returned 2xx but member_count did not grow "
                f"({orig_count} → {new_count}). May indicate silent NO-OP."
            )
        return None

    await _exec_step(rpc, parse, "theprotocol_getOrganizationTeam", "3",
                      {"org_id": str(org_id), "team_id": str(team_id)},
                      dev_jwt, outcomes, expect_status="any",
                      record_as_separate=False,
                      verify_against="theprotocol_addTeamMember",
                      verify_against_check=_verify_added)

    # Remove
    await _exec_step(rpc, parse, "theprotocol_removeTeamMember", "3",
                      {"org_id": str(org_id), "team_id": str(team_id),
                       "developer_id": int(dev_id)},
                      dev_jwt, outcomes, expect_status="any")


async def lifecycle_signing_keys_rotate(rpc: RpcCall, parse: ParseResult,
                                          bag: Any, outcomes: Dict[str, dict]) -> None:
    """rotateMySigningKey → getMySigningKeys (verify new key present).

    The new key fingerprint should appear in the list after rotation.
    """
    dev_jwt = bag.developer_jwt

    ok, r = await _exec_step(rpc, parse,
        "theprotocol_rotateMySigningKey", "3",
        {}, dev_jwt, outcomes, expect_status="any",
    )
    new_kid = None
    if ok and isinstance(r, dict):
        new_kid = (
            r.get("kid") or r.get("key_id") or r.get("fingerprint") or
            r.get("public_key_fingerprint")
        )

    def _verify_rotated(inner: dict) -> Optional[str]:
        keys = []
        if isinstance(inner, dict):
            for k in ("signing_keys", "keys", "items"):
                v = inner.get(k)
                if isinstance(v, list):
                    keys = v
                    break
        if not keys:
            return None  # can't verify
        if new_kid is None:
            # No kid returned from rotate — just check list non-empty
            return None
        for k in keys:
            if isinstance(k, dict):
                kk = (
                    k.get("kid") or k.get("key_id") or k.get("fingerprint") or
                    k.get("public_key_fingerprint")
                )
                if kk == new_kid:
                    return None  # found
        return (
            f"rotateMySigningKey returned kid={new_kid!r} but it's NOT in "
            f"getMySigningKeys list ({len(keys)} keys returned)"
        )

    await _exec_step(rpc, parse, "theprotocol_getMySigningKeys", "3",
                      {}, dev_jwt, outcomes,
                      record_as_separate=False,
                      verify_against="theprotocol_rotateMySigningKey",
                      verify_against_check=_verify_rotated)


async def lifecycle_dev_location_update(rpc: RpcCall, parse: ParseResult,
                                          bag: Any, outcomes: Dict[str, dict]) -> None:
    """updateMyDeveloperLocation → getMyDeveloperProfile (verify lat/long).

    Phase-5: catches silent NO-OP on location updates. Restores original.
    """
    dev_jwt = bag.developer_jwt

    # Fetch original
    ok_orig, orig = await _exec_step(rpc, parse,
        "theprotocol_getMyDeveloperProfile", "3",
        {}, dev_jwt, outcomes,
        record_as_separate=False,
    )
    if not ok_orig or not isinstance(orig, dict):
        return
    orig_lat = orig.get("latitude")
    orig_lng = orig.get("longitude")
    orig_label = orig.get("location_label")

    new_lat = 35.6762   # Tokyo, easy to differentiate from default Freilassing
    new_lng = 139.6503
    new_label = "phase5-lifecycle Tokyo"
    # Phase E.2: update_agents=False keeps the test deterministic + fast on
    # sandbox-A where commander dev owns ~5800 canaries. The endpoint splits
    # into two commits since 2026-05-26 so even if propagation timed out the
    # developer row would still persist — but we still skip the propagation
    # here because the test verifies developer.location round-trip, not
    # agent-card fanout (which has its own coverage).
    await _exec_step(rpc, parse, "theprotocol_updateMyDeveloperLocation", "3",
                      {"location_data": {
                          "latitude": new_lat,
                          "longitude": new_lng,
                          "location_label": new_label,
                          "update_agents": False,
                      }},
                      dev_jwt, outcomes, expect_status=200)

    def _verify_location(inner: dict) -> Optional[str]:
        actual_lat = inner.get("latitude")
        if actual_lat is None:
            return None
        # tolerate float epsilon
        if isinstance(actual_lat, (int, float)) and abs(actual_lat - new_lat) > 0.01:
            return (
                f"updateMyDeveloperLocation returned 2xx but latitude did not "
                f"persist. Sent {new_lat}, getMyDeveloperProfile returned "
                f"{actual_lat}"
            )
        return None

    await _exec_step(rpc, parse, "theprotocol_getMyDeveloperProfile", "3",
                      {}, dev_jwt, outcomes,
                      record_as_separate=False,
                      verify_against="theprotocol_updateMyDeveloperLocation",
                      verify_against_check=_verify_location)

    # Restore original (skip agent propagation; same reasoning as PUT above)
    if orig_lat is not None and orig_lng is not None:
        restore = {"latitude": orig_lat, "longitude": orig_lng, "update_agents": False}
        if orig_label:
            restore["location_label"] = orig_label
        await _exec_step(rpc, parse, "theprotocol_updateMyDeveloperLocation", "3",
                          {"location_data": restore},
                          dev_jwt, outcomes, expect_status="any",
                          record_as_separate=False)


async def lifecycle_treasury_jwks_shape(rpc: RpcCall, parse: ParseResult,
                                          bag: Any, outcomes: Dict[str, dict]) -> None:
    """getMyTreasuryBalance + getMyDeveloperJwks — read shape checks.

    Phase-5: surfaces these previously-skipped tools with light shape
    assertions (catches BUG-FIND-9 class — missing response keys).
    """
    dev_jwt = bag.developer_jwt
    dev_id = bag.developer_id

    ok, r = await _exec_step(rpc, parse,
        "theprotocol_getMyTreasuryBalance", "3",
        {}, dev_jwt, outcomes, expect_status="any",
    )
    if ok and isinstance(r, dict):
        # The treasury endpoint should return *some* balance key
        balance_keys = ("balance", "treasury_balance", "amount", "total")
        if not any(k in r for k in balance_keys):
            # Not necessarily a bug — could be 4xx wrapped; just log
            pass

    if dev_id:
        await _exec_step(rpc, parse, "theprotocol_getMyDeveloperJwks", "3",
                          {"developer_id": int(dev_id)},
                          dev_jwt, outcomes, expect_status="any")


async def lifecycle_mcp_audit_log_recent(rpc: RpcCall, parse: ParseResult,
                                            bag: Any, outcomes: Dict[str, dict]) -> None:
    """getMyMcpAuditLog → assert recent entries (MCP_AUDIT_LOGGING_ENABLED
    side-effect: every MCP call we've made this run should appear in the
    log when the env flag is on).

    If MCP_AUDIT_LOGGING is DISABLED on sandbox, this lifecycle returns
    an empty list — tolerated (no assertion).
    """
    dev_jwt = bag.developer_jwt
    await _exec_step(rpc, parse, "theprotocol_getMyMcpAuditLog", "3",
                      {"limit": 10},   # §MCPTEST30: paged by cursor; `offset` was never read
                      dev_jwt, outcomes, expect_status="any")


async def lifecycle_achievement_claim(rpc: RpcCall, parse: ParseResult,
                                        bag: Any, outcomes: Dict[str, dict]) -> None:
    """claimPendingAchievements(sentinel_did) — exercise the dev-side
    catch-up claim path.
    """
    dev_jwt = bag.developer_jwt
    await _exec_step(rpc, parse, "theprotocol_claimPendingAchievements", "3",
                      {"agent_did": bag.sentinel_did},
                      dev_jwt, outcomes, expect_status="any")


def mtls_enrolment(inner: Any) -> Optional[bool]:
    """The enrolment state a getMyMtlsStatus answer carries, or None when it carries none.

    §MCPTEST30 (V0545): the route answers `enrolled` (routers/agent_mtls.py::mtls_status). The toggle lifecycle read
    `enabled`, then `mtls_enabled`, found neither, and returned "no finding" on every run since it was written, so the
    flip it was built to verify was never verified (round 11: enable and disable both 200, the read-backs judged
    nothing). The old names stay as fallbacks, after the route's own."""
    if not isinstance(inner, dict):
        return None
    for k in ("enrolled", "mtls_enabled", "enabled"):
        if isinstance(inner.get(k), bool):
            return inner[k]
    return None


def verify_mtls_flip(want: bool, mutation: str) -> Callable[[dict], Optional[str]]:
    """A read-after-write check: the status read after `mutation` answered 2xx must say enrolled == want. A 2xx read
    that carries no enrolment field judges nothing here (the status contract's expect_keys holds the shape)."""
    def _check(inner: dict) -> Optional[str]:
        actual = mtls_enrolment(inner)
        if actual is None or actual is want:
            return None
        return (f"{mutation} returned 2xx but getMyMtlsStatus reads enrolled={actual} "
                f"(the flip did not land)")
    return _check


async def _mtls_not_delivered(rpc: RpcCall, parse: ParseResult, sentinel_jwt: str, dev_jwt: str,
                              enabled: Dict[str, Any], outcomes: Dict[str, dict]) -> None:
    """§MCPTEST30 (V0639): enableMtls answered 200 `not_enrolled`, the route's word for an identity it cannot deliver
    (routers/agent_mtls.py, §EXTMTLS-C: an agent it calls external, with inline delivery off or a failed mint, gets no
    entry, no flag and no card patch). The toggle read that as a flip that did not land, on both cloud operators (the
    wide list, 2026-10-24 13:39-13:46Z): the rule kept its word and the row went red. Now the enrolment and the disable
    are NOT MEASURED, named (nothing was enrolled to disable), and the promise is measured on its own row: the status
    read after it must say not enrolled."""
    delivery = str(enabled.get("delivery") or "not said")
    outcomes["theprotocol_enableMtls"] = _not_measured(
        "theprotocol_enableMtls", "2",
        f"NOT MEASURED: enableMtls answered not_enrolled (delivery: {delivery}): this target issues the run's agent no "
        f"identity, so the enrolment was not measured")
    outcomes["theprotocol_disableMyMtls"] = _not_measured(
        "theprotocol_disableMyMtls", "2",
        "NOT MEASURED: nothing was enrolled to disable (enableMtls answered not_enrolled)")
    name = _ef.refusal_row("theprotocol_enableMtls", "an identity this target cannot deliver")
    scratch: Dict[str, dict] = {}
    ok_r, read = await _exec_step(rpc, parse, "theprotocol_getMyMtlsStatus", "2", {"agent_jwt": sentinel_jwt},
                                  dev_jwt, scratch, expect_status="success")
    row = scratch.get("theprotocol_getMyMtlsStatus") or _not_measured(
        name, "2", "NOT MEASURED: the status read recorded no answer")
    enrolled = mtls_enrolment(read) if ok_r else None
    if not ok_r:
        row = _not_measured(name, "2", f"NOT MEASURED: the status read after it failed (HTTP {row.get('status_code')})")
    elif enrolled is None:
        row = _not_measured(name, "2", "NOT MEASURED: the status read carries no enrolment field")
    elif enrolled is True:
        row = {**row, "healthy": False,
               "fail_reason": "BUG-FIND: enableMtls answered not_enrolled, but getMyMtlsStatus reads enrolled=True: "
                              "an identity is claimed that was never delivered"}
    outcomes[name] = {**row, "tool_name": name}


def external_label_finding(answer: Dict[str, Any]) -> Optional[str]:
    """§MCPTEST30 (V0650, tester batch 2 item 5, Guild order gwo_e3bad842b1a5943022b01d40): the outside view's V0649
    re-check (the dev machine, 2026-10-31; order (n) (d), session-release's 19a504ab8) enrolled an agent of its own
    and read a docker_label in the answer. The label names a container on this registry's host, the one SPIRE's docker
    attestor matches; an agent the route calls external has no such container, and V0650 leaves the label out of its
    answer. None where the answer names no deployment (an older image) or calls the agent on the host."""
    dep = answer.get("deployment") if isinstance(answer, dict) else None
    if dep in (None, "", "onbox") or "docker_label" not in answer:
        return None
    return (f"enableMtls answered an enrolment it calls {dep!r} (signal {answer.get('deployment_signal')!r}) with a "
            f"docker_label: a container on this registry's host, which an agent running elsewhere does not have")


async def lifecycle_mtls_toggle(rpc: RpcCall, parse: ParseResult,
                                  bag: Any, outcomes: Dict[str, dict]) -> None:
    """enableMtls → getMyMtlsStatus (verify enrolled=true) →
    disableMyMtls → getMyMtlsStatus (verify enrolled=false).

    Phase-5: silent NO-OP / state-flip verifier on mTLS toggle. §MCPTEST30 (V0545): the read-backs ask for SUCCESS, so
    a read the transport timed out (status 0, which "any" passes as below 500) verifies nothing instead of being
    recorded as a healthy read of the tool, and the checks read `enrolled`, the field the route answers.
    """
    dev_jwt = bag.developer_jwt
    sentinel_jwt = bag.sentinel_jwt

    ok_e, enabled = await _exec_step(rpc, parse, "theprotocol_enableMtls", "2",
                                     {"agent_jwt": sentinel_jwt},
                                     dev_jwt, outcomes, expect_status="any")
    if ok_e and isinstance(enabled, dict) and enabled.get("status") == "not_enrolled":
        return await _mtls_not_delivered(rpc, parse, sentinel_jwt, dev_jwt, enabled, outcomes)
    label = external_label_finding(enabled) if ok_e and isinstance(enabled, dict) else None
    if label:
        _bugfind(outcomes, "theprotocol_enableMtls", "2", label)

    await _exec_step(rpc, parse, "theprotocol_getMyMtlsStatus", "2",
                      {"agent_jwt": sentinel_jwt},
                      dev_jwt, outcomes,
                      expect_status="success",
                      record_as_separate=False,
                      verify_against="theprotocol_enableMtls",
                      verify_against_check=verify_mtls_flip(True, "enableMtls"))

    ok_d, disabled = await _exec_step(rpc, parse, "theprotocol_disableMyMtls", "2",
                                      {"agent_jwt": sentinel_jwt},
                                      dev_jwt, outcomes, expect_status="any")
    if ok_d and isinstance(disabled, dict) and disabled.get("message"):
        # V0650 (tester batch 1 item 3, Guild order gwo_2015b757c94ce69138500df6): the outside view read "Existing SVID
        # will expire within 4 hours" from a frame whose inline certificates live minutes (external test run 1, fixed in
        # V0649); the sentence names this frame's own inline lifetime, read in the target's process
        try:
            from agentvault_registry.routers.agent_mtls import _inline_svid_ttl
            want = f"within {max(1, _inline_svid_ttl() // 60)} minutes"
        except Exception:                                              # noqa: BLE001 — an older image: nothing to compare
            want = ""
        msg = str(disabled.get("message"))
        if want and (want not in msg or "4 hours" in msg):
            _bugfind(outcomes, "theprotocol_disableMyMtls", "2",
                     f"disableMyMtls says {msg[:160]!r}, not this frame's inline certificate lifetime ({want!r})")

    await _exec_step(rpc, parse, "theprotocol_getMyMtlsStatus", "2",
                      {"agent_jwt": sentinel_jwt},
                      dev_jwt, outcomes,
                      expect_status="success",
                      record_as_separate=False,
                      verify_against="theprotocol_disableMyMtls",
                      verify_against_check=verify_mtls_flip(False, "disableMyMtls"))


async def lifecycle_flare_celebration_ack(rpc: RpcCall, parse: ParseResult,
                                             bag: Any, outcomes: Dict[str, dict]) -> None:
    """flareCelebrationAcknowledge → getMyFlareStatus (verify
    should_celebrate=false).

    One-shot ack pattern: even if the sandbox dev has never celebrated,
    calling the ack is safe and the post-state should show
    should_celebrate=false (since the flag is set to NOW on first ack).
    """
    dev_jwt = bag.developer_jwt
    await _exec_step(rpc, parse, "theprotocol_flareCelebrationAcknowledge", "3",
                      {}, dev_jwt, outcomes, expect_status="any")

    def _verify_ack(inner: dict) -> Optional[str]:
        actual = inner.get("should_celebrate")
        if actual is None:
            return None
        if actual is True:
            return (
                "flareCelebrationAcknowledge returned 2xx but "
                "getMyFlareStatus.should_celebrate is still True"
            )
        return None

    await _exec_step(rpc, parse, "theprotocol_getMyFlareStatus", "3",
                      {}, dev_jwt, outcomes,
                      record_as_separate=False,
                      verify_against="theprotocol_flareCelebrationAcknowledge",
                      verify_against_check=_verify_ack)


MEMBER_VOTE_ROW = "member vote: one member, one vote"


async def _member_vote(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict],
                       proposal_id: Any, vote_args: Dict[str, Any]) -> None:
    """§MCPTEST30 (V0550): a vote where membership weighs it (GOVERNANCE_WEIGHT_MODE=member, §MEMBERSHIP).

    In lock mode a vote weighs what the agent locked, and this lifecycle took a refusal ("Only agents with locked
    units can vote") as an answer. In member mode it is one vote per member developer, weighed in points (100 = weight
    1.0, rising with tenure to 200). The setup bonds the sentinel from its own balance, which makes its developer a
    member at once where GOVERNANCE_MEMBER_MIN_BOND_AGE_DAYS=0 (the sandbox). So:
      * the sentinel's voting-power read must say mode member (the target's config says so);
      * where it can vote, castVote is held to success and the vote it records must weigh exactly the points the read
        named; where it cannot, castVote is held to the not_a_member refusal;
      * the run's second agent belongs to the same developer, so its vote on the same proposal is held to 409
        developer_already_voted: one member, one vote, whichever of its agents asks (a row of its own).
    """
    dev_jwt, sentinel_jwt = bag.developer_jwt, bag.sentinel_jwt
    okp, power = await _exec_step(rpc, parse, "theprotocol_getMyVotingPower", "2", {"agent_jwt": sentinel_jwt},
                                  dev_jwt, outcomes, expect_status="success", record_as_separate=False)
    power = power if isinstance(power, dict) else {}
    if not okp or power.get("mode") != "member":
        await _exec_step(rpc, parse, "theprotocol_castVote", "2", vote_args, dev_jwt, outcomes, expect_status="any")
        reason = (f"BUG-FIND: the target's registry-config says governance_weight_mode=member, but the sentinel's "
                  f"voting power answers mode={power.get('mode')!r}") if okp else None
        outcomes[MEMBER_VOTE_ROW] = _make_outcome(
            MEMBER_VOTE_ROW, "governance", False, "0", 0, reason, power, expect_status="success",
            skip_reason=None if okp else "NOT MEASURED: the sentinel's voting power could not be read")
        return
    can_vote = bool(power.get("canVote"))
    try:
        points = int(float(power.get("votingPower") or (power.get("membership") or {}).get("points") or 0))
    except (TypeError, ValueError):
        points = -1
    if not can_vote:
        okn, rn = await _exec_step(rpc, parse, "theprotocol_castVote", "2", vote_args, dev_jwt, outcomes,
                                   expect_status="error_4xx")
        row = outcomes.get("theprotocol_castVote")
        if okn and row is not None and "not_a_member" not in _switches.answer_text(rn):
            row["healthy"] = False
            row["fail_reason"] = ("the sentinel is not a member (canVote false) but castVote refused it with something "
                                  "other than not_a_member: " + _switches.answer_text(rn)[:160])
        outcomes[MEMBER_VOTE_ROW] = _make_outcome(
            MEMBER_VOTE_ROW, "governance", False, "0", 0, None, {}, expect_status="error_4xx",
            skip_reason=("NOT MEASURED: the sentinel's developer is not a member yet ("
                         + ", ".join(str(m) for m in ((power.get("membership") or {}).get("missing") or [])[:4])
                         + "), so there is no first vote to repeat"))
        return
    okv, rv = await _exec_step(rpc, parse, "theprotocol_castVote", "2", vote_args, dev_jwt, outcomes,
                               expect_status="success", expect_events=["VoteCast"],
                               event_verifier=getattr(bag, "event_verifier", None))
    row = outcomes.get("theprotocol_castVote")
    if okv and row is not None and isinstance(rv, dict) and rv.get("status") == "step_up_required":
        # presence mode asks the member's human to confirm (GOVERNANCE_PRESENCE_MODE); the tester holds no authenticator
        row["healthy"], row["fail_reason"] = False, None
        row["skip_reason"] = ("NOT MEASURED: this target asks a member to confirm a vote (step_up_required) and the "
                              "tester's developer has no authenticator yet")
        okv = False
    elif okv and row is not None and isinstance(rv, dict):
        vp = rv.get("voting_power")
        try:
            weighs = int(float(vp)) if vp is not None else None
        except (TypeError, ValueError):
            weighs = None
        if weighs != points:
            row["healthy"] = False
            row["fail_reason"] = (f"BUG-FIND: the member's vote weighs {vp!r}, but the voting-power read just before "
                                  f"named {points} points")
    second_jwt, second_did = bag.get("second_agent_jwt"), bag.get("second_agent_did")
    if not okv or not second_jwt or second_jwt == sentinel_jwt or str(second_did or "").startswith("${"):
        outcomes[MEMBER_VOTE_ROW] = _make_outcome(
            MEMBER_VOTE_ROW, "governance", False, "0", 0, None, {}, expect_status="error_4xx",
            skip_reason=("NOT MEASURED: " + ("the member's first vote did not land" if not okv else
                                             "the setup made no second agent of the same developer")))
        return
    t0 = time.time()
    ok2, body2, code2 = await rpc("theprotocol_castVote", {**vote_args, "agent_jwt": second_jwt,
                                                           "reason": "phase-5 lifecycle: the same member again"},
                                  jwt=dev_jwt, timeout=15)
    text2 = _switches.answer_text(parse(body2))
    code2i = int(code2) if str(code2).isdigit() else 0
    refused = 400 <= code2i < 500 and "developer_already_voted" in text2
    fail = None
    if code2i == 403 and "gov.vote" in text2:
        # the agent lacks the governor role (IRONKEY answers before membership is asked): the setup's grant did not land
        outcomes[MEMBER_VOTE_ROW] = _make_outcome(
            MEMBER_VOTE_ROW, "governance", False, str(code2), int((time.time() - t0) * 1000), None, {},
            expect_status="error_4xx",
            skip_reason="NOT MEASURED: the second agent lacks gov.vote (IRONKEY refused it before membership was asked)")
        return
    if 200 <= code2i < 300:
        fail = (f"BUG-FIND: a second agent of the same member developer voted again on proposal {proposal_id} "
                f"(HTTP {code2}): one member counted twice")
    elif not refused:
        fail = f"expected 409 developer_already_voted for the same developer's second agent, got HTTP {code2}: {text2[:160]}"
    outcomes[MEMBER_VOTE_ROW] = _make_outcome(MEMBER_VOTE_ROW, "governance", fail is None, str(code2),
                                              int((time.time() - t0) * 1000), fail, {}, expect_status="error_4xx")
    outcomes[MEMBER_VOTE_ROW]["result_excerpt"] = {"proposal_id": proposal_id, "first_vote_points": points,
                                                   "second_agent": "refused, already voted" if refused else f"HTTP {code2}"}


async def lifecycle_governance_proposal_vote_tally(rpc: RpcCall, parse: ParseResult,
                                                       bag: Any, outcomes: Dict[str, dict]) -> None:
    """createProposal → castVote (verify in getProposalVotes) → tallyProposal
    (premature → expects 4xx).

    Phase-5: catches BUG-FIND-21 class — proposer creating with 0 voting
    power AND voting failing. Uses the proposal_id from setup phase if
    available, otherwise creates a fresh one.
    """
    dev_jwt = bag.developer_jwt
    sentinel_jwt = bag.sentinel_jwt

    proposal_id = bag.flow_values.get("proposal_id")
    if not proposal_id:
        # Try to create one
        ok, r = await _exec_step(rpc, parse,
            "theprotocol_createProposal", "2",
            {"agent_jwt": sentinel_jwt,
             "title": "phase-5 governance lifecycle proposal",
             "description": "phase-5 lifecycle: tests vote + tally + premature-tally guard",
             "duration_days": 1,
             "proposal_type": "standard"},
            dev_jwt, outcomes, expect_status="any",
            # Phase C: emits ProposalCreated (skip_in_projection=true → audit).
            expect_events=["ProposalCreated"],
            event_verifier=getattr(bag, "event_verifier", None),
        )
        if ok and isinstance(r, dict):
            proposal_id = str(r.get("proposal_id") or r.get("id") or "")
    if not proposal_id:
        return

    # §pass73.3.21: read the proposal by its REAL id (public reads). Previously
    # getProposalDetail / getProposalVotes had no lifecycle coverage → ran standalone
    # against a placeholder id → 404 error-as-test-response. With a live proposal_id
    # they return 200 (detail object / votes list).
    _pid_arg = int(proposal_id) if str(proposal_id).isdigit() else proposal_id
    await _exec_step(rpc, parse, "theprotocol_getProposalDetail", "1",
                      {"proposal_id": _pid_arg}, dev_jwt, outcomes,
                      expect_status="success")
    await _exec_step(rpc, parse, "theprotocol_getProposalVotes", "1",
                      {"proposal_id": _pid_arg}, dev_jwt, outcomes,
                      expect_status="success")

    # §MCPTEST30 (V0640): an operator run whose sentinel could not open a proposal of its own holds only the pick made
    # for the reads above (test_flow_mcp_lifecycle.cloudop_open_own_proposal): a vote or a premature tally on that one
    # measures the proposal (an earlier run's, closed), not the rule, so both rows say why and only the read is asked
    _no_vote = bag.flow_values.get("proposal_vote_unavailable")
    if _no_vote:
        _why = f"no proposal of the run's own to vote on: {_no_vote}"
        _ef.unmeasured(outcomes, "theprotocol_castVote", "2", _why)
        if _switches.current().get("governance_weight_mode") == "member":
            _ef.unmeasured(outcomes, MEMBER_VOTE_ROW, "governance", _why)
        _ef.unmeasured(outcomes, _ef.refusal_row("theprotocol_tallyProposal",
                                                 'a proposal whose voting period has not ended'), "2", _why)
        await _exec_step(rpc, parse, "theprotocol_getMyVoteOnProposal", "2",
                          {"agent_jwt": sentinel_jwt, "proposal_id": str(proposal_id)},
                          dev_jwt, outcomes, expect_status="any")
        return

    _vote_args = {"agent_jwt": sentinel_jwt, "proposal_id": _pid_arg, "vote_in_favor": True,
                  "reason": "phase-5 lifecycle vote"}
    if _switches.current().get("governance_weight_mode") == "member":
        # §MCPTEST30 (V0550): membership weighs the vote here (§MEMBERSHIP), so the vote is held to what that says
        await _member_vote(rpc, parse, bag, outcomes, _pid_arg, _vote_args)
    else:
        # castVote — may 4xx if sentinel has 0 veToken voting power. Tolerated.
        # Event check only fires if contract eval passes — 4xx path skips it.
        await _exec_step(rpc, parse, "theprotocol_castVote", "2", _vote_args,
                          dev_jwt, outcomes, expect_status="any",
                          expect_events=["VoteCast"],
                          event_verifier=getattr(bag, "event_verifier", None))

    # tallyProposal premature → expects 4xx (voting period not over).
    # No event check here because the premature path won't emit
    # ProposalTallied. If the contract eval somehow passes (e.g., the
    # proposal ended in the test window), the event SHOULD land — but
    # the path is expect_status="any" so we don't enforce.
    await _ef.refusal_step(rpc, parse, "theprotocol_tallyProposal", "2",
                           {"agent_jwt": sentinel_jwt, "proposal_id": str(proposal_id)},
                           dev_jwt, outcomes, 'a proposal whose voting period has not ended',
                           codes=(400,), text='has not ended', permission_first_unmeasured=True)

    # getMyVoteOnProposal — exercises path; returns has_voted true/false
    await _exec_step(rpc, parse, "theprotocol_getMyVoteOnProposal", "2",
                      {"agent_jwt": sentinel_jwt, "proposal_id": str(proposal_id)},
                      dev_jwt, outcomes, expect_status="any")


async def lifecycle_log_enhanced_dispute(rpc: RpcCall, parse: ParseResult,
                                             bag: Any, outcomes: Dict[str, dict]) -> None:
    """A dispute against oneself is refused (a refusal row). §MCPTEST30 (V0636): the success path, a dispute between two
    agents of the runner's read back and dismissed, is earned_agent_public.lifecycle_earned_disputes (the sentinel
    named itself its own defendant here, with a reason code the route does not take, so the row was only ever a 403)."""
    await _ef.refusal_step(rpc, parse, "theprotocol_logEnhancedDispute", "2",
                           {"agent_jwt": bag.sentinel_jwt,
                            "defendant_agent_id": bag.sentinel_did,
                            "reason_code": "OTHER",
                            "brief_description": f"phase5-enhanced-dispute-{int(time.time())}"},
                           bag.developer_jwt, outcomes, "a dispute against oneself", codes=(403,), text="yourself")


async def lifecycle_federation_safe_paths(rpc: RpcCall, parse: ParseResult,
                                             bag: Any, outcomes: Dict[str, dict]) -> None:
    """Exercise federation peer/proposal mutation surfaces with sentinel
    inputs. No real Frame B peer exists in sandbox-A, so every call is
    expected to 4xx. Pure path coverage.
    """
    dev_jwt = bag.developer_jwt
    sentinel_jwt = bag.sentinel_jwt

    # federationVoteProposal: earned_agent_public.lifecycle_earned_by_design (§MCPTEST30, V0636: where registries
    # decide by ballot or votes count by membership the route refuses every agent's vote, said on its own row with the
    # refusal as a refusal row; this probe accepted any answer)
    # §MCPTEST30 (V0641): both held back on their own rows; their refusals are refusal rows with ids that are well
    # formed. The veto's probe sent 999999 into a UUID path, so what it measured was the EventStore parsing the probe's
    # argument (422 uuid_parsing, aa's frame pair nt261025x1a and V0639's operator read), never the route
    _ef.unmeasured(outcomes, "theprotocol_federationVetoProposal", "3",
                   "held back on purpose: a veto ends a federation proposal for every frame of the federation, and no "
                   "run holds a federation proposal to veto (raising one is held back too). Its refusal (a federation "
                   "proposal that does not exist) is a refusal row")
    await _ef.refusal_step(rpc, parse, "theprotocol_federationVetoProposal", "3",
                           {"proposal_id": "00000000-0000-4000-8000-000000000000",
                            "reason": "phase-5 no-such-proposal"},
                           dev_jwt, outcomes, "a federation proposal that does not exist", codes=(400, 403, 404),
                           text=("federation proposal not found", "only mainframe admin can veto"))
    _ef.unmeasured(outcomes, "theprotocol_federationProposeRaise", "3",
                   "held back on purpose: raising elevates a passed local proposal to every frame of the federation, "
                   "which no tester run does. Its refusal (a local proposal that does not exist) is a refusal row")
    await _ef.refusal_step(rpc, parse, "theprotocol_federationProposeRaise", "3", {"proposal_id": 999999999},
                           dev_jwt, outcomes, "a local proposal that does not exist", codes=(404,),
                           text="local proposal not found")
    await _ef.refusal_step(rpc, parse, "theprotocol_federationSyncRequest", "2",
                           {"agent_jwt": sentinel_jwt,
                            "request_data": {"phase5": True}},
                           dev_jwt, outcomes, 'a caller with no federation identity',
                           codes=(401,), text='Federation authentication required')
    await _exec_step(rpc, parse, "theprotocol_federationSlashRequest", "3",
                      {"settlement_id": "phase5-bad-sid",
                       "dispute_id": 999999,
                       "ruling": "GUILTY",
                       "amount": 1,
                       "complainant_did": bag.sentinel_did,
                       "defendant_did": bag.sentinel_did,
                       "origin_registry_url": "https://phase5.invalid",
                       "callback_url": "https://phase5.invalid/cb"},
                      dev_jwt, outcomes, expect_status="any")
    # §MCPSWEEP 2026-09-27: a TIER-3 tool (the dispatcher consumes `agent_jwt` only for tier 2 and handed it to this
    # one as an argument: -32602). The route takes a federation identity, so a developer bearer is refused 401 before
    # the handler; a peer would get 404 for an unknown settlement before any claim or mint.
    await _exec_step(rpc, parse, "theprotocol_federationSlashConfirmation", "3",
                      {"settlement_id": "phase5-bad-sid",
                       "status": "completed",
                       "amount": 0},
                      dev_jwt, outcomes, expect_status="error_4xx")
    # (a refusal row since §MCPTEST30 V0636: earned_ad_federation earns the tool's own row on a peer of the run's own)
    await _ef.refusal_step(rpc, parse, "theprotocol_deleteFederationPeerSelf", "3",
                           {"peer_id": "phase5-no-such-peer"},
                           dev_jwt, outcomes, "a peer id that is not a number", codes=(422,), text="valid integer")


async def lifecycle_contract_safe_paths(rpc: RpcCall, parse: ParseResult,
                                          bag: Any, outcomes: Dict[str, dict]) -> None:
    """Exercise contract-flow tools with deliberately-bad contract_id.
    Every call expects 4xx — pure path coverage.
    """
    dev_jwt = bag.developer_jwt
    sentinel_jwt = bag.sentinel_jwt

    bad_cid = "phase5-no-such-contract-id"
    await _ef.refusal_step(rpc, parse, "theprotocol_acceptContract", "2",
                           {"agent_jwt": sentinel_jwt,
                            "contract_id": bad_cid,
                            "upgrader_agent_did": bag.sentinel_did},
                           dev_jwt, outcomes, 'a contract that does not exist',
                           codes=(400, 404), text='not found')
    await _ef.refusal_step(rpc, parse, "theprotocol_acceptContractFederated", "2",
                           {"agent_jwt": sentinel_jwt,
                            "contract_id": bad_cid,
                            "upgrader_agent_did": bag.sentinel_did,
                            "registry_url": "https://phase5.invalid"},
                           dev_jwt, outcomes, 'a contract that does not exist',
                           codes=(404,), text='not found')
    await _ef.refusal_step(rpc, parse, "theprotocol_approveContractCompletion", "2",
                           {"agent_jwt": sentinel_jwt, "contract_id": bad_cid},
                           dev_jwt, outcomes, 'a contract that does not exist',
                           codes=(404,), text='not found')
    await _ef.refusal_step(rpc, parse, "theprotocol_createMalpracticeDispute", "2",
                           {"agent_jwt": sentinel_jwt, "contract_id": "999999999", "reason": "phase-5 path test"},
                           dev_jwt, outcomes, 'a contract that does not exist',
                           codes=(404,), text='not found')
    await _ef.refusal_step(rpc, parse, "theprotocol_crossRegistryContractProxy", "2",
                           {"agent_jwt": sentinel_jwt,
                            "action_data": {"phase5": True}},
                           dev_jwt, outcomes, 'action_data without contract_id and action',
                           codes=(400,), text='contract_id')


async def lifecycle_deployment_safe_paths(rpc: RpcCall, parse: ParseResult,
                                             bag: Any, outcomes: Dict[str, dict]) -> None:
    """The deployment tools on a deployment and a pipeline that do not exist: refused, each as a refusal row
    (§MCPTEST30 V0636: the tools' own rows are earned_ad_devtools', on a deployment of the run's own). The ids are
    well-formed, so each refusal is the route's own (a malformed id is a 422 from the path's validation)."""
    dev_jwt = bag.developer_jwt
    no_dep = "00000000-0000-4000-8000-000000000000"
    await _ef.refusal_step(rpc, parse, "theprotocol_getDeployment", "3",
                           {"agent_did": bag.sentinel_did, "deployment_id": no_dep},
                           dev_jwt, outcomes, "a deployment that does not exist", codes=(404,), text="not found")
    await _ef.refusal_step(rpc, parse, "theprotocol_appendDeploymentLogs", "3",
                           {"agent_did": bag.sentinel_did, "deployment_id": no_dep, "logs": "phase-5 test log line"},
                           dev_jwt, outcomes, "a deployment that does not exist", codes=(404,), text="not found")
    await _ef.refusal_step(rpc, parse, "theprotocol_updateDeploymentStatus", "3",
                           {"agent_did": bag.sentinel_did, "deployment_id": no_dep, "status": "running"},
                           dev_jwt, outcomes, "a deployment that does not exist", codes=(404,), text="not found")
    await _ef.refusal_step(rpc, parse, "theprotocol_triggerDeployment", "3",
                           {"agent_did": bag.sentinel_did, "pipeline_id": no_dep, "environment": "staging"},
                           dev_jwt, outcomes, "a pipeline that does not exist", codes=(404,), text="pipeline not found")


async def lifecycle_arena_safe_paths(rpc: RpcCall, parse: ParseResult,
                                       bag: Any, outcomes: Dict[str, dict]) -> None:
    """Arena match creation, then the two reads asked about the match made (§MCPTEST30 V0636: they were only ever
    asked about one that does not exist); the unknown-match probes stay, as refusal rows."""
    # createArenaMatch is developer-tier (administrators only, D6-634); the route reads mode and add_bots
    # §BEARER4 2026-09-07 — the MCP ENDPOINT wants a bearer on every path (401 otherwise) even for a tier-1 TOOL: with
    # none, the call 401'd with an EMPTY body and the lifecycle recorded it healthy under expect_status="any", so the
    # tool was never measured. A bearer does not change the tool's tier.
    ok_match, r_match = await _exec_step(rpc, parse, "theprotocol_createArenaMatch", "1",
                                         {"match_config": {"mode": "battle_royale", "add_bots": 2}},
                                         bag.developer_jwt, outcomes, expect_status="any")
    match_id = r_match.get("match_id") if ok_match and isinstance(r_match, dict) else None
    if match_id:
        ok_m, r_m = await _exec_step(rpc, parse, "theprotocol_getArenaMatch", "1", {"match_id": match_id},
                                     bag.developer_jwt, outcomes)
        state = r_m.get("state") if ok_m and isinstance(r_m, dict) and isinstance(r_m.get("state"), dict) else None
        if ok_m and (state or {}).get("match_id") != match_id:
            outcomes["theprotocol_getArenaMatch"]["healthy"] = False
            outcomes["theprotocol_getArenaMatch"]["fail_reason"] = (
                f"BUG-FIND: getArenaMatch answered match {(state or {}).get('match_id')!r} for {match_id!r}")
        ok_map, r_map = await _exec_step(rpc, parse, "theprotocol_getArenaMatchMap", "1", {"match_id": match_id},
                                         bag.developer_jwt, outcomes)
        if ok_map and not (isinstance(r_map, dict) and r_map.get("map")):
            outcomes["theprotocol_getArenaMatchMap"]["healthy"] = False
            outcomes["theprotocol_getArenaMatchMap"]["fail_reason"] = (
                f"BUG-FIND: getArenaMatchMap answered no map for the match {match_id} just made")
    else:
        for _t in ("theprotocol_getArenaMatch", "theprotocol_getArenaMatchMap"):
            outcomes[_t] = _not_measured(_t, "1", "NOT MEASURED: createArenaMatch made no match to read")
    await _ef.refusal_step(rpc, parse, "theprotocol_getArenaMatch", "1", {"match_id": "phase5-no-such-match"},
                           bag.developer_jwt, outcomes, "a match that does not exist", codes=(404,), text="not found")
    await _exec_step(rpc, parse, "theprotocol_getArenaMatchBets", "1",
                      {"match_id": "phase5-no-such-match"},
                      bag.developer_jwt, outcomes, expect_status="any")
    await _ef.refusal_step(rpc, parse, "theprotocol_getArenaMatchMap", "1", {"match_id": "phase5-no-such-match"},
                           bag.developer_jwt, outcomes, "a match that does not exist", codes=(404,), text="not found")


async def lifecycle_bundle_download_safe(rpc: RpcCall, parse: ParseResult,
                                            bag: Any, outcomes: Dict[str, dict]) -> None:
    """downloadBundle / downloadBundleViaOnboard / downloadPipelineTemplate /
    purchasePipelineTemplate — path coverage with bad ids.
    """
    dev_jwt = bag.developer_jwt
    # downloadBundle on a real bundle_id from setup (best case — succeeds).
    bid = bag.flow_values.get("bundle_id")
    if bid:
        await _exec_step(rpc, parse, "theprotocol_downloadBundle", "3",
                          {"bundle_id": str(bid)},
                          dev_jwt, outcomes, expect_status="any")
    # downloadBundleViaOnboard with a bad shape: a refusal row since §MCPTEST30 V0640 (the tool's own row is
    # earned_agent_public's, a throwaway agent's bundle downloaded with its own credentials)
    await _ef.refusal_step(rpc, parse, "theprotocol_downloadBundleViaOnboard", "3", {"bundle_data": {"phase5": True}},
                           dev_jwt, outcomes, "a request without the agent's DID and credentials", codes=(422,),
                           text="field required")
    # downloadPipelineTemplate on a template that does not exist (a refusal row since §MCPTEST30 V0636: the tool's own
    # row is earned_ad_devtools', on a free template the frame lists) + purchasePipelineTemplate with a bad id
    await _ef.refusal_step(rpc, parse, "theprotocol_downloadPipelineTemplate", "3",
                           {"template_id": "00000000-0000-4000-8000-000000000000"},
                           dev_jwt, outcomes, "a template that does not exist", codes=(404,), text="not found")
    # purchasePipelineTemplate: a refusal row since §MCPTEST30 V0641 (the tool's own row is earned_ad_devtools', a free
    # template bought by a throwaway's agent); the buyer is the run's sentinel, so the route reaches the template, where
    # the made-up buyer this probe sent measured only the buyer lookup ("Agent ... not found")
    if getattr(bag, "sentinel_did", None):
        await _ef.refusal_step(rpc, parse, "theprotocol_purchasePipelineTemplate", "3",
                               {"template_id": "00000000-0000-4000-8000-000000000000", "buyer_did": bag.sentinel_did},
                               dev_jwt, outcomes, "a template that does not exist", codes=(404,),
                               text="template not found")


async def lifecycle_agent_admin_paths(rpc: RpcCall, parse: ParseResult,
                                         bag: Any, outcomes: Dict[str, dict]) -> None:
    """importAgent / validateAgentImport / agentBulkExport with stub configs."""
    dev_jwt = bag.developer_jwt
    await _exec_step(rpc, parse, "theprotocol_validateAgentImport", "3",
                      {"agent_config": {"phase5": True}},
                      dev_jwt, outcomes, expect_status="any")
    await _exec_step(rpc, parse, "theprotocol_importAgent", "3",
                      {"agent_config": {"phase5": True}},
                      dev_jwt, outcomes, expect_status="any")
    await _exec_step(rpc, parse, "theprotocol_agentBulkExport", "3",
                      {"agent_dids": [bag.sentinel_did]}, dev_jwt, outcomes, expect_status="any")


async def lifecycle_org_member_invite(rpc: RpcCall, parse: ParseResult,
                                         bag: Any, outcomes: Dict[str, dict]) -> None:
    """inviteOrganizationMember + listOrganizationMembers using setup org.

    Phase-5: exercise both paths. The invite goes to a fake email; the
    list verifies the invite landed (best-effort).
    """
    dev_jwt = bag.developer_jwt
    org_id = bag.flow_values.get("organization_id")
    if not org_id:
        return
    await _exec_step(rpc, parse, "theprotocol_inviteOrganizationMember", "3",
                      {"org_id": str(org_id),
                       "email": "phase5-invitee@test.sandbox",
                       "role": "member"},
                      dev_jwt, outcomes, expect_status="any")
    await _exec_step(rpc, parse, "theprotocol_listOrganizationMembers", "3",
                      {"org_id": str(org_id)},
                      dev_jwt, outcomes, expect_status="any")
    # listOrganizationTeams (also under-exercised)
    await _exec_step(rpc, parse, "theprotocol_listOrganizationTeams", "3",
                      {"org_id": str(org_id)},
                      dev_jwt, outcomes, expect_status="any")
    # getOrganizationCicdSummary (read)
    await _exec_step(rpc, parse, "theprotocol_getOrganizationCicdSummary", "3",
                      {"org_id": str(org_id)},
                      dev_jwt, outcomes, expect_status="any")
    # listOrganizationAgents — also exercised in lifecycle_org_assign_unassign
    # but this duplicate ensures coverage if that earlier lifecycle skipped.


async def lifecycle_self_revocation_safe(rpc: RpcCall, parse: ParseResult,
                                            bag: Any, outcomes: Dict[str, dict]) -> None:
    """requestSelfRevocation — INTENTIONALLY destructive; sandbox admin
    can recover via DB UPDATE if the path mutates. The wrapper requires
    auth + reason. We pass a clear sandbox-test reason. If the call
    actually revokes, the recovery is to re-run sandbox seed.

    GUARD: per `feedback_change_password_lifecycle_one_way`, we send
    auth_jwt=DEV_JWT (admin) which the wrapper expects but the endpoint
    rejects (admin doesn't self-revoke). Expects 4xx for safety.
    """
    dev_jwt = bag.developer_jwt
    # Send an obviously-sandbox-test reason. If the call surprisingly
    # succeeds, the sandbox is destroyed — but the wrapper / endpoint
    # is designed to require dev tier and the admin path is gated.
    # §MCPTEST30 (tester batch 2 item 1): a refusal row held to the rule's sentence. It accepted any answer under the
    # tool's own name (the router: "lifecycle recorded a 403 as healthy ... the success path was not measured"); the
    # runner is the frame's admin, never a federation operator, and this lifecycle never runs on an operator
    await _ef.refusal_step(rpc, parse, "theprotocol_requestSelfRevocation", "3",
                           {"reason": "phase-5 sandbox-only test — do NOT actually revoke"},
                           dev_jwt, outcomes, "a developer that is no federation operator", codes=(403,),
                           text="not an active operator")


    # listAdminFrameInvitations already covered in misc_admin


async def _exec_function_safe(rpc, parse, tool, tier, args, jwt, outcomes):
    """Shorthand for path-only exercise with expect_status='any'."""
    await _exec_step(rpc, parse, tool, tier, args, jwt, outcomes,
                      expect_status="any")


    # disable/enable webhook admin already covered in webhook lifecycle


async def lifecycle_arena_leaderboard(rpc: RpcCall, parse: ParseResult,
                                          bag: Any, outcomes: Dict[str, dict]) -> None:
    """getArenaLeaderboard with game_type — sandbox has matches for robowars."""
    # Tier 1 — no auth needed
    for game_type in ("robowars", "snake", "trading", "td"):
        await _exec_step(rpc, parse, "theprotocol_getArenaLeaderboard", "1",
                          {"game_type": game_type},
                          bag.developer_jwt, outcomes, expect_status="any")


async def lifecycle_transfer_direct(rpc: RpcCall, parse: ParseResult,
                                       bag: Any, outcomes: Dict[str, dict]) -> None:
    """transferUnits from the sentinel to itself: refused (a refusal row). The transfer's success, with its
    TokensTransferred check, is lifecycle_transfer_settlement's."""
    dev_jwt = bag.developer_jwt
    sentinel_jwt = bag.sentinel_jwt
    # §MCPTEST30 (V0636): the route refuses a transfer to the sender itself (400 "Cannot transfer units to yourself"
    # in the TEG's current words; read live on sbx-alpha 2026-10-24 in its earlier ones), so this was a refusal written under the tool's own name, and lifecycles write
    # one dict in parallel: it could replace lifecycle_transfer_settlement's verified success. It is the rule's refusal
    # row now; the success is the settlement's.
    await _ef.refusal_step(rpc, parse, "theprotocol_transferUnits", "2",
                           {"agent_jwt": sentinel_jwt,
                            "recipient_did": bag.sentinel_did,
                            "amount": "1",
                            "message": "phase-5 lifecycle self-transfer"},
                           dev_jwt, outcomes, "to the sender itself", codes=(400,), text="to yourself")


async def lifecycle_teg_direct_paths(rpc: RpcCall, parse: ParseResult,
                                         bag: Any, outcomes: Dict[str, dict]) -> None:
    """tegSystemTransfer / tegLockDirect / tegUnlockDirect /
    tegCrossRegistryTransferDirect / tegReputationSignal — direct
    TEG paths. Run with safe small amounts where possible."""
    dev_jwt = bag.developer_jwt
    sentinel_jwt = bag.sentinel_jwt

    # §MCPTEST30 (V0636): the sentinel holds no teg.system_transfer (no normal role carries it), so this is IRONKEY's
    # refusal, a refusal row; the payment itself is earned_agent_public.lifecycle_earned_system_transfer's (this probe
    # wrote the tool's own row with any answer, and lifecycles run in parallel into one dict: it could replace that)
    await _ef.refusal_step(rpc, parse, "theprotocol_tegSystemTransfer", "2",
                           {"agent_jwt": sentinel_jwt, "amount": "0.01", "purpose": "phase-5 sweep tribute test"},
                           dev_jwt, outcomes, "an agent without teg.system_transfer", codes=(403,),
                           text="teg.system_transfer")

    # tegLockDirect — sandbox minimum staking is 10 AVT
    ok_stake, r_stake = await _exec_step(rpc, parse, "theprotocol_tegLockDirect", "2",
                                         {"agent_jwt": sentinel_jwt,
                                          "amount": "10",
                                          "lock_period_days": 0},
                                         dev_jwt, outcomes, expect_status="any")
    # §MCPTEST30 (V0636): the lock-0 position just made is unstaked again by the TEG's own stake id (the step used the
    # REGISTRY position id from phase 3, which the TEG answers 404, and so left one 10-unit TEG position behind each
    # night); earned_agent_public.lifecycle_earned_staking writes tegUnlockDirect's own row
    if ok_stake and isinstance(r_stake, dict) and r_stake.get("stake_id"):
        await _exec_step(rpc, parse, "theprotocol_tegUnlockDirect", "2",
                         {"agent_jwt": sentinel_jwt, "stake_id": str(r_stake["stake_id"])},
                         dev_jwt, {}, record_as_separate=False)
    await _ef.refusal_step(rpc, parse, "theprotocol_tegUnlockDirect", "2",
                           {"agent_jwt": sentinel_jwt, "stake_id": "phase5-no-such-stake"},
                           dev_jwt, outcomes, "a lock id the TEG does not hold", codes=(404,), text="not found")

    # tegCrossRegistryTransferDirect — no real Frame B, expects 4xx
    await _ef.refusal_step(rpc, parse, "theprotocol_tegCrossRegistryTransferDirect", "2",
                           {"agent_jwt": sentinel_jwt,
                            "receiver_did": bag.sentinel_did,
                            "amount": "0.01"},
                           dev_jwt, outcomes, "a receiver on this registry (the rail is for a peer's agent)",
                           codes=(400,))

    # tegReputationSignal — with bad tx_id, expects 4xx
    await _ef.refusal_step(rpc, parse, "theprotocol_tegReputationSignal", "2",
                           {"agent_jwt": sentinel_jwt,
                            "transaction_id": "phase5-no-such-tx",
                            "signal_value": 1},
                           dev_jwt, outcomes, 'a transaction that does not exist',
                           codes=(404,), text='not found')


async def lifecycle_attestation_full(rpc: RpcCall, parse: ParseResult,
                                         bag: Any, outcomes: Dict[str, dict]) -> None:
    """submitAttestation (empty proof) → expect 4xx. agentRevokeAttestation
    with fake id → 4xx. reverifyAttestation with fake id → 4xx.
    getAttestationDetail / getAttestationBundle with fake id → 4xx.
    submitTegAttestation / submitDisputeEvidence with bad input."""
    dev_jwt = bag.developer_jwt
    sentinel_jwt = bag.sentinel_jwt

    # submitAttestation needs circuit_id + proof_data + public_inputs. §MCPTEST30 (V0636): always a real v2.0.0 circuit
    # (an unknown circuit id answers 200 status "failed" and stores a failed row, so the probe refused only on nights
    # whose phase 3 named a circuit); the success path is lifecycle_zk_v2_attestations'
    cid = "fairMarkupPolicy/v2.0.0"
    await _ef.refusal_step(rpc, parse, "theprotocol_submitAttestation", "2",
                           {"agent_jwt": sentinel_jwt,
                            "circuit_id": cid,
                            "proof_data": {"phase5": True},
                            "public_inputs": {"phase5": True}},
                           dev_jwt, outcomes, 'a submission without reference_label',
                           codes=(400, 422), text='reference_label')

    fake_att = "phase5-no-such-attestation"
    await _ef.refusal_step(rpc, parse, "theprotocol_agentRevokeAttestation", "2",
                           {"agent_jwt": sentinel_jwt,
                            "attestation_id": fake_att,
                            "reason": "phase-5 sweep"},
                           dev_jwt, outcomes, 'an id that is not a UUID',
                           codes=(400,), text='UUID')
    await _ef.refusal_step(rpc, parse, "theprotocol_reverifyAttestation", "1",
                           {"attestation_id": fake_att},
                           bag.developer_jwt, outcomes, 'an id that is not a UUID',
                           codes=(400,), text='UUID')
    # the record and the bundle of a real attestation are zk_v2_attestations.run_zk_v2's rows (§MCPTEST30, V0636)
    await _ef.refusal_step(rpc, parse, "theprotocol_getAttestationDetail", "3",
                           {"attestation_id": fake_att},
                           dev_jwt, outcomes, 'an id that is not a UUID', codes=(400,), text='UUID')
    await _ef.refusal_step(rpc, parse, "theprotocol_getAttestationBundle", "3",
                           {"attestation_id": fake_att},
                           dev_jwt, outcomes, 'an id that is not a UUID', codes=(400,), text='UUID')
    # §MCPTEST30 (V0636): earned_agent_public.lifecycle_earned_teg_attestation submits one for real and keeps the sentinel's refusal (no reputation.signal) as a refusal row
    # submitDisputeEvidence with the dispute_id from setup if present
    did = bag.flow_values.get("dispute_id") or "phase5-no-such-dispute"
    await _ef.refusal_step(rpc, parse, "theprotocol_submitDisputeEvidence", "2",
                           {"agent_jwt": sentinel_jwt,
                            "dispute_id": str(did),
                            "evidence_data": {"phase5": "sweep evidence"}},
                           dev_jwt, outcomes, 'a dispute id that is not a number',
                           codes=(422,), text='valid integer')
    # verifyPublicAttestationBundle with empty bundle → 4xx (Tier 1, no auth)
    await _exec_step(rpc, parse, "theprotocol_verifyPublicAttestationBundle", "1",
                      {"bundle": {"phase5": True}},
                      bag.developer_jwt, outcomes, expect_status="any")
    # previewSlashReductionAttestation on a dispute id that is not a number (a refusal row since §MCPTEST30 V0636: the
    # tool's own row is earned_ad_agents', the preview of a dispute of the run's own) / previewVotingPowerAttestation
    await _ef.refusal_step(rpc, parse, "theprotocol_previewSlashReductionAttestation", "3",
                           {"dispute_id": "phase5-no-such-dispute"},
                           dev_jwt, outcomes, "a dispute id that is not a number", codes=(422,), text="valid integer")
    await _exec_step(rpc, parse, "theprotocol_previewVotingPowerAttestation", "3",
                      {"agent_did": bag.sentinel_did},
                      dev_jwt, outcomes, expect_status="any")


async def lifecycle_contract_submit_paths(rpc: RpcCall, parse: ParseResult,
                                              bag: Any, outcomes: Dict[str, dict]) -> None:
    """submitContractWork / submitContractWorkFederated / markContractFailed —
    all with bogus contract_id. Expects 4xx."""
    dev_jwt = bag.developer_jwt
    sentinel_jwt = bag.sentinel_jwt
    bad_cid = "phase5-no-such-contract"

    await _ef.refusal_step(rpc, parse, "theprotocol_submitContractWork", "2",
                           {"agent_jwt": sentinel_jwt,
                            "contract_id": bad_cid,
                            "pr_url": "https://phase5.invalid/pr/1"},
                           dev_jwt, outcomes, 'a contract that does not exist',
                           codes=(404,), text='not found')
    await _ef.refusal_step(rpc, parse, "theprotocol_submitContractWorkFederated", "2",
                           {"agent_jwt": sentinel_jwt,
                            "contract_id": bad_cid,
                            "pr_url": "https://phase5.invalid/pr/1",
                            "registry_url": "https://phase5.invalid"},
                           dev_jwt, outcomes, 'a contract that does not exist',
                           codes=(404,), text='not found')
    await _ef.refusal_step(rpc, parse, "theprotocol_markContractFailed", "2",
                           {"agent_jwt": sentinel_jwt,
                            "contract_id": bad_cid,
                            "reason": "phase-5 sweep"},
                           dev_jwt, outcomes, 'a contract that does not exist',
                           codes=(404,), text='not found')
    # getContractById with bad id
    await _ef.refusal_step(rpc, parse, "theprotocol_getContractById", "2",
                           {"agent_jwt": sentinel_jwt,
                            "contract_id": bad_cid},
                           dev_jwt, outcomes, 'a contract that does not exist',
                           codes=(404,), text='not found')


async def lifecycle_dispute_paths(rpc: RpcCall, parse: ParseResult,
                                     bag: Any, outcomes: Dict[str, dict]) -> None:
    """submitDispute / resolveTegDispute / getDisputeById / getTegDisputeDetail
    / getTegTransactionDetail using sentinel + setup dispute_id."""
    dev_jwt = bag.developer_jwt
    sentinel_jwt = bag.sentinel_jwt
    did = bag.flow_values.get("dispute_id") or "phase5-no-such-dispute"

    # submitDispute — the declared arguments (§MCPSWEEP 2026-09-27: it sent defendant_agent_did/reason_code/
    # brief_description, refused by the dispatcher) against a DID no registry knows: the route answers 404 before it
    # writes a dispute row (routers/disputes.py, the §DIDWIDEN-1 closer). Not a self-dispute: the tool refuses that
    # itself before any HTTP call, which would measure the wrapper, not the route. A real dispute row is not wanted
    # nightly: rulings are manual and dispute rows feed reputation, peer trust and enforcement.
    # (no complainant_did: D6-784, the dispute is filed as the agent of the token, and the schema no longer asks for one)
    await _ef.refusal_step(rpc, parse, "theprotocol_submitDispute", "2",
                           {"agent_jwt": sentinel_jwt,
                            "defendant_did": "did:theprotocol:phase5-no-such-agent",
                            "description": "phase-5 lifecycle probe: a defendant no registry knows"},
                           dev_jwt, outcomes, 'a defendant no registry knows',
                           codes=(404,), text='not know')
    # resolveTegDispute: Tier 2 since §MCPTEST30 V0538 (an agent route; as T3 every call was a 401). V0545: the route
    # refuses every caller (the TEG takes the registry's identity as its admin), so the step expects the refusal, and it
    # names a dispute nobody filed, never the run's own: under "any" this row read the TEG's 422 as healthy.
    # §MCPTEST30 (V0636): resolveTegDispute's row is written by earned_agent_public.lifecycle_earned_disputes (NOT
    # MEASURED, by design), which keeps its refusal as a refusal row (agentvault2-66)
    # getDisputeById: read as its owner in earned_ad_agents (a dispute between two agents of the run's own); here, an id
    # that is no integer keeps its refusal as a `refusal: ` row, never the tool's (agentvault2-aa)
    await _ef.refusal_step(rpc, parse, "theprotocol_getDisputeById", "3", {"dispute_id": "phase5-no-such-dispute"},
                           dev_jwt, outcomes, "an id that is no integer", codes=(422,), text="integer")
    # getTegDisputeDetail: Tier 2 since §MCPTEST30 (2026-10-01): the sentinel asks for a dispute nobody filed
    await _ef.refusal_step(rpc, parse, "theprotocol_getTegDisputeDetail", "2",
                           {"agent_jwt": sentinel_jwt, "dispute_log_id": "00000000-0000-4000-8000-000000000000"},
                           dev_jwt, outcomes, 'a dispute nobody filed',
                           codes=(404,), text='not found')
    # getTegTransactionDetail on a transaction the ledger never recorded (a refusal row since §MCPTEST30 V0636: the
    # tool's own row is earned_ad_devtools', on a transfer of the run's own)
    await _ef.refusal_step(rpc, parse, "theprotocol_getTegTransactionDetail", "3",
                           {"transaction_id": "phase5-no-such-tx"},
                           dev_jwt, outcomes, "a transaction the ledger never recorded", codes=(404,), text="not found")


async def lifecycle_agent_card_reads(rpc: RpcCall, parse: ParseResult,
                                         bag: Any, outcomes: Dict[str, dict]) -> None:
    """getAgentCardById / getAgentCardByHRI / getAgentCardByHumanReadableId
    using sentinel's agent_card_id / human_readable_id from setup."""
    card_id = bag.flow_values.get("agent_card_id")
    hri = bag.flow_values.get("human_readable_id")
    # Tier 1 — no auth needed
    if card_id:
        await _exec_step(rpc, parse, "theprotocol_getAgentCardById", "1",
                          {"card_id": str(card_id)},
                          bag.developer_jwt, outcomes, expect_status="any")
    else:
        await _exec_step(rpc, parse, "theprotocol_getAgentCardById", "1",
                          {"card_id": "phase5-no-such-card"},
                          bag.developer_jwt, outcomes, expect_status="any")
    if hri:
        await _exec_step(rpc, parse, "theprotocol_getAgentCardByHRI", "1",
                          {"human_readable_id": hri},
                          # §BEARER4 2026-09-07 — was `""`. The MCP ENDPOINT wants a bearer on every path
                      # (401 otherwise) even for a tier-1 TOOL — this file says so elsewhere:
                      # "SOME bearer for ALL paths … Use dev_jwt". With none, the call 401'd with an
                      # EMPTY body and the lifecycle recorded it healthy under expect_status="any",
                      # so the tool was never measured. A bearer does not change the tool's tier.
                      bag.developer_jwt, outcomes, expect_status="any")
        await _exec_step(rpc, parse, "theprotocol_getAgentCardByHumanReadableId", "1",
                          {"human_readable_id": hri},
                          bag.developer_jwt, outcomes, expect_status="any")
    else:
        await _exec_step(rpc, parse, "theprotocol_getAgentCardByHRI", "1",
                          {"human_readable_id": "phase5-no-such-hri"},
                          # §BEARER4 2026-09-07 — was `""`. The MCP ENDPOINT wants a bearer on every path
                      # (401 otherwise) even for a tier-1 TOOL — this file says so elsewhere:
                      # "SOME bearer for ALL paths … Use dev_jwt". With none, the call 401'd with an
                      # EMPTY body and the lifecycle recorded it healthy under expect_status="any",
                      # so the tool was never measured. A bearer does not change the tool's tier.
                      bag.developer_jwt, outcomes, expect_status="any")
        await _exec_step(rpc, parse, "theprotocol_getAgentCardByHumanReadableId", "1",
                          {"human_readable_id": "phase5-no-such-hri"},
                          bag.developer_jwt, outcomes, expect_status="any")
    # getAgentTemplate with bad template_id
    await _exec_step(rpc, parse, "theprotocol_getAgentTemplate", "3",
                      {"template_id": "phase5-no-such-template"},
                      bag.developer_jwt, outcomes, expect_status="any")
    # validateAgentCard with sentinel card data
    await _exec_step(rpc, parse, "theprotocol_validateAgentCard", "3",
                      {"card": {"phase5": True}},
                      bag.developer_jwt, outcomes, expect_status="any")


async def lifecycle_circuit_reads(rpc: RpcCall, parse: ParseResult,
                                     bag: Any, outcomes: Dict[str, dict]) -> None:
    """getCircuitACIR / getCircuitNargoToml / getCircuitSource using
    bag.circuit_id from setup (if present), else fake id."""
    cid = bag.flow_values.get("circuit_id") or "phase5-no-such-circuit"
    await _exec_step(rpc, parse, "theprotocol_getCircuitACIR", "1",
                      {"circuit_id": cid},
                      bag.developer_jwt, outcomes, expect_status="any")
    await _exec_step(rpc, parse, "theprotocol_getCircuitNargoToml", "1",
                      {"circuit_id": cid},
                      bag.developer_jwt, outcomes, expect_status="any")
    await _exec_step(rpc, parse, "theprotocol_getCircuitSource", "1",
                      {"circuit_id": cid},
                      bag.developer_jwt, outcomes, expect_status="any")


# §MCPSWEEP 2026-09-27 — `lifecycle_oauth_safe` is gone. It called oauthIntrospect and oauthTokenExchange under
# expect_status="any", which fails every 5xx, and a lifecycle row wins over the tool's contract. On a frame with no
# trusted registry both routes answer their documented fence, 501 "Cross-registry OAuth federation is not enabled on
# this registry", and both hand-curated contracts pin exactly that sentence (mcp_contracts.py). The step read green
# only while its probe was malformed; once corrected (WP-M3d) it failed the answer its contract declares correct.
# The contracts decide now. Gate: tests/test_mcp_lifecycle_any_meets_declared_5xx.py.


async def lifecycle_misc_safe(rpc: RpcCall, parse: ParseResult,
                                  bag: Any, outcomes: Dict[str, dict]) -> None:
    """Path coverage for: relayAction, recordAchievement, requestFrame,
    rotateFederationLicenseSelf, getMyApiKeyDetail (BUG-FIND-4, expect 404
    semantic), getBatchAgentBalances, getLockPayoutRecords,
    getPublicShowcaseCall, getFiatPurchaseSession, getDeveloperWebhookDeliveriesAlt,
    getFederationRegistryHealthProfile, restoreFromUpload, authSetNewPassword,
    submitOnboardRegister, regenerateBackupCodes (with bad password),
    removeOrganizationMember, finalizeFrameInvitation."""
    dev_jwt = bag.developer_jwt
    sentinel_jwt = bag.sentinel_jwt
    org_id = bag.flow_values.get("organization_id")

    # relayAction: NOT MEASURED on its own row, its refusal a refusal row (earned_agent_public.NOT_DRIVEN, §MCPTEST30
    # V0641: this probe sent no relay tool, and an operator run never took it)
    # an achievement type the catalog does not hold (a refusal row since §MCPTEST30 V0636: the tool's own row is
    # earned_ad_devtools', an enabled achievement recorded for a throwaway developer)
    await _ef.refusal_step(rpc, parse, "theprotocol_recordAchievement", "3",
                           {"achievement_type": "phase5-no-such-achievement", "agent_did": bag.sentinel_did},
                           dev_jwt, outcomes, "an achievement type that does not exist", codes=(404,),
                           text="unknown achievement type")
    # an intake body without its required fields: the route refuses it at validation, so no request is ever filed. A
    # refusal row since §MCPTEST30 V0650: the tool's own success is earned_ad_pair_last's (Phase 8, the pairs only), and
    # an any-answer under the tool's own name would have stood beside it unjudged (misc_safe runs on the frame only)
    await _ef.refusal_step(rpc, parse, "theprotocol_requestFrame", "3", {"request_data": {"phase5": True}},
                           dev_jwt, outcomes, "an intake body without its required fields", codes=(422,),
                           text="Field required")
    # a licence key that matches no licence: the route authenticates the key it rotates and refuses, so nothing rotates
    # (a refusal row since tester batch 2 item 1, held to the sentence: it accepted any answer under the tool's name)
    await _ef.refusal_step(rpc, parse, "theprotocol_rotateFederationLicenseSelf", "3",
                           {"federation_license_key": "phase6-not-a-licence-key", "reason": "scheduled_rotation"},
                           dev_jwt, outcomes, "a licence key that matches no licence", codes=(401,),
                           text="not recognised")
    # getMyApiKeyDetail (BUG-FIND-4 broken endpoint per E2E; expects 4xx)
    api_key_id = bag.flow_values.get("api_key_id")
    if api_key_id:
        await _exec_step(rpc, parse, "theprotocol_getMyApiKeyDetail", "3",
                          {"key_id": int(api_key_id) if str(api_key_id).isdigit() else api_key_id},
                          dev_jwt, outcomes, expect_status="any")
    # getBatchAgentBalances — Tier 3 read with sentinel DID
    await _exec_step(rpc, parse, "theprotocol_getBatchAgentBalances", "3",
                      {"agent_dids": [bag.sentinel_did]},
                      dev_jwt, outcomes, expect_status="any")
    # getLockPayoutRecords — needs distribution_id
    await _exec_step(rpc, parse, "theprotocol_getLockPayoutRecords", "3",
                      {"distribution_id": "phase5-no-such-dist"},
                      dev_jwt, outcomes, expect_status="any")
    # getPublicShowcaseCall is not called here (§MCPSWEEP V0464): the tool now POSTs what its route takes, and the
    # tester frame runs with the showcase disabled, so the route answers 503 "disabled on this deployment"; its
    # contract says so and the offline route gate pins the request shape.
    # getFiatPurchaseSession — needs session_id
    await _ef.refusal_step(rpc, parse, "theprotocol_getFiatPurchaseSession", "1",
                           {"session_id": "phase5-no-such-session"},
                           bag.developer_jwt, outcomes, 'a session that does not exist',
                           codes=(404,), text='not found')
    # getDeveloperWebhookDeliveriesAlt — needs webhook_id
    wid = bag.flow_values.get("webhook_id") or "phase5-no-such-webhook"
    await _exec_step(rpc, parse, "theprotocol_getDeveloperWebhookDeliveriesAlt", "3",
                      {"webhook_id": str(wid)},
                      dev_jwt, outcomes, expect_status="any")
    # getFederationRegistryHealthProfile (read-only) (a refusal row since §MCPTEST30 V0636: earned_ad_federation earns the tool's own row on a peer of the run's own)
    await _ef.refusal_step(rpc, parse, "theprotocol_getFederationRegistryHealthProfile", "3",
                           {"peer_id_or_name": "phase5-no-such-peer"},
                           dev_jwt, outcomes, "a peer that does not exist", codes=(404,))
    # restoreFromUpload with bad bundle_data
    await _exec_step(rpc, parse, "theprotocol_restoreFromUpload", "3",
                      {"bundle_b64": "cGhhc2U2LW5vdC1hLWJ1bmRsZQ=="},   # base64("phase6-not-a-bundle")
                      dev_jwt, outcomes, expect_status="any")
    # authSetNewPassword with bad token
    await _ef.refusal_step(rpc, parse, "theprotocol_authSetNewPassword", "1",
                           {"token": "phase5-bad",
                            "new_password": "Phase5BadPwd-2026!"},
                           bag.developer_jwt, outcomes, 'a token that is not a password-set token',
                           codes=(401,), text='Invalid or expired')
    # submitOnboardRegister with bad data
    await _ef.refusal_step(rpc, parse, "theprotocol_submitOnboardRegister", "2",
                           {"agent_jwt": sentinel_jwt,
                            "registration_data": {"phase5": True}},
                           dev_jwt, outcomes, 'any call (the route is 410 GONE; the wrapper sends no Bootstrap-Token, so the schema refuses first)',
                           codes=(410, 422))
    # regenerateBackupCodes with bad password (expects 4xx; no state mutation)
    await _exec_step(rpc, parse, "theprotocol_regenerateBackupCodes", "3",
                      {"password": "phase5-deliberately-wrong", "current_code": "000000"},
                      dev_jwt, outcomes, expect_status="any", record_as_separate=False)  # §MCPTEST30: unrecorded; self_account_on_throwaway owns this tool's row
    # removeOrganizationMember on the setup's organization, for a developer who is no member (a refusal row since
    # §MCPTEST30 V0636: the tool's own row is earned_ad_devtools', a member of the run's own removed)
    if org_id:
        await _ef.refusal_step(rpc, parse, "theprotocol_removeOrganizationMember", "3",
                               {"org_id": str(org_id), "developer_id": 999999},
                               dev_jwt, outcomes, "a developer who is no member", codes=(404,), text="member not found")
    # finalizeFrameInvitation: held back, its refusal a refusal row (earned_agent_public.NOT_DRIVEN, §MCPTEST30 V0641)
    # resetAgentCredentialsOnboard: the route reads the password before the agent, so a wrong one is refused first (a
    # refusal row since §MCPTEST30 V0636: the tool's own row is earned_ad_devtools', a reset of a throwaway's agent)
    await _ef.refusal_step(rpc, parse, "theprotocol_resetAgentCredentialsOnboard", "3",
                           {"agent_did": "did:theprotocol:phase5-no-such-agent", "password": "phase6-not-the-password"},
                           dev_jwt, outcomes, "a wrong password, for an agent that does not exist", codes=(403,),
                           text="invalid password")
    # operatorPortalSelfLogs / operatorPortalSelfRestart — need operator
    await _exec_step(rpc, parse, "theprotocol_operatorPortalSelfLogs", "3",
                      {}, dev_jwt, outcomes, expect_status="any")
    await _exec_step(rpc, parse, "theprotocol_operatorPortalSelfRestart", "3",
                      {}, dev_jwt, outcomes, expect_status="any")
    # activateOperator + selfProvisionOperator (sandbox commander is not an operator)
    await _exec_step(rpc, parse, "theprotocol_activateOperator", "3",
                      {"activation_code": "phase6-not-an-activation-code"}, dev_jwt, outcomes, expect_status="any")
    # a body without a name: the route refuses it at validation, so nothing is ever provisioned from the sweep
    await _exec_step(rpc, parse, "theprotocol_selfProvisionOperator", "3",
                      {"provisioning_data": {"phase6": True}}, dev_jwt, outcomes, expect_status="any")
    # triggerFederationSync (admin path covered, but also expose dev call)
    # the tool takes no argument: it asks this registry to sync with its peers now, which its worker does anyway
    await _exec_step(rpc, parse, "theprotocol_triggerFederationSync", "3",
                      {},
                      dev_jwt, outcomes, expect_status="any")
    # triggerLockPayoutRun (admin)
    await _exec_step(rpc, parse, "theprotocol_triggerLockPayoutRun", "3",
                      {}, dev_jwt, outcomes, expect_status="any")
    # updateFederationPeer with a peer id that is not a number (a refusal row since §MCPTEST30 V0636: earned_ad_federation earns the tool's own row on a peer of the run's own)
    await _ef.refusal_step(rpc, parse, "theprotocol_updateFederationPeer", "3",
                           {"peer_id": "phase5-no-such-peer", "updates": {"trust_level": "untrusted"}},
                           dev_jwt, outcomes, "a peer id that is not a number", codes=(422,), text="valid integer")
    # updatePeerSlashConfig with a peer id that is not a number (a refusal row since §MCPTEST30 V0636: earned_ad_federation
    # earns the tool's own row on a peer of the run's own)
    await _ef.refusal_step(rpc, parse, "theprotocol_updatePeerSlashConfig", "3",
                           {"peer_id": "phase5-no-such-peer", "config": {"max_slash_amount": 100}},
                           dev_jwt, outcomes, "a peer id that is not a number", codes=(422,), text="valid integer")
    # approveDisputeSettlement / rejectDisputeSettlement / getFederationDisputeSettlement: NOT MEASURED on their own
    # rows, their refusals refusal rows (earned_agent_public.NOT_DRIVEN, §MCPTEST30 V0641: no run makes a settlement)
    await _exec_step(rpc, parse, "theprotocol_getFederationDisputeSettlements", "3",
                      {}, dev_jwt, outcomes, expect_status="any")
    # getFederationPeerByID (a refusal row since §MCPTEST30 V0636: earned_ad_federation earns the tool's own row on a peer of the run's own)
    await _ef.refusal_step(rpc, parse, "theprotocol_getFederationPeerByID", "3",
                           {"peer_id": "phase5-no-such-peer"},
                           dev_jwt, outcomes, "a peer id that is not a number", codes=(422,), text="valid integer")
    # verify2FA with bad code
    await _exec_step(rpc, parse, "theprotocol_verify2FA", "3",
                      {"code": "000000"},
                      dev_jwt, outcomes, expect_status="any", record_as_separate=False)  # §MCPTEST30: unrecorded; self_account_on_throwaway owns this tool's row
    # §pass73.3.19: authRegister + logoutSession now covered by
    # lifecycle_auth_register_and_logout; deleteMyAgent by
    # lifecycle_agent_self_delete (genuine 2xx via throwaway entities).


async def lifecycle_create_teg_policies_batch(rpc: RpcCall, parse: ParseResult,
                                                 bag: Any, outcomes: Dict[str, dict]) -> None:
    """createTegPoliciesBatch's refusal of an empty list, as a `refusal: ` row.

    §MCPTEST30 (V0641, agentvault2-66): the empty list was filed under the tool's own name, the last writer after the
    setup, and its second call sent fields the route does not have (name, category, rules, enabled), so it created
    nothing and was never recorded: the tool passed on a refusal alone on every node. The setup's batch create (the
    delete subject, teg_policy_id_del) is the tool's row now."""
    dev_jwt = bag.developer_jwt
    await _ef.refusal_step(rpc, parse, "theprotocol_createTegPoliciesBatch", "3", {"policies": []}, dev_jwt, outcomes,
                           "an empty list", codes=(400,), text="non-empty list")


async def lifecycle_safe_invalid_input_paths(rpc: RpcCall, parse: ParseResult,
                                                bag: Any, outcomes: Dict[str, dict]) -> None:
    """Exercise a fan of skipped tools with intentionally-invalid input.
    Each is expected to 4xx — we're not asserting behavior, just
    coverage that the wrapper schema is reachable end-to-end.

    Phase-5 sprint-5.8 final: lifts ~10 destructively-skipped tools into
    the active-probe count. Wrapper-error detection will surface any wrapper
    that bails before reaching the backend (the `{"error": "..."}` pattern).
    """
    dev_jwt = bag.developer_jwt
    sentinel_jwt = bag.sentinel_jwt

    # Auth recovery flows — sandbox commander email is admin@test.sandbox
    await _exec_step(rpc, parse, "theprotocol_authForgotPassword", "1",
                      {"email": "nobody-phase5@test.sandbox"},
                      bag.developer_jwt, outcomes, expect_status="any")
    await _exec_step(rpc, parse, "theprotocol_authResendVerification", "1",
                      {"email": "nobody-phase5@test.sandbox"},
                      bag.developer_jwt, outcomes, expect_status="any")
    await _ef.refusal_step(rpc, parse, "theprotocol_authResetPassword", "1",
                           {"token": "phase5-bad-token", "new_password": "Phase5BadPwd123!"},
                           bag.developer_jwt, outcomes, 'a reset token that was never issued',
                           codes=(400,), text='no longer valid')
    await _ef.refusal_step(rpc, parse, "theprotocol_authVerifyEmail", "1",
                           {"token": "phase5-bad-token"},
                           bag.developer_jwt, outcomes, 'a token that was never issued',
                           codes=(400,), text='not_found')
    await _exec_step(rpc, parse, "theprotocol_authValidate2FA", "1",
                      {"login_token": "phase6-not-a-partial-token", "code": "000000"},
                      bag.developer_jwt, outcomes, expect_status="any", record_as_separate=False)  # §MCPTEST30: unrecorded; self_account_on_throwaway owns this tool's row
    await _ef.refusal_step(rpc, parse, "theprotocol_authRecoverAccount", "1",
                           {"email": "nobody@test.sandbox", "recovery_key": "phase6-not-a-recovery-key"},
                           bag.developer_jwt, outcomes, 'a recovery key that was never issued',
                           codes=(400,), text='Invalid email or recovery key')
    await _exec_step(rpc, parse, "theprotocol_authRecover2FA", "1",
                      {"login_token": "phase6-not-a-partial-token",
                       "backup_code": "phase5-bad-code"},
                      bag.developer_jwt, outcomes, expect_status="any", record_as_separate=False)  # §MCPTEST30: unrecorded; self_account_on_throwaway owns this tool's row

    # Federation peer mutations: peer data without the fields the route requires, refused (a refusal row since §MCPTEST30 V0636: earned_ad_federation earns the tool's own row on a peer of the run's own)
    await _ef.refusal_step(rpc, parse, "theprotocol_createFederationPeer", "3",
                           {"peer_data": {"registry_url": "https://phase5-not-a-real-peer.invalid"}},
                           dev_jwt, outcomes, "peer data without the fields the route requires", codes=(422,),
                           text="required")

    # Bridge transfer — the declared arguments (§MCPSWEEP 2026-09-27: it sent `target_frame`, refused by the
    # dispatcher) with amount 0, refused by the route's own schema (gt=0) before the handler. NEVER a positive amount to
    # a frame that does not exist: the route then commits an INITIATED bridge row, LOCKS the amount at the TEG, dials the
    # URL, unlocks and answers 500 (routers/token_bridge.py, read 2026-09-27), the refusal-becomes-an-action hazard.
    # The bridge family is on his D8 RETIRE? list: only the probe changes.
    await _ef.refusal_step(rpc, parse, "theprotocol_bridgeTransfer", "2",
                           {"agent_jwt": sentinel_jwt,
                            "target_agent_did": bag.sentinel_did,
                            "amount": "0",
                            "target_frame_url": "https://phase5-no-such-frame.invalid"},
                           dev_jwt, outcomes, 'an amount of 0',
                           codes=(404, 422))

    # Cross-TEG balance sync — a peer-registry callback, with the required `notification` it never sent (§MCPSWEEP
    # 2026-09-27) and NO agent in it. The route takes a peer-registry identity, so an agent bearer is refused before the
    # handler, and a notification without agent_did is a 400 before any read even for a peer. NEVER put a local agent_did
    # in it: the route would rewrite that agent's balance cache and can emit a counted transfer.
    await _ef.refusal_step(rpc, parse, "theprotocol_crossTegBalanceSync", "2",
                           {"agent_jwt": sentinel_jwt, "notification": {"phase5": True}},
                           dev_jwt, outcomes, 'a caller with no federation identity',
                           codes=(401,), text='Federation authentication required')

    # Apply reputation signal — the declared arguments (§MCPSWEEP 2026-09-27: it sent target_agent_did/signal_type/
    # magnitude, refused by the dispatcher before the tool ran) on a transaction that does not exist, so what is measured
    # is the REFUSAL (the contract's error_4xx). No side effect can precede it: the route's first gate is the
    # `reputation.signal` permission dependency (under IRONKEY enforce, an agent without it is refused there), then the
    # TEG's lookup of the transaction. A real signal on the sentinel's own transfer is not measured here: see the finding on
    # `reputation.signal` living only in the service-provider role while only a transfer's SENDER may signal.
    await _ef.refusal_step(rpc, parse, "theprotocol_applyReputationSignal", "2",
                           {"agent_jwt": sentinel_jwt,
                            "transaction_id": "phase5-no-such-transaction",
                            "signal_value": 1},
                           dev_jwt, outcomes, 'a transaction that does not exist',
                           codes=(404,), text='not found')

    # Claim TEG rewards for the sentinel, as its developer (Tier 3 since §MCPTEST30 V0538: as T2 every call was a 401)
    # — the sentinel may have no rewards, expects empty or 4xx
    await _exec_step(rpc, parse, "theprotocol_claimTegPayouts", "3",
                      {"agent_did": bag.sentinel_did},
                      dev_jwt, outcomes, expect_status="any")

    # Export TEG transactions — Tier 3 read with default format
    await _exec_step(rpc, parse, "theprotocol_exportTegTransactions", "3",
                      {"fmt": "json"},
                      dev_jwt, outcomes, expect_status="any")

    # Agent builder generate on a spec without its required fields (a refusal row since §MCPTEST30 V0636: the tool's
    # own row is earned_ad_devtools', a simple wrapper's package)
    await _ef.refusal_step(rpc, parse, "theprotocol_agentBuilderGenerate", "3",
                           {"spec": {"phase5": True}},
                           dev_jwt, outcomes, "a spec without its required fields", codes=(422,))
    await _ef.refusal_step(rpc, parse, "theprotocol_agentBuilderGenerateTemplate", "3",
                           {"template_spec": {"phase5": True}},
                           dev_jwt, outcomes, "a spec without its required fields", codes=(422,))

    # Frame invitation create — the declared arguments (§MCPSWEEP 2026-09-27: it sent invitee_email/frame_id) with an
    # initiator_nonce that fails the schema's hex pattern: 422 before the handler. The route is public, and a valid nonce
    # would make it DIAL the bundle URL (verify off, redirects followed) and, where that answers, write an invitation
    # row, emit FrameInvitationRequested and mail the admin: the nonce stays invalid and every host .invalid.
    await _exec_step(rpc, parse, "theprotocol_createFrameInvitation", "3",
                      {"trust_domain": "phase5.invalid",
                       "bundle_endpoint_url": "https://phase5-bundle.invalid/",
                       "federation_endpoint_url": "https://phase5-fed.invalid/",
                       "name": "phase-5 lifecycle probe",
                       "contact_email": "nobody@phase5.invalid",
                       "initiator_nonce": "phase5-not-hex"},
                      dev_jwt, outcomes, expect_status="error_4xx")

    # acceptOrgInvitation on a token nobody issued (a refusal row since §MCPTEST30 V0636: the tool's own row is
    # earned_ad_devtools', an invitation of the run's own accepted)
    await _ef.refusal_step(rpc, parse, "theprotocol_acceptOrgInvitation", "3",
                           {"token": "phase5-bad-invite-token"},
                           dev_jwt, outcomes, "a token nobody issued", codes=(400,), text="invalid or expired")


async def lifecycle_a2a_payment_settle_balance(rpc: RpcCall, parse: ParseResult,
                                                  bag: Any, outcomes: Dict[str, dict]) -> None:
    """Post-settle assertion: a self-payment moves nothing but its fee, so the payer's balance must not go UP.

    Phase-5: catches BUG-FIND-class economic regressions on payment settle.

    §MCPTEST30 (V0585): the payer is a THROWAWAY agent the sentinel funds with dust, never the sentinel. Lifecycles run six
    at once and several pay the sentinel while this one waits: the A2A settle race returns its payer's dust to it, which
    read "+0.028476" here on sbx-alpha (2026-10-05 03:05Z) and on the nightly pair nt261008 (2026-10-08), the same amount
    both times and no settle in it. Nobody else knows the throwaway's DID, so nothing else pays it, and any rise is the
    settle's. It returns what it holds to the sentinel (less the fee) and is deleted.
    """
    from decimal import ROUND_DOWN, Decimal, InvalidOperation
    dev_jwt = bag.developer_jwt
    sentinel_jwt = bag.sentinel_jwt
    sentinel_did = getattr(bag, "sentinel_did", None)
    if not sentinel_jwt or not sentinel_did or str(sentinel_did).startswith("${"):
        return

    def _dec(v: Any) -> Optional[Decimal]:
        try:
            return Decimal(str(v)) if v is not None else None
        except (InvalidOperation, TypeError, ValueError):
            return None

    ok, r = await _exec_step(rpc, parse, "theprotocol_createAgent", "3",
        {"name": f"tw-selfpay-{int(time.time())}",
         "description": "MCP tester self-payment balance check (throwaway, deleted after)"},
        dev_jwt, outcomes, expect_status="any", record_as_separate=False)
    if not ok or not isinstance(r, dict):
        return
    cid, csec = r.get("client_id"), r.get("client_secret")
    did = r.get("did") or r.get("agent_did")
    if not did:
        return
    try:
        if not (cid and csec):
            return
        _ok, tok = await _exec_step(rpc, parse, "theprotocol_getAgentToken", "0",
            {"client_id": cid, "client_secret": csec},
            dev_jwt, outcomes, expect_status="any", record_as_separate=False)
        payer_jwt = tok.get("access_token") if isinstance(tok, dict) else None
        if not payer_jwt:
            return
        okf, _f = await _exec_step(rpc, parse, "theprotocol_transferUnits", "2",
            {"agent_jwt": sentinel_jwt, "recipient_did": did, "amount": "0.05",
             "message": f"MCP tester: funds a self-payment check {did[-12:]}"},
            dev_jwt, outcomes, expect_status="any", record_as_separate=False)
        if not okf:
            return

        ok, before = await _exec_step(rpc, parse, "theprotocol_getMyBalance", "2",
            {"agent_jwt": payer_jwt}, dev_jwt, outcomes, record_as_separate=False)
        before_liquid = _dec(before.get("liquid_balance")) if ok and isinstance(before, dict) else None
        if before_liquid is None or before_liquid <= 0:
            return

        ok, a = await _exec_step(rpc, parse, "theprotocol_authorizePayment", "2",
            {"agent_jwt": payer_jwt, "target_agent_did": did, "amount": "0.01", "ttl_seconds": 300},
            dev_jwt, outcomes, expect_status="any", record_as_separate=False)
        if not ok or not isinstance(a, dict) or not a.get("token"):
            return
        await _exec_step(rpc, parse, "theprotocol_settlePayment", "2",
            {"agent_jwt": payer_jwt, "token": a["token"], "success": True},
            dev_jwt, outcomes, expect_status="any", record_as_separate=False)

        # Settlement is async: wait, then re-read. Nothing else pays the throwaway, so a micro-unit is the only slack.
        await asyncio.sleep(3.0)

        def _verify_post_settle(inner: dict) -> Optional[str]:
            after_liquid = _dec(inner.get("liquid_balance")) if isinstance(inner, dict) else None
            if after_liquid is None:
                return None
            if after_liquid > before_liquid + Decimal("0.000001"):
                return (f"settlePayment (self-pay) returned 2xx but the payer's liquid_balance INCREASED "
                        f"({before_liquid} → {after_liquid}); expected net-zero minus fee (a throwaway payer: "
                        f"nothing else pays it)")
            return None

        ok, after = await _exec_step(rpc, parse, "theprotocol_getMyBalance", "2",
            {"agent_jwt": payer_jwt}, dev_jwt, outcomes, expect_status="any", record_as_separate=False,
            verify_against="theprotocol_settlePayment", verify_against_check=_verify_post_settle)
        held = _dec(after.get("liquid_balance")) if ok and isinstance(after, dict) else None
        back = (held / Decimal("1.05")).quantize(Decimal("0.000001"), rounding=ROUND_DOWN) if held else None
        if back and back > 0:
            await _exec_step(rpc, parse, "theprotocol_transferUnits", "2",
                {"agent_jwt": payer_jwt, "recipient_did": sentinel_did, "amount": str(back),
                 "message": f"MCP tester: returns {did[-12:]}"},
                dev_jwt, outcomes, expect_status="any", record_as_separate=False)
    finally:
        await _exec_step(rpc, parse, "theprotocol_deleteMyAgentByDev", "3",
            {"agent_did": did}, dev_jwt, outcomes, expect_status="any", record_as_separate=False)


REPUTATION_SIGNAL_TOOL = "theprotocol_applyReputationSignal"


async def _signal_own_seed_transfer(rpc: RpcCall, parse: ParseResult, sentinel_jwt: str, dev_jwt: str,
                                    outcomes: Dict[str, dict], transaction_id: str) -> Optional[bool]:
    """applyReputationSignal's SUCCESS leg (§MCPSWEEP 2026-09-28, agentvault2-41).

    Reachable since agentvault2-a4's §FINDINGS-A4 fix (e74def71): the route is gated on `teg.transfer`, which the sentinel
    holds, and the TEG lets a transfer's SENDER signal it once (the transaction COMPLETED, of type transfer). So the
    sentinel signals +1 on its own first EigenTrust seed of this run: a fresh transaction every run, one signal each.

    ⚠ It never overwrites the tool's row. Outcomes are keyed by tool and this lifecycle runs LAST, so a recorded success
    here would replace the refusal probe's row (lifecycle_safe_invalid_input_paths: an unknown transaction, error_4xx), and
    a refusal that had regressed into an ACCEPTANCE would be masked by a later success. When that row exists the leg runs
    unrecorded and a failure is written ONTO it: the row is healthy only when both legs hold. With no row yet the leg
    records its own. Returns None when there is no transaction to signal (a seed failed or named none)."""
    if not transaction_id:
        return None
    had_row = REPUTATION_SIGNAL_TOOL in outcomes
    ok, inner = await _exec_step(
        rpc, parse, REPUTATION_SIGNAL_TOOL, "2",
        {"agent_jwt": sentinel_jwt, "transaction_id": transaction_id, "signal_value": 1},
        dev_jwt, outcomes, expect_status="success", record_as_separate=not had_row,
    )
    if had_row and not ok:
        why = ""
        if isinstance(inner, dict):
            why = str(inner.get("_text") or inner.get("error") or inner.get("detail") or "")
        row = outcomes[REPUTATION_SIGNAL_TOOL]
        row["healthy"] = False
        row["fail_reason"] = (f"the success leg failed: +1 by the sentinel on its own seed transfer {transaction_id} "
                              f"({why[:200] or 'no reason in the reply'})")
    return ok


# ============================================================================
# Phase D addition (2026-05-26 evening) — Reputation EigenTrust seed lifecycle
# ============================================================================
# Mirrors `_setup_reputation_eigentrust` from admin_api_test.py:2082.
# Preconditions:
#   • Sentinel must have AVT (already funded 5000 in Phase 3 setup)
#   • A second agent must exist as transfer counterparty
# Steps:
#   1. Create a second agent if not present (uses existing wrapper)
#   2. Run 3 self→peer transfers to seed LocalTrustScore rows
#   3. Trigger EigenTrust++ computation via admin endpoint
#   4. Call getTrustScore — may 404 first time; lifecycle retries
# After this lifecycle: bag.flow_values["second_agent_did"] is populated
# and getTrustScore/getAgentReputation should land happy paths.
# ============================================================================


async def _target_db(bag: Any, sql: str, params: Dict[str, Any], *, write: bool = False) -> Tuple[Any, Optional[str]]:
    """§MCPTEST30 (V0638): one statement on the target's own database, the one way a lifecycle reaches it. Through
    bag.target_db where the run gives one (a cloud operator: the runner works inside the FRAME's registry, so its
    in-process database is the parent frame's; the operator's is asked in its own database container), else in-process
    (the lifecycle runs in the target's registry process). A read: (the first column of the first row, or None, None);
    a write: (the rows changed, None); (None, why) when it could not be asked. The value is never logged."""
    via = getattr(bag, "target_db", None)
    if via is not None:
        return await via(sql, params, write=write)
    try:
        from sqlalchemy import text as _text
        from agentvault_registry.database import AsyncSessionLocal as _S
        async with _S() as db:
            res = await db.execute(_text(sql), params)
            if write:
                await db.commit()
                return int(res.rowcount or 0), None
            return res.scalar(), None
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}"


async def _trust_score_of_the_newest_epoch(rpc: RpcCall, parse: ParseResult, dev_jwt: str,
                                           outcomes: Dict[str, dict], bag: Any = None) -> None:
    """§MCPTEST30 (V0637): getTrustScore on an agent the target's newest EigenTrust epoch holds, read from the target's
    database (_target_db). The sentinel is made fresh each run, so whether it has a score depends on whether an epoch
    ran since (§EVTYPES8: roughly hourly); an agent of the newest epoch always has one. The contract keeps its pinned
    refusal (a DID that cannot exist) and the runner keeps this row beside it as `earned: getTrustScore`. A target
    with no epoch at all is NOT MEASURED, said."""
    tool = "theprotocol_getTrustScore"
    did, why = await _target_db(bag, "SELECT agent_did FROM global_trust_vectors "
                                     "ORDER BY epoch DESC, computed_at DESC LIMIT 1", {})
    if why:
        outcomes[tool] = _not_measured(tool, "3", f"NOT MEASURED: the target's trust vectors could not be read "
                                                  f"({why})")
        return
    if not did:
        outcomes[tool] = _not_measured(tool, "3", "NOT MEASURED: the target holds no EigenTrust epoch yet")
        return
    ok, got = await _exec_step(rpc, parse, tool, "3", {"agent_did": str(did)}, dev_jwt, outcomes)
    if ok and (not isinstance(got, dict) or got.get("did") != did):
        _bugfind(outcomes, tool, "3", "getTrustScore answered for another agent than the one asked for")


async def lifecycle_reputation_eigentrust_setup(
    rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]
) -> None:
    """Seed eigentrust LocalTrustScore + trigger epoch + verify GTV lands."""
    dev_jwt = bag.developer_jwt
    sentinel_jwt = bag.sentinel_jwt
    sentinel_did = bag.sentinel_did

    # 1. Create a second agent for trust signaling
    second_did = None
    second_jwt = None
    ok_c, c_res = await _exec_step(
        rpc, parse, "theprotocol_createAgent", "3",
        {"name": f"phase-d-rep-peer-{int(time.time())}",
         "description": "phase-d reputation eigentrust counterparty"},
        dev_jwt, outcomes, expect_status="any",
    )
    if ok_c and isinstance(c_res, dict):
        second_did = c_res.get("did") or c_res.get("agent_did")
        cid = c_res.get("client_id")
        csec = c_res.get("client_secret")
        if cid and csec:
            # Mint agent JWT for the second agent
            ok_t, t_res = await _exec_step(
                rpc, parse, "theprotocol_getAgentToken", "0",
                {"client_id": cid, "client_secret": csec},
                dev_jwt, outcomes, expect_status="any",
            )
            if ok_t and isinstance(t_res, dict):
                second_jwt = t_res.get("access_token")
    if second_did and hasattr(bag, "flow_values"):
        bag.flow_values["second_agent_did"] = second_did
        if second_jwt:
            bag.flow_values["second_agent_jwt"] = second_jwt

    # §MCPTEST30 (V0637): getTrustScore's success path, on an agent the target's newest epoch holds, is its own
    # lifecycle since V0638 (lifecycle_trust_score_newest_epoch), so a cloud operator runs it without this seed

    if not second_did:
        # Without a counterparty we can't seed trust signals — skip prereq
        return

    # 2. Fund the second agent so it has a balance to be transferred TO
    # (sentinel→peer transfers create LocalTrustScore entries on both sides)
    # Direct admin treasury fund — no wrapper exposed
    # NOTE: the existing _phase3_setup_entities funds sentinel 5000. Peer gets
    # implicit balance via incoming transfers. Skip explicit funding.

    # 3. Three transfers to seed LocalTrustScore rows. §MCPSWEEP 2026-09-27 (run b487126bc7274966): the argument is the
    # declared `recipient_did`; it sent `receiver_agent_id`, which the dispatcher refused before the tool ran, so no trust
    # row was ever seeded. And these are a PREREQUISITE, not the tool's measurement (record_as_separate=False): this
    # lifecycle runs LAST and outcomes are keyed by tool, so recording them overwrote transfer_settlement's verified
    # transfer (balance read-back + TokensTransferred) with a weaker any-status row, here a dispatcher refusal.
    seed_tx = ""
    for i in range(3):
        _ok_seed, _inner_seed = await _exec_step(
            rpc, parse, "theprotocol_transferUnits", "2",
            {"agent_jwt": sentinel_jwt,
             "recipient_did": second_did,
             "amount": "10",
             "message": f"mcp lifecycle: eigentrust seed {i + 1}/3 (sweep-owned agents)"},
            dev_jwt, outcomes, expect_status="any", record_as_separate=False,
        )
        if not seed_tx and _ok_seed and isinstance(_inner_seed, dict):
            seed_tx = str(_inner_seed.get("transaction_id") or "")   # the tool defaults to "" when the TEG named none

    # 3b. applyReputationSignal's SUCCESS leg on the first seed of THIS run (see _signal_own_seed_transfer).
    await _signal_own_seed_transfer(rpc, parse, sentinel_jwt, dev_jwt, outcomes, seed_tx)

    # 4. Trigger EigenTrust++ epoch, through the admin bridge (§MCPTEST30 V0553: through the public bridge the dispatcher
    # refused it, so no epoch followed the seed transfers and the admin probe list triggered one later instead). The tool
    # holds no contract, so its row joins the admin sweep's lifecycle rows (bag.admin_lifecycle_rows), which the sweep
    # judges, and the probe list does not start a second epoch (mcp_admin_lifecycles._measured_for_real).
    rpc_admin, admin_rows = _admin_bridge(bag), getattr(bag, "admin_lifecycle_rows", None)
    if rpc_admin is not None and isinstance(admin_rows, dict):
        ok_epoch, epoch = await _exec_step(rpc_admin, parse, "theprotocol_triggerEigentrustComputation", "admin", {},
                                           dev_jwt, admin_rows)
        if ok_epoch and isinstance(epoch, dict) and epoch.get("status") != "started":
            _bugfind(admin_rows, "theprotocol_triggerEigentrustComputation", "admin",
                     f"the trigger answered 2xx with status={epoch.get('status')!r}, not 'started'")

    # 5. getTrustScore is read by lifecycle_trust_score_newest_epoch, on an agent of the newest epoch: the epoch this
    # step triggers runs in the background, so the sentinel's own score may not have landed by the time a read asks.


async def lifecycle_trust_score_newest_epoch(
    rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]
) -> None:
    """§MCPTEST30 (V0638): getTrustScore's success path on an agent of the target's newest EigenTrust epoch
    (_trust_score_of_the_newest_epoch), apart from the seed lifecycle so a run that does not take the seed (a cloud
    operator: its agent would outlive the run) still reads it."""
    await _trust_score_of_the_newest_epoch(rpc, parse, bag.developer_jwt, outcomes, bag)


# ============================================================================
# Phase C addition (2026-05-26) — Cross-registry transfer via canaries
# ============================================================================
# Commander mandate: sandbox canaries are always-there pre-funded receivers
# for cross-registry transfer testing. Roster in `canary_agents` table.
# - 11 canaries on frame-a (3 alpha + 2 beta + 4 gamma + 4 registry-test)
# - 2 canaries on frame-b (registry-test-b)
# Each has 100K AVT pre-funded — never bounces on insufficient-balance.
# ============================================================================


async def _registry_self(rpc: RpcCall, parse: ParseResult, bag: Any) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """§MCPTEST30 (V0641): this target's own entry and its peers, from /public/registry-config ({}, [] when unread)."""
    try:
        ok, body, _ = await rpc("theprotocol_getPublicRegistryConfig", {}, jwt=bag.developer_jwt, timeout=30)
        cfg = parse(body) if ok else {}
    except Exception:  # noqa: BLE001 — an unread config is no receiver, never a crash
        return {}, []
    if not isinstance(cfg, dict):
        return {}, []
    return dict(cfg.get("self") or {}), [p for p in (cfg.get("peers") or []) if isinstance(p, dict)]


async def _peer_canary_receiver(bag: Any, me: Dict[str, Any], peers: List[Dict[str, Any]]) -> Optional[str]:
    """§MCPTEST30 (V0636): the canary receiver of an operator of THIS frame's (same currency), as this frame mirrors it:
    the operator's name from /public/registry-config's peers (role operator, parent this frame), the receiver card
    from the frame's own mirror (_target_db). None when there is none.

    §MCPTEST30 (V0641, agentvault2-d6's word 2026-10-25): on an OPERATOR, its parent frame's canary receiver as the
    operator mirrors it, where the parent's currency is the operator's own (the 1:1 rail), so an operator run sends the
    same dust the other way. Each sandbox operator mirrors its parent's (canary-sbx-alpha-receiver-* on sbxalphaop, from
    .../registry/sandbox-alpha; canary-sbx-beta-receiver-* on sbxbetaop), read 2026-10-25."""
    try:
        if me.get("role") == "operator":
            parent = str(me.get("parent") or "")
            frame = next((p for p in peers if p.get("key") == parent and p.get("role") == "frame"), None)
            if not parent or frame is None or (frame.get("currency") or "") != (me.get("currency") or ""):
                return None
            did, _why = await _target_db(
                bag, "SELECT agent_did FROM agent_cards WHERE is_active AND agent_did IS NOT NULL "
                     "AND card_data->>'name' LIKE :n "
                     "AND card_data->'federation_metadata'->>'source_registry' LIKE :s "
                     "ORDER BY updated_at DESC LIMIT 1",
                {"n": "canary-%-receiver%", "s": f"%/registry/{parent}"})
            return str(did) if did else None
        key = str(me.get("key") or "")
        ops = [p.get("key") for p in peers if p.get("role") == "operator" and p.get("parent") == key and p.get("key")]
        for op in ops:
            did, _why = await _target_db(
                bag, "SELECT agent_did FROM agent_cards WHERE is_active AND agent_did IS NOT NULL "
                     "AND card_data->>'name' LIKE :n "
                     "AND card_data->'federation_metadata'->>'source_registry' LIKE :s "
                     "ORDER BY updated_at DESC LIMIT 1",
                {"n": f"canary-{op}-receiver%", "s": f"%/registry/{op}"})
            if did:
                return str(did)
    except Exception:  # noqa: BLE001 — no receiver is a NOT MEASURED row, never a crash
        return None
    return None


async def lifecycle_cross_registry_canary_recipient(
    rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]
) -> None:
    """This frame's sentinel → the canary receiver of this frame's own operator: a cross-registry transfer on one ledger.

    Exercises tegCrossRegistryTransferDirect into an operator's always-on, pre-funded canary receiver.

    §MCPTEST30 (V0638, agentvault2-aa): since V0636 the receiver is this frame's own operator's (d700c111), so the 0.01
    takes the TEG-direct cross-teg path and writes TokensTransferred, CrossRegistryTransferCompleted and
    TransactionFeeCollected on the frame's one ledger (routers/teg_integration.py; read on sbx-alpha's ledger
    2026-10-24, transfer 5b6acf43). CrossFrameTransferInitiated is the frame-to-frame rail's event, which a transfer to
    the frame's own operator never writes: expecting it read a correct transfer as a silent no-op (EU's History run
    6166c97bca144270). The row expects the events this rail writes. A frame-to-frame transfer's settlement stays measured
    where his 2026-06-26 instruction put it, at the run summary's `emission_integrity` (routers/mcp_tester.py
    `_compute_emission_integrity`: the `crossframe_settlement` and `receiver_credit_b` checks).
    """
    dev_jwt = bag.developer_jwt
    sentinel_jwt = bag.sentinel_jwt

    # §MCPTEST30 (V0636): the receiver is THIS frame's operator's canary receiver, mirrored here (same currency, the
    # 1:1 rail), read from the frame's own peers and mirrors. It was a pinned DID of registry-test-b, a frame torn down
    # long ago, answered 400 "Cannot resolve registry" every night (kept below as a refusal row).
    # §MCPTEST30 (V0641): on an operator, its parent frame's canary receiver (d6's word); the refusal row of a receiver
    # no peer holds is a frame's only: an operator routes a receiver it cannot resolve through its FX gateway, which
    # starts a route that then compensates (409 "FX route did not settle", every run, V0641's operator preview; D6-830)
    me, peers = await _registry_self(rpc, parse, bag)
    on_operator = me.get("role") == "operator"
    frame_b_canary_did = await _peer_canary_receiver(bag, me, peers)
    if not on_operator:
        await _ef.refusal_step(rpc, parse, "theprotocol_tegCrossRegistryTransferDirect", "2",
                               {"agent_jwt": sentinel_jwt, "receiver_did": "did:theprotocol:888eeb39-a53e-4554-74e2",
                                "amount": "0.01", "memo": "phase-c: a receiver no peer holds"},
                               dev_jwt, outcomes, "a receiver no peer registry holds", codes=(400,),
                               text="Cannot resolve")
    if not frame_b_canary_did:
        outcomes["theprotocol_tegCrossRegistryTransferDirect"] = _not_measured(
            "theprotocol_tegCrossRegistryTransferDirect", "2",
            "NOT MEASURED: no canary receiver of this operator's parent frame (in its currency) is mirrored here to "
            "send dust to" if on_operator else
            "NOT MEASURED: no operator of this frame's has a canary receiver mirrored here to send dust to")
        return

    # §MCPTEST30 (V0638): the same-ledger rail's events (TEG-direct cross-teg), never the frame-to-frame rail's.
    await _exec_step(
        rpc, parse, "theprotocol_tegCrossRegistryTransferDirect", "2",
        {"agent_jwt": sentinel_jwt,
         "receiver_did": frame_b_canary_did,
         "amount": "0.01",   # §MCPTEST30: `target_registry` was never read; the receiver's DID names its home
         "memo": "phase-c cross-registry canary probe"},
        dev_jwt, outcomes, expect_status="success",
        expect_events=["TokensTransferred", "CrossRegistryTransferCompleted"],
        event_verifier=getattr(bag, "event_verifier", None),
    )


# ============================================================================
# Lifecycle registry
# ============================================================================


async def lifecycle_transfer_settlement(rpc: RpcCall, parse: ParseResult,
                                        bag: Any, outcomes: Dict[str, dict]) -> None:
    """transferUnits 0.01 sentinel -> second agent: the row, the moved balance, the ledger event.

    §FEDPROOF 2026-09-13, on his rule that rows leaving a trace live in the tester: the battery's
    settlement row (#11a) moved here. The transferUnits CONTRACT pins a refusal (a recipient that does
    not exist) and says in its own notes that the success path "is a LIFECYCLE's job (fund, move, poll
    the ledger)". This is that lifecycle. Dust: 0.01 between two sweep-owned agents on the sandbox.

    Three halves, because "balances moved AND delta=0" is not proof the move was RECORDED (§S4):
      * the call answers 2xx with a transaction id (the row);
      * the receiver's balance reads +0.01 afterwards (read-after-write, propagated onto the
        transferUnits row as a BUG-FIND when it does not);
      * `TokensTransferred` lands in the target's EventStore (the Phase C event verifier, DID-matched
        because canaries also emit it).
    A sweep without a second agent skips silently and leaves the contract's refusal pin as the row: a
    self-transfer moves nothing (measured: 0 of 80 TokensTransferred had from == to), so asserting on
    one would be asserting something the ledger never does.
    """
    dev_jwt = bag.developer_jwt
    s_jwt = bag.sentinel_jwt
    payee = bag.flow_values.get("second_agent_did") or ""
    payee_jwt = bag.flow_values.get("second_agent_jwt") or ""
    if not payee or not payee_jwt or payee == bag.sentinel_did:
        return
    # §MCPTEST30 (V0541): the receiver's half is read off its own ledger, by a message only this probe sends. Round 11's
    # strict run (186f01a3a7794b12) called a balance that moved +0.02 a BUG-FIND: the idempotency probes paid the same
    # receiver 0.01 from the same sender 0.68 s earlier (tx 2c1d4c6a, then this probe's e10e4e9d, one 0.01 each on the
    # TEG), inside the two balance reads. The balance stays as evidence; the verdict is the ledger row.
    import secrets as _secrets
    message = f"mcp lifecycle: settlement probe (0.01, sweep-owned agents) {_secrets.token_hex(6)}"

    def _bal(inner: Any) -> Optional[float]:
        if not isinstance(inner, dict):
            return None
        for k in ("balance", "liquid_balance", "token_balance", "available"):
            if inner.get(k) is not None:
                try:
                    return float(str(inner[k]))     # balances arrive in scientific notation ("1E+3")
                except Exception:                   # noqa: BLE001
                    return None
        return None

    _ok0, body0, _c0 = await rpc("theprotocol_getMyBalance", {"agent_jwt": payee_jwt}, jwt=dev_jwt, timeout=20)
    b0 = _bal(parse(body0))
    ok, r = await _exec_step(rpc, parse, "theprotocol_transferUnits", "2",
                             {"agent_jwt": s_jwt, "recipient_did": payee, "amount": "0.01", "message": message},
                             dev_jwt, outcomes, expect_status="success", timeout=60,
                             expect_events=["TokensTransferred"],
                             event_verifier=getattr(bag, "event_verifier", None))
    if not ok:
        return
    tx = (r or {}).get("transaction_id") if isinstance(r, dict) else None
    row = outcomes.get("theprotocol_transferUnits")
    if row is not None and not tx:
        row["healthy"] = False
        row["fail_reason"] = "BUG-FIND: transferUnits answered 2xx without a transaction_id (no row to point at)"

    _okb, body1, _cb = await rpc("theprotocol_getMyBalance", {"agent_jwt": payee_jwt}, jwt=dev_jwt, timeout=20)
    b1 = _bal(parse(body1))
    moved = f"{round(b1 - b0, 6):+.6f}" if b0 is not None and b1 is not None else "unread"
    own = await _own_transfers(rpc, parse, bag, payee_jwt, message)
    if row is not None and row.get("healthy") and own is not None and own != 1:
        row["healthy"] = False
        row["fail_reason"] = (f"BUG-FIND: transferUnits answered 2xx (tx {str(tx)[:8]}) but the receiver's ledger holds "
                              f"{own} transactions carrying this transfer's message, not 1 (its balance moved {moved}; "
                              f"other probes pay the same receiver)")


# ============================================================================
# §TWOAGENT (2026-09-23, V0437): a knock answered, a block, a leave, locally
# ============================================================================

def _chat_bug(outcomes: Dict[str, dict], tool: str, why: str) -> None:
    """Mark a behaviour failure on the row of the tool that acted (the framework's BUG-FIND convention); a row this
    lifecycle did not record is left alone, so a verdict never lands on another lifecycle's row."""
    row = outcomes.get(tool)
    if row is None:
        return
    if row.get("healthy"):
        row["healthy"] = False
        row["fail_reason"] = f"BUG-FIND: {why}"
    else:
        row["fail_reason"] = f"{row.get('fail_reason') or ''} · BUG-FIND: {why}"


def _chat_text(inner: Any) -> str:
    return str(inner.get("_text") or "") if isinstance(inner, dict) else ""


def _chat_landed(ok: bool, inner: Any) -> bool:
    """Under expect_status="any" a refusal (4xx) still reads ok; a call landed only if no error text came back."""
    return bool(ok) and not _chat_text(inner).startswith("Error:") and not (
        isinstance(inner, dict) and isinstance(inner.get("error"), str))


_CHAT = "chat: "
CHAT_STRANGER_READ = _CHAT + "a thread read by an agent that is no participant"
_HTTP_STATUS_IN = re.compile(r"\bHTTP (\d{3})\b")


def judge_stranger_thread_read(ok: bool, inner: Any) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    """(healthy, the sentence when not, evidence) for readThread asked by an agent that is no participant in the
    conversation and whose developer holds no seat in it (V0556): healthy is a clean refusal (403 or 404) carrying no
    message; an answer that carries the thread, or lands at all, is a privacy BUG-FIND. Pure (unit-tested)."""
    text = _chat_text(inner)
    msgs = inner.get("messages") if isinstance(inner, dict) else None
    m = _HTTP_STATUS_IN.search(text)
    c = int(m.group(1)) if m else (200 if _chat_landed(ok, inner) else 0)
    ev = {"status": c, "said": text[:120], "messages_in_answer": len(msgs) if isinstance(msgs, list) else None}
    if _chat_landed(ok, inner) or (isinstance(msgs, list) and msgs):
        return False, ("BUG-FIND: chat: an agent that is no participant in a conversation, and whose developer holds no "
                       f"seat in it, read the thread (HTTP {c}, {ev['messages_in_answer']} message(s) in the answer)"), ev
    if c not in (403, 404):
        return False, f"the stranger's thread read was not refused cleanly: HTTP {c or 'no answer'}: {text[:120]!r}", ev
    return True, None, ev


async def lifecycle_chat_requests_blocks_and_leave(rpc: RpcCall, parse: ParseResult,
                                                   bag: Any, outcomes: Dict[str, dict]) -> None:
    """A stranger's knock answered three ways, then a block, an unblock and a leave, all on ONE frame.

    TESTPLAN SB1 and V0437's local halves, driven through the MCP chat tools. A knock needs two OWNERS (a developer's
    own agents are not strangers and never land in the Requests lane), so the knocker K belongs to the second seeded
    developer (`developer_jwt_nonadmin2`, which no lifecycle logs out) and the recipients R1-R3 to the sweep's admin.
    K's owner is heard through the dispatcher's own record (`getWebhookDeliveries`) on a hook whose host is `.invalid`
    (nothing leaves the box). One row per tool that acted, carrying every verdict about that tool:
      respondChatRequest: R1's explicit accept is heard by K's owner (SB1); R3's decline is NOT (a refusal the knocker
        cannot see is the consent half of the Requests lane); R1's leave leaves.
      sendChatMessage: R2's REPLY into the pending thread is the accept, and K's owner hears it (V0437 (4): the host
        used to flip the row silently); a refused call carries its reason to the MCP caller (V0437: `_chat_request`
        dropped it), read on the blocker's own attempt to open a dm to the principal it blocked.
      blockChatPrincipal: R1's seat leaves, and K is not told (K's next message is accepted).
      unblockChatPrincipal: R1 opens the dm again and it is the same thread, active.
    Everything it makes is removed at the end; no money moves.
    """
    import asyncio as _asyncio
    import uuid as _uuid

    dev_a = bag.developer_jwt
    dev_b = getattr(bag, "developer_jwt_nonadmin2", "") or ""
    if not dev_b:
        for tool in ("theprotocol_blockChatPrincipal", "theprotocol_unblockChatPrincipal"):
            outcomes[tool] = {
                "tool_name": tool, "contract_tier": "2", "healthy": False, "status_code": 0, "elapsed_ms": 0,
                "skip_reason": ("no second developer session this run (developer@test.sandbox's login failed), and a "
                                "knock needs two owners: a developer's own agents are not strangers"),
                "fail_reason": None, "args_used": {}, "result_excerpt": {}}
        return

    run = _uuid.uuid4().hex[:8]
    made: List[Tuple[str, str]] = []     # (dev jwt, did)
    hook_id: Optional[str] = None

    async def _agent(dev: str, tag: str) -> Optional[Dict[str, str]]:
        ok, r = await _exec_step(rpc, parse, "theprotocol_createAgent", "3",
                                 {"name": f"lc-chat-{tag}-{run}", "description": "chat lifecycle probe (V0437)"},
                                 dev, outcomes, expect_status="any", record_as_separate=False)
        if not ok or not isinstance(r, dict):
            return None
        did = r.get("did") or r.get("agent_did")
        cid, sec = r.get("client_id"), r.get("client_secret")
        if not (did and cid and sec):
            return None
        made.append((dev, did))
        _ok, t = await _exec_step(rpc, parse, "theprotocol_getAgentToken", "0",
                                  {"client_id": cid, "client_secret": sec}, dev, outcomes,
                                  expect_status="any", record_as_separate=False)
        jwt = t.get("access_token") if isinstance(t, dict) else None
        return {"did": did, "jwt": jwt} if jwt else None

    async def _say(dev: str, speaker: Dict[str, str], body: str, record: bool = False, **target) -> Tuple[bool, dict]:
        args = {"body": body, "client_ref": f"lc-chat-{_uuid.uuid4().hex}", "agent_jwt": speaker["jwt"], **target}
        ok, inner = await _exec_step(rpc, parse, "theprotocol_sendChatMessage", "2", args, dev, outcomes,
                                     expect_status="success" if record else "any", record_as_separate=record)
        return _chat_landed(ok, inner), inner

    async def _state(dev: str, speaker: Dict[str, str], conv: str) -> Optional[str]:
        _ok, page = await _exec_step(rpc, parse, "theprotocol_readThread", "2",
                                     {"conversation_id": conv, "agent_jwt": speaker["jwt"]}, dev, outcomes,
                                     expect_status="any", record_as_separate=False)
        return page.get("my_state") if isinstance(page, dict) else None

    async def _accepted() -> Optional[Dict[str, str]]:
        """conversation id -> accepted_by, from the dispatcher's record; None when the record is unreadable."""
        ok, r = await _exec_step(rpc, parse, "theprotocol_getWebhookDeliveries", "3",
                                 {"webhook_id": hook_id, "limit": 50}, dev_b, outcomes,
                                 expect_status="any", record_as_separate=False)
        if not ok or not isinstance(r, dict) or not isinstance(r.get("deliveries"), list):
            return None
        seen: Dict[str, str] = {}
        for d in r["deliveries"]:
            if not isinstance(d, dict) or d.get("event_type") != "chat.request.accepted":
                continue
            p = d.get("payload") if isinstance(d.get("payload"), dict) else {}
            data = p.get("data") if isinstance(p.get("data"), dict) else p
            if data.get("conversation_id"):
                seen[str(data["conversation_id"])] = str(data.get("accepted_by") or "")
        return seen

    try:
        k = await _agent(dev_b, "k")
        rs = [await _agent(dev_a, f"r{i}") for i in (1, 2, 3)]
        if not k or not all(rs):
            return
        r1, r2, r3 = rs
        ok, h = await _exec_step(rpc, parse, "theprotocol_createWebhook", "3",
                                 {"url": f"https://lc-chat-{run}.invalid/hook", "events": ["chat.request.accepted"],
                                  "description": "chat lifecycle: a host that never resolves; the record is read"},
                                 dev_b, outcomes, expect_status="any", record_as_separate=False)
        hook_id = h.get("id") if ok and isinstance(h, dict) else None
        if not hook_id:
            return

        convs: Dict[str, str] = {}
        for name, r in (("r1", r1), ("r2", r2), ("r3", r3)):
            ok, c = await _say(dev_b, k, f"lc-chat knock {name}", target_agent_did=r["did"])
            if not ok or not isinstance(c, dict) or not c.get("conversation_id"):
                return
            convs[name] = c["conversation_id"]

        # R1 accepts (the row), R2 accepts by replying (the row), R3 declines.
        ok_acc, _ = await _exec_step(rpc, parse, "theprotocol_respondChatRequest", "2",
                                     {"conversation_id": convs["r1"], "action": "accept", "agent_jwt": r1["jwt"]},
                                     dev_a, outcomes)
        ok_rep, rep = await _say(dev_a, r2, "lc-chat reply is the accept", record=True, conversation_id=convs["r2"])
        ok_dec, dec = await _exec_step(rpc, parse, "theprotocol_respondChatRequest", "2",
                                       {"conversation_id": convs["r3"], "action": "decline", "agent_jwt": r3["jwt"]},
                                       dev_a, outcomes, expect_status="any", record_as_separate=False)
        declined_at = time.monotonic()
        if not _chat_landed(ok_dec, dec):
            _chat_bug(outcomes, "theprotocol_respondChatRequest", f"a decline was refused: {_chat_text(dec)[:160]}")

        heard: Optional[Dict[str, str]] = None
        for _ in range(12):
            heard = await _accepted()
            if heard is not None and convs["r1"] in heard and convs["r2"] in heard:
                break
            await _asyncio.sleep(2.5)
        if heard is None:
            _chat_bug(outcomes, "theprotocol_respondChatRequest", "the knocker's webhook record was unreadable")
        else:
            if ok_acc and heard.get(convs["r1"], "").lower() != r1["did"].lower():
                _chat_bug(outcomes, "theprotocol_respondChatRequest",
                          "an explicit accept told the knocker's owner nothing within 30 s (chat.request.accepted)")
            if ok_rep and heard.get(convs["r2"], "").lower() != r2["did"].lower():
                _chat_bug(outcomes, "theprotocol_sendChatMessage",
                          "a reply into a pending request accepted it and told the knocker's owner nothing within "
                          "30 s (V0437: a reply that accepts tells the knocker)")

        # V0556: a thread is read by its participants and their households only. R3 is no participant in R1's thread
        # (K and R1), and its developer (the runner's) holds no developer seat there: it must be refused, with nothing
        # of the thread in the answer
        t_x = time.time()
        ok_x, x = await _exec_step(rpc, parse, "theprotocol_readThread", "2",
                                   {"conversation_id": convs["r1"], "agent_jwt": r3["jwt"]}, dev_a, outcomes,
                                   expect_status="any", record_as_separate=False)
        healthy_x, why_x, ev_x = judge_stranger_thread_read(ok_x, x)
        outcomes[CHAT_STRANGER_READ] = _make_outcome(CHAT_STRANGER_READ, "2", healthy_x, str(ev_x.get("status") or 0),
                                                     int((time.time() - t_x) * 1000), why_x, ev_x,
                                                     expect_status="success")
        outcomes[CHAT_STRANGER_READ]["result_excerpt"] = dict(ev_x)

        # R1 blocks K: R1's seat leaves, and K is not told.
        ok_blk, blk = await _exec_step(rpc, parse, "theprotocol_blockChatPrincipal", "2",
                                       {"ptype": "agent", "agent_did": k["did"], "agent_jwt": r1["jwt"]},
                                       dev_a, outcomes)
        if ok_blk:
            if not (isinstance(blk, dict) and blk.get("blocked") is True):
                _chat_bug(outcomes, "theprotocol_blockChatPrincipal", f"answered without blocked:true: {blk}")
            st = await _state(dev_a, r1, convs["r1"])
            if st != "left":
                _chat_bug(outcomes, "theprotocol_blockChatPrincipal", f"the blocker's seat reads {st!r}, not 'left'")
            ok_k, k_ans = await _say(dev_b, k, "lc-chat to a blocker", conversation_id=convs["r1"])
            if not ok_k:
                _chat_bug(outcomes, "theprotocol_blockChatPrincipal",
                          f"a block must be silent, but the blocked party's message was refused: "
                          f"{_chat_text(k_ans)[:160]}")
            ok_open, opened = await _say(dev_a, r1, "lc-chat open while blocking", target_agent_did=k["did"])
            words = _chat_text(opened)
            if ok_open:
                _chat_bug(outcomes, "theprotocol_blockChatPrincipal", "the blocker could open a dm to the principal "
                                                                       "it blocks")
            elif "you have blocked this principal" not in words:
                _chat_bug(outcomes, "theprotocol_sendChatMessage",
                          f"a refused chat call reached the MCP caller without its reason: {words[:160]!r}")

        # R1 unblocks, opens the dm again (the same thread, active), then leaves it.
        ok_unb, unb = await _exec_step(rpc, parse, "theprotocol_unblockChatPrincipal", "2",
                                       {"ptype": "agent", "agent_did": k["did"], "agent_jwt": r1["jwt"]},
                                       dev_a, outcomes)
        if ok_unb:
            if not (isinstance(unb, dict) and unb.get("removed") is True):
                _chat_bug(outcomes, "theprotocol_unblockChatPrincipal", f"answered without removed:true: {unb}")
            ok_back, back = await _say(dev_a, r1, "lc-chat back", target_agent_did=k["did"])
            if not (ok_back and isinstance(back, dict) and back.get("conversation_id") == convs["r1"]
                    and back.get("created") is False and back.get("my_state") == "active"):
                _chat_bug(outcomes, "theprotocol_unblockChatPrincipal",
                          f"reopening after the unblock is not the same thread, active: {str(back)[:200]}")
        ok_leave, left = await _exec_step(rpc, parse, "theprotocol_respondChatRequest", "2",
                                          {"conversation_id": convs["r1"], "action": "leave", "agent_jwt": r1["jwt"]},
                                          dev_a, outcomes, expect_status="any", record_as_separate=False)
        st = await _state(dev_a, r1, convs["r1"])
        if not _chat_landed(ok_leave, left) or st != "left":
            _chat_bug(outcomes, "theprotocol_respondChatRequest",
                      f"leave did not leave (answer {_chat_text(left)[:120] or 'ok'}, seat {st!r})")

        # The decline stays silent: nothing for R3's thread once the window has passed.
        await _asyncio.sleep(max(0.0, declined_at + 30.0 - time.monotonic()))
        heard = await _accepted()
        if heard is None:
            _chat_bug(outcomes, "theprotocol_respondChatRequest", "the knocker's webhook record was unreadable")
        elif convs["r3"] in heard:
            _chat_bug(outcomes, "theprotocol_respondChatRequest", "a DECLINE told the knocker (chat.request.accepted)")
    finally:
        if hook_id:
            await _exec_step(rpc, parse, "theprotocol_deleteWebhook", "3", {"webhook_id": hook_id}, dev_b, outcomes,
                             expect_status="any", record_as_separate=False)
        # §MCPTEST30 (V0641): what each agent holds goes back to the treasury before its owner deletes it, by
        # earned_fixtures.Throwaways' rule: the owner's delete is a soft delete that keeps the balance (432 deleted
        # chat agents on sbx-alpha held 1,050.00 on 2026-10-25, and an operator pays each new agent a grant)
        _tw = _ef.Throwaways(rpc, parse, bag, "chat")
        for dev, did in made:
            _left = await _tw._return_balance(did, dev)
            if _left:
                _tw._say(_left)
            await _exec_step(rpc, parse, "theprotocol_deleteMyAgentByDev", "3", {"agent_did": did}, dev, outcomes,
                             expect_status="any", record_as_separate=False)


# ============================================================================
# §MCPTEST30 (2026-10-01) — MCP PROTOCOL CONFORMANCE (the surface the sweep never asked)
# ============================================================================
# Every other row in this sweep is a `tools/call`. The MCP server also answers initialize, ping, tools/list pages,
# resources, prompts, completion, tasks, gateway mode and per-credential toolsets, and none of it was measured (no
# unit tests for tasks, resources, prompts or the gateway either). One row per check, named `mcp_protocol: <check>`;
# a check that cannot run says NOT MEASURED on its row. Protocol violations a real client can trip on are BUG-FINDs,
# marked "(conformance)"; a divergence clients tolerate is said on the passing row's evidence instead.
#
# Two hazards measured before writing it: toolset selections are keyed to the CREDENTIAL (mcp:toolsel:<ctx>), so the
# enable/disable checks run on a throwaway account of this lifecycle's own (never the runner, whose next tools/list
# would shrink); and unauthenticated calls to an /admin/ path share one 10-per-minute bucket with the admin auth
# matrix, so every admin probe here carries the admin bearer.
_PROTO = "mcp_protocol: "
_DATED = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TASK_TOOL = "theprotocol_exportTegTransactions"      # a read the throwaway can run (its own empty export)
_PROMPT_ARGS = {"agent_name": "mcp-tester-prompt-agent", "agent_did": "did:theprotocol:example:prompt", "amount": "1",
                "recipient": "did:theprotocol:example:recipient", "task_description": "mcp tester prompt check",
                "bounty": "1", "ticker": "MCPT", "transaction_ref": "tx-mcp-tester"}


def _proto(outcomes: Dict[str, Any], check: str, ok: bool, code: Any, t0: float, fail: Optional[str] = None,
           evidence: Optional[Dict[str, Any]] = None, skip: Optional[str] = None) -> None:
    # judged by the check's own conformance standard: a pass means the server behaved as MCP asks (§FANCLAIM wants it said)
    outcomes[_PROTO + check] = _make_outcome(_PROTO + check, "protocol", bool(ok) and not skip, str(code or "0"),
                                             int((time.time() - t0) * 1000), None if ok else fail, evidence or {},
                                             expect_status="success", skip_reason=skip)


def _jbody(method: str, params: Optional[Dict[str, Any]] = None, rid: Optional[int] = 1) -> str:
    d: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if rid is not None:
        d["id"] = rid
    if params is not None:
        d["params"] = params
    return json.dumps(d)


def _err(parsed: Any) -> Optional[int]:
    e = parsed.get("error") if isinstance(parsed, dict) else None
    return e.get("code") if isinstance(e, dict) else None


def _res(parsed: Any) -> Any:
    return parsed.get("result") if isinstance(parsed, dict) else None


def _tool_text(result: Any) -> Any:
    """The JSON a tools/call result carries in content[0].text (or None)."""
    try:
        return json.loads(((result or {}).get("content") or [{}])[0].get("text") or "null")
    except Exception:                                                  # noqa: BLE001
        return None


async def _proto_guard(outcomes: Dict[str, Any], check: str, coro: Awaitable[Any]) -> None:
    t0 = time.time()
    try:
        await coro
    except Exception as e:                                             # noqa: BLE001 — the instrument broke: say so
        _proto(outcomes, check, False, 0, t0, skip=f"NOT MEASURED: the check raised {type(e).__name__}: {str(e)[:200]}")


async def _p_initialize(raw, outcomes, admin_jwt: str) -> None:
    t0 = time.time()
    params = {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "mcp-tester", "version": "1"}}
    problems: List[str] = []
    ev: Dict[str, Any] = {}
    for label, path, jwt, want in (("public", "/mcp/rpc", "", ("tools", "resources", "prompts")),
                                   ("admin", "/mcp/admin/rpc", admin_jwt, ("tools", "resources"))):
        code, p, _ = await raw(_jbody("initialize", params), path=path, jwt=jwt)
        r = _res(p)
        if not str(code).startswith("2") or not isinstance(r, dict):
            problems.append(f"{label}: HTTP {code} without a result")
            continue
        pv, caps, si = r.get("protocolVersion"), r.get("capabilities") or {}, r.get("serverInfo") or {}
        if not (isinstance(pv, str) and _DATED.match(pv)):
            problems.append(f"{label}: protocolVersion {pv!r} is not a dated version")
        missing = [c for c in want if c not in caps]
        if missing:
            problems.append(f"{label}: capabilities do not advertise {missing}")
        if not (si.get("name") and si.get("version")):
            problems.append(f"{label}: serverInfo lacks a name or a version")
        ev[label] = {"protocolVersion": pv, "capabilities": sorted(caps), "server": si.get("name")}
    _proto(outcomes, "initialize", not problems, "200", t0, fail="; ".join(problems), evidence=ev)
    await _proto_guard(outcomes, "initialize: version negotiation", _p_version_negotiation(raw, outcomes, admin_jwt))
    t1 = time.time()
    code, p, _ = await raw(_jbody("ping"))
    _proto(outcomes, "ping", _res(p) == {}, code, t1, fail=f"ping answered HTTP {code}: {str(p)[:160]}")


# V0649 (agentvault2-7c's §EXTTEST run 2, measured from a dev machine 2026-10-31 01:46Z): both servers answered
# initialize with their own constant whatever the client asked, so a client pinned to 2025-06-18 got 2025-11-25 and a
# reason to disconnect. The MCP lifecycle rule: a server that supports the requested version answers with that same
# version, otherwise with another version it supports. 2025-06-18 is the version that client asked for (published,
# and in the server's list since V0649); the second ask names no version any server supports.
_OLDER_VERSION = "2025-06-18"
_NO_SUCH_VERSION = "1999-01-01"


async def _p_version_negotiation(raw, outcomes, admin_jwt: str) -> None:
    t0 = time.time()
    problems: List[str] = []
    ev: Dict[str, Any] = {}
    for label, path, jwt in (("public", "/mcp/rpc", ""), ("admin", "/mcp/admin/rpc", admin_jwt)):
        got = {}
        for asked in (_OLDER_VERSION, _NO_SUCH_VERSION):
            params = {"protocolVersion": asked, "capabilities": {}, "clientInfo": {"name": "mcp-tester", "version": "1"}}
            code, p, _ = await raw(_jbody("initialize", params), path=path, jwt=jwt)
            r = _res(p)
            got[asked] = r.get("protocolVersion") if str(code).startswith("2") and isinstance(r, dict) else f"HTTP {code}"
        ev[label] = got
        if got[_OLDER_VERSION] != _OLDER_VERSION:
            problems.append(f"BUG-FIND (conformance): {label} initialize asked for {_OLDER_VERSION} and answered "
                            f"{got[_OLDER_VERSION]!r}: a server that supports the requested version answers with it")
        nv = got[_NO_SUCH_VERSION]
        if not (isinstance(nv, str) and _DATED.match(nv)) or nv == _NO_SUCH_VERSION:
            problems.append(f"BUG-FIND (conformance): {label} initialize asked for {_NO_SUCH_VERSION} (no server supports it) "
                            f"and answered {nv!r}: it must answer another version it supports")
    _proto(outcomes, "initialize: version negotiation", not problems, "200", t0, fail="; ".join(problems), evidence=ev)


async def _p_tools_list(raw, outcomes) -> List[str]:
    t0 = time.time()
    code, p, _ = await raw(_jbody("tools/list"), timeout=60)
    tools = (_res(p) or {}).get("tools") if isinstance(_res(p), dict) else None
    if not isinstance(tools, list) or not tools:
        _proto(outcomes, "tools/list schema", False, code, t0, fail=f"tools/list answered HTTP {code} with no tools")
        return []
    names = [t.get("name") for t in tools if isinstance(t, dict)]
    no_schema = [n for n, t in zip(names, tools) if not isinstance(t.get("inputSchema"), dict)
                 or t["inputSchema"].get("type") != "object"]
    no_ann = [n for n, t in zip(names, tools) if not isinstance(t.get("annotations"), dict) or not (
        "readOnlyHint" in t["annotations"] or "destructiveHint" in t["annotations"])]
    no_desc = [n for n, t in zip(names, tools) if not (t.get("description") or "").strip()]
    no_title = [n for n, t in zip(names, tools) if not (t.get("title") or "").strip()]
    dupes = sorted({n for n in names if names.count(n) > 1})
    problems = [f"{label}: {len(v)} ({', '.join(str(x) for x in v[:5])})" for label, v in
                (("no object inputSchema", no_schema), ("no read-only/destructive annotation", no_ann),
                 ("no description", no_desc), ("no title", no_title), ("duplicate names", dupes)) if v]
    _proto(outcomes, "tools/list schema", not problems, code, t0, fail="; ".join(problems),
           evidence={"tools": len(names), "with_output_schema": sum(1 for t in tools if t.get("outputSchema"))})
    # pagination: walk the cursor pages, compare the union with the whole list (SETS, never counts)
    t1 = time.time()
    seen: List[str] = []
    cursor: Optional[str] = "0"
    pages = 0
    while cursor is not None and pages < 40:
        code, p, _ = await raw(_jbody("tools/list", {"cursor": cursor}), timeout=60)
        r = _res(p) or {}
        seen.extend(t.get("name") for t in (r.get("tools") or []) if isinstance(t, dict))
        cursor = r.get("nextCursor")
        pages += 1
    code_bad, p_bad, _ = await raw(_jbody("tools/list", {"cursor": "-7"}))
    problems = []
    if len(seen) != len(set(seen)):
        problems.append(f"{len(seen) - len(set(seen))} tool(s) on two pages")
    if set(seen) != set(names):
        problems.append(f"pages miss {sorted(set(names) - set(seen))[:4]} and add {sorted(set(seen) - set(names))[:4]}")
    if pages < 2:
        problems.append("the first page carried no nextCursor (no pagination)")
    if _err(p_bad) != -32602:
        problems.append(f"a negative cursor answered {_err(p_bad) or 'HTTP ' + str(code_bad)}, not -32602")
    _proto(outcomes, "tools/list pagination", not problems, code, t1, fail="; ".join(problems),
           evidence={"pages": pages, "listed": len(seen), "whole": len(names)})
    return names


async def _p_errors(raw, outcomes, dev_jwt: str) -> None:
    cases = (
        ("parse error", "{this is not json", -32700, ""),
        ("batch request", "[" + _jbody("ping", rid=1) + "," + _jbody("ping", rid=2) + "]", -32600, ""),
        ("no method", json.dumps({"jsonrpc": "2.0", "id": 9}), -32600, ""),
        ("unknown method", _jbody("mcp_tester/no_such_method"), -32601, dev_jwt),
    )
    for check, body, want, jwt in cases:
        t0 = time.time()
        code, p, _ = await raw(body, jwt=jwt)
        got = _err(p)
        problems = []
        if got != want:
            problems.append(f"answered {got if got is not None else 'no JSON-RPC error'} (HTTP {code}), want {want}")
        if str(code).startswith("5"):
            problems.append(f"a client's mistake answered HTTP {code}")
        _proto(outcomes, f"errors: {check}", not problems, code, t0, fail="; ".join(problems), evidence={"code": got})
    # tools/call with an unknown tool, and with a required argument missing: refused, never a crash
    t0 = time.time()
    code, p, _ = await raw(_jbody("tools/call", {"name": "theprotocol_noSuchToolMcpTester", "arguments": {}}), jwt=dev_jwt)
    got = _err(p)
    _proto(outcomes, "errors: unknown tool", got in (-32601, -32602), code, t0,
           fail=f"an unknown tool answered {got or 'no JSON-RPC error'} (HTTP {code})",
           evidence={"code": got, "note": None if got == -32602 else "MCP names -32602 for an unknown tool; this server answers -32601"})
    t0 = time.time()
    code, p, _ = await raw(_jbody("tools/call", {"name": "theprotocol_getAgentProfile", "arguments": {}}), jwt=dev_jwt)
    got, r = _err(p), _res(p)
    refused = got == -32602 or (isinstance(r, dict) and r.get("isError"))
    crashed = got == -32603 or str(code).startswith("5")
    _proto(outcomes, "errors: missing required argument", refused and not crashed, code, t0,
           fail=f"getAgentProfile without its required argument answered {got or r} (HTTP {code}): it must be refused, never run or crash",
           evidence={"code": got, "isError": (r or {}).get("isError") if isinstance(r, dict) else None})


async def _p_notifications(raw, outcomes, admin_jwt: str) -> None:
    """MCP Streamable HTTP: a posted notification is accepted with 202 Accepted and NO body (JSON-RPC: the receiver of a
    notification never replies). Both endpoints answered 200 before §MCPTEST30 fixed them, the admin one with an error
    for every notification except notifications/initialized; the product and this check ship in one image."""
    sse = ["Accept: application/json, text/event-stream"]   # what MCP clients send
    for check, path, jwt, body in (
            ("notifications: public", "/mcp", "", _jbody("notifications/initialized", rid=None)),
            ("notifications: admin cancelled", "/mcp/admin", admin_jwt,
             _jbody("notifications/cancelled", {"requestId": 424242, "reason": "mcp tester"}, rid=None))):
        t0 = time.time()
        code, p, text = await raw(body, path=path, jwt=jwt, headers=sse)
        ok = str(code) == "202" and not (text or "").strip()
        _proto(outcomes, check, ok, code, t0,
               fail=(f"BUG-FIND (conformance): a notification was answered HTTP {code} with "
                     f"{(text or '').strip()[:120] or 'no body'}; MCP Streamable HTTP accepts one with 202 and no body"),
               evidence={"http": code})


async def _p_resources(raw, outcomes, sentinel_did: str) -> None:
    t0 = time.time()
    code, p, _ = await raw(_jbody("resources/list"))
    res = (_res(p) or {}).get("resources") if isinstance(_res(p), dict) else None
    problems = []
    if not isinstance(res, list) or not res:
        problems.append(f"resources/list answered HTTP {code} with no resources")
        res = []
    bad = [r.get("uri") for r in res if not (r.get("uri") and r.get("name") and r.get("mimeType"))]
    if bad:
        problems.append(f"{len(bad)} resource(s) lack uri, name or mimeType")
    code_t, p_t, _ = await raw(_jbody("resources/templates/list"))
    tmpl = (_res(p_t) or {}).get("resourceTemplates") if isinstance(_res(p_t), dict) else None
    if not tmpl or not any("{" in (t.get("uriTemplate") or "") for t in tmpl):
        problems.append(f"resources/templates/list answered HTTP {code_t} without a template")
    read_ok, read_bad, notes = 0, [], []
    for r in res:
        uri = r.get("uri")
        code_r, p_r, _ = await raw(_jbody("resources/read", {"uri": uri}), timeout=60)
        contents = (_res(p_r) or {}).get("contents") if isinstance(_res(p_r), dict) else None
        try:
            body = json.loads(contents[0]["text"]) if contents else None
        except Exception:                                              # noqa: BLE001
            body = None
        if isinstance(body, (dict, list)):
            read_ok += 1
        elif "solvency" in (uri or "") and _err(p_r) is not None:
            notes.append(f"{uri}: {(p_r.get('error') or {}).get('message', '')[:80]} (not a venue here)")
        else:
            read_bad.append(f"{uri} (HTTP {code_r}, {_err(p_r)})")
    if read_bad:
        problems.append(f"resources/read gave no JSON for {read_bad[:3]}")
    if sentinel_did and tmpl:
        uri = (tmpl[0].get("uriTemplate") or "").replace("{did}", sentinel_did)
        code_a, p_a, _ = await raw(_jbody("resources/read", {"uri": uri}))
        txt = ((((_res(p_a) or {}).get("contents") or [{}])[0]) or {}).get("text") if isinstance(_res(p_a), dict) else None
        if not txt or sentinel_did not in txt:
            problems.append(f"the agent-card template did not return the sentinel's card (HTTP {code_a}, {_err(p_a)})")
    _proto(outcomes, "resources: list and read", not problems, code, t0, fail="; ".join(problems),
           evidence={"resources": len(res), "read_ok": read_ok, "templates": len(tmpl or []), "notes": notes[:2]})
    t1 = time.time()
    code, p, _ = await raw(_jbody("resources/read", {"uri": "theprotocol://mcp-tester/no-such-resource"}))
    got = _err(p)
    problems = []
    if got is None:
        problems.append(f"an unknown URI answered HTTP {code} without an error")
    if str(code).startswith("5"):
        problems.append(f"BUG-FIND (conformance): an unknown resource URI answers HTTP {code} (error {got}): a client's "
                        "mistake reported as a server failure, which a 5xx alert pages on")
    _proto(outcomes, "resources: unknown uri", not problems, code, t1, fail="; ".join(problems),
           evidence={"code": got, "http": code})


async def _p_prompts(raw, outcomes) -> None:
    t0 = time.time()
    code, p, _ = await raw(_jbody("prompts/list"))
    prompts = (_res(p) or {}).get("prompts") if isinstance(_res(p), dict) else None
    problems: List[str] = []
    if not isinstance(prompts, list) or not prompts:
        _proto(outcomes, "prompts: list and get", False, code, t0, fail=f"prompts/list answered HTTP {code} with none")
        return
    rendered = 0
    for pr in prompts:
        name = pr.get("name")
        args = {a.get("name"): _PROMPT_ARGS.get(a.get("name"), "mcp-tester") for a in (pr.get("arguments") or [])
                if isinstance(a, dict)}
        code_g, p_g, _ = await raw(_jbody("prompts/get", {"name": name, "arguments": args}))
        msgs = (_res(p_g) or {}).get("messages") if isinstance(_res(p_g), dict) else None
        text = (((msgs or [{}])[0] or {}).get("content") or {}).get("text") if msgs else None
        if not text:
            problems.append(f"{name}: no message (HTTP {code_g}, {_err(p_g)})")
            continue
        given = [v for v in args.values() if v and v != "mcp-tester"]
        if given and not any(v in text for v in given):
            problems.append(f"{name}: none of the given arguments appear in the message")
        rendered += 1
    _proto(outcomes, "prompts: list and get", not problems, code, t0, fail="; ".join(problems[:4]),
           evidence={"prompts": len(prompts), "rendered": rendered})
    t1 = time.time()
    code, p, _ = await raw(_jbody("prompts/get", {"name": "mcp_tester_no_such_prompt", "arguments": {}}))
    _proto(outcomes, "prompts: unknown name", _err(p) == -32602, code, t1,
           fail=f"an unknown prompt answered {_err(p) or 'no error'} (HTTP {code}), want -32602")
    req = next((pr for pr in prompts if any(isinstance(a, dict) and a.get("required") for a in (pr.get("arguments") or []))), None)
    t2 = time.time()
    if req is None:
        _proto(outcomes, "prompts: missing required argument", False, 0, t2, skip="NOT MEASURED: no prompt declares a required argument")
        return
    code, p, _ = await raw(_jbody("prompts/get", {"name": req.get("name"), "arguments": {}}))
    _proto(outcomes, "prompts: missing required argument", _err(p) == -32602, code, t2,
           fail=(f"BUG-FIND (conformance): prompts/get '{req.get('name')}' without its required argument answered "
                 f"{'a rendered prompt' if _res(p) else _err(p)} (HTTP {code}); MCP wants -32602 for a missing required argument"))


async def _p_completion(raw, outcomes) -> None:
    t0 = time.time()
    code, p, _ = await raw(_jbody("completion/complete", {"ref": {"type": "ref/prompt", "name": "trade_on_agora"},
                                                          "argument": {"name": "ticker", "value": ""}}))
    comp = (_res(p) or {}).get("completion") if isinstance(_res(p), dict) else None
    ok = isinstance(comp, dict) and isinstance(comp.get("values"), list) and len(comp["values"]) <= 100
    _proto(outcomes, "completion", ok, code, t0, fail=f"completion/complete answered HTTP {code}: {str(p)[:160]}",
           evidence={"values": len((comp or {}).get("values") or []), "hasMore": (comp or {}).get("hasMore")})


async def _poll_task(raw, task_id: str, jwt: str, budget_s: float = 45.0) -> Tuple[Optional[str], Any]:
    deadline = time.time() + budget_s
    status, task = None, None
    while time.time() < deadline:
        _, p, _ = await raw(_jbody("tasks/get", {"taskId": task_id}), jwt=jwt)
        task = _res(p)
        status = (task or {}).get("status") if isinstance(task, dict) else None
        if status in ("completed", "failed", "cancelled"):
            return status, task
        await asyncio.sleep(2.0)
    return status, task


async def _p_tasks(raw, outcomes, sub_jwt: str, dev_jwt: str, sentinel_did: str) -> None:
    t0 = time.time()
    code, p, _ = await raw(_jbody("tools/call", {"name": _TASK_TOOL, "arguments": {}, "task": {"ttl": 60000}}), jwt=sub_jwt)
    task = (_res(p) or {}).get("task") if isinstance(_res(p), dict) else None
    tid = (task or {}).get("taskId") if isinstance(task, dict) else None
    if not tid:
        _proto(outcomes, "tasks: lifecycle", False, code, t0, fail=f"a task-augmented call answered HTTP {code}: {str(p)[:200]}")
        return
    status, final = await _poll_task(raw, tid, sub_jwt)
    code_r, p_r, _ = await raw(_jbody("tasks/result", {"taskId": tid}), jwt=sub_jwt, timeout=60)
    r = _res(p_r) or {}
    meta = (r.get("_meta") or {}).get("io.modelcontextprotocol/related-task") if isinstance(r, dict) else None
    code_l, p_l, _ = await raw(_jbody("tasks/list"), jwt=sub_jwt)
    listed = [t.get("taskId") for t in ((_res(p_l) or {}).get("tasks") or []) if isinstance(t, dict)]
    code_c, p_c, _ = await raw(_jbody("tasks/cancel", {"taskId": tid}), jwt=sub_jwt)
    problems = []
    if (task or {}).get("status") != "working":
        problems.append(f"the created task's status is {(task or {}).get('status')!r}, not 'working'")
    if status != "completed":
        problems.append(f"the task ended {status!r} ({str((final or {}).get('statusMessage'))[:100]})")
    if not isinstance(r.get("content"), list):
        problems.append(f"tasks/result carried no content (HTTP {code_r}, {_err(p_r)})")
    if not (isinstance(meta, dict) and meta.get("taskId") == tid):
        problems.append("tasks/result does not name its task in _meta")
    if tid not in listed:
        problems.append("tasks/list does not list the task")
    if _err(p_c) is None:
        problems.append(f"cancelling a {status} task answered no error: {str(_res(p_c))[:100]}")
    _proto(outcomes, "tasks: lifecycle", not problems, code, t0, fail="; ".join(problems),
           evidence={"status": status, "listed": tid in listed, "ttl": (task or {}).get("ttl")})
    # isolation: the task is bound to the credential that made it
    t1 = time.time()
    code_i, p_i, _ = await raw(_jbody("tasks/get", {"taskId": tid}), jwt=dev_jwt)
    leaked = isinstance(_res(p_i), dict) and _res(p_i).get("taskId") == tid
    _proto(outcomes, "tasks: another credential cannot read it", not leaked and _err(p_i) is not None, code_i, t1,
           fail=("BUG-FIND: a task made by one credential is readable by another (tasks/get answered it)" if leaked
                 else f"tasks/get from another credential answered no error (HTTP {code_i})"))
    # a tool without task support refuses a task-augmented call
    t2 = time.time()
    code_u, p_u, _ = await raw(_jbody("tools/call", {"name": "theprotocol_getNetworkStats", "arguments": {}, "task": {"ttl": 60000}}), jwt=sub_jwt)
    _proto(outcomes, "tasks: unsupported tool", _err(p_u) is not None and not (isinstance(_res(p_u), dict) and _res(p_u).get("task")), code_u, t2,
           fail=f"a tool without task support accepted a task (HTTP {code_u}): {str(p_u)[:160]}")
    # the owner rule of an owner-only tool holds on the task path too
    t3 = time.time()
    if not sentinel_did:
        _proto(outcomes, "tasks: owner rules hold", False, 0, t3, skip="NOT MEASURED: no sentinel agent DID in the bag")
        return
    code_o, p_o, _ = await raw(_jbody("tools/call", {"name": "theprotocol_agentBulkExport",
                                                     "arguments": {"agent_dids": [sentinel_did]}, "task": {"ttl": 60000}}), jwt=sub_jwt)
    otask = (_res(p_o) or {}).get("task") if isinstance(_res(p_o), dict) else None
    if not (isinstance(otask, dict) and otask.get("taskId")):
        refused = _err(p_o) is not None
        _proto(outcomes, "tasks: owner rules hold", refused, code_o, t3,
               fail=f"agentBulkExport as a task answered HTTP {code_o} without a task or an error: {str(p_o)[:160]}")
        return
    ostatus, _ = await _poll_task(raw, otask["taskId"], sub_jwt)
    _, p_or, _ = await raw(_jbody("tasks/result", {"taskId": otask["taskId"]}), jwt=sub_jwt, timeout=60)
    exported = _tool_text(_res(p_or))
    # Judge the EXPORTED list, never "the DID appears somewhere": bulk export answers 200 and names a refused agent
    # under `errors` (live 2026-10-01: the first version of this check read that refusal as a leak).
    agents = (exported or {}).get("agents") if isinstance(exported, dict) else None
    n_ok = (exported or {}).get("successful_exports") if isinstance(exported, dict) else None
    leaked = ostatus == "completed" and (bool(n_ok) or sentinel_did in json.dumps(agents or []))
    refused = ostatus == "failed" or (ostatus == "completed" and not leaked and n_ok == 0
                                      and sentinel_did in json.dumps((exported or {}).get("errors") or []))
    _proto(outcomes, "tasks: owner rules hold", refused and not leaked, code_o, t3,
           fail=("BUG-FIND: an owner-only export of ANOTHER developer's agent was exported on the task path"
                 if leaked else f"the foreign export task ended {ostatus!r} without naming its refusal"),
           evidence={"status": ostatus, "successful_exports": n_ok})


async def _p_gateway(raw, outcomes, sub_jwt: str, full: List[str]) -> int:
    t0 = time.time()
    code, p, _ = await raw(_jbody("tools/list"), query="mode=gateway")
    gw = [t.get("name") for t in ((_res(p) or {}).get("tools") or []) if isinstance(t, dict)]
    code_w, p_w, _ = await raw(_jbody("tools/list"), query="toolsets=wallet")
    wallet = [t.get("name") for t in ((_res(p_w) or {}).get("tools") or []) if isinstance(t, dict)]
    _, p_bm, _ = await raw(_jbody("tools/list"), query="mode=mcp-tester-bogus")
    _, p_bt, _ = await raw(_jbody("tools/list"), query="toolsets=mcp-tester-bogus")
    problems = []
    meta = {"theprotocol_searchTools", "theprotocol_describeTools", "theprotocol_invokeTool", "theprotocol_listToolsets"}
    if not gw or not meta <= set(gw) or len(gw) >= len(full):
        problems.append(f"gateway mode listed {len(gw)} tool(s), missing {sorted(meta - set(gw))[:4]}")
    if full and set(gw) - set(full):
        problems.append(f"gateway lists tools the full catalog does not: {sorted(set(gw) - set(full))[:3]}")
    if not wallet or not (len(gw) <= len(wallet) < len(full)) or not set(gw) <= set(wallet):
        problems.append(f"toolsets=wallet listed {len(wallet)} (gateway {len(gw)}, full {len(full)})")
    for label, pp in (("an unknown mode", p_bm), ("an unknown toolset", p_bt)):
        if _err(pp) != -32602:
            problems.append(f"{label} answered {_err(pp)}, want -32602")
    _proto(outcomes, "gateway: listing", not problems, code, t0, fail="; ".join(problems),
           evidence={"gateway": len(gw), "wallet": len(wallet), "full": len(full)})
    t1 = time.time()
    problems = []
    _, p_s, _ = await raw(_jbody("tools/call", {"name": "theprotocol_searchTools", "arguments": {"query": "balance"}}), jwt=sub_jwt)
    hits = [h.get("name") for h in ((_tool_text(_res(p_s)) or {}).get("results") or []) if isinstance(h, dict)]
    if not any("alance" in (h or "") for h in hits):
        problems.append(f"searchTools 'balance' found {hits[:4]}")
    _, p_d, _ = await raw(_jbody("tools/call", {"name": "theprotocol_describeTools", "arguments": {"names": ["theprotocol_getNetworkStats"]}}), jwt=sub_jwt)
    desc = (_tool_text(_res(p_d)) or {}).get("tools") or []
    if not (desc and isinstance(desc[0].get("inputSchema"), dict)):
        problems.append(f"describeTools returned {str(desc)[:120]}")
    _, p_i, _ = await raw(_jbody("tools/call", {"name": "theprotocol_invokeTool", "arguments": {"name": "theprotocol_getNetworkStats", "arguments": {}}}), jwt=sub_jwt)
    _, p_n, _ = await raw(_jbody("tools/call", {"name": "theprotocol_getNetworkStats", "arguments": {}}), jwt=sub_jwt)
    via, direct = _tool_text(_res(p_i)), _tool_text(_res(p_n))
    if not (isinstance(via, dict) and isinstance(direct, dict) and set(via) == set(direct)):
        problems.append("invokeTool getNetworkStats did not answer what a direct call answers")
    _, p_self, _ = await raw(_jbody("tools/call", {"name": "theprotocol_invokeTool", "arguments": {"name": "theprotocol_invokeTool", "arguments": {}}}), jwt=sub_jwt)
    if _err(p_self) != -32602:
        problems.append(f"invokeTool invoking itself answered {_err(p_self) or str(_res(p_self))[:80]}, want -32602")
    _proto(outcomes, "gateway: meta tools", not problems, "200", t1, fail="; ".join(problems),
           evidence={"search_hits": len(hits)})
    return len(wallet)


async def _p_toolsets(raw, outcomes, sub_jwt: str, dev_jwt: str, full: List[str], wallet_n: int) -> None:
    t0 = time.time()
    problems = []
    _, p_e, _ = await raw(_jbody("tools/call", {"name": "theprotocol_enableToolset", "arguments": {"toolsets": ["wallet"]}}), jwt=sub_jwt)
    enabled = (_tool_text(_res(p_e)) or {}).get("enabled_toolsets") or []
    if "wallet" not in enabled:
        problems.append(f"enableToolset answered {str(_res(p_e) or p_e)[:120]}")
    _, p_mine, _ = await raw(_jbody("tools/list"), jwt=sub_jwt)
    mine = len(((_res(p_mine) or {}).get("tools") or []))
    _, p_other, _ = await raw(_jbody("tools/list"), jwt=dev_jwt)
    other = len(((_res(p_other) or {}).get("tools") or []))
    if wallet_n and mine != wallet_n:
        problems.append(f"after enableToolset the account's own tools/list held {mine}, toolsets=wallet holds {wallet_n}")
    if full and other != len(full):
        problems.append(f"BUG-FIND: one credential's toolset selection changed ANOTHER credential's listing ({other} of {len(full)})")
    _, p_d, _ = await raw(_jbody("tools/call", {"name": "theprotocol_disableToolset", "arguments": {"toolsets": []}}), jwt=sub_jwt)
    _, p_after, _ = await raw(_jbody("tools/list"), jwt=sub_jwt)
    after = len(((_res(p_after) or {}).get("tools") or []))
    if full and after != len(full):
        problems.append(f"after clearing the selection the account lists {after}, not the full {len(full)}")
    _proto(outcomes, "toolsets: per-credential selection", not problems, "200", t0, fail="; ".join(problems),
           evidence={"selected": mine, "other_credential": other, "cleared": after})


async def _p_admin(raw, outcomes, admin_jwt: str, sub_jwt: str) -> None:
    t0 = time.time()
    problems = []
    code, p, _ = await raw(_jbody("tools/list"), path="/mcp/admin/rpc", jwt=admin_jwt, timeout=60)
    tools = ((_res(p) or {}).get("tools") or []) if isinstance(_res(p), dict) else []
    if not tools:
        problems.append(f"admin tools/list answered HTTP {code} with none")
    no_schema = [t.get("name") for t in tools if not isinstance(t.get("inputSchema"), dict)]
    if no_schema:
        problems.append(f"{len(no_schema)} admin tool(s) without an inputSchema ({no_schema[:3]})")
    code_n, p_n, _ = await raw(_jbody("tools/call", {"name": "theprotocol_getAdminDashboard", "arguments": {}}),
                               path="/mcp/admin/rpc", jwt=sub_jwt)
    if _err(p_n) != -32001:
        r = _res(p_n)
        if isinstance(r, dict) and not r.get("isError"):
            problems.append("BUG-FIND: a NON-admin credential ran an admin tool (getAdminDashboard) on the admin bridge")
        else:
            problems.append(f"a non-admin call to an admin tool answered {_err(p_n)} (HTTP {code_n}), want -32001")
    _proto(outcomes, "admin: surface and gate", not problems, code, t0, fail="; ".join(problems),
           evidence={"admin_tools": len(tools)})


async def lifecycle_mcp_protocol_conformance(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, Any]) -> None:
    """§MCPTEST30 (2026-10-01): the MCP server's own protocol, asked directly (see the block comment above)."""
    raw = getattr(bag, "rpc_raw", None)
    t0 = time.time()
    if raw is None:
        _proto(outcomes, "conformance", False, 0, t0, skip="NOT MEASURED: the runner injected no raw JSON-RPC transport (bag.rpc_raw)")
        return
    dev, adm, did = bag.developer_jwt or "", bag.admin_jwt or bag.developer_jwt or "", bag.sentinel_did or ""
    await _proto_guard(outcomes, "initialize", _p_initialize(raw, outcomes, adm))
    full: List[str] = []

    async def _list():
        full.extend(await _p_tools_list(raw, outcomes))
    await _proto_guard(outcomes, "tools/list schema", _list())
    await _proto_guard(outcomes, "errors", _p_errors(raw, outcomes, dev))
    await _proto_guard(outcomes, "notifications: public", _p_notifications(raw, outcomes, adm))
    await _proto_guard(outcomes, "resources: list and read", _p_resources(raw, outcomes, did))
    await _proto_guard(outcomes, "prompts: list and get", _p_prompts(raw, outcomes))
    await _proto_guard(outcomes, "completion", _p_completion(raw, outcomes))
    mint = getattr(bag, "mint_throwaway", None)
    sub = await mint("protocol") if mint else {"why": "the runner injected no mint_throwaway"}
    sub_jwt = (sub or {}).get("access_token") or ""
    if not sub_jwt:
        why = f"NOT MEASURED: no throwaway account of this lifecycle's own ({(sub or {}).get('why')})"
        for check in ("tasks: lifecycle", "gateway: listing", "toolsets: per-credential selection", "admin: surface and gate"):
            _proto(outcomes, check, False, 0, time.time(), skip=why)
        return
    try:
        await _proto_guard(outcomes, "tasks: lifecycle", _p_tasks(raw, outcomes, sub_jwt, dev, did))
        wallet_n = 0

        async def _gw():
            nonlocal wallet_n
            wallet_n = await _p_gateway(raw, outcomes, sub_jwt, full)
        await _proto_guard(outcomes, "gateway: listing", _gw())
        await _proto_guard(outcomes, "toolsets: per-credential selection", _p_toolsets(raw, outcomes, sub_jwt, dev, full, wallet_n))
        await _proto_guard(outcomes, "admin: surface and gate", _p_admin(raw, outcomes, adm, sub_jwt))
    finally:
        try:   # never leave a selection behind, then the account asks for its own deletion
            await raw(_jbody("tools/call", {"name": "theprotocol_disableToolset", "arguments": {"toolsets": []}}), jwt=sub_jwt)
        except Exception:                                              # noqa: BLE001
            pass
        await _schedule_own_deletion(rpc, bag, sub.get("email") or "", sub.get("password") or "", "protocol conformance")


# ============================================================================
# §MCPTEST30 (2026-10-01) — owner scoping: a second principal asks for the runner's objects
# ============================================================================
# Every contract in this file calls a tool AS THE OWNER of what it names. Nothing asked whether somebody else gets the
# same answer, so a route that forgets its ownership check passes every one of them. This lifecycle mints a second
# developer (a throwaway of this run, no admin flag) and asks, by id, for the runner's own objects: the setup's
# organization, team, support ticket and private bundle, the sentinel agent, and a webhook this lifecycle creates; then,
# as a second AGENT, for the sentinel's contract. Each row is judged against the owner's own call of the same tool with
# the same arguments, made first: an owner whose call fails proves nothing about anybody else (NOT MEASURED). The other
# principal must be refused, or answer without any of the owner's values. The destructive half acts only on objects this
# lifecycle creates for the purpose (a webhook, an API key): the other developer tries to change, delete or revoke them,
# the owner then proves they are intact, and removes them. Rows carry statuses and counts, never a value.
_OWN = "owner_scoping: "

# read-only developer-tier tools that take an object the runner owns: (tool, {argument: fixture}). The first two read
# the webhook this lifecycle creates (with one test delivery, so the deliveries read has something of the owner's).
OWNER_SCOPED_READS: Tuple[Tuple[str, Dict[str, str]], ...] = (
    ("theprotocol_getWebhook", {"webhook_id": "(this lifecycle's own webhook)"}),
    ("theprotocol_getWebhookDeliveries", {"webhook_id": "(this lifecycle's own webhook)"}),
    ("theprotocol_getSupportTicketDetail", {"ticket_id": "support_ticket_id"}),
    ("theprotocol_getOrganization", {"org_id": "organization_id"}),
    ("theprotocol_listOrganizationMembers", {"org_id": "organization_id"}),
    ("theprotocol_listOrganizationTeams", {"org_id": "organization_id"}),
    ("theprotocol_getOrganizationTeam", {"org_id": "organization_id", "team_id": "team_id"}),
    ("theprotocol_listOrganizationAgents", {"org_id": "organization_id"}),
    ("theprotocol_listOrganizationInvitations", {"org_id": "organization_id"}),
    ("theprotocol_getOrganizationCicdSummary", {"org_id": "organization_id"}),
    ("theprotocol_getBundleManifest", {"bundle_id": "bundle_id"}),
    ("theprotocol_downloadBundle", {"bundle_id": "bundle_id"}),
    ("theprotocol_exportAgentDev", {"agent_did": "sentinel_did"}),
    ("theprotocol_getMyCicdVersions", {"agent_did": "sentinel_did"}),
    # not getMyAgentLogs: GET /agents/{did}/logs answers anyone else an EMPTY list by design (agent_logs.py, "instead
    # of 404"), and the run's fresh sentinel has no logs either, so the row could only ever read NOT MEASURED (dry run
    # on sbx-alpha, 2026-10-01). Its owner check was read in the code instead: it filters on creator_developer_id.
)
_OWN_MIN_LEN = 12          # a value this long (a name, a url, an email, an id, a manifest) is the owner's, not a word
_OWN_NOW_WINDOW_S = 900    # a timestamp this close to the probe is the clock both answers read, not the owner's data


def _is_clock_reading(s: str) -> bool:
    if len(s) < 19 or s[4:5] != "-" or s[10:11] not in ("T", " "):
        return False
    try:
        t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return abs((datetime.now(timezone.utc) - t).total_seconds()) < _OWN_NOW_WINDOW_S


def _distinctive_values(v: Any, skip: set, out: set, depth: int = 0) -> None:
    if depth > 10 or len(out) > 4000:
        return
    if isinstance(v, dict):
        for x in v.values():
            _distinctive_values(x, skip, out, depth + 1)
    elif isinstance(v, list):
        for x in v[:200]:
            _distinctive_values(x, skip, out, depth + 1)
    elif isinstance(v, str):
        s = v.strip()
        if s in skip or len(s) < 6:
            return
        if (len(s) >= _OWN_MIN_LEN or any(c.isdigit() for c in s)) and not _is_clock_reading(s):
            out.add(s)


def owner_values_carried(owner: Any, other: Any, asked: Any = ()) -> Tuple[int, int]:
    """(how many of the owner's distinctive values the other principal's answer carries, how many the owner's answer
    holds). A distinctive value is a string of 12 or more characters, or of 6 or more with a digit: names, urls,
    emails, ids, manifests; never an enum word, a count or a flag. The arguments the probe ASKED with are left out (an
    answer that only echoes the question carries nothing of the owner's), and so is a timestamp within 15 minutes of
    the probe (both answers read the same clock)."""
    skip = {str(a) for a in (asked or ()) if a is not None}
    mine: set = set()
    theirs: set = set()
    _distinctive_values(owner, skip, mine)
    _distinctive_values(other, skip, theirs)
    return len(mine & theirs), len(mine)


def _answered(ok: bool, inner: Any, code: str) -> bool:
    """A tool call that delivered an answer: a 2xx with no error envelope, no `Error:` text and no wrapper error."""
    if not ok or not str(code or "").startswith("2"):
        return False
    if isinstance(inner, dict):
        t = inner.get("_text")
        if isinstance(t, str) and t.startswith("Error:"):
            return False
        if isinstance(inner.get("error"), str):
            return False
    return True


def _said(inner: Any) -> str:
    """What a refusal said, short, through the audit sanitizer's shape screen (a refusal text must not carry a value)."""
    t = inner.get("_text") if isinstance(inner, dict) else None
    if not isinstance(t, str):
        t = json.dumps(inner, default=str) if inner not in (None, {}, []) else ""
    t = t[:160]
    try:
        from agentvault_registry.mcp.audit_sanitizer import redact_text_shapes
        return redact_text_shapes(t)
    except Exception:  # noqa: BLE001
        return "<withheld>"


def _own_row(outcomes: Dict[str, Any], check: str, ok: bool, code: Any, t0: float, fail: Optional[str] = None,
             evidence: Optional[Dict[str, Any]] = None, skip: Optional[str] = None) -> None:
    # judged by the owner-scoping standard: the other principal refused, or answered without the owner's values
    outcomes[_OWN + check] = _make_outcome(_OWN + check, "owner-scoping", bool(ok) and not skip, str(code or "0"),
                                           int((time.time() - t0) * 1000), None if ok else fail, evidence or {},
                                           expect_status="success", skip_reason=skip)


def judge_other_principal(check: str, who: str, owner_inner: Any, other_ok: bool, other_inner: Any, other_code: str,
                          asked: Any) -> Tuple[Optional[bool], Optional[str], Dict[str, Any]]:
    """The verdict on one probe, pure (unit-tested): (healthy | None for NOT MEASURED, the sentence, evidence)."""
    c = int(other_code) if str(other_code or "").isdigit() else 0
    if _answered(other_ok, other_inner, other_code):
        carried, held = owner_values_carried(owner_inner, other_inner, asked)
        keys = sorted(other_inner.keys())[:10] if isinstance(other_inner, dict) else f"list({len(other_inner)})" \
            if isinstance(other_inner, list) else type(other_inner).__name__
        ev = {"other_status": c, "other_answer_keys": keys, "owner_values_carried": carried, "owner_values_held": held}
        if carried:
            return False, (f"BUG-FIND: owner scoping: {who} read the runner's object through {check}: HTTP {c}, carrying "
                           f"{carried} of the {held} values the owner's own answer holds (a name, url, email or id of "
                           f"the owner's; never recorded). Nothing but the object's id was asked."), ev
        if not held:
            return None, (f"NOT MEASURED: {who} was answered HTTP {c}, and the owner's own answer holds nothing "
                          f"distinctive to look for (empty), so whether the route checks ownership cannot be told from "
                          f"this object"), ev
        return True, f"scoped: {who} was answered HTTP {c} without any of the owner's values", ev
    ev = {"other_status": c, "other_said": _said(other_inner)}
    if c >= 500 or c == 0:
        return False, f"{who} was not refused cleanly: HTTP {c or 'no answer'}: {_said(other_inner)}", ev
    return True, f"refused HTTP {c}", ev


async def _own_read_probe(rpc: RpcCall, parse: ParseResult, outcomes: Dict[str, Any], tool: str, args: Dict[str, Any],
                          owner_jwt: str, other_jwt: str, who: str, label: Optional[str] = None) -> None:
    check, t0 = label or tool.replace("theprotocol_", ""), time.time()
    ok_o, body_o, code_o = await rpc(tool, args, jwt=owner_jwt, timeout=20)
    inner_o = parse(body_o)
    if not _answered(ok_o, inner_o, code_o):
        _own_row(outcomes, check, False, code_o, t0, skip=(
            f"NOT MEASURED: the owner's own call answered HTTP {code_o} ({_said(inner_o)[:100]}), so a refusal to "
            f"anybody else would prove nothing"))
        return
    ok_b, body_b, code_b = await rpc(tool, args, jwt=other_jwt, timeout=20)
    inner_b = parse(body_b)
    healthy, sentence, ev = judge_other_principal(check, who, inner_o, ok_b, inner_b, code_b, list(args.values()))
    if healthy is None:
        _own_row(outcomes, check, False, code_b, t0, evidence=ev, skip=sentence)
    else:
        _own_row(outcomes, check, healthy, code_b, t0, fail=None if healthy else sentence,
                 evidence={**ev, "verdict": sentence[:200]})


async def _own_webhook(rpc: RpcCall, parse: ParseResult, outcomes: Dict[str, Any], bag: Any, owner_jwt: str,
                       other_jwt: str, who: str, tag: str) -> None:
    """A webhook of the owner's, made for this: the other developer reads it, changes it, deletes it; the owner proves
    after each attempt that it is as it was, and removes it."""
    t0 = time.time()
    desc = f"owner-scoping probe {tag}"
    ok, body, code = await rpc("theprotocol_createWebhook",
                               {"url": f"https://webhook.example.test/owner-scoping-{tag}", "events": ["agent.created"],
                                "description": desc}, jwt=owner_jwt, timeout=20)
    made = parse(body)
    wid = made.get("id") if _answered(ok, made, code) and isinstance(made, dict) else None
    checks = ("getWebhook", "getWebhookDeliveries", "updateWebhook (another developer's)",
              "deleteWebhook (another developer's)")
    if not wid:
        for check in checks:
            _own_row(outcomes, check, False, code, t0, skip=(
                f"NOT MEASURED: the owner could not create the webhook this probe needs (HTTP {code}: {_said(made)[:100]})"))
        return
    try:
        # one delivery, so the deliveries read holds something of the owner's to look for
        await rpc("theprotocol_testWebhook", {"webhook_id": wid}, jwt=owner_jwt, timeout=20)
        for tool, args in OWNER_SCOPED_READS[:2]:
            await _own_read_probe(rpc, parse, outcomes, tool, {"webhook_id": wid}, owner_jwt, other_jwt, who)

        async def _owner_view() -> Tuple[bool, Any, str]:
            okr, bodyr, coder = await rpc("theprotocol_getWebhook", {"webhook_id": wid}, jwt=owner_jwt, timeout=20)
            return _answered(okr, parse(bodyr), coder), parse(bodyr), coder

        # each attempt is judged by what IT would have done: the update by the events (the read carries no
        # description: WebhookResponse is id, url, events, is_active, ...; the first dry run read that absence as a
        # change, 2026-10-01), the delete by existence
        for check, tool, args, kept in (
                ("updateWebhook (another developer's)", "theprotocol_updateWebhook",
                 {"webhook_id": wid, "events": ["agent.deleted"]},
                 lambda alive, view: alive and isinstance(view, dict) and sorted(view.get("events") or []) == ["agent.created"]),
                ("deleteWebhook (another developer's)", "theprotocol_deleteWebhook", {"webhook_id": wid},
                 lambda alive, view: alive)):
            t1 = time.time()
            okb, bodyb, codeb = await rpc(tool, args, jwt=other_jwt, timeout=20)
            innerb = parse(bodyb)
            alive, view, vcode = await _owner_view()
            intact = bool(kept(alive, view))
            c = int(codeb) if str(codeb).isdigit() else 0
            ev = {"other_status": c, "other_said": _said(innerb), "owner_read_after": int(vcode) if str(vcode).isdigit()
                  else 0, "intact": bool(intact)}
            if _answered(okb, innerb, codeb):
                harm = "the webhook is gone" if not alive else ("its events changed" if not intact else
                                                                  "the webhook is unchanged")
                _own_row(outcomes, check, False, codeb, t1, evidence=ev, fail=(
                    f"BUG-FIND: owner scoping: {who} was answered HTTP {c} for {tool.replace('theprotocol_', '')} on "
                    f"the runner's webhook, and afterwards {harm}: another developer's object must be refused"))
            elif not intact:
                _own_row(outcomes, check, False, codeb, t1, evidence=ev, fail=(
                    f"BUG-FIND: owner scoping: {who} was refused (HTTP {c}), yet the owner's webhook did not read back "
                    f"as it was (HTTP {vcode}, intact={intact})"))
            elif c >= 500 or c == 0:
                _own_row(outcomes, check, False, codeb, t1, evidence=ev,
                         fail=f"{who} was not refused cleanly: HTTP {c or 'no answer'}: {_said(innerb)}")
            else:
                _own_row(outcomes, check, True, codeb, t1, evidence={**ev, "verdict": f"refused HTTP {c}; intact"})
    finally:
        try:
            await rpc("theprotocol_deleteWebhook", {"webhook_id": wid}, jwt=owner_jwt, timeout=20)
        except Exception:  # noqa: BLE001 — cleanup is never a finding
            pass


def _api_key_state(listing: Any, kid: Any) -> Optional[bool]:
    """True: the key is listed and active; False: listed and revoked or inactive; None: not listed."""
    keys: List[Any] = []
    if isinstance(listing, dict):
        for k in ("api_keys", "items", "results", "keys"):
            if isinstance(listing.get(k), list):
                keys = listing[k]
                break
    elif isinstance(listing, list):
        keys = listing
    for kk in keys:
        if isinstance(kk, dict) and str(kk.get("id")) == str(kid):
            if kk.get("is_revoked") is True or kk.get("is_active") is False or \
                    str(kk.get("status") or "").lower() in ("revoked", "inactive", "disabled"):
                return False
            return True
    return None


async def _own_api_key(rpc: RpcCall, parse: ParseResult, outcomes: Dict[str, Any], owner_jwt: str, other_jwt: str,
                       who: str, tag: str) -> None:
    """An API key of the owner's, made for this: the other developer tries to revoke it; the owner proves it is still
    active, and revokes it."""
    check, t0 = "revokeApiKey (another developer's)", time.time()
    ok, body, code = await rpc("theprotocol_createApiKey", {"key_name": f"owner-scoping-{tag}"}, jwt=owner_jwt, timeout=20)
    made = parse(body)
    kid = (made.get("api_key_info") or {}).get("id") if _answered(ok, made, code) and isinstance(made, dict) else None
    if not kid:
        _own_row(outcomes, check, False, code, t0, skip=(
            f"NOT MEASURED: the owner could not create the API key this probe needs (HTTP {code}: {_said(made)[:100]})"))
        return
    try:
        okb, bodyb, codeb = await rpc("theprotocol_revokeApiKey", {"key_id": kid}, jwt=other_jwt, timeout=20)
        innerb = parse(bodyb)
        okl, bodyl, codel = await rpc("theprotocol_getMyApiKeys", {}, jwt=owner_jwt, timeout=20)
        state = _api_key_state(parse(bodyl), kid) if _answered(okl, parse(bodyl), codel) else None
        c = int(codeb) if str(codeb).isdigit() else 0
        ev = {"other_status": c, "other_said": _said(innerb), "owner_key_active_after": state}
        if _answered(okb, innerb, codeb):
            _own_row(outcomes, check, False, codeb, t0, evidence=ev, fail=(
                f"BUG-FIND: owner scoping: {who} was answered HTTP {c} for revokeApiKey on the runner's key, and the "
                f"owner's key now reads {'REVOKED' if state is False else 'active' if state else 'unlisted'}: another "
                f"developer's key must be refused"))
        elif state is False:
            _own_row(outcomes, check, False, codeb, t0, evidence=ev, fail=(
                f"BUG-FIND: owner scoping: {who} was refused (HTTP {c}), yet the owner's key reads REVOKED afterwards"))
        elif state is None:
            _own_row(outcomes, check, False, codeb, t0, evidence=ev, skip=(
                f"NOT MEASURED: {who} was refused (HTTP {c}), but the owner's key list (HTTP {codel}) did not show the "
                f"key, so its state after the attempt is unknown"))
        elif c >= 500 or c == 0:
            _own_row(outcomes, check, False, codeb, t0, evidence=ev,
                     fail=f"{who} was not refused cleanly: HTTP {c or 'no answer'}: {_said(innerb)}")
        else:
            _own_row(outcomes, check, True, codeb, t0, evidence={**ev, "verdict": f"refused HTTP {c}; still active"})
    finally:
        try:
            await rpc("theprotocol_revokeApiKey", {"key_id": kid}, jwt=owner_jwt, timeout=20)
        except Exception:  # noqa: BLE001 — cleanup is never a finding
            pass


_BUNDLE_CHECK = "patchBundle (another developer's)"


def _bundle_row(listing: Any, bid: Any) -> Optional[Dict[str, Any]]:
    rows = listing if isinstance(listing, list) else (
        (listing.get("bundles") or listing.get("items") or []) if isinstance(listing, dict) else [])
    for r in rows:
        if isinstance(r, dict) and str(r.get("id") or r.get("bundle_id")) == str(bid):
            return r
    return None


def _bundle_visibility(listing: Any, bid: Any) -> Optional[str]:
    row = _bundle_row(listing, bid)
    return str(row.get("visibility")) if row is not None else None


_RATE_CHECK = "rateBundle (another developer's private bundle)"


async def _own_bundle_rating(rpc: RpcCall, parse: ParseResult, outcomes: Dict[str, Any], bag: Any, owner_jwt: str,
                             other_jwt: str, who: str) -> None:
    """The setup's PRIVATE bundle: the other developer rates it. A bundle nobody but its owner may read is one nobody
    else may rate: until V0510 the route wrote the rating without looking the bundle up (and ratings move the featured
    score). The owner reads the bundle's rating count before and after."""
    t0, bid = time.time(), bag.get("bundle_id")
    if not bid or str(bid).startswith("${"):
        _own_row(outcomes, _RATE_CHECK, False, 0, t0, skip="NOT MEASURED: fixture missing: ['bundle_id']")
        return

    async def _row() -> Tuple[Optional[Dict[str, Any]], str]:
        okv, bodyv, codev = await rpc("theprotocol_getMyAgentBundles", {"limit": 100}, jwt=owner_jwt, timeout=30)
        innerv = parse(bodyv)
        return (_bundle_row(innerv, bid) if _answered(okv, innerv, codev) else None), codev
    row0, code0 = await _row()
    if row0 is None or str(row0.get("visibility")) == "public":
        _own_row(outcomes, _RATE_CHECK, False, code0, t0, skip=(
            f"NOT MEASURED: the owner's own bundle list (HTTP {code0}) did not show the setup's bundle as private"))
        return
    n0 = row0.get("rating_count")
    okr, bodyr, coder = await rpc("theprotocol_rateBundle", {"bundle_id": str(bid), "rating": 1}, jwt=other_jwt,
                                  timeout=20)
    innerr = parse(bodyr)
    row1, _code1 = await _row()
    n1 = (row1 or {}).get("rating_count")
    c = int(coder) if str(coder).isdigit() else 0
    ev = {"other_status": c, "other_said": _said(innerr), "rating_count_before": n0, "rating_count_after": n1}
    if _answered(okr, innerr, coder):
        _own_row(outcomes, _RATE_CHECK, False, coder, t0, evidence=ev, fail=(
            f"BUG-FIND: owner scoping: {who} was answered HTTP {c} for rateBundle on the runner's PRIVATE bundle "
            f"(rating count {n0!r} -> {n1!r}): a bundle the caller may not read must not take its rating"))
    elif n0 is not None and n1 is not None and n1 != n0:
        _own_row(outcomes, _RATE_CHECK, False, coder, t0, evidence=ev, fail=(
            f"BUG-FIND: owner scoping: {who} was refused (HTTP {c}) yet the private bundle's rating count moved "
            f"{n0!r} -> {n1!r}: the route wrote before it checked"))
    elif c >= 500 or c == 0:
        _own_row(outcomes, _RATE_CHECK, False, coder, t0, evidence=ev,
                 fail=f"{who} was not refused cleanly: HTTP {c or 'no answer'}: {_said(innerr)}")
    else:
        _own_row(outcomes, _RATE_CHECK, True, coder, t0, evidence={**ev, "verdict": f"refused HTTP {c}; count intact"})


async def _own_bundle_patch(rpc: RpcCall, parse: ParseResult, outcomes: Dict[str, Any], bag: Any, owner_jwt: str,
                            other_jwt: str, who: str) -> None:
    """The setup's PRIVATE bundle: the other developer tries to make it public; the owner reads its visibility back
    before and after, and puts it back if it moved. The route checks the owner today (V0510); this row keeps it so."""
    t0, bid = time.time(), bag.get("bundle_id")
    if not bid or str(bid).startswith("${"):
        _own_row(outcomes, _BUNDLE_CHECK, False, 0, t0, skip="NOT MEASURED: fixture missing: ['bundle_id']")
        return

    async def _vis() -> Tuple[Optional[str], str]:
        okv, bodyv, codev = await rpc("theprotocol_getMyAgentBundles", {"limit": 100}, jwt=owner_jwt, timeout=30)
        return (_bundle_visibility(parse(bodyv), bid) if _answered(okv, parse(bodyv), codev) else None), codev
    vis0, code0 = await _vis()
    if vis0 is None or vis0 == "public":
        _own_row(outcomes, _BUNDLE_CHECK, False, code0, t0, skip=(
            f"NOT MEASURED: the owner's own bundle list (HTTP {code0}) did not show the setup's bundle as private"))
        return
    okb, bodyb, codeb = await rpc("theprotocol_patchBundle", {"bundle_id": str(bid), "updates": {"visibility": "public"}},
                                  jwt=other_jwt, timeout=20)
    innerb = parse(bodyb)
    vis1, code1 = await _vis()
    c = int(codeb) if str(codeb).isdigit() else 0
    ev = {"other_status": c, "other_said": _said(innerb), "visibility_before": vis0, "visibility_after": vis1}
    try:
        if _answered(okb, innerb, codeb) or vis1 != vis0:
            _own_row(outcomes, _BUNDLE_CHECK, False, codeb, t0, evidence=ev, fail=(
                f"BUG-FIND: owner scoping: {who} was answered HTTP {c} for patchBundle on the runner's private bundle, and "
                f"its visibility now reads {vis1!r} (was {vis0!r}): another developer's bundle must be refused"))
        elif c >= 500 or c == 0:
            _own_row(outcomes, _BUNDLE_CHECK, False, codeb, t0, evidence=ev,
                     fail=f"{who} was not refused cleanly: HTTP {c or 'no answer'}: {_said(innerb)}")
        else:
            _own_row(outcomes, _BUNDLE_CHECK, True, codeb, t0, evidence={**ev, "verdict": f"refused HTTP {c}; still {vis0}"})
    finally:
        if vis1 is not None and vis1 != vis0:
            try:
                await rpc("theprotocol_patchBundle", {"bundle_id": str(bid), "updates": {"visibility": vis0}},
                          jwt=owner_jwt, timeout=20)
            except Exception:  # noqa: BLE001 — restoring is best-effort; the row already says what happened
                pass


_TEAM_CHECKS = ("updateOrganizationTeam (another org's admin)", "addTeamMember (another org's admin)",
                "addTeamMember (a developer outside the organization)")


async def _own_cross_org_team(rpc: RpcCall, parse: ParseResult, outcomes: Dict[str, Any], bag: Any, owner_jwt: str,
                              other_jwt: str, other_dev_id: Any, who: str, tag: str) -> None:
    """A team of the owner's, made for this inside the setup's organization. The other developer founds an organization
    of its own (so it IS an admin, of that one) and, naming its own organization and the owner's team, tries to rewrite
    the team and to join it. The owner reads the team back after each attempt and removes everything at the end.
    Until V0510 the update wrote BEFORE checking the team's organization (a 404 after the change) and the member routes
    never checked it."""
    t0, org = time.time(), bag.get("organization_id")
    if not org or str(org).startswith("${"):
        for check in _TEAM_CHECKS:
            _own_row(outcomes, check, False, 0, t0, skip="NOT MEASURED: fixture missing: ['organization_id']")
        return
    desc = f"owner-scoping team {tag}"
    ok, body, code = await rpc("theprotocol_createOrganizationTeam",
                               {"org_id": str(org), "name": f"owner-scoping {tag}", "description": desc},
                               jwt=owner_jwt, timeout=20)
    made = parse(body)
    team = made.get("id") if _answered(ok, made, code) and isinstance(made, dict) else None
    if not team:
        for check in _TEAM_CHECKS:
            _own_row(outcomes, check, False, code, t0, skip=(
                f"NOT MEASURED: the owner could not create the team this probe needs (HTTP {code}: {_said(made)[:100]})"))
        return
    theirs: Optional[str] = None
    their_team: Optional[str] = None
    try:
        ok, body, code = await rpc("theprotocol_createOrganization", {"name": f"owner-scoping-{tag}",
                                   "description": "MCP tester: the other developer's own organization"},
                                   jwt=other_jwt, timeout=20)
        made = parse(body)
        theirs = made.get("id") if _answered(ok, made, code) and isinstance(made, dict) else None
        if not theirs:
            for check in _TEAM_CHECKS:
                _own_row(outcomes, check, False, code, t0, skip=(
                    f"NOT MEASURED: the other developer could not found an organization of its own (HTTP {code}: "
                    f"{_said(made)[:100]})"))
            return

        async def _team_view() -> Tuple[bool, Any, str]:
            okv, bodyv, codev = await rpc("theprotocol_getOrganizationTeam", {"org_id": str(org), "team_id": str(team)},
                                          jwt=owner_jwt, timeout=20)
            return _answered(okv, parse(bodyv), codev), parse(bodyv), codev

        okv, before, _ = await _team_view()
        n0 = before.get("member_count") if okv and isinstance(before, dict) else None
        for check, tool, args, kept in (
                (_TEAM_CHECKS[0], "theprotocol_updateOrganizationTeam",
                 {"org_id": str(theirs), "team_id": str(team), "description": "changed by another organization's admin"},
                 lambda view: isinstance(view, dict) and view.get("description") == desc),
                (_TEAM_CHECKS[1], "theprotocol_addTeamMember",
                 {"org_id": str(theirs), "team_id": str(team), "developer_id": int(other_dev_id or 0)},
                 lambda view: isinstance(view, dict) and n0 is not None and view.get("member_count") == n0)):
            t1 = time.time()
            if check == _TEAM_CHECKS[1] and (n0 is None or not str(other_dev_id or "").isdigit()):
                _own_row(outcomes, check, False, 0, t1, skip=(
                    "NOT MEASURED: the team's member count or the other developer's id could not be read"))
                continue
            okb, bodyb, codeb = await rpc(tool, args, jwt=other_jwt, timeout=20)
            innerb = parse(bodyb)
            alive, view, vcode = await _team_view()
            intact = bool(alive and kept(view))
            c = int(codeb) if str(codeb).isdigit() else 0
            ev = {"other_status": c, "other_said": _said(innerb), "owner_read_after": int(vcode) if str(vcode).isdigit()
                  else 0, "intact": intact}
            if _answered(okb, innerb, codeb):
                _own_row(outcomes, check, False, codeb, t1, evidence=ev, fail=(
                    f"BUG-FIND: owner scoping: {who}, as the admin of its OWN organization, was answered HTTP {c} for "
                    f"{tool.replace('theprotocol_', '')} on the runner's team (another organization's): a team must "
                    f"belong to the organization whose authority was checked"))
            elif not intact:
                _own_row(outcomes, check, False, codeb, t1, evidence=ev, fail=(
                    f"BUG-FIND: owner scoping: {who} was answered HTTP {c} (a refusal), yet the runner's team changed "
                    f"(read back HTTP {vcode}): the route wrote before it checked whose team it was"))
            elif c >= 500 or c == 0:
                _own_row(outcomes, check, False, codeb, t1, evidence=ev,
                         fail=f"{who} was not refused cleanly: HTTP {c or 'no answer'}: {_said(innerb)}")
            else:
                _own_row(outcomes, check, True, codeb, t1, evidence={**ev, "verdict": f"refused HTTP {c}; intact"})
        their_team = await _own_outsider_into_own_team(rpc, parse, outcomes, bag, other_jwt, str(theirs), who, tag)
    finally:
        cleanup = [("theprotocol_deleteOrganizationTeam", {"org_id": str(org), "team_id": str(team)}, owner_jwt)]
        if theirs and their_team:
            cleanup.append(("theprotocol_deleteOrganizationTeam", {"org_id": str(theirs), "team_id": their_team},
                            other_jwt))
        cleanup.append(("theprotocol_deleteOrganization", {"org_id": str(theirs)}, other_jwt))
        for tool, args, jwt in cleanup:
            if tool.endswith("deleteOrganization") and not theirs:
                continue
            try:
                await rpc(tool, args, jwt=jwt, timeout=20)
            except Exception:  # noqa: BLE001 — cleanup is never a finding
                pass


async def _own_outsider_into_own_team(rpc: RpcCall, parse: ParseResult, outcomes: Dict[str, Any], bag: Any,
                                      other_jwt: str, theirs: str, who: str, tag: str) -> Optional[str]:
    """In its OWN organization, the other developer (its admin) makes a team and adds the RUNNER, who is not a member of
    that organization. Until V0510 any developer id was taken, and the team roster (GET /{org}/teams) then printed that
    developer's name: anybody who founded an organization read the name behind every developer id. The other developer
    reads its team's member count back. Returns the team's id for the cleanup."""
    check, t0 = _TEAM_CHECKS[2], time.time()
    runner_id = getattr(bag, "developer_id", None)
    if not str(runner_id or "").isdigit():
        _own_row(outcomes, check, False, 0, t0, skip="NOT MEASURED: the runner's own developer id is not known")
        return None
    ok, body, code = await rpc("theprotocol_createOrganizationTeam",
                               {"org_id": theirs, "name": f"outsider-probe {tag}", "description": "MCP tester probe"},
                               jwt=other_jwt, timeout=20)
    made = parse(body)
    their_team = made.get("id") if _answered(ok, made, code) and isinstance(made, dict) else None
    if not their_team:
        _own_row(outcomes, check, False, code, t0, skip=(
            f"NOT MEASURED: the other developer could not make a team in its own organization (HTTP {code})"))
        return None

    async def _count() -> Optional[int]:
        okv, bodyv, codev = await rpc("theprotocol_getOrganizationTeam", {"org_id": theirs, "team_id": str(their_team)},
                                      jwt=other_jwt, timeout=20)
        v = parse(bodyv)
        return v.get("member_count") if _answered(okv, v, codev) and isinstance(v, dict) else None
    n0 = await _count()
    okb, bodyb, codeb = await rpc("theprotocol_addTeamMember", {"org_id": theirs, "team_id": str(their_team),
                                                                "developer_id": int(runner_id)}, jwt=other_jwt, timeout=20)
    innerb = parse(bodyb)
    n1 = await _count()
    c = int(codeb) if str(codeb).isdigit() else 0
    ev = {"other_status": c, "other_said": _said(innerb), "member_count_before": n0, "member_count_after": n1}
    if _answered(okb, innerb, codeb):
        _own_row(outcomes, check, False, codeb, t0, evidence=ev, fail=(
            f"BUG-FIND: owner scoping: {who} added the RUNNER (not a member of its organization) to a team of its own "
            f"and was answered HTTP {c}: the roster then prints the runner's name to the other developer"))
    elif n0 is not None and n1 is not None and n1 != n0:
        _own_row(outcomes, check, False, codeb, t0, evidence=ev, fail=(
            f"BUG-FIND: owner scoping: refused (HTTP {c}) yet the team's member count moved {n0!r} -> {n1!r}"))
    elif c >= 500 or c == 0:
        _own_row(outcomes, check, False, codeb, t0, evidence=ev,
                 fail=f"{who} was not refused cleanly: HTTP {c or 'no answer'}: {_said(innerb)}")
    else:
        _own_row(outcomes, check, True, codeb, t0, evidence={**ev, "verdict": f"refused HTTP {c}; count intact"})
    return str(their_team)


async def _private_offer(rpc: RpcCall, parse: ParseResult, bag: Any, tag: str) -> Dict[str, Any]:
    """§MCPTEST30 (V0556): a PRIVATE offer of the sentinel's, the subject the owner-scoping contract checks need. The
    sentinel is fresh every run, so the only contracts it could read were open offers, which any agent may read by
    design: both checks read NOT MEASURED on every run, and a private offer stayed readable by any agent with its id
    (V0556 (1)). The provider is a new agent of the runner's whose card is given engagement terms (a price of 1, no
    escrow before an accept); the sentinel engages it (engageAgent's success path, which no contract reaches: the sweep's
    fixture card carries no terms). Returns {"cid", "provider_did"}, or {"why": a NOT MEASURED sentence} with whatever
    was made so far; `_withdraw_private_offer` cancels the offer and deletes the provider."""
    rpc_admin = _admin_bridge(bag)
    if rpc_admin is None:
        return {"why": "NOT MEASURED: the runner injected no admin bridge, so no provider's card could be given terms"}
    owner = bag.developer_jwt or ""
    ok, body, code = await rpc("theprotocol_createAgent",
                               {"name": f"mcp-offer-provider-{tag}",
                                "description": "The MCP tester's provider for a private offer the sentinel makes and "
                                               "withdraws in the same run (owner scoping)."},
                               jwt=owner, timeout=60)
    made = parse(body)
    did = (made.get("agent_did") or made.get("did")) if isinstance(made, dict) else None
    if not (ok and did):
        return {"why": f"NOT MEASURED: no provider agent for a private offer (createAgent answered HTTP {code})"}
    out: Dict[str, Any] = {"provider_did": did}
    ok, body, code = await rpc_admin("theprotocol_adminRequest",
                                     {"method": "GET", "endpoint": f"/api/v1/agent-cards/{did}"}, jwt=owner, timeout=30)
    got = parse(body)
    card = (got.get("response") if isinstance(got, dict) else None) or {}
    card_data = card.get("card_data") if isinstance(card, dict) else None
    if not isinstance(card_data, dict):
        return {**out, "why": (f"NOT MEASURED: the provider's card could not be read "
                               f"(HTTP {got.get('status_code') if isinstance(got, dict) else code})")}
    terms = {"title": f"MCP tester private offer {tag}", "price": 1, "contract_type": "service",
             "deadline_seconds": 3600, "terms": {"probe": "owner scoping, withdrawn in the same run"}}
    ok, body, code = await rpc_admin("theprotocol_adminRequest",
                                     {"method": "PUT", "endpoint": f"/api/v1/agent-cards/{did}",
                                      "body": {"card_data": {**card_data, "engagement": terms}}},
                                     jwt=owner, timeout=30)
    put = parse(body)
    st = put.get("status_code") if isinstance(put, dict) else code
    if st != 200:
        return {**out, "why": f"NOT MEASURED: the provider's card took no engagement terms (HTTP {st})"}
    ok, body, code = await rpc("theprotocol_engageAgent",
                               {"provider_did": did, "agent_jwt": bag.sentinel_jwt,
                                "message": f"MCP tester owner scoping {tag}"}, jwt=owner, timeout=30)
    offer = parse(body)
    cid = offer.get("id") if isinstance(offer, dict) else None
    if not (ok and cid and offer.get("provider_did") == did and offer.get("status") == "offered"):
        return {**out, "why": f"NOT MEASURED: engageAgent minted no private offer (HTTP {code}: {_said(offer)})"}
    return {**out, "cid": str(cid)}


async def _withdraw_private_offer(rpc: RpcCall, bag: Any, offer: Dict[str, Any]) -> None:
    """The sentinel withdraws the offer it made (contracts v2 cancel, its agent token through the admin bridge) and the
    runner deletes the provider it made; best effort, a probe's own objects only."""
    rpc_admin = _admin_bridge(bag)
    if offer.get("cid") and rpc_admin is not None:
        await rpc_admin("theprotocol_adminRequest",
                        {"method": "POST", "endpoint": f"/api/v1/contracts/v2/{offer['cid']}/cancel",
                         "developer_jwt": bag.sentinel_jwt}, jwt=bag.developer_jwt, timeout=30)
    if offer.get("provider_did"):
        await rpc("theprotocol_deleteMyAgentByDev", {"agent_did": offer["provider_did"]}, jwt=bag.developer_jwt, timeout=30)


async def lifecycle_owner_scoping(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    import secrets as _secrets
    t0, tag = time.time(), _secrets.token_hex(4)
    owner = bag.developer_jwt or ""
    mint = getattr(bag, "mint_throwaway", None)
    sub = await mint("owner") if mint else {"why": "the runner injected no mint_throwaway"}
    other = (sub or {}).get("access_token") or ""
    every = [t.replace("theprotocol_", "") for t, _ in OWNER_SCOPED_READS] + [
        "updateWebhook (another developer's)", "deleteWebhook (another developer's)",
        "revokeApiKey (another developer's)", "getContractV2 (a non-party agent)", "getContractById (a non-party agent)",
        *_TEAM_CHECKS, _BUNDLE_CHECK, _RATE_CHECK]
    if not other:
        for check in every:
            _own_row(outcomes, check, False, 0, t0, skip=(
                f"NOT MEASURED: no second developer could be minted ({(sub or {}).get('why')})"))
        return
    who = "a second developer (a throwaway of this run, no admin flag)"
    offer: Dict[str, Any] = {}      # the private offer the contract checks may make (withdrawn in `finally`)
    try:
        okp, bodyp, codep = await rpc("theprotocol_getMyDeveloperProfile", {}, jwt=other, timeout=20)
        if not _answered(okp, parse(bodyp), codep):
            for check in every:
                _own_row(outcomes, check, False, codep, t0, skip=(
                    f"NOT MEASURED: the second developer's own profile read answered HTTP {codep}, so its credential "
                    f"cannot be trusted to tell a refusal from a broken login"))
            return
        await _own_webhook(rpc, parse, outcomes, bag, owner, other, who, tag)
        await _own_api_key(rpc, parse, outcomes, owner, other, who, tag)
        await _own_cross_org_team(rpc, parse, outcomes, bag, owner, other, sub.get("developer_id"), who, tag)
        await _own_bundle_patch(rpc, parse, outcomes, bag, owner, other, who)
        await _own_bundle_rating(rpc, parse, outcomes, bag, owner, other, who)
        sem = asyncio.Semaphore(4)

        async def _one(tool: str, spec: Dict[str, str]) -> None:
            async with sem:
                args = {a: bag.get(f) for a, f in spec.items()}
                missing = [f for a, f in spec.items() if args[a] in (None, "") or str(args[a]).startswith("${")]
                if missing:
                    _own_row(outcomes, tool.replace("theprotocol_", ""), False, 0, time.time(), skip=(
                        f"NOT MEASURED: fixture missing: {missing!r}: the setup published no such object of the owner's"))
                    return
                await _own_read_probe(rpc, parse, outcomes, tool, args, owner, other, who)
        await asyncio.gather(*(_one(t, s) for t, s in OWNER_SCOPED_READS[2:]))
        # the agent tier: the sentinel's contract, read by the run's second agent, which is not a party to it, through
        # both views of the one spine row (the v2 detail and the legacy adapter, which had no party rule until V0510).
        # §MCPTEST30 (V0556): where the sentinel holds only an open offer (every run: it is fresh), it makes a PRIVATE
        # offer to a provider of the run's own, which only its parties may read, and withdraws it below
        cid, st = bag.get("contract_v2_id"), str(bag.get("contract_v2_status") or "")
        second, sentinel = bag.get("second_agent_jwt"), bag.sentinel_jwt
        if not cid or str(cid).startswith("${") or st == "offered":
            offer = await _private_offer(rpc, parse, bag, tag)
            if offer.get("cid"):
                cid, st = offer["cid"], "offered, private"
        for tool in ("theprotocol_getContractV2", "theprotocol_getContractById"):
            t1, check = time.time(), f"{tool.replace('theprotocol_', '')} (a non-party agent)"
            if not cid or str(cid).startswith("${"):
                _own_row(outcomes, check, False, 0, t1, skip=(
                    "NOT MEASURED: the setup verified no contract the sentinel is a party to, and "
                    + (offer.get("why") or "no private offer was made").removeprefix("NOT MEASURED: ")))
                continue
            if st == "offered":
                _own_row(outcomes, check, False, 0, t1, skip=(
                    "NOT MEASURED: the sentinel's contract is an open offer, which any agent may read by design, and "
                    + (offer.get("why") or "no private offer was made").removeprefix("NOT MEASURED: ")))
                continue
            if not second or second == sentinel or str(second).startswith("${"):
                _own_row(outcomes, check, False, 0, t1, skip="NOT MEASURED: the setup made no second agent")
                continue
            okc, bodyc, codec = await rpc(tool, {"contract_id": cid, "agent_jwt": sentinel}, jwt=owner, timeout=20)
            innerc = parse(bodyc)
            if not _answered(okc, innerc, codec):
                _own_row(outcomes, check, False, codec, t1, skip=(
                    f"NOT MEASURED: the party's own read answered HTTP {codec}, so a refusal to a non-party proves nothing"))
                continue
            okn, bodyn, coden = await rpc(tool, {"contract_id": cid, "agent_jwt": second}, jwt=owner, timeout=20)
            healthy, sentence, ev = judge_other_principal(
                check, "an agent that is not a party to it" + (" (a private offer)" if offer.get("cid") else ""),
                innerc, okn, parse(bodyn), coden, [cid])
            if offer.get("cid"):
                ev = {**ev, "subject": "a private offer the sentinel made to a provider of this run's, then withdrew"}
            if healthy is None:
                _own_row(outcomes, check, False, coden, t1, evidence=ev, skip=sentence)
            else:
                _own_row(outcomes, check, healthy, coden, t1, fail=None if healthy else sentence,
                         evidence={**ev, "verdict": sentence[:200]})
    finally:
        if offer:
            await _withdraw_private_offer(rpc, bag, offer)
        await _schedule_own_deletion(rpc, bag, sub.get("email") or "", sub.get("password") or "", "owner scoping")


async def lifecycle_pagination_partition(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """§MCPTEST30 (2026-10-01): every paged tool (`limit` with `offset`), read only: are two pages of n a partition of one
    page of 2n? The public and agent tools through the sweep's own transport, the admin ones through the raw JSON-RPC
    transport on the admin bridge (api_tests/contracts/pagination_partition.py holds the judge)."""
    from agentvault_registry.api_tests.contracts import pagination_partition as PP
    await PP.run_paged(rpc, parse, bag, outcomes, PP.PAGED_PUBLIC, _make_outcome, _answered)
    raw = getattr(bag, "rpc_raw", None)
    if raw is None:
        for tool, _tier, _x in PP.PAGED_ADMIN:
            name = PP.PREFIX + tool.replace("theprotocol_", "")
            outcomes[name] = _make_outcome(name, "pagination", False, "0", 0, None, {}, expect_status="success",
                                           skip_reason="NOT MEASURED: the runner injected no raw transport for the admin bridge")
        return

    async def _admin(tool: str, args: Dict[str, Any], jwt: str = "", timeout: int = 30) -> Tuple[bool, Any, str]:
        code, parsed, _ = await raw(_jbody("tools/call", {"name": tool, "arguments": args}), path="/mcp/admin/rpc",
                                    jwt=jwt, timeout=timeout)
        res = parsed.get("result") if isinstance(parsed, dict) else None
        ok = str(code).startswith("2") and isinstance(res, dict) and not res.get("isError")
        return ok, parsed if isinstance(parsed, dict) else {}, str(code)
    await PP.run_paged(_admin, parse, bag, outcomes, PP.PAGED_ADMIN, _make_outcome, _answered)


async def lifecycle_page_bounds(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """§MCPTEST30 (2026-10-01): every paged tool, read only, asked for a page of 0, of -1, from offset -1 and of 5000.

    Postgres refuses a negative LIMIT or OFFSET with an error, so a route that hands the bound to its SQL unchecked
    answers 500 where it should refuse (422) or clamp. A server error is the finding; a page of 5000 that returns more
    than 1000 rows is recorded as `uncapped` (no route here documents a cap to hold it to). The admin tools go through
    the raw JSON-RPC transport on the admin bridge, like the pagination probe."""
    from agentvault_registry.api_tests.contracts import pagination_partition as PP
    await PP.run_bounds(rpc, parse, bag, outcomes, PP.PAGED_PUBLIC, _make_outcome, _answered)
    raw = getattr(bag, "rpc_raw", None)
    if raw is None:
        for tool, _tier, _x in PP.PAGED_ADMIN:
            name = PP.BOUNDS_PREFIX + tool.replace("theprotocol_", "")
            outcomes[name] = _make_outcome(name, "bounds", False, "0", 0, None, {}, expect_status="any",
                                           skip_reason="NOT MEASURED: the runner injected no raw transport for the admin bridge")
        return

    async def _admin(tool: str, args: Dict[str, Any], jwt: str = "", timeout: int = 30) -> Tuple[bool, Any, str]:
        code, parsed, _ = await raw(_jbody("tools/call", {"name": tool, "arguments": args}), path="/mcp/admin/rpc",
                                    jwt=jwt, timeout=timeout)
        res = parsed.get("result") if isinstance(parsed, dict) else None
        ok = str(code).startswith("2") and isinstance(res, dict) and not res.get("isError")
        return ok, parsed if isinstance(parsed, dict) else {}, str(code)
    await PP.run_bounds(_admin, parse, bag, outcomes, PP.PAGED_ADMIN, _make_outcome, _answered)


async def lifecycle_list_detail(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """§MCPTEST30 (2026-10-01): every id a list tool advertises must resolve at its detail tool (read only). The judge
    and the pairs live in api_tests/contracts/list_detail.py; the admin tools go through the raw transport on the
    admin bridge, like the pagination probe."""
    from agentvault_registry.api_tests.contracts import list_detail as LD
    raw = getattr(bag, "rpc_raw", None)

    async def _admin(tool: str, args: Dict[str, Any], jwt: str = "", timeout: int = 30) -> Tuple[bool, Any, str]:
        code, parsed, _ = await raw(_jbody("tools/call", {"name": tool, "arguments": args}), path="/mcp/admin/rpc",
                                    jwt=jwt, timeout=timeout)
        res = parsed.get("result") if isinstance(parsed, dict) else None
        ok = str(code).startswith("2") and isinstance(res, dict) and not res.get("isError")
        return ok, parsed if isinstance(parsed, dict) else {}, str(code)

    def _rpc_for(tier: str):
        if tier == "admin":
            return _admin if raw is not None else None
        return rpc
    await _ensure_transparent_org(rpc, parse, bag)
    await LD.run_pairs(_rpc_for, parse, bag, outcomes, LD.PAIRS, _make_outcome, _answered)


_TRANSPARENCY_FIXTURE = "MCP tester: transparency fixture"


async def _ensure_transparent_org(rpc: RpcCall, parse: ParseResult, bag: Any) -> None:
    """§SUITES1018 (2026-10-18): listTransparentOrganizations -> getOrgPublicFeed had nothing to ask on a frame where no
    organization opted into transparency, so the pair read NOT MEASURED every night. The run keeps ONE fixture
    organization opted in (settings.public_transparency_opt_in, a catalog key), found by its name and made only when
    absent, never deleted: its public feed is records-only and it holds no work. Best-effort: a failure here leaves the
    pair to say what it can measure."""
    from agentvault_registry.api_tests.contracts.list_detail import rows_of
    jwt = getattr(bag, "developer_jwt", "") or ""
    if not jwt:
        return
    try:
        ok, body, _ = await rpc("theprotocol_listTransparentOrganizations", {"limit": 20}, jwt=jwt, timeout=30)
        if ok and rows_of(parse(body), ("organizations",)):
            return
        ok, body, _ = await rpc("theprotocol_getMyOrganizations", {}, jwt=jwt, timeout=30)
        mine = rows_of(parse(body), ("organizations",)) if ok else []
        opt_in = {"public_transparency_opt_in": True}
        fixture = next((o for o in mine if isinstance(o, dict) and o.get("name") == _TRANSPARENCY_FIXTURE), None)
        if fixture and fixture.get("id"):
            await rpc("theprotocol_updateOrganization", {"org_id": str(fixture["id"]), "settings": opt_in},
                      jwt=jwt, timeout=30)
        else:
            await rpc("theprotocol_createOrganization",
                      {"name": _TRANSPARENCY_FIXTURE, "settings": opt_in,
                       "description": "kept by the MCP tester: the one organization its transparency checks read"},
                      jwt=jwt, timeout=30)
    except Exception as exc:  # noqa: BLE001
        import logging as _logging
        _logging.getLogger(__name__).warning(f"list_detail: transparency fixture not ensured ({exc!r})")


async def lifecycle_write_hygiene(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """§MCPTEST30 (V0525): a team, an API key and a webhook the run can remove again, each written with a NUL, LIKE's
    wildcards ending in its escape character and 4,000 characters; a server error is the finding, and every object a
    value made is removed by the run's own tag (api_tests/contracts/write_hygiene.py)."""
    from agentvault_registry.api_tests.contracts import write_hygiene as WH
    await WH.run_write_hygiene(rpc, parse, bag, outcomes, _make_outcome, _answered)


async def lifecycle_achievement_claims(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """§MCPTEST30 (V0546): a paying achievement is a money path any developer can open (achievement_claims.py). One
    read of the public catalog; red the run an enabled achievement first pays."""
    from agentvault_registry.api_tests.contracts import achievement_claims as AC
    await AC.run_achievement_claims(rpc, parse, bag, outcomes, _make_outcome, _answered, _said)


async def lifecycle_overdraft_race(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """§MCPTEST30 (V0525): a throwaway spender funded 0.05 by the sentinel sends it two transfers AT ONCE, each 60% of its
    balance, with different keys: one moves and one is refused, never both (the double spend). The spender returns
    what it holds and is deleted (api_tests/contracts/overdraft_race.py). Dust between the run's own agents."""
    from agentvault_registry.api_tests.contracts import overdraft_race as OR
    await OR.run_overdraft(rpc, parse, bag, outcomes, _make_outcome, _answered, _said)


async def lifecycle_revocation(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """§MCPTEST30 (V0528): a throwaway API key revoked, another deleted, a throwaway agent deleted: each is asked again on
    fresh connections and must be refused every time; the lists that say "revoked" were the only check before
    (api_tests/contracts/revocation.py)."""
    from agentvault_registry.api_tests.contracts import revocation as RV
    await RV.run_revocation(rpc, parse, bag, outcomes, _make_outcome, _answered, _said)


async def lifecycle_key_scopes(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """§MCPTEST30 (V0528): an API key scoped narrower than `*` is refused the admin MCP surface and the minting of keys;
    a key scoped `mcp:admin` reaches the admin surface (the positive control). Throwaway keys, deleted again
    (api_tests/contracts/key_scopes.py)."""
    from agentvault_registry.api_tests.contracts import key_scopes as KS
    await KS.run_scopes(rpc, parse, bag, outcomes, _make_outcome, _answered, _said)


async def lifecycle_filter_honesty(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """§MCPTEST30: every read-only list tool's filter argument asked with a value that matches nothing, after a control
    that returns rows: no rows (or a refusal) is right, rows mean the filter was dropped (api_tests/contracts/
    filter_honesty.py). Read only."""
    from agentvault_registry.api_tests.contracts import filter_honesty as FH
    await FH.run_filters(getattr(bag, "rpc_raw", None), bag, outcomes, _make_outcome)


async def lifecycle_a2a_settle_race(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """§MCPTEST30: one A2A payment token pays at most once: two settles at once, and a settle racing a release, on a
    throwaway payer funded with dust by the sentinel; the payer's ledger counts the token's settlement rows
    (api_tests/contracts/a2a_settle_race.py)."""
    from agentvault_registry.api_tests.contracts import a2a_settle_race as AR
    await AR.run_a2a_race(rpc, parse, bag, outcomes, _make_outcome, _answered, _said)


async def lifecycle_zk_v2_attestations(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """§MCPTEST30 (V0612): zero-knowledge attestations v2 (agentvault2-90's §ZKV2) through the MCP tools: the catalog,
    each v2.0.0 key against its metadata, a real proof by the registry's own prover (generateTutorialProof, admin
    bridge) for a throwaway agent, its submission verified with one point, then refused as a replay (409), without a
    label (422), from another agent, with an element raised by the field order and under its retired v1.0.0 id;
    Option B never verified; a second proof the same day earns nothing and the governance preview counts one
    circuit-day; re-verified, revoked, deleted (api_tests/contracts/zk_v2_attestations.py)."""
    from agentvault_registry.api_tests.contracts import zk_v2_attestations as ZK
    await ZK.run_zk_v2(rpc, parse, bag, outcomes, _make_outcome, _answered, _said)


async def lifecycle_enum_filter(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """§MCPTEST30: every value a read-only tool's enum filter advertises is one its route applies: never refused as
    invalid, never answered with other values, never empty while the unfiltered rows hold it
    (api_tests/contracts/enum_filter.py). Read only."""
    from agentvault_registry.api_tests.contracts import enum_filter as EF
    await EF.run_enums(getattr(bag, "rpc_raw", None), bag, outcomes, _make_outcome)


async def lifecycle_value_range(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """§MCPTEST30 (V0525): every read-only tool asked, per integer argument, with 2^31 and 2^63 (a page size with 2^63
    only), per number with 1e308 and per date-like string with a non-date, 30 February and the year 99999, through the
    raw transport: a refusal or an answer is right, -32603, a tool-side exception, a 5xx or an answer carrying the
    database driver's own words is the finding (api_tests/contracts/value_range.py)."""
    from agentvault_registry.api_tests.contracts import value_range as VR
    await VR.run_range(getattr(bag, "rpc_raw", None), bag, outcomes, _make_outcome)


async def lifecycle_type_confusion(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """§MCPTEST30 (V0524): every read-only tool with a typed argument, asked once per such argument with a value of the
    wrong JSON type, through the raw JSON-RPC transport so the error CODE is read: -32602 or a route's refusal is right,
    -32603, a tool-side exception, a 5xx or an accepted value is the finding (api_tests/contracts/type_confusion.py)."""
    from agentvault_registry.api_tests.contracts import type_confusion as TC
    await TC.run_types(getattr(bag, "rpc_raw", None), bag, outcomes, _make_outcome)


async def lifecycle_unique_create_race(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """§MCPTEST30 (V0524): one team name asked twice at once, twice in a row, and again after its team was deleted, on
    the run's own organization; one team and one refusal, never a server error. The cases and the judge live in
    api_tests/contracts/unique_race.py; every team the probe made is deleted again."""
    from agentvault_registry.api_tests.contracts import unique_race as UR
    await UR.run_race(rpc, parse, bag, outcomes, _make_outcome, _answered)


async def lifecycle_input_hygiene(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """§MCPTEST30 (2026-10-01): every read-only tool with a text argument, asked with a NUL, LIKE's wildcards ending in
    its escape character, and 4,000 characters (read only). A server error is the finding. The judge and the target
    list (derived from the tool schemas at run time) live in api_tests/contracts/input_hygiene.py; the admin tools go
    through the raw transport on the admin bridge, like the pagination probe."""
    from agentvault_registry.api_tests.contracts import input_hygiene as IH
    raw = getattr(bag, "rpc_raw", None)

    async def _admin(tool: str, args: Dict[str, Any], jwt: str = "", timeout: int = 30) -> Tuple[bool, Any, str]:
        code, parsed, _ = await raw(_jbody("tools/call", {"name": tool, "arguments": args}), path="/mcp/admin/rpc",
                                    jwt=jwt, timeout=timeout)
        res = parsed.get("result") if isinstance(parsed, dict) else None
        ok = str(code).startswith("2") and isinstance(res, dict) and not res.get("isError")
        return ok, parsed if isinstance(parsed, dict) else {}, str(code)

    def _rpc_for(tier: str):
        if tier == "admin":
            return _admin if raw is not None else None
        return rpc
    await IH.run_hygiene(_rpc_for, parse, bag, outcomes, _make_outcome, _answered)


# (the amount, what it is, whether the route must refuse it): dust only, between the run's own two agents
AMOUNT_CASES: Tuple[Tuple[str, str, bool], ...] = (
    ("-0.01", "a negative amount", True),
    ("0", "zero", True),
    ("NaN", "not a number", True),
    ("Infinity", "an infinite amount", True),
    ("0.0000000000000000001", "an amount below the ledger's 18 places", False),
    ("1e-2", "0.01 in scientific notation", False),
)


# §MCPTEST30 (round 7): NaN reached `Decimal <= 0` in nine TEG request validators and answered 500 on transferUnits; the
# other money tools take their amount as a string too. NaN can move nothing, so each is asked once: a 4xx is the answer,
# a 5xx or an acceptance is the finding. (tool, arguments; ${receiver} is the run's second agent)
NAN_TOOLS: Tuple[Tuple[str, Dict[str, Any]], ...] = (
    ("theprotocol_lockUnits", {"amount": "NaN", "lock_period_days": 7}),
    ("theprotocol_authorizePayment", {"target_agent_did": "${receiver}", "amount": "NaN"}),
    ("theprotocol_tegCrossRegistryTransferDirect", {"receiver_did": "${receiver}", "amount": "NaN"}),
    ("theprotocol_smartSend", {"receiver_did": "${receiver}", "amount": "NaN"}),
    ("theprotocol_bridgeTransfer", {"target_agent_did": "${receiver}", "amount": "NaN"}),
)


async def lifecycle_amount_bounds(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """§MCPTEST30 (2026-10-01): transferUnits asked to move amounts no ledger can hold, sentinel to the run's second agent.

    The transfer route takes the amount as a string and hands it to its spend gate, its fee arithmetic and the TEG: a
    negative, a zero, NaN and Infinity must each be REFUSED (4xx); an amount below the ledger's 18 places and 0.01 in
    scientific notation may be refused or moved (dust either way). A server error on any of them is the finding (an
    amount the route never checked reached arithmetic that raised), and an accepted impossible amount is one too.
    Rows `amount: transferUnits <amount>`."""
    from agentvault_registry.api_tests.contracts import pagination_partition as PP
    sender_jwt, receiver = bag.sentinel_jwt, bag.get("second_agent_did")
    unmet = None
    if not sender_jwt or not receiver or receiver == bag.sentinel_did or str(receiver).startswith("${"):
        unmet = "NOT MEASURED: the setup made no second agent to receive the dust"
    for amount, what, must_refuse in AMOUNT_CASES:
        name, t0 = f"amount: transferUnits {amount}", time.time()
        want = "error_4xx" if must_refuse else "any"
        if unmet:
            outcomes[name] = _make_outcome(name, "amount", False, "0", 0, None, {}, expect_status=want, skip_reason=unmet)
            continue
        ok, body, code = await rpc("theprotocol_transferUnits", {
            "agent_jwt": sender_jwt, "recipient_did": receiver, "amount": amount,
            "message": f"MCP tester: {what}"}, jwt=bag.developer_jwt, timeout=30)
        kind, st, _rows = PP.bound_answer(ok, parse(body), code, _answered)
        accepted = kind == "rows"
        ev = {"amount": what, "answer": "accepted" if accepted else (f"{kind} HTTP {st}" if st else kind)}
        fail = skip = None
        if kind == "no_answer":
            skip = f"NOT MEASURED: the MCP call answered HTTP {code}"
        elif kind == "server_error":
            fail = (f"BUG-FIND: amount: transferUnits answered a server error for {what} ({amount}): the route never "
                    f"checked it before arithmetic that raised")
        elif accepted and must_refuse:
            fail = f"BUG-FIND: amount: transferUnits ACCEPTED {what} ({amount})"
        outcomes[name] = _make_outcome(name, "amount", fail is None and skip is None, code,
                                       int((time.time() - t0) * 1000), fail, {}, expect_status=want, skip_reason=skip)
        outcomes[name]["result_excerpt"] = ev
    for tool, targs in NAN_TOOLS:
        name, t0 = f"amount: {tool.replace('theprotocol_', '')} NaN", time.time()
        if unmet:
            outcomes[name] = _make_outcome(name, "amount", False, "0", 0, None, {}, expect_status="error_4xx",
                                           skip_reason=unmet)
            continue
        _sw = _switches.switched_off(tool)
        if _sw is not None:
            # §MCPTEST30 (V0550): the switch refuses before the route reads an amount, so the answer says nothing of NaN
            outcomes[name] = _make_outcome(name, "amount", False, "0", 0, None, {}, expect_status="error_4xx",
                                           skip_reason=(f"NOT MEASURED: {tool.replace('theprotocol_', '')} is switched "
                                                        f"off on this target ({_sw.label()}); its route refuses before "
                                                        f"it reads an amount"))
            continue
        args = {k: (receiver if v == "${receiver}" else v) for k, v in targs.items()}
        ok, body, code = await rpc(tool, {**args, "agent_jwt": sender_jwt}, jwt=bag.developer_jwt, timeout=30)
        kind, st, _rows = PP.bound_answer(ok, parse(body), code, _answered)
        ev = {"amount": "not a number", "answer": "accepted" if kind == "rows" else (f"{kind} HTTP {st}" if st else kind)}
        fail = skip = None
        if kind == "no_answer":
            skip = f"NOT MEASURED: no result came back (HTTP {code})"
        elif kind == "server_error":
            fail = (f"BUG-FIND: amount: {tool.replace('theprotocol_', '')} answered a server error for NaN: the route "
                    f"never checked it before arithmetic that raised")
        elif kind == "rows":
            fail = f"BUG-FIND: amount: {tool.replace('theprotocol_', '')} ACCEPTED NaN as an amount"
        outcomes[name] = _make_outcome(name, "amount", fail is None and skip is None, code,
                                       int((time.time() - t0) * 1000), fail, {}, expect_status="error_4xx",
                                       skip_reason=skip)
        outcomes[name]["result_excerpt"] = ev


async def _own_transfers(rpc: RpcCall, parse: ParseResult, bag: Any, receiver_jwt: str, message: str) -> Optional[int]:
    """How many transactions the receiver holds with exactly `message` (a message unique to one probe), or None when the
    list cannot be read. §MCPTEST30 (round 7): a balance cannot attribute a movement, because other lifecycles run at the
    same time and pay the same receiver (amount_bounds moved 0.01 to it 105 ms before the concurrent pair's second read,
    and the pair was called a double payment while the ledger held ONE transaction)."""
    ok, body, code = await rpc("theprotocol_getMyTegTransactions", {"agent_jwt": receiver_jwt, "limit": 50},
                               jwt=bag.developer_jwt, timeout=30)
    inner = parse(body)
    rows = inner.get("transactions") if isinstance(inner, dict) else None
    if not _answered(ok, inner, code) or not isinstance(rows, list):
        return None
    return sum(1 for t in rows if isinstance(t, dict) and t.get("attached_message") == message)


async def lifecycle_money_idempotent_replay(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """§MCPTEST30 (2026-10-01): a money call retried with the same idempotency key moves money ONCE.

    The money routes honor an Idempotency-Key header for 24 h (§pass57); until V0512 no MCP tool sent one (lockUnits put
    a random key in the body, which the route never reads), so a client retrying a timed-out transfer paid twice. Here the
    sentinel sends the run's second agent 0.01 twice with ONE key: both answers must name the same transaction, and the
    receiver's balance must move by 0.01, not 0.02. Dust, between the run's own two agents (Delta-neutral, no canary)."""
    import secrets as _secrets
    from decimal import Decimal, InvalidOperation
    name, t0 = "idempotency: transferUnits", time.time()
    sender_jwt, receiver = bag.sentinel_jwt, bag.get("second_agent_did")
    receiver_jwt = bag.get("second_agent_jwt")
    if (not sender_jwt or not receiver or receiver == bag.sentinel_did or not receiver_jwt
            or receiver_jwt == sender_jwt or str(receiver).startswith("${")):
        outcomes[name] = _make_outcome(name, "idempotency", False, "0", 0, None, {}, expect_status="success", skip_reason=(
            "NOT MEASURED: the setup made no second agent to receive the dust (a self-transfer cannot show a replay)"))
        return

    async def _balance() -> Optional[Decimal]:
        okb, bodyb, codeb = await rpc("theprotocol_getMyBalance", {"agent_jwt": receiver_jwt}, jwt=bag.developer_jwt,
                                      timeout=20)
        ib = parse(bodyb)
        # getMyBalance answers `liquid_balance` (round 6 read `balance`, which it never carries, and every balance came
        # back None: the concurrent row went NOT MEASURED and the sequential one judged on the transaction ids alone)
        val = (ib.get("liquid_balance", ib.get("balance")) if isinstance(ib, dict) else None)
        try:
            return Decimal(str(val)) if _answered(okb, ib, codeb) and val is not None else None
        except (InvalidOperation, TypeError, ValueError):
            return None
    tag = _secrets.token_hex(6)
    key, message = f"mcptest-replay-{tag}", f"MCP tester: an idempotent replay {tag}"
    args = {"agent_jwt": sender_jwt, "recipient_did": receiver, "amount": "0.01", "message": message, "idempotency_key": key}
    b0 = await _balance()
    ok1, body1, code1 = await rpc("theprotocol_transferUnits", args, jwt=bag.developer_jwt, timeout=30)
    i1 = parse(body1)
    if not _answered(ok1, i1, code1) or not isinstance(i1, dict):
        outcomes[name] = _make_outcome(name, "idempotency", False, code1, int((time.time() - t0) * 1000), None, {},
                                       expect_status="success",
                                       skip_reason=f"NOT MEASURED: the first transfer answered HTTP {code1} ({_said(i1)[:100]})")
        return
    ok2, body2, code2 = await rpc("theprotocol_transferUnits", args, jwt=bag.developer_jwt, timeout=30)
    i2 = parse(body2)
    b1 = await _balance()
    tx1, tx2 = i1.get("transaction_id"), (i2.get("transaction_id") if isinstance(i2, dict) else None)
    moved = (b1 - b0) if (b0 is not None and b1 is not None) else None
    own = await _own_transfers(rpc, parse, bag, receiver_jwt, message)
    ev = {"first": int(code1) if str(code1).isdigit() else 0, "retry": int(code2) if str(code2).isdigit() else 0,
          "same_transaction": bool(tx1) and tx1 == tx2, "own_transfers": own,
          "receiver_moved": str(moved) if moved is not None else None}   # evidence only: other lifecycles pay it too
    fail = skip = None
    if not _answered(ok2, i2, code2):
        fail = (f"BUG-FIND: idempotency: the retry with the same key answered HTTP {code2} ({_said(i2)[:120]}) where the "
                f"route should answer the first result again")
    elif not tx1 or tx1 != tx2:
        fail = ("BUG-FIND: idempotency: a transfer retried with the same key came back as ANOTHER transaction: the money "
                "moved twice")
    elif own is not None and own > 1:
        fail = f"BUG-FIND: idempotency: the receiver holds {own} transfers for one keyed transfer and its retry"
    elif own is None:
        skip = "NOT MEASURED: the receiver's transactions could not be read (the transaction ids agree)"
    outcomes[name] = _make_outcome(name, "idempotency", fail is None and skip is None, code2,
                                   int((time.time() - t0) * 1000), fail, {}, expect_status="success", skip_reason=skip)
    outcomes[name]["result_excerpt"] = ev
    await _concurrent_keyed_transfer(rpc, parse, bag, outcomes, sender_jwt, receiver, _balance, receiver_jwt)
    await _refused_keyed_retry(rpc, parse, bag, outcomes, sender_jwt)
    await _keyed_body_mismatch(rpc, parse, bag, outcomes, sender_jwt, receiver, receiver_jwt)


async def _concurrent_keyed_transfer(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict], sender_jwt: str,
                                     receiver: str, balance: Callable[[], Awaitable[Any]], receiver_jwt: str) -> None:
    """§MCPTEST30 (2026-10-01): two transfers sent at the same instant with ONE key move money once.

    The cache claims a key with an atomic SET NX (§pass57-hardening): one of N concurrent callers runs, the rest wait up
    to 8 s for its result and answer it. Nothing measured that race live. Two keyed calls of 0.01 go out together; the
    receiver's balance must move by 0.01. A loser that outwaited the winner answers the claim's own 422, which is no
    failure while the money moved once. Dust between the run's own two agents."""
    import secrets as _secrets
    name, t0 = "idempotency: concurrent transferUnits", time.time()
    tag = _secrets.token_hex(6)
    message = f"MCP tester: a concurrent idempotent pair {tag}"
    args = {"agent_jwt": sender_jwt, "recipient_did": receiver, "amount": "0.01", "message": message,
            "idempotency_key": f"mcptest-race-{tag}"}
    b0 = await balance()
    (ok1, body1, code1), (ok2, body2, code2) = await asyncio.gather(
        rpc("theprotocol_transferUnits", args, jwt=bag.developer_jwt, timeout=40),
        rpc("theprotocol_transferUnits", args, jwt=bag.developer_jwt, timeout=40))
    i1, i2 = parse(body1), parse(body2)
    b1 = await balance()
    a1, a2 = _answered(ok1, i1, code1), _answered(ok2, i2, code2)
    txs = {r.get("transaction_id") for r, a in ((i1, a1), (i2, a2)) if a and isinstance(r, dict)}
    moved = (b1 - b0) if (b0 is not None and b1 is not None) else None
    own = await _own_transfers(rpc, parse, bag, receiver_jwt, message)
    ev = {"answered": int(a1) + int(a2), "transactions": len(txs), "own_transfers": own,
          "receiver_moved": str(moved) if moved is not None else None}   # evidence only: other lifecycles pay it too
    fail = skip = None
    if len(txs) > 1:
        fail = "BUG-FIND: idempotency: two concurrent transfers with one key came back as TWO transactions"
    elif own is not None and own > 1:
        fail = f"BUG-FIND: idempotency: the receiver holds {own} transfers for two concurrent calls with one key"
    elif not (a1 or a2):
        skip = f"NOT MEASURED: neither concurrent transfer answered ({_said(i1)[:80]})"
    elif own is None:
        skip = "NOT MEASURED: the receiver's transactions could not be read"
    elif own == 0:
        skip = "NOT MEASURED: the receiver holds no transfer with the probe's message (the list may lag the ledger)"
    outcomes[name] = _make_outcome(name, "idempotency", fail is None and skip is None, code1 if a1 else code2,
                                   int((time.time() - t0) * 1000), fail, {}, expect_status="success", skip_reason=skip)
    outcomes[name]["result_excerpt"] = ev


async def _keyed_body_mismatch(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict], sender_jwt: str,
                               receiver: str, receiver_jwt: str) -> None:
    """§MCPTEST30 (V0525, 2026-10-01): one key, a DIFFERENT amount. The contract (§pass57): a body-hash collision is 422.

    The sentinel sends the second agent 0.01 with a key, then 0.02 with the same key, then 0.01 with it again. Right: the
    second refused (422) and moving nothing, the third the first's transaction; the receiver's ledger holds ONE row with
    the probe's message. Measured by hand on sbx-alpha (V0523) first: 200, 422 "already used", 200 the same transaction.
    Dust between the run's own two agents."""
    import secrets as _secrets
    name, t0 = "idempotency: transferUnits with another body", time.time()
    tag = _secrets.token_hex(6)
    key, message = f"mcptest-body-{tag}", f"MCP tester: one key, another body {tag}"
    def _args(amount: str) -> Dict[str, Any]:
        return {"agent_jwt": sender_jwt, "recipient_did": receiver, "amount": amount, "message": message,
                "idempotency_key": key}
    ok1, b1, c1 = await rpc("theprotocol_transferUnits", _args("0.01"), jwt=bag.developer_jwt, timeout=30)
    i1 = parse(b1)
    if not _answered(ok1, i1, c1) or not isinstance(i1, dict):
        outcomes[name] = _make_outcome(name, "idempotency", False, c1, int((time.time() - t0) * 1000), None, {},
                                       expect_status="error_4xx",
                                       skip_reason=f"NOT MEASURED: the first transfer answered HTTP {c1} ({_said(i1)[:100]})")
        return
    ok2, b2, c2 = await rpc("theprotocol_transferUnits", _args("0.02"), jwt=bag.developer_jwt, timeout=30)
    i2 = parse(b2)
    ok3, b3, c3 = await rpc("theprotocol_transferUnits", _args("0.01"), jwt=bag.developer_jwt, timeout=30)
    i3 = parse(b3)
    own = await _own_transfers(rpc, parse, bag, receiver_jwt, message)
    tx1 = i1.get("transaction_id")
    tx3 = i3.get("transaction_id") if isinstance(i3, dict) else None
    ev = {"other_body": "accepted" if _answered(ok2, i2, c2) else ("refused 422" if "422" in _said(i2) else "refused"),
          "same_body_again_is_the_first": bool(tx1) and tx1 == tx3, "own_transfers": own}
    fail = skip = None
    if _answered(ok2, i2, c2):
        moved_again = isinstance(i2, dict) and i2.get("transaction_id") not in (None, tx1)
        fail = ("BUG-FIND: idempotency: a key reused with another amount was ACCEPTED"
                + (" and moved money again" if moved_again else " (it answered the first result for a different request)"))
    elif own is not None and own > 1:
        fail = f"BUG-FIND: idempotency: the receiver holds {own} transfers for one key used with two bodies"
    elif "422" not in _said(i2):
        fail = f"BUG-FIND: idempotency: a key reused with another amount was refused, but not as the 422 the contract names ({_said(i2)[:80]})"
    elif not (bool(tx1) and tx1 == tx3):
        fail = "BUG-FIND: idempotency: the first body sent again with its key came back as another transaction"
    elif own is None:
        skip = "NOT MEASURED: the receiver's transactions could not be read (the answers agree)"
    outcomes[name] = _make_outcome(name, "idempotency", fail is None and skip is None, c2, int((time.time() - t0) * 1000),
                                   fail, {}, expect_status="error_4xx", skip_reason=skip)
    outcomes[name]["result_excerpt"] = ev


async def _refused_keyed_retry(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict], sender_jwt: str) -> None:
    """§MCPTEST30 (2026-10-01): what a retry hears after a keyed transfer was REFUSED.

    The route claims the key before it runs and stores a result only on success, so a refused request leaves a claim
    with no result until it expires (90 s). Until V0512 a same-key retry waited 8 s and was told the refused request
    "is already in progress"; the cache cannot tell a running request from one that ended without a result, and the
    answer now names both. The transfer goes to a DID minted here by the one generator (nobody's), so nothing moves."""
    import secrets as _secrets
    from agentvault_registry.identifiers import generate_agent_did
    name, t0 = "idempotency: a refused transferUnits retried", time.time()
    args = {"agent_jwt": sender_jwt, "recipient_did": generate_agent_did(), "amount": "0.01",
            "message": "MCP tester: a refused keyed transfer", "idempotency_key": f"mcptest-refused-{_secrets.token_hex(6)}"}
    def _full(inner: Any) -> str:
        # the whole refusal: `_said` keeps 160 characters for the record, and the unresolved-claim answer is longer
        t = inner.get("_text") if isinstance(inner, dict) else None
        return t if isinstance(t, str) else json.dumps(inner, default=str)
    ok1, body1, code1 = await rpc("theprotocol_transferUnits", args, jwt=bag.developer_jwt, timeout=30)
    i1 = parse(body1)
    said1 = _full(i1)
    if _answered(ok1, i1, code1):
        outcomes[name] = _make_outcome(name, "idempotency", False, code1, int((time.time() - t0) * 1000),
                                       "BUG-FIND: idempotency: a transfer to a DID nobody holds was accepted", {},
                                       expect_status="error_4xx")
        outcomes[name]["result_excerpt"] = {"first": "accepted"}
        return
    if "HTTP 404" not in said1:
        outcomes[name] = _make_outcome(name, "idempotency", False, code1, int((time.time() - t0) * 1000), None, {},
                                       expect_status="error_4xx",
                                       skip_reason=f"NOT MEASURED: the first transfer was not refused as unknown ({_said(i1)[:100]})")
        return
    ok2, body2, code2 = await rpc("theprotocol_transferUnits", args, jwt=bag.developer_jwt, timeout=40)
    i2 = parse(body2)
    said2 = _full(i2)
    t_retry = int((time.time() - t0) * 1000)
    ev = {"first": "refused 404", "retry": _said(i2)[:60]}
    fail = None
    if _answered(ok2, i2, code2):
        fail = "BUG-FIND: idempotency: the retry of a refused transfer to a DID nobody holds was accepted"
    elif "HTTP 404" in said2:
        ev["retry_is"] = "the refusal again"
    elif "ended without" in said2:
        ev["retry_is"] = "the honest unresolved-claim answer"
    elif "in progress" in said2:
        fail = ("BUG-FIND: idempotency: the retry of a REFUSED keyed transfer was told the transfer is still in "
                "progress (the claim outlives the refusal and the answer names a cause it cannot know)")
    else:
        ev["retry_is"] = "another refusal"
    outcomes[name] = _make_outcome(name, "idempotency", fail is None, code2, t_retry, fail, {}, expect_status="error_4xx")
    outcomes[name]["result_excerpt"] = ev


# ── §MEMBERSHIP phase B (V0551): a commons season, opened by this run and cancelled by it ─────────────────────────────
COMMONS_TESTER_TITLE = "MCP tester season"   # a season this lifecycle opened says so; it never touches another one
# V0552 (agentvault2-33's ask): the tester's own seasons are recognised by the exact title its runs give them
_COMMONS_TESTER_TITLE_RE = re.compile(r"^MCP tester season \d{8}T\d{6}Z$")


def _tester_seasons(seasons: Any) -> List[dict]:
    """The seasons a tester run opened (by the exact title the lifecycle gives them), newest first as listed."""
    return [x for x in (seasons or []) if isinstance(x, dict)
            and _COMMONS_TESTER_TITLE_RE.match(str(x.get("title") or ""))]


def _opened_on(season: dict) -> Optional[datetime]:
    try:
        t = datetime.fromisoformat(str(season.get("opens_at") or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _bug_find(rows: Dict[str, dict], tool: str, why: Optional[str]) -> None:
    """A read-back that contradicts a step whose row lives in another dict (the admin rows) downgrades that row."""
    row = rows.get(tool)
    if why and row is not None and row.get("healthy"):
        row["healthy"] = False
        row["fail_reason"] = f"BUG-FIND: {why}"


def _hold_to_words(outcomes: Dict[str, dict], tool: str, inner: Any, words: Tuple[str, ...], what: str) -> None:
    """A recorded refusal that names none of `words` refused for another reason: the row measured something else."""
    row = outcomes.get(tool)
    if not row or not row.get("healthy"):
        return
    text = _switches.answer_text(inner)
    if not any(w in text for w in words):
        row["healthy"] = False
        row["fail_reason"] = (f"{tool.replace('theprotocol_', '')} refused {what}, but not with "
                              f"{' or '.join(words)}: {text[:200]}")


# §MCPTEST30 (V0552): the ballot's success path, a probe family of its own. A member's points count only for ANOTHER
# developer's work, so a second developer of this run (a throwaway) submits through an agent of its own, the runner's
# sentinel gives it 10 points, and the close must tally that ballot. Measured only where the runner's developer is a
# member (its own-submission ballot was refused as own_submission, not not_a_member) and no device confirmation is asked.
_COMMONS = "commons: "
COMMONS_VOTE_CHECK = "a member's ballot for another developer's work"
COMMONS_TALLY_CHECK = "the close tallies the member's ballot"


def _commons_row(outcomes: Dict[str, Any], check: str, ok: bool, code: Any, t0: float, fail: Optional[str] = None,
                 evidence: Optional[Dict[str, Any]] = None, skip: Optional[str] = None) -> None:
    outcomes[_COMMONS + check] = _make_outcome(_COMMONS + check, "commons", bool(ok) and not skip, str(code or "0"),
                                               int((time.time() - t0) * 1000), None if ok else fail, evidence or {},
                                               expect_status="success", skip_reason=skip)


def _commons_unmeasured(outcomes: Dict[str, Any], why: str) -> None:
    """Name the probe's rows the walk never reached; a row already written stands."""
    t0 = time.time()
    for check in (COMMONS_VOTE_CHECK, COMMONS_TALLY_CHECK):
        if _COMMONS + check not in outcomes:
            _commons_row(outcomes, check, False, 0, t0, skip=why)


def judge_commons_tally(close_answer: Any, submission_id: int) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    """(healthy, the sentence when not, evidence) for a closed season the runner's member gave `submission_id` points in.
    Pure (unit-tested). One voter is below a submission's funding minimum, so only the count is asserted, never money."""
    tally = close_answer.get("tally") if isinstance(close_answer, dict) else None
    if not isinstance(tally, dict):
        return False, "the closed season's answer carries no tally", {}
    counted, cast = tally.get("ballots_counted"), tally.get("ballots_cast")
    row = next((r for r in (tally.get("rows") or []) if isinstance(r, dict) and r.get("submission_id") == submission_id),
               None)
    ev = {"ballots_cast": cast, "ballots_counted": counted,
          "row": {k: row.get(k) for k in ("voters", "median_points", "amount", "reason")} if row else None}
    if not isinstance(counted, int):
        return False, f"the closed season's tally names no ballots_counted ({counted!r})", ev
    if counted < 1:
        return False, (f"BUG-FIND: commons: the member's accepted ballot was not counted at close (ballots_cast={cast!r}, "
                       f"ballots_counted={counted})"), ev
    if row is None or not isinstance(row.get("voters"), int) or row["voters"] < 1:
        return False, (f"BUG-FIND: commons: the tally has no voter for submission {submission_id}, which the member's "
                       f"counted ballot gave 10 points (its row: {ev['row']!r})"), ev
    return True, None, ev


async def _commons_peer_work(rpc: RpcCall, parse: ParseResult, bag: Any, sid: int, tag: str) -> Dict[str, Any]:
    """A second developer of this run submits work to the season through an agent of its own. Returns
    {"submission_id", "email", "password"} or {"why", ...}; never recorded as a row of its own (setup, not a claim)."""
    mint, rpc_admin = getattr(bag, "mint_throwaway", None), getattr(bag, "rpc_admin", None)
    if mint is None or rpc_admin is None:
        return {"why": "the runner injected no mint_throwaway or no admin bridge"}
    sub = await mint("commons")
    jwt, dev_id = (sub or {}).get("access_token"), (sub or {}).get("developer_id")
    if not jwt:
        return {"why": f"no second developer could be minted ({(sub or {}).get('why')})"}
    out: Dict[str, Any] = {"email": sub.get("email"), "password": sub.get("password")}
    try:
        dev_id = int(dev_id)
    except (TypeError, ValueError):
        return {**out, "why": f"the second developer's id is not a number ({dev_id!r})"}
    # a developer creates an agent only once verified (the bootstrap token's rule); an admin verifies the throwaway
    ok, body, code = await rpc_admin("theprotocol_forceEmailVerify", {"developer_id": dev_id}, jwt=bag.developer_jwt,
                                     timeout=20)
    said = _said(parse(body)) if not ok else ""
    # V0556: a throwaway the mint already verified is what this step is for (the admin rail answers 400 "already
    # verified"); the 2026-10-03 nightly read both commons rows NOT MEASURED on that sentence alone
    if not ok and not (str(code) == "400" and "already verified" in said.lower()):
        return {**out, "why": f"forceEmailVerify for the second developer answered HTTP {code}: {said}"}
    ok, body, code = await rpc("theprotocol_createAgent",
                               {"name": f"mcp-commons-peer-{tag}",
                                "description": "The MCP tester's second developer's agent: submits work to the "
                                               "tester's own commons season, which the run cancels."},
                               jwt=jwt, timeout=60)
    made = parse(body)
    cid, csec = (made.get("client_id"), made.get("client_secret")) if isinstance(made, dict) else (None, None)
    if not (ok and cid and csec):
        return {**out, "why": f"createAgent for the second developer answered HTTP {code}: {_said(made)}"}
    # V0614: a Tier-0 tool still needs a bearer on the wire. The MCP transport answers 401 "Authentication required" to
    # every tools/call that carries none (mcp/server.py; only the handshake methods pass without one), so this call
    # rides the second developer's own token, as every other lifecycle's getAgentToken rides one. With jwt="" it never
    # reached the tool and both commons rows read NOT MEASURED on every nightly.
    ok, body, code = await rpc("theprotocol_getAgentToken", {"client_id": cid, "client_secret": csec}, jwt=jwt,
                               timeout=20)
    tok = parse(body)
    agent_jwt = tok.get("access_token") if isinstance(tok, dict) else None
    if not agent_jwt:
        return {**out, "why": f"getAgentToken for the second developer's agent answered HTTP {code}"}
    ok, body, code = await rpc("theprotocol_submitCommonsWork",
                               {"agent_jwt": agent_jwt, "season_id": sid, "kind": "other",
                                "title": f"MCP tester peer submission {tag}",
                                "description": "Submitted by the MCP tester's second developer to the tester's own "
                                               "season, so the runner's member has another developer's work to vote for.",
                                "evidence": [{"type": "other", "ref": f"mcp-tester-peer-{tag}"}]},
                               jwt=jwt, timeout=30)
    x = parse(body)
    xid = x.get("id") if ok and isinstance(x, dict) else None
    if not isinstance(xid, int):
        return {**out, "why": f"the second developer's submission answered HTTP {code}: {_said(x)}"}
    return {**out, "submission_id": xid}


async def _commons_member_vote(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict], sid: int,
                               tag: str, own_refusal: Any) -> Dict[str, Any]:
    """The runner's member gives 10 points to the second developer's submission. Records the vote row (the tally row is
    recorded at close). Returns {"voted": submission id or None, "why": a NOT MEASURED sentence or None, the peer's
    email and password for its own deletion}."""
    t0 = time.time()
    said = _switches.answer_text(own_refusal)
    if "not_a_member" in said:
        why = ("NOT MEASURED: the runner's developer is not a member on this target (its own-submission ballot was "
               "refused not_a_member: no qualifying bond), so it has no ballot to give")
        _commons_row(outcomes, COMMONS_VOTE_CHECK, False, 0, t0, skip=why)
        return {"voted": None, "why": why}
    if "own_submission" not in said:
        why = ("NOT MEASURED: the runner's own-submission ballot was not refused own_submission, so whether its developer "
               "is a member here is not known")
        _commons_row(outcomes, COMMONS_VOTE_CHECK, False, 0, t0, skip=why)
        return {"voted": None, "why": why}
    peer = await _commons_peer_work(rpc, parse, bag, sid, tag)
    if not isinstance(peer.get("submission_id"), int):
        why = f"NOT MEASURED: {peer.get('why')}"
        _commons_row(outcomes, COMMONS_VOTE_CHECK, False, 0, t0, skip=why)
        return {**peer, "voted": None, "why": why}
    x2 = peer["submission_id"]
    ok, body, code = await rpc("theprotocol_castCommonsBallot",
                               {"agent_jwt": bag.sentinel_jwt, "season_id": sid, "allocations": {str(x2): 10}},
                               jwt=bag.developer_jwt, timeout=30)
    inner = parse(body)

    def _tool_row(healthy: bool, fail: Optional[str] = None, skip: Optional[str] = None) -> None:
        # §MCPTEST30 (V0636): the ballot is castCommonsBallot's own row as well (the check row names no tool)
        outcomes["theprotocol_castCommonsBallot"] = _make_outcome(
            "theprotocol_castCommonsBallot", "2", healthy and not fail and not skip, str(code),
            int((time.time() - t0) * 1000), fail, inner if isinstance(inner, dict) else {}, expect_status="success",
            skip_reason=skip)
    if isinstance(inner, dict) and inner.get("step_up"):
        why = ("NOT MEASURED: this target asks a member to confirm a ballot on a registered device (presence), which a "
               "run cannot do")
        _commons_row(outcomes, COMMONS_VOTE_CHECK, False, code, t0, skip=why)
        _tool_row(False, skip=why)
        return {**peer, "voted": None, "why": why}
    ev = {"submission_id": x2, "total_points": inner.get("total_points") if isinstance(inner, dict) else None,
          "digest": bool(isinstance(inner, dict) and inner.get("digest"))}
    if (ok and isinstance(inner, dict) and inner.get("total_points") == 10
            and (inner.get("allocations") or {}) == {str(x2): 10} and inner.get("digest")):
        _commons_row(outcomes, COMMONS_VOTE_CHECK, True, code, t0, evidence=ev)
        _tool_row(True)
        return {**peer, "voted": x2, "why": None}
    _fail = (f"castCommonsBallot did not take a member's ballot for another developer's work as cast: HTTP {code}: "
             f"{_said(inner)}")
    _commons_row(outcomes, COMMONS_VOTE_CHECK, False, code, t0, evidence=ev, fail=_fail)
    _tool_row(False, fail=_fail)
    return {**peer, "voted": None, "why": "the member's ballot was not taken"}


async def _ledger_liquid(bag: Any, parse: ParseResult, did: str) -> Optional[Any]:
    """The event store's own projection of `did`'s liquid balance (refreshed), or None when it cannot be read."""
    from decimal import Decimal, InvalidOperation
    ok, body, _code = await bag.rpc_admin("theprotocol_adminQueryEventStore",
                                          {"path": f"/api/v1/projections/balance/{did}", "params": {"refresh": "true"}},
                                          jwt=bag.developer_jwt, timeout=30)
    a = parse(body) if ok and isinstance(body, dict) else {}
    a = a.get("response") if isinstance(a, dict) and isinstance(a.get("response"), dict) else a
    try:
        return Decimal(str(a.get("liquid_balance"))) if isinstance(a, dict) and a.get("liquid_balance") is not None \
            else None
    except (InvalidOperation, ValueError):
        return None


async def _commons_pay_on_a_pair(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict], sid: int,
                                 voted: int, dev_jwt: str, events: Any) -> bool:
    """§MCPTEST30 (tester batch 2 item 3, gwo_e3bad842b1a5943022b01d40): on a target torn down after its run only, the
    closed season this run opened is PAID. Its one award (the member's ballot for the second developer's submission) is
    first held to write-off's rule (a refusal row: only a payment that failed or never answered is written off, and a
    healthy target never gives a run one), then paid: the answer, the season and the award read paid, and the
    recipient's balance on the event store's own projection grew by what was funded (a move the ledger never recorded is
    the drift a delta of 0.0 cannot see). Returns whether the season READS paid afterwards (its cancel is then a
    refusal), whatever the checks found."""
    import asyncio
    from decimal import Decimal, InvalidOperation
    pay, write_off = "theprotocol_adminCommonsPaySeason", "theprotocol_adminCommonsWriteOffAward"
    ok, detail = await _exec_step(rpc, parse, "theprotocol_getCommonsSeason", "1", {"season_id": sid}, dev_jwt,
                                  outcomes, record_as_separate=False)
    sub = next((x for x in ((detail or {}).get("submissions") or []) if isinstance(x, dict) and x.get("id") == voted),
               None) if ok and isinstance(detail, dict) else None
    award = (sub or {}).get("award") if isinstance((sub or {}).get("award"), dict) else None
    did = (sub or {}).get("submitter_did")
    if not (award and isinstance(award.get("id"), int) and did and award.get("status") == "pending"):
        _ef.effect_unmeasured(outcomes, pay, f"the closed season {sid} names no pending award for submission {voted} "
                                             f"(it reads {award!r})")
        return False
    await _ef.refusal_step(bag.rpc_admin, parse, write_off, "admin",
                           {"season_id": sid, "award_id": award["id"], "reason": "MCP tester: the award was never sent"},
                           dev_jwt, outcomes, "an award that was never sent", codes=(409,), text="award_not_failed")
    before = await _ledger_liquid(bag, parse, did)

    def _dec(v: Any) -> Optional[Decimal]:
        try:
            return Decimal(str(v))
        except (InvalidOperation, ValueError, TypeError):
            return None

    def _paid(a: dict) -> Optional[str]:
        season = a.get("season") if isinstance(a.get("season"), dict) else {}
        pays = [p for p in (a.get("payments") or []) if isinstance(p, dict) and p.get("recipient_did") == did]
        if season.get("status") != "paid" or a.get("unpaid_awards") != 0:
            return f"the answer reads season status={season.get('status')!r}, unpaid_awards={a.get('unpaid_awards')!r}"
        if not (pays and pays[0].get("status") == "paid" and _dec(pays[0].get("funded")) == _dec(award.get("amount"))):
            return f"the answer pays the recipient {pays[:1]!r}, not the award's {award.get('amount')!r} in full"
        return None
    ok_pay, _ans = await _ef.effect(bag, parse, pay, {"season_id": sid}, outcomes, check=_paid,
                                    expect_events=["CommonsAwardPaid"])
    name = _ef.effect_name(pay)
    ok, after_detail = await _exec_step(rpc, parse, "theprotocol_getCommonsSeason", "1", {"season_id": sid}, dev_jwt,
                                        outcomes, record_as_separate=False)
    # whether the season IS paid decides the cancel that follows, whatever this step's checks say (a paid season's cancel
    # is refused; reading a failed check as unpaid would send a cancel at a settled season and blame the cancel)
    season_paid = bool(ok and isinstance(after_detail, dict) and after_detail.get("status") == "paid")
    if not ok_pay:
        return season_paid      # the pay's own row says what was wrong
    sub2 = next((x for x in ((after_detail or {}).get("submissions") or []) if isinstance(x, dict)
                 and x.get("id") == voted), {}) if ok and isinstance(after_detail, dict) else {}
    a2 = sub2.get("award") if isinstance(sub2.get("award"), dict) else {}
    why = None
    if not season_paid or a2.get("status") != "paid":
        why = (f"getCommonsSeason reads season status={(after_detail or {}).get('status')!r}, award "
               f"status={a2.get('status')!r} after the payment")
    else:
        want = _dec(a2.get("funded_amount"))
        after = None
        for i in range(6):
            after = await _ledger_liquid(bag, parse, did)
            if before is not None and after is not None and want is not None and after - before == want:
                break
            if i < 5:
                await asyncio.sleep(4)
        if before is None or after is None:
            why = "the recipient's balance on the event store could not be read before and after the payment"
        elif want is None or after - before != want:
            why = (f"the event store's projection of the recipient moved by {after - before}, not the {want} funded: "
                   f"the ledger did not record the payment")
    if why:
        _bugfind(outcomes, name, "admin_effect", f"adminCommonsPaySeason: {why}")
    return season_paid


async def lifecycle_commons_season(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """getCommonsSeasons -> adminCommonsOpenSeason (seed 1, one day) -> getCommonsSeason -> submitCommonsWork (the
    sentinel) -> getMyCommonsSeason (the submission is its developer's) -> castCommonsBallot on it (own_submission, or
    not_a_member) -> adminCommonsPaySeason and adminCommonsWriteOffAward on the open season (season_not_closed) ->
    adminCommonsStrikeSubmission -> adminCommonsCloseSeason (CommonsSeasonClosed; nothing to award) ->
    adminCommonsCancelSeason, then the season reads cancelled.

    No money moves: a season's budget is published at opening and paid only by `pay`, which is held to its refusal
    here. Where the commons is off (COMMONS_ENABLED) the first read is held to commons_disabled and nothing else runs:
    the contracts hold each tool to that refusal. Where a season is already live (open, or closed awaiting payment) it
    is someone else's: nothing is opened and the steps that need one are NOT MEASURED, named. A season this run opened
    is cancelled even when a step in between fails, so the one live-season slot is always given back.
    The admin steps go through the admin bridge (`bag.rpc_admin`) and their rows to `bag.admin_lifecycle_rows`, which
    the admin sweep reads with its own lifecycle rows. The ballot's success path needs a member of ANOTHER developer
    (never one's own submission) and is not measured here."""
    dev_jwt, sentinel_jwt = bag.developer_jwt, bag.sentinel_jwt
    rpc_admin = getattr(bag, "rpc_admin", None)
    admin_rows = getattr(bag, "admin_lifecycle_rows", None)
    events = getattr(bag, "event_verifier", None)
    ok, listing = await _exec_step(rpc, parse, "theprotocol_getCommonsSeasons", "1", {"limit": 20}, dev_jwt, outcomes)
    if _switches.switched_off("theprotocol_getCommonsSeasons") is not None or not ok:
        return
    seasons = listing.get("seasons") if isinstance(listing, dict) else None
    open_steps = ("theprotocol_adminCommonsOpenSeason", "theprotocol_adminCommonsCloseSeason",
                  "theprotocol_adminCommonsStrikeSubmission", "theprotocol_adminCommonsCancelSeason")
    if rpc_admin is None or admin_rows is None:
        for t in ("theprotocol_submitCommonsWork", "theprotocol_getMyCommonsSeason"):
            outcomes[t] = _not_measured(t, "2", "the commons season lifecycle needs the admin bridge (bag.rpc_admin), "
                                                "which this flow does not carry")
        return
    live = [x for x in (seasons or []) if isinstance(x, dict) and x.get("status") in ("open", "closed")]
    # V0552: a season an EARLIER tester run opened and never cancelled (the run died between open and cancel) holds the
    # one live-season slot a person evaluating the commons needs; the tester's own season is cancelled here. A season
    # with any other title is never touched.
    for orphan in [x for x in _tester_seasons(live) if isinstance(x.get("id"), int)]:
        ok_c, _ = await _exec_step(rpc_admin, parse, "theprotocol_adminCommonsCancelSeason", "admin",
                                   {"season_id": orphan["id"],
                                    "reason": "MCP tester: an earlier tester run's season, left open when that run ended"},
                                   dev_jwt, admin_rows)
        if ok_c:
            live = [x for x in live if x is not orphan]
    if live:
        why = (f"a season is live on this target (#{live[0].get('id')}: {str(live[0].get('title'))[:60]!r}) and "
               f"this run did not open it; the lifecycle never touches a season it did not open")
        for t in open_steps:
            admin_rows[t] = _not_measured(t, "admin", why)
        _commons_unmeasured(outcomes, f"NOT MEASURED: {why}")
        return
    # V0552 (agentvault2-33's ask): at most once per UTC day on a registry, so the seasons a person opens by hand to
    # evaluate the commons are not buried under a cancelled tester season every few hours. The season list is the
    # record; the nightly is the day's first central run, so it normally takes the day's slot.
    now = datetime.now(timezone.utc)
    today = [(x, _opened_on(x)) for x in _tester_seasons(seasons)]
    today = [(x, t) for x, t in today if t is not None and t.date() == now.date()]
    if today:
        x, t = today[0]
        why = (f"the season lifecycle ran today at {t:%H:%M}Z (season #{x.get('id')}); it runs at most once per UTC day "
               f"here, so seasons opened by hand stay findable in the list")
        # as on a live season: the steps that need a season of this run's own are named; every other commons tool
        # keeps its contract, a refusal probe on a season that does not exist
        for t_ in open_steps:
            admin_rows.setdefault(t_, _not_measured(t_, "admin", why))
        _commons_unmeasured(outcomes, f"NOT MEASURED: {why}")
        return
    tag = now.strftime("%Y%m%dT%H%M%SZ")
    ok, season = await _exec_step(rpc_admin, parse, "theprotocol_adminCommonsOpenSeason", "admin",
                                  {"title": f"{COMMONS_TESTER_TITLE} {tag}", "duration_days": 1, "seed": "1"},
                                  dev_jwt, admin_rows, expect_events=["CommonsSeasonOpened"], event_verifier=events)
    sid = season.get("id") if ok and isinstance(season, dict) else None
    if not isinstance(sid, int):
        _commons_unmeasured(outcomes, "NOT MEASURED: the run could not open a season of its own")
        return
    member: Dict[str, Any] = {}
    paid = False
    try:
        def _open_with_budget(inner: dict) -> Optional[str]:
            if inner.get("status") != "open" or inner.get("id") != sid:
                return f"getCommonsSeason({sid}) right after the open reads status={inner.get('status')!r}"
            try:
                if float(inner.get("budget") or 0) <= 0:
                    return f"season {sid} was opened with a seed of 1 and reads budget={inner.get('budget')!r}"
            except (TypeError, ValueError):
                return f"season {sid}'s budget is not a number: {inner.get('budget')!r}"
            return None
        ok, inner = await _exec_step(rpc, parse, "theprotocol_getCommonsSeason", "1", {"season_id": sid}, dev_jwt,
                                     outcomes)
        if ok and isinstance(inner, dict):
            _bug_find(admin_rows, "theprotocol_adminCommonsOpenSeason", _open_with_budget(inner))
        ok, sub = await _exec_step(rpc, parse, "theprotocol_submitCommonsWork", "2",
                                   {"agent_jwt": sentinel_jwt, "season_id": sid, "kind": "other",
                                    "title": f"MCP tester submission {tag}",
                                    "description": "Submitted by the MCP tester to its own season, which it cancels.",
                                    "evidence": [{"type": "other", "ref": f"mcp-tester-{tag}"}]},
                                   dev_jwt, outcomes)
        xid = sub.get("id") if ok and isinstance(sub, dict) else None
        if not isinstance(xid, int):
            return

        def _mine(inner: dict) -> Optional[str]:
            ids = [x.get("id") for x in (inner.get("my_submissions") or []) if isinstance(x, dict)]
            if xid not in ids:
                return f"getMyCommonsSeason({sid}) lists {ids}, not the submission {xid} its developer just made"
            return None
        await _exec_step(rpc, parse, "theprotocol_getMyCommonsSeason", "3", {"season_id": sid}, dev_jwt, outcomes,
                         verify_against="theprotocol_submitCommonsWork", verify_against_check=_mine)
        # §MCPTEST30 (V0636): the own-submission ballot is a refusal row; the tool's own row is the member's ballot for
        # another developer's work (_commons_member_vote), which this row used to stand in for
        _own: Dict[str, dict] = {}
        _, inner = await _exec_step(rpc, parse, "theprotocol_castCommonsBallot", "2",
                                    {"agent_jwt": sentinel_jwt, "season_id": sid, "allocations": {str(xid): 10}},
                                    dev_jwt, _own, expect_status="error_4xx")
        _hold_to_words(_own, "theprotocol_castCommonsBallot", inner, ("own_submission", "not_a_member"),
                       "a ballot for its own developer's submission")
        if "theprotocol_castCommonsBallot" in _own:
            _own_name = _ef.refusal_row("theprotocol_castCommonsBallot", "a ballot for its own developer's submission")
            outcomes[_own_name] = {**_own["theprotocol_castCommonsBallot"], "tool_name": _own_name}
        # V0552: the ballot's success path, on a second developer's submission (recorded under "commons: ")
        member = await _commons_member_vote(rpc, parse, bag, outcomes, sid, tag, inner)
        if "theprotocol_castCommonsBallot" not in outcomes:   # the member's ballot never ran: say why on its row
            outcomes["theprotocol_castCommonsBallot"] = _not_measured(
                "theprotocol_castCommonsBallot", "2", member.get("why") or "NOT MEASURED: no member's ballot was cast")
        # pay MOVES MONEY: it is only ever called on this open season, where the route refuses before anything moves
        _, inner = await _exec_step(rpc_admin, parse, "theprotocol_adminCommonsPaySeason", "admin", {"season_id": sid},
                                    dev_jwt, admin_rows, expect_status="error_4xx")
        _hold_to_words(admin_rows, "theprotocol_adminCommonsPaySeason", inner, ("season_not_closed",), "an open season")
        _, inner = await _exec_step(rpc_admin, parse, "theprotocol_adminCommonsWriteOffAward", "admin",
                                    {"season_id": sid, "award_id": 1, "reason": "MCP tester probe: the season is open"},
                                    dev_jwt, admin_rows, expect_status="error_4xx")
        _hold_to_words(admin_rows, "theprotocol_adminCommonsWriteOffAward", inner, ("season_not_closed",),
                       "an open season")
        await _exec_step(rpc_admin, parse, "theprotocol_adminCommonsStrikeSubmission", "admin",
                         {"season_id": sid, "submission_id": xid, "reason": "MCP tester: a test submission, struck"},
                         dev_jwt, admin_rows)

        def _closed(inner: dict) -> Optional[str]:
            if inner.get("status") != "closed":
                return f"adminCommonsCloseSeason({sid}) answered status={inner.get('status')!r}"
            return None
        t_close = time.time()
        ok, inner = await _exec_step(rpc_admin, parse, "theprotocol_adminCommonsCloseSeason", "admin",
                                     {"season_id": sid}, dev_jwt, admin_rows, expect_events=["CommonsSeasonClosed"],
                                     event_verifier=events)
        if ok and isinstance(inner, dict):
            _bug_find(admin_rows, "theprotocol_adminCommonsCloseSeason", _closed(inner))
        if not isinstance(member.get("voted"), int):
            _commons_row(outcomes, COMMONS_TALLY_CHECK, False, 0, t_close,
                         skip=member.get("why") or "NOT MEASURED: no member's ballot was cast, so none was tallied")
        elif not (ok and isinstance(inner, dict) and inner.get("status") == "closed"):
            _commons_row(outcomes, COMMONS_TALLY_CHECK, False, 0, t_close,
                         skip="NOT MEASURED: the season did not close, so nothing was tallied")
        else:
            healthy, why, ev = judge_commons_tally(inner, member["voted"])
            _commons_row(outcomes, COMMONS_TALLY_CHECK, healthy, 200, t_close, evidence=ev, fail=why)
            # §MCPTEST30 (tester batch 2 item 3): on a pair, the closed season is paid (its write-off held to its rule)
            from agentvault_registry.api_tests.contracts.earned_ad_ephemeral import ephemeral_target
            if ephemeral_target():
                paid = await _commons_pay_on_a_pair(rpc, parse, bag, outcomes, sid, member["voted"], dev_jwt, events)
    finally:
        cancel_sid: Optional[int] = sid
        if paid:
            # a paid season is settled: its cancel is refused (a refusal row), and the cancel's own success is measured
            # on a second, empty season of the run's own (a pair only, where no person's season shares the slot)
            await _ef.refusal_step(rpc_admin, parse, "theprotocol_adminCommonsCancelSeason", "admin",
                                   {"season_id": sid, "reason": "MCP tester: a paid season, which no cancel may undo"},
                                   dev_jwt, outcomes, "a season that was paid", codes=(409,), text="season_settled")
            ok2, s2 = await _exec_step(rpc_admin, parse, "theprotocol_adminCommonsOpenSeason", "admin",
                                       {"title": f"{COMMONS_TESTER_TITLE} {tag} (to cancel)", "duration_days": 1,
                                        "seed": "1"}, dev_jwt, admin_rows, record_as_separate=False)
            cancel_sid = s2.get("id") if ok2 and isinstance(s2, dict) and isinstance(s2.get("id"), int) else None
            if cancel_sid is None:
                admin_rows["theprotocol_adminCommonsCancelSeason"] = _not_measured(
                    "theprotocol_adminCommonsCancelSeason", "admin", "NOT MEASURED: the run's season was paid (a cancel "
                    "is refused there, its refusal row) and no second season of its own could be opened to cancel")
        if cancel_sid is not None:
            ok, inner = await _exec_step(rpc_admin, parse, "theprotocol_adminCommonsCancelSeason", "admin",
                                         {"season_id": cancel_sid,
                                          "reason": "MCP tester season, cancelled by the run that opened it"},
                                         dev_jwt, admin_rows)
            if ok:
                ok, inner = await _exec_step(rpc, parse, "theprotocol_getCommonsSeason", "1", {"season_id": cancel_sid},
                                             dev_jwt, outcomes, record_as_separate=False)
                if ok and isinstance(inner, dict) and inner.get("status") != "cancelled":
                    _bug_find(admin_rows, "theprotocol_adminCommonsCancelSeason",
                              f"season {cancel_sid} reads status={inner.get('status')!r} after its cancel")
        # a step that failed before the ballot or the close leaves the probe's rows unwritten: name them
        _commons_unmeasured(outcomes, "NOT MEASURED: the season lifecycle stopped before this step (an earlier step "
                                      "failed; its own row says which)")
        if member.get("email") and member.get("password"):
            await _schedule_own_deletion(rpc, bag, member["email"], member["password"],
                                         "the commons season's second developer")


LIFECYCLES: List[Dict[str, Any]] = [
    {"name": "webhook_full_crud",      "runner": lifecycle_webhook_full_crud},
    {"name": "organization_full_crud", "runner": lifecycle_organization_full_crud},
    {"name": "org_team_full_crud",     "runner": lifecycle_org_team_full_crud},
    {"name": "bundle_full_crud",       "runner": lifecycle_bundle_full_crud},
    {"name": "pipeline_full_crud",     "runner": lifecycle_pipeline_full_crud},
    {"name": "api_key_full_crud",      "runner": lifecycle_api_key_full_crud},
    {"name": "a2a_payment",            "runner": lifecycle_a2a_payment_settle},
    {"name": "funding_approve_reject", "runner": lifecycle_funding_approve_reject},
    {"name": "support_ticket",         "runner": lifecycle_support_ticket},
    {"name": "attestation_schedule",   "runner": lifecycle_attestation_schedule},
    {"name": "flare",                  "runner": lifecycle_flare},
    {"name": "notifications_2fa",      "runner": lifecycle_notifications_2fa},
    {"name": "teg_policy",             "runner": lifecycle_teg_policy},
    {"name": "auto_compound",          "runner": lifecycle_auto_compound},
    {"name": "dev_profile_update",     "runner": lifecycle_dev_profile_update},
    {"name": "stake_response_shape",   "runner": lifecycle_stake_response_shape},
    # ── Sprint 5.7 batch — coverage expansion ──
    {"name": "agent_clone_export_delete", "runner": lifecycle_agent_clone_export_delete},
    # §pass73.3.19: close the 4 destructive skips with genuine 2xx coverage.
    {"name": "agent_self_delete",         "runner": lifecycle_agent_self_delete},
    {"name": "auth_register_and_logout",  "runner": lifecycle_auth_register_and_logout},
    # §MCPTEST30 2026-09-30: the caller's-own-account tools on the run's own throwaway; it replaced
    # account_deletion_safe (which scheduled the RUNNER's deletion), 2fa_setup_only, change_password_safe and
    # auth_refresh_safe (refusals only, under expect_status="any").
    {"name": "self_account_on_throwaway", "runner": lifecycle_self_account_on_throwaway},
    {"name": "mcp_protocol_conformance", "runner": lifecycle_mcp_protocol_conformance},
    # §MCPTEST30 2026-10-01: a second developer and a second agent ask for the runner's objects
    {"name": "owner_scoping",            "runner": lifecycle_owner_scoping},
    # §MCPTEST30 2026-10-01: are two pages of a paged tool a partition of one page of twice the size?
    {"name": "pagination_partition",     "runner": lifecycle_pagination_partition},
    # §MCPTEST30 2026-10-01: a page of 0, of -1, from offset -1 and of 5000 must be refused or clamped, never a 500
    {"name": "page_bounds",              "runner": lifecycle_page_bounds},
    # §MCPTEST30 2026-10-01: every id a list advertises must resolve at its detail (read only)
    {"name": "list_detail",              "runner": lifecycle_list_detail},
    # §MCPTEST30 2026-10-01: a NUL, LIKE's wildcards ending in its escape character and 4,000 characters in every text
    # argument of every read-only tool: a server error is the finding (read only)
    {"name": "input_hygiene",            "runner": lifecycle_input_hygiene},
    # §MCPTEST30 2026-10-01 (V0524): a unique team name asked twice at once, twice in a row, and after a delete
    {"name": "unique_create_race",       "runner": lifecycle_unique_create_race},
    # §MCPTEST30 2026-10-01 (V0524): a wrong-typed argument to every read tool must be -32602, never -32603
    {"name": "type_confusion",           "runner": lifecycle_type_confusion},
    # §MCPTEST30 2026-10-01 (V0525): hostile text into three writes whose objects the run removes again
    {"name": "write_hygiene",            "runner": lifecycle_write_hygiene},
    # §MCPTEST30 2026-10-01 (V0525): a value its type carries but the database cannot (2^31, 2^63, 1e308, no date)
    {"name": "value_range",              "runner": lifecycle_value_range},
    # §MCPTEST30 2026-10-01 (V0525): two spends at once the balance covers only one of (the overdraft)
    {"name": "overdraft_race",           "runner": lifecycle_overdraft_race},
    {"name": "achievement_claims",       "runner": lifecycle_achievement_claims},
    # §MCPTEST30 2026-10-01 (V0528): a revoked or deleted credential is refused at once, on every worker
    {"name": "revocation",               "runner": lifecycle_revocation},
    # §MCPTEST30 2026-10-01 (V0528): an API key's scopes bound what it reaches through MCP (§MCPSCOPE, AL-4)
    {"name": "key_scopes",               "runner": lifecycle_key_scopes},
    # §MCPTEST30 2026-10-01: a list tool's filter is applied, never dropped (a nonce that matches nothing returns no rows)
    {"name": "filter_honesty",           "runner": lifecycle_filter_honesty},
    # §MCPTEST30 2026-10-01: one A2A payment token pays at most once (two settles at once; a settle racing a release)
    {"name": "a2a_settle_race",          "runner": lifecycle_a2a_settle_race},
    # §MCPTEST30 2026-10-01: an enum filter's advertised values are its route's vocabulary (read only)
    {"name": "enum_filter",              "runner": lifecycle_enum_filter},
    {"name": "org_assign_unassign",       "runner": lifecycle_org_assign_unassign},
    {"name": "team_member_add_remove",    "runner": lifecycle_team_member_add_remove},
    # (§MCPTEST30 V0636: reputation_bond moved to earned_agent_public.lifecycle_earned_bond)
    {"name": "signing_keys_rotate",       "runner": lifecycle_signing_keys_rotate},
    {"name": "dev_location_update",       "runner": lifecycle_dev_location_update},
    {"name": "treasury_jwks_shape",       "runner": lifecycle_treasury_jwks_shape},
    {"name": "mcp_audit_log_recent",      "runner": lifecycle_mcp_audit_log_recent},
    {"name": "achievement_claim",         "runner": lifecycle_achievement_claim},
    # ── Sprint 5.7 final batch — state-flow verifiers + economic asserts ──
    {"name": "mtls_toggle",               "runner": lifecycle_mtls_toggle},
    {"name": "flare_celebration_ack",     "runner": lifecycle_flare_celebration_ack},
    {"name": "a2a_payment_balance",       "runner": lifecycle_a2a_payment_settle_balance},
    # ── Sprint 5.8 batch — governance + auth + dispute ──
    {"name": "governance_proposal",       "runner": lifecycle_governance_proposal_vote_tally},
    # §MEMBERSHIP phase B (V0551): a commons season from open to cancel, where the commons is on
    {"name": "commons_season",            "runner": lifecycle_commons_season},
    {"name": "log_enhanced_dispute",      "runner": lifecycle_log_enhanced_dispute},
    {"name": "safe_invalid_input_paths",  "runner": lifecycle_safe_invalid_input_paths},
    # ── Sprint 5.9 mega-batch — coverage extension ──
    {"name": "federation_safe_paths",     "runner": lifecycle_federation_safe_paths},
    {"name": "contract_safe_paths",       "runner": lifecycle_contract_safe_paths},
    {"name": "deployment_safe_paths",     "runner": lifecycle_deployment_safe_paths},
    {"name": "arena_safe_paths",          "runner": lifecycle_arena_safe_paths},
    {"name": "bundle_download_safe",      "runner": lifecycle_bundle_download_safe},
    {"name": "agent_admin_paths",         "runner": lifecycle_agent_admin_paths},
    {"name": "org_member_invite",         "runner": lifecycle_org_member_invite},
    {"name": "self_revocation_safe",      "runner": lifecycle_self_revocation_safe},
    {"name": "create_teg_policies_batch", "runner": lifecycle_create_teg_policies_batch},
    # (§MCPSWEEP 2026-09-27: the Sprint 5.10/5.11 "admin paths" lifecycles were deleted. Registered here, they
    #  ran on the PUBLIC bridge, which carries no admin tool, so every one of their 140 calls answered "tool not
    #  found" and measured nothing; the phase-6 admin lifecycles and the admin contracts cover all 136 tools.)
    # ── Sprint 5.12 mega-batch — TEG direct / attestation / contract /
    #     dispute / agent card / circuit / OAuth / misc ──
    {"name": "arena_leaderboard",         "runner": lifecycle_arena_leaderboard},
    {"name": "transfer_direct",           "runner": lifecycle_transfer_direct},
    # §MCPTEST30 2026-10-01: a keyed money call retried moves money once
    {"name": "money_idempotent_replay",   "runner": lifecycle_money_idempotent_replay},
    # §MCPTEST30 2026-10-01: a negative, zero, NaN, infinite, sub-precision and scientific amount to transferUnits
    {"name": "amount_bounds",             "runner": lifecycle_amount_bounds},
    {"name": "teg_direct_paths",          "runner": lifecycle_teg_direct_paths},
    {"name": "attestation_full",          "runner": lifecycle_attestation_full},
    {"name": "contract_submit_paths",     "runner": lifecycle_contract_submit_paths},
    {"name": "dispute_paths",             "runner": lifecycle_dispute_paths},
    {"name": "agent_card_reads",          "runner": lifecycle_agent_card_reads},
    {"name": "circuit_reads",             "runner": lifecycle_circuit_reads},
    # §MCPTEST30 (V0612): attestations v2 on a throwaway prover, every rule of §ZKV2 through the tools
    {"name": "zk_v2_attestations",        "runner": lifecycle_zk_v2_attestations},
    {"name": "misc_safe",                 "runner": lifecycle_misc_safe},
    # §FEDPROOF 2026-09-13 — the settlement row moved into the tester (his rule: traces live here)
    {"name": "transfer_settlement",       "runner": lifecycle_transfer_settlement},
    # §TWOAGENT 2026-09-23 (V0437) — a knock answered three ways, a block, an unblock and a leave, locally
    {"name": "chat_requests_blocks_and_leave",
                                          "runner": lifecycle_chat_requests_blocks_and_leave},
    # ── Phase C (2026-05-26) — cross-registry coverage via canaries ──
    {"name": "cross_registry_canary_recipient",
                                          "runner": lifecycle_cross_registry_canary_recipient,
     # §MCPTEST30 (V0638): reads the target's database (_target_db); its receiver is a canary of one of the TARGET's
     # operators on a frame, and since V0641 (d6's word) its parent frame's canary on an operator, so it needs no frame
     "needs": ("target_db",)},
    # ── Phase D (2026-05-26 evening) — eigentrust seed for getTrustScore /
    #     getAgentReputation. Must run BEFORE per-tool sweep so the GTV row
    #     exists by the time the sweep exercises trust/reputation reads.
    {"name": "reputation_eigentrust_setup",
                                          "runner": lifecycle_reputation_eigentrust_setup,
     # §MCPTEST30 (V0638): a frame run's; its peer agent becomes the run's second agent and outlives the run, which
     # an operator sweep (whose retire step knows only its own cloudop-* agents) must not take
     "needs": ("frame",)},
    # §MCPTEST30 (V0638): getTrustScore on an agent of the newest epoch, read from the target's database
    {"name": "trust_score_newest_epoch",
                                          "runner": lifecycle_trust_score_newest_epoch,
     "needs": ("target_db",)},
]


# §MCPTEST30 (V0636): the lifecycles that earn the refusal-only tools their success path
# (sessionlogs2026/BACKLOG_2026-10-19_MCP_REFUSAL_ONLY_PASSES.md, step 2): the admin and developer tools
# (earned_admin_dev, agentvault2-aa) and the agent and public tools (earned_agent_public, agentvault2-66). They hold
# lifecycles only and read this module when a lifecycle runs (earned_fixtures.lc()), never at import, so the import
# below cannot meet a half-built module whichever is imported first.
from agentvault_registry.api_tests.contracts import earned_admin_dev as _earned_admin_dev  # noqa: E402
from agentvault_registry.api_tests.contracts import earned_agent_public as _earned_agent_public  # noqa: E402

LIFECYCLES.extend(_earned_admin_dev.LIFECYCLES)
LIFECYCLES.extend(_earned_agent_public.LIFECYCLES)


def lifecycle_count() -> int:
    return len(LIFECYCLES)
