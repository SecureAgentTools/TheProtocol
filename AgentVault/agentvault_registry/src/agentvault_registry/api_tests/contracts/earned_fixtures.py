"""§MCPTEST30 (V0636): the subjects a refusal-only tool earns its success path on, and the row helpers the earned
lifecycles share (sessionlogs2026/BACKLOG_2026-10-19_MCP_REFUSAL_ONLY_PASSES.md, step 2; his word of 2026-10-24 to
close the gaps).

V0635's run passed 192 tool rows on a refusal alone: each tool was called on an object that does not exist, its route
said 404, and nothing else in the run reached what the tool does. EU's tester router counts such a row as not measured
(routers/mcp_tester._apply_refusal_only). A tool earns its success path back on a subject the run makes for it alone:
a throwaway developer (bag.mint_throwaway) and, where the tool acts on an agent, a throwaway agent of that developer,
made, used and cleared away inside one lifecycle (`Throwaways`).

The rows:
  - the tool's own row, where a lifecycle runs it on such a subject (`step`);
  - `admin_effect: <tool>` for an admin step through the admin bridge (`effect`): where the tool's contract pins a
    refusal (override_coverage_fan) its own row stays that refusal, and the router reads the tool as measured by
    either row;
  - `refusal: <tool> <what>` for a refusal kept beside the success (`refusal_step`): the negative test is kept, and it
    no longer stands in for the tool's measurement;
  - NOT MEASURED, named (`unmeasured`, `effect_unmeasured`), where a subject could not be made: never a quiet gap.

Two modules hold the earned lifecycles, one per session working on them: earned_admin_dev (agentvault2-aa: the admin
and developer tools) and earned_agent_public (agentvault2-66: the agent and public tools). They hold lifecycles only;
mcp_lifecycles.py extends its LIFECYCLES with theirs at its end. None of the three earned modules imports
mcp_lifecycles at module level (`lc()` reads it when a lifecycle runs), so any of them may be imported first.
"""
from __future__ import annotations

import json
import logging
import re
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

RpcCall = Callable[..., Awaitable[Tuple[bool, dict, str]]]
ParseResult = Callable[[dict], dict]

REFUSAL = "refusal: "
# a real success a lifecycle measured under a pinned tool's own name, kept by the runner beside the pinned refusal
# (test_flow_mcp_lifecycle.kept_lifecycle_rows)
EARNED_ROW = "earned: "
# the refusals a route gives for a subject or an input it must not act on
REFUSAL_CODES: Tuple[int, ...] = (400, 401, 403, 404, 409, 422)


def lc() -> Any:
    """mcp_lifecycles, read when a lifecycle runs: it imports the earned modules at its end, so importing it here at
    module level would be circular."""
    from agentvault_registry.api_tests.contracts import mcp_lifecycles
    return mcp_lifecycles


def bare(tool: str) -> str:
    return tool[len("theprotocol_"):] if tool.startswith("theprotocol_") else tool


def refusal_row(tool: str, what: str) -> str:
    """`refusal: rotateAgentCredentials an agent that does not exist`."""
    return f"{REFUSAL}{bare(tool)} {what}".rstrip()


async def step(rpc: RpcCall, parse: ParseResult, tool: str, tier: str, args: Dict[str, Any], jwt: str,
               outcomes: Dict[str, dict], **kw: Any) -> Tuple[bool, dict]:
    """mcp_lifecycles._exec_step: the tool's own row (or none, with record_as_separate=False)."""
    return await lc()._exec_step(rpc, parse, tool, tier, args, jwt, outcomes, **kw)


# the agent permission check's refusal (AGENT_RBAC_MODE=enforce, PART 14): "Agent lacks required permission: <perm>"
_PERMISSION_FIRST = re.compile(r"lacks required permission:\s*([\w.:-]+)")


async def refusal_step(rpc: RpcCall, parse: ParseResult, tool: str, tier: str, args: Dict[str, Any], jwt: str,
                       outcomes: Dict[str, dict], what: str, *, codes: Tuple[int, ...] = REFUSAL_CODES,
                       text: Union[str, Tuple[str, ...]] = "", permission_first_unmeasured: bool = False) -> bool:
    """Calls `tool` with an input its route must refuse and files the row under `refusal: <tool> <what>`, never under
    the tool's own name. The row passes only on one of `codes`, and, when `text` is given, with it in the answer (a
    refusal for another reason did not test the rule). `text` may be a tuple of alternatives, any of which says the
    rule (§MCPTEST30 V0641: a frame and an operator refuse some inputs at different depths, in different words).
    Returns whether the row passed.

    permission_first_unmeasured (§MCPTEST30 V0639, agentvault2-aa): where the asking agent may lack the permission the
    route checks first (a cloud operator enforcing agent permissions, whose run agent holds no governance role), a 403
    that is the permission check's is NOT MEASURED, naming the permission: the rule under test was not reached, and the
    403 neither proves nor disproves it. Off by default: everywhere else such a 403 stays the failure it is."""
    scratch: Dict[str, dict] = {}
    _ok, inner = await step(rpc, parse, tool, tier, args, jwt, scratch, expect_status="error_4xx")
    name = refusal_row(tool, what)
    row = scratch.get(tool) or lc()._not_measured(name, tier, "NOT MEASURED: the refusal step recorded no answer")
    row["tool_name"] = name
    texts = tuple(t for t in ((text,) if isinstance(text, str) else tuple(text)) if t)
    if permission_first_unmeasured and row.get("status_code") == 403:
        m = _PERMISSION_FIRST.search(json.dumps(inner, default=str)[:1200] if inner else "")
        if m:
            outcomes[name] = lc()._not_measured(
                name, tier, f"NOT MEASURED: the agent permission check answered first (HTTP 403, {m.group(1)}): this "
                            f"registry enforces agent permissions and the asking agent holds no {m.group(1)}, so "
                            f"{what} was not reached")
            outcomes[name]["tool_name"] = name
            return False
    # §MCPTEST30 (V0641): a 5xx the caller names in `codes` is the route's own refusal (the relay route answers 502 when
    # the agent's address answers, but not as a relay); it is held to the words like any other, never a bare 5xx
    _st = row.get("status_code")
    if (not row.get("healthy") and isinstance(_st, int) and _st >= 500 and _st in codes and texts
            and not row.get("skip_reason") and not row.get("switched_off")):
        row["healthy"], row["fail_reason"] = True, None
    if row.get("healthy") and not row.get("skip_reason") and not row.get("switched_off"):
        st = row.get("status_code")
        if codes and st not in codes:
            row["healthy"] = False
            row["fail_reason"] = f"{bare(tool)} refused {what} with HTTP {st}, not one of {list(codes)}"
        elif texts:
            blob = json.dumps(inner, default=str)[:1200] if inner else ""
            if not any(t.lower() in blob.lower() for t in texts):
                said = repr(texts[0]) if len(texts) == 1 else "any of " + ", ".join(repr(t) for t in texts)
                row["healthy"] = False
                row["fail_reason"] = (f"{bare(tool)} refused {what} with HTTP {st}, but not for the rule under test "
                                      f"(the answer does not say {said})")
    outcomes[name] = row
    return bool(row.get("healthy"))


async def effect(bag: Any, parse: ParseResult, tool: str, args: Dict[str, Any], outcomes: Dict[str, dict], *,
                 check: Optional[Callable[[dict], Optional[str]]] = None, jwt: Optional[str] = None,
                 expect_events: Optional[List[str]] = None) -> Tuple[bool, dict]:
    """An admin step on the run's own subject, through the admin bridge, recorded as `admin_effect: <tool>`
    (mcp_lifecycles._admin_effect). NOT MEASURED, named, when the flow carries no admin bridge."""
    m = lc()
    rpc_admin = m._admin_bridge(bag)
    if rpc_admin is None:
        effect_unmeasured(outcomes, tool, "this flow carries no admin bridge (bag.rpc_admin)")
        return False, {}
    return await m._admin_effect(rpc_admin, parse, tool, args, jwt or bag.developer_jwt, outcomes, check=check,
                                 expect_events=expect_events,
                                 event_verifier=getattr(bag, "event_verifier", None) if expect_events else None)


def effect_name(tool: str) -> str:
    return lc().admin_effect_row(tool)


def _named(why: str) -> str:
    return why if why.startswith("NOT MEASURED") else f"NOT MEASURED: {why}"


def unmeasured(outcomes: Dict[str, dict], name: str, tier: str, why: str) -> None:
    """A row the lifecycle owes and could not measure, with the reason (a skip, never a pass)."""
    outcomes[name] = lc()._not_measured(name, tier, _named(why))


def effect_unmeasured(outcomes: Dict[str, dict], tool: str, why: str) -> None:
    """The `admin_effect: <tool>` row, NOT MEASURED with the reason."""
    name = effect_name(tool)
    row = lc()._not_measured(tool, "admin", _named(why))
    row.update(tool_name=name, contract_tier="admin_effect")
    outcomes[name] = row


def said(inner: Any) -> str:
    """What a refusal said, short and through the audit sanitizer's shape screen."""
    return lc()._said(inner)


def own_developer_id(bag: Any) -> Optional[int]:
    """The run's own developer as a number, or None. §MCPTEST30 V0645 (agentvault2-66, 2026-10-26): every broadcast a
    run composes is a direct notice to it. A broadcast to everyone reached every developer of the federation: V0644's
    operator read (2026-10-26 15:50-15:56Z) put four on both sandbox frames' consoles, copied by the federation's
    fan-out, while agentvault2-5b's console proof ran there. A direct notice is shown to its developer alone and never
    copied to a peer (routers/admin_broadcast.py, §SECFIX D6-305)."""
    v = str(getattr(bag, "developer_id", "") or "")
    return int(v) if v.isdigit() and int(v) > 0 else None


def zip_answer(ans: Any) -> Tuple[bool, List[Dict[str, Any]]]:
    """§MCPTEST30 (V0640): whether a tool's answer is a zip, and its entries as names and sizes, never its bytes. A
    binary answer reads as a manifest (a non-empty `files` list of {name, size}, fix/mcp-binary-answers) or, before it,
    as the first 300 characters of the file as text (`raw`), where only the zip signature can be read (no entries)."""
    if not isinstance(ans, dict):
        return False, []
    files = ans.get("files")
    if isinstance(files, list):
        entries = [{"name": str(f["name"]), "size": f.get("size")} for f in files
                   if isinstance(f, dict) and f.get("name")]
        return bool(entries), entries
    raw = ans.get("raw")
    return isinstance(raw, str) and raw.startswith("PK"), []


def tool_row(tool: str, outcomes: Dict[str, dict], tier: str, healthy: bool, code: Any, elapsed_ms: int,
             fail: Optional[str], excerpt: Dict[str, Any]) -> None:
    """§MCPTEST30 (V0640): a tool's own row written by hand, for an answer whose excerpt must not come from the answer
    (a file's bytes, a credential the request carried): the lifecycle states what the row keeps. The one-writer gate
    reads it as the tool's earned row (tests/test_mcp_one_writer_per_row.py)."""
    row = lc()._make_outcome(tool, tier, bool(healthy) and not fail, str(code or "0"), int(elapsed_ms), fail, {})
    row["result_excerpt"] = dict(excerpt)
    outcomes[tool] = row


class Throwaways:
    """The subjects one lifecycle makes for itself, cleared away when it ends: call `close()` in a `finally`.

        t = Throwaways(rpc, parse, bag, "rotate-creds")
        try:
            dev = await t.developer("rotate-creds")      # {email, password, developer_id, access_token, ...}
            ag = await t.agent(dev)                       # {did, client_id, client_secret, agent_jwt, owner_jwt}
            if ag.get("why"): ...                         # NOT MEASURED, named
        finally:
            await t.close()

    A developer is registered by the runner (bag.mint_throwaway: the reserved example.com domain, `mcp-throwaway-`
    in its name) and verified through the admin rail where the mint left it unverified. What an agent holds goes back
    to the treasury (`_return_balance`), then the owner deletes it (deleteMyAgentByDev) and the developer asks for its
    own deletion (the 14-day cooling-off, then the daily anonymizer): the rail a person uses. A step that already
    removed a subject says so (`forget_agent`, `forget_developer`). Cleanup is unrecorded and best-effort: it never
    costs a verdict, and a balance it could not return is said (`_say`)."""

    def __init__(self, rpc: RpcCall, parse: ParseResult, bag: Any, tag: str):
        self.rpc, self.parse, self.bag, self.tag = rpc, parse, bag, tag
        self._devs: List[Dict[str, Any]] = []
        self._agents: List[Tuple[str, str]] = []          # (did, the owner's developer token)

    async def developer(self, role: str, verify: bool = True) -> Dict[str, Any]:
        """A developer of this run's own, or {"why": ...}. `verify=False` leaves the e-mail as the registration left it
        (a lifecycle that measures forceEmailVerify verifies it itself)."""
        mint = getattr(self.bag, "mint_throwaway", None)
        if mint is None:
            return {"why": "the runner injected no mint_throwaway"}
        sub = dict(await mint(role) or {})
        if not sub.get("access_token"):
            return {"why": f"no throwaway developer could be minted ({sub.get('why')})"}
        self._devs.append(sub)
        try:
            sub["developer_id"] = int(sub.get("developer_id"))
        except (TypeError, ValueError):
            return {**sub, "why": f"the throwaway developer's id is not a number ({sub.get('developer_id')!r})"}
        rpc_admin = getattr(self.bag, "rpc_admin", None)
        if rpc_admin is not None and verify:
            # a developer creates an agent only once verified (the bootstrap token's rule); an already verified mint
            # answers 400 "already verified", which is what this step is for
            ok, body, code = await rpc_admin("theprotocol_forceEmailVerify", {"developer_id": sub["developer_id"]},
                                             jwt=self.bag.developer_jwt, timeout=20)
            if not ok:
                why = said(self.parse(body) if isinstance(body, dict) else {})
                if not (str(code) == "400" and "already verified" in why.lower()):
                    return {**sub, "why": f"forceEmailVerify for the throwaway developer answered HTTP {code}: {why}"}
        return sub

    async def agent(self, dev: Dict[str, Any], label: str = "") -> Dict[str, Any]:
        """An agent of `dev`, with its credentials and an agent token, or {"why": ...}."""
        owner_jwt = dev.get("access_token")
        if not owner_jwt or dev.get("why"):
            return {"why": dev.get("why") or "no developer to own the agent"}
        name = f"mcp-earn-{self.tag}{'-' + label if label else ''}-{int(time.time())}"
        ok, body, code = await self.rpc("theprotocol_createAgent", {
            "name": name[:100],
            "description": f"The MCP tester's throwaway agent ({self.tag}): made for one lifecycle, deleted after it."},
            jwt=owner_jwt, timeout=60)
        made = self.parse(body) if isinstance(body, dict) else {}
        made = made if isinstance(made, dict) else {}
        did, cid, csec = made.get("did") or made.get("agent_did"), made.get("client_id"), made.get("client_secret")
        if not (ok and did and cid and csec):
            return {"why": f"createAgent for the throwaway developer answered HTTP {code}: {said(made)}"}
        self._agents.append((did, owner_jwt))
        # a tier-0 tool still needs a bearer on the wire (V0614): the owner's token carries it
        ok, body, code = await self.rpc("theprotocol_getAgentToken", {"client_id": cid, "client_secret": csec},
                                        jwt=owner_jwt, timeout=20)
        tok = self.parse(body) if isinstance(body, dict) else {}
        agent_jwt = tok.get("access_token") if isinstance(tok, dict) else None
        if not agent_jwt:
            return {"did": did, "why": f"getAgentToken for the throwaway agent answered HTTP {code}"}
        return {"did": did, "name": name, "client_id": cid, "client_secret": csec, "agent_jwt": agent_jwt,
                "owner_jwt": owner_jwt, "developer_id": dev.get("developer_id")}

    def adopt(self, did: str, owner_jwt: str) -> None:
        """An agent a step made outside agent() (another creation rail): close() returns what it holds and deletes it
        as the others (V0650, agentvault2-d3)."""
        if did and all(d != did for d, _j in self._agents):
            self._agents.append((did, owner_jwt))

    def owner_changed(self, did: str, owner_jwt: str) -> None:
        """A step handed the agent to another developer of the run: close() deletes it as that one."""
        self._agents = [(d, owner_jwt if d == did else j) for d, j in self._agents]

    async def relogin(self, dev: Dict[str, Any]) -> Optional[str]:
        """A fresh token for `dev` (after a step revoked its sessions), carried to the agents it owns; None if the login
        is refused."""
        login = getattr(self.bag, "dev_login", None)
        if login is None or not dev.get("email"):
            return None
        code, tok = await login(dev["email"], dev.get("password") or "")
        fresh = (tok or {}).get("access_token") if str(code).startswith("2") else None
        if fresh:
            old = dev.get("access_token")
            dev["access_token"] = fresh
            self._agents = [(d, fresh if j == old else j) for d, j in self._agents]
        return fresh

    def forget_agent(self, did: str) -> None:
        """A step deleted or handed the agent away: close() leaves it alone."""
        self._agents = [(d, j) for d, j in self._agents if d != did]

    def forget_developer(self, email: str) -> None:
        """A step deleted the developer, or changed its password: close() leaves it alone."""
        self._devs = [d for d in self._devs if d.get("email") != email]

    async def _return_balance(self, did: str, owner_jwt: str) -> Optional[str]:
        """What `did` holds goes back to the treasury before its owner deletes it, by the rule of the runner's
        _retire_cloudop_agents (V0528): the owner reads the balance and the admin bridge returns exactly that through
        tegTreasuryReceive. A throwaway developer's first agent is paid the genesis grant from the treasury, and the
        owner's delete is a soft delete that keeps it: the operator sweeps of 2026-10-24 left 135,000 on sbxalphaop
        and 100,524 on sbxbetaop that way, and sbxbetaop's treasury fell to a single grant. An entry that carries an
        error, or a read that failed, is unread and never a zero (the batch route answers "0" beside its error).
        Returns None when nothing is left behind, else the line the run says."""
        ok, body, code = await self.rpc("theprotocol_getBatchAgentBalances", {"agent_dids": [did]}, jwt=owner_jwt,
                                        timeout=20)
        inner = self.parse(body) if isinstance(body, dict) else {}
        balances = inner.get("balances") if isinstance(inner, dict) else None
        entry = balances.get(did) if isinstance(balances, dict) else None
        if not ok or not isinstance(entry, dict) or entry.get("error"):
            why = entry.get("error") if isinstance(entry, dict) and entry.get("error") else f"HTTP {code}"
            return f"{did}: its balance could not be read ({why}), nothing returned"
        try:
            held = Decimal(str(entry.get("balance")))
        except (InvalidOperation, ValueError):
            held = None
        if held is None or not held.is_finite():
            return f"{did}: its balance could not be read (the read said {entry.get('balance')!r}), nothing returned"
        if held <= 0:
            return None
        amount = format(held, "f")
        rpc_admin = getattr(self.bag, "rpc_admin", None)
        if rpc_admin is None:
            return f"{did}: {amount} held, not returned (this flow carries no admin bridge)"
        ok, body, code = await rpc_admin("theprotocol_tegTreasuryReceive", {
            "source_agent_did": did, "amount": amount, "reason": "mcp_tester_fixture_retired",
            "reference_id": f"mcp-tester-retire-{did[-12:]}"}, jwt=self.bag.developer_jwt, timeout=25)
        if not ok:
            refused = said(self.parse(body) if isinstance(body, dict) else {})
            return f"{did}: {amount} held, not returned (tegTreasuryReceive answered HTTP {code}: {refused})"
        return None

    def _say(self, line: str) -> None:
        """A balance close() left behind, said in the run and never as a red row: a warning in the run's log, and a line
        in bag.throwaway_balances, which the runner's summary carries."""
        logger.warning("MCP tester: the throwaway lifecycle %s left a balance behind: %s", self.tag, line)
        kept = getattr(self.bag, "throwaway_balances", None)
        if isinstance(kept, list):
            kept.append(f"{self.tag}: {line}")

    async def close(self) -> None:
        for did, owner_jwt in reversed(self._agents):
            try:
                left = await self._return_balance(did, owner_jwt)
            except Exception as e:                                     # noqa: BLE001 — cleanup is never a finding
                left = f"{did}: its balance was not returned ({type(e).__name__})"
            if left:
                self._say(left)
            try:
                await self.rpc("theprotocol_deleteMyAgentByDev", {"agent_did": did}, jwt=owner_jwt, timeout=30)
            except Exception:                                          # noqa: BLE001 — cleanup is never a finding
                pass
        self._agents = []
        for dev in self._devs:
            if dev.get("email") and dev.get("password"):
                await lc()._schedule_own_deletion(self.rpc, self.bag, dev["email"], dev["password"],
                                                  f"the earned lifecycle {self.tag}'s throwaway")
        self._devs = []
