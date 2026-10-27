"""§MCPTEST30 (2026-10-01) — does a read tool's route check the text it is handed before its SQL does?

Postgres refuses a NUL in any text value (asyncpg: invalid byte sequence for encoding "UTF8": 0x00), a LIKE pattern may
not end in its escape character, and Python refuses a NUL in a file path or a subprocess argument (ValueError). A route
that hands such a value on unchecked answers 500 where it should refuse (4xx) or find nothing. Measured by hand before
this probe existed, with no login at all: `GET /api/v1/discover?query=...%00...` and
`GET /api/v1/fiat/flare/agent/...%00...` answered 500 on sbx-alpha (V0515); V0523 refuses a NUL in a request path or
query string at the edge (middleware/nul_refusal.py).

Every READ-ONLY MCP tool (the server's own readOnlyHint, mcp/tool_metadata.derive_annotations) that takes a text
argument is asked once per hostile value, every text argument set to it: a NUL inside, LIKE's two wildcards ending in
its escape character, and 4,000 characters. The list is derived from the tool schemas at run time, so a tool added
tomorrow is asked too. Left out on purpose: the credential exchanges (a hostile client id is a failed login) and the
tools that call out (a showcase agent, a peer). A server error is the finding; a refusal or an empty answer is the
route doing its job. A value the MCP tool could not put into its URL at all (httpx: InvalidURL) is a finding too: the
tool put the argument into its route path unencoded (V0515 measured 108 such values; V0523 encodes every path segment
through core.path_segment.seg), and the same tool would send a `/`, `..`, `?` or `#` to a different route than its
name says. Rows keep kinds and statuses, never a value or a row.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from agentvault_registry.api_tests.contracts import pagination_partition as PP

PREFIX = "hygiene: "
LONG = 4000
# §MCPTEST30 (V0639, agentvault2-aa): core/mainframe_gate.py's refusal on a registry that is not a sovereign mainframe
# (a cloud operator): a deliberate 503 that answers before any value reaches the route, so the route's hygiene
# cannot be measured there. Read as a server error, it made seven red rows per operator sweep (2026-10-24).
GATE_SENTENCE = "runs on sovereign mainframes only"
# (label, value): every text argument of a tool is set to one value per call
HOSTILE: Tuple[Tuple[str, str], ...] = (
    ("nul", "mcp-probe\x00nul"),
    ("escape", "mcp-probe%_\\"),
    ("long", "p" * LONG),
)
# arguments that carry a credential or decide who is asking: never set to a hostile value
NEVER_HOSTILE = frozenset({"agent_jwt", "developer_jwt", "agent_token", "client_id", "client_secret", "token", "password"})
# read-only by their annotation, but each exchanges a credential or calls out: left out on purpose
LEFT_OUT: Dict[str, str] = {
    "theprotocol_getAgentToken": "a credential exchange: a hostile client id is a failed login",
    "theprotocol_oauthIntrospect": "a credential check",
    "theprotocol_compositeHealthCheck": "takes an agent token",
    "theprotocol_getPublicShowcaseCall": "calls a showcase agent's service",
    "theprotocol_probeTopologyPeer": "dials a peer",
}
_UNSENT = re.compile(r"InvalidURL|non-printable ASCII character in URL")
_FILL: Dict[str, Any] = {"integer": 1, "number": 1, "boolean": False, "array": [], "object": {}}

Target = Tuple[str, str, List[str], Dict[str, Any]]


def targets(public_schemas: Iterable[dict], admin_schemas: Iterable[dict], tier2: Iterable[str], tier3: Iterable[str],
            annotate: Callable[[str], Dict[str, bool]]) -> List[Target]:
    """(tool, tier: '1' | '2' | '3' | 'admin', the text arguments to set, a filler for each required argument that is
    not text) for every read-only tool with at least one text argument. A tool on both surfaces is asked once, on the
    public one; a tool whose annotation cannot be read is never taken for a read."""
    t2, t3 = set(tier2), set(tier3)
    out: List[Target] = []
    seen = set()
    for surface, schemas in (("public", public_schemas), ("admin", admin_schemas)):
        for t in schemas:
            name = (t or {}).get("name") or ""
            if not name or name in seen:
                continue
            seen.add(name)
            if name in LEFT_OUT:
                continue
            try:
                if not annotate(name).get("readOnlyHint"):
                    continue
            except Exception:  # noqa: BLE001
                continue
            schema = t.get("inputSchema") or {}
            props = schema.get("properties") or {}
            required = set(schema.get("required") or [])
            text: List[str] = []
            fill: Dict[str, Any] = {}
            for p, spec in props.items():
                if p in NEVER_HOSTILE:
                    continue
                ty = spec.get("type") if isinstance(spec, dict) else None
                types = ty if isinstance(ty, list) else [ty]
                if "string" in types:
                    text.append(p)
                elif p in required:
                    fill[p] = _FILL.get(types[0], 1) if types else 1
            if not text:
                continue
            tier = "admin" if surface == "admin" else ("2" if name in t2 else "3" if name in t3 else "1")
            out.append((name, tier, sorted(text), fill))
    return out


def default_targets() -> List[Target]:
    """The targets from the running server's own schemas, tier sets and annotations."""
    from agentvault_registry.mcp import server as S
    from agentvault_registry.mcp import server_admin as SA
    from agentvault_registry.mcp.tool_metadata import derive_annotations
    return targets(S.ALL_TOOL_SCHEMAS, SA.ADMIN_TOOL_SCHEMAS, S.TIER2_TOOLS, S.TIER3_TOOLS, derive_annotations)


def answer_kind(ok: bool, inner: Any, code: Any, answered: Callable) -> Tuple[str, Optional[int], Optional[int]]:
    """`unsent` when the MCP tool could not put the value into its URL (the route never saw it); otherwise the bounds
    judge's kinds: `rows`, `refused`, `server_error`, `no_answer`."""
    if not answered(ok, inner, code):
        try:
            blob = inner if isinstance(inner, str) else json.dumps(inner, default=str)
        except Exception:  # noqa: BLE001
            blob = str(inner)
        if _UNSENT.search(blob or ""):
            return "unsent", None, None
    kind, st, rows = PP.bound_answer(ok, inner, code, answered)
    # the gate's words decide, at any refusal status: 503 today, and agentvault2-d6 means to make it a 404 (V0639),
    # which would otherwise read as the route refusing the value, a pass the route never earned
    if kind in ("server_error", "refused") and GATE_SENTENCE in _blob(inner):
        return "gated", st, None
    return kind, st, rows


def _blob(inner: Any) -> str:
    try:
        return inner if isinstance(inner, str) else json.dumps(inner, default=str)
    except Exception:  # noqa: BLE001
        return str(inner)


def verdict(answers: Dict[str, Tuple[str, Optional[int], Optional[int]]]
            ) -> Tuple[Optional[bool], Optional[str], Dict[str, Any]]:
    """(healthy | None for NOT MEASURED, the failure or skip sentence, per-value evidence). A server error is a finding
    (the route), and so is a value that never left the tool (the tool's own URL); a refusal, a page of rows and an
    empty answer all kept the value away from what it could break."""
    ev: Dict[str, Any] = {}
    for label, (kind, st, rows) in answers.items():
        ev[label] = (f"{rows} rows" if kind == "rows" and rows is not None else "answered" if kind == "rows"
                     else f"{kind} HTTP {st}" if st else kind)
    errs = [label for label, (kind, _st, _rows) in answers.items() if kind == "server_error"]
    if errs:
        return False, (f"BUG-FIND: hygiene: a text argument the route does not check answered a server error "
                       f"({', '.join(errs)}): the value reached its SQL, a file path or a subprocess unchecked"), ev
    unsent = [label for label, (kind, _st, _rows) in answers.items() if kind == "unsent"]
    if unsent:
        return False, (f"BUG-FIND: hygiene: the tool could not put a text argument into its URL ({', '.join(unsent)}): it "
                       f"interpolates the value unencoded, so a '/', '..', '?' or '#' in it would send the call to "
                       f"another route (core.path_segment.seg encodes one path segment)"), ev
    if all(kind == "no_answer" for kind, _st, _rows in answers.values()):
        return None, "NOT MEASURED: no hostile value reached the route over MCP", ev
    kinds = [kind for kind, _st, _rows in answers.values()]
    if "gated" in kinds and "rows" not in kinds:
        return None, ("NOT MEASURED: the route runs on sovereign mainframes only, and this registry's gate answered "
                      "before a hostile value reached it"), ev
    return True, None, ev


async def run_hygiene(rpc_for: Callable[[str], Optional[Callable]], parse: Callable, bag: Any,
                      outcomes: Dict[str, dict], make_outcome: Callable, answered: Callable,
                      todo: Optional[List[Target]] = None) -> None:
    """One `hygiene: <tool>` row per target, each asked once per HOSTILE value (read only); targets a few at a time
    (api_tests/contracts/probe_pool.py, V0525)."""
    from agentvault_registry.api_tests.contracts import probe_pool

    async def one(target: Target) -> None:
        tool, tier, text, fill = target
        t0 = time.time()
        name = PREFIX + tool.replace("theprotocol_", "")
        rpc = rpc_for(tier)
        if rpc is None:
            outcomes[name] = make_outcome(name, "hygiene", False, "0", 0, None, {}, expect_status="any",
                                          skip_reason="NOT MEASURED: the runner injected no raw transport for the admin bridge")
            return
        base, jwt, unmet = PP.args_for("2" if tier == "2" else "1", {}, bag)
        if unmet:
            outcomes[name] = make_outcome(name, "hygiene", False, "0", 0, None, {}, expect_status="any", skip_reason=unmet)
            return
        answers: Dict[str, Tuple[str, Optional[int], Optional[int]]] = {}
        last_code: Any = 0
        for label, value in HOSTILE:
            args = {**base, **fill, **{p: value for p in text}}
            ok, body, code = await rpc(tool, args, jwt=jwt, timeout=30)
            answers[label], last_code = answer_kind(ok, parse(body), code, answered), code
        healthy, sentence, ev = verdict(answers)
        ev["arguments"] = list(text)
        outcomes[name] = make_outcome(name, "hygiene", bool(healthy), str(last_code or "0"),
                                      int((time.time() - t0) * 1000), sentence if healthy is False else None, {},
                                      expect_status="any", skip_reason=sentence if healthy is None else None)
        outcomes[name]["result_excerpt"] = ev   # per-value kinds and statuses, never a value or a row
    await probe_pool.each(todo if todo is not None else default_targets(), one)
