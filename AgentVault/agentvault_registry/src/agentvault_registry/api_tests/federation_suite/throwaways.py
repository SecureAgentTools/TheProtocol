"""§MCPTEST30 V0641 (agentvault2-aa, 2026-10-25): what a federation-suite test makes, the suite retires.

agentvault2-66's census on sbx-beta (2026-10-24 23:3xZ): 1,105 ACTIVE fedsuite-* agents under the suite's developer
(ironkey 531, mech 231, xfr 172, esping 145, ctr 20, ev 4, a2a 2; 2026-09-04 on), 485 of them holding about 29,748
liquid and 440 staked. V0639 returned what the ironkey helper's agents hold before its delete
(test_ironkey_authority_clamp._cleanup); every other helper made agents and left them.

Each helper now names an agent here the moment its DID is known (`made`), and the decorator retires what the test did
not retire itself once the test's verdict is in, a deferred check's after its judgment (`close`):
- the owner (the label's developer) reads the balance error-first: an entry with an error, or a failed read, is unread
  and never a zero;
- the frame's admin bridge returns exactly that through tegTreasuryReceive;
- then the owner deletes it (a soft delete, which keeps a balance: hence the return first).
A test that retires an agent itself (`_cleanup`, or a delete that is its own act) says so (`retired`), and the close
skips it. A stake is not returned (its lock decides). Cleanup never costs a verdict: what it leaves behind is logged and
kept on the outcome. An agent a test keeps on purpose (the ballot member whose own bond holds the developer's
membership) is never named here.
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextvars import ContextVar
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

CLOSE_BUDGET_SEC = 120.0       # one test's close; what it did not reach is said


class Made:
    """The agents one test made (label, did) in the order made, and the ones it retired itself."""

    def __init__(self, rig: Any):
        self.rig = rig
        self.agents: List[Tuple[str, str]] = []
        self.retired: Set[str] = set()

    def pending(self) -> List[Tuple[str, str]]:
        seen: Set[str] = set()
        out = []
        for label, did in self.agents:
            if did not in self.retired and did not in seen:
                seen.add(did)
                out.append((label, did))
        return out


# asyncio copies the context per Task, so the list begun inside a test's Task is that test's alone, and the tasks the
# test starts share it (the same object) under the runner's bounded concurrency
_RUN: ContextVar[Optional[Made]] = ContextVar("fedsuite_throwaways", default=None)


def begin(rig: Any) -> Made:
    run = Made(rig)
    _RUN.set(run)
    return run


def adopt(run: Optional[Made]) -> None:
    """A deferred check runs in the runner's Task, not its test's: it takes the test's list back, so a retire inside
    the check is seen and an agent it makes is named."""
    if run is not None:
        _RUN.set(run)


def made(label: str, did: Any) -> None:
    """A helper made `did` on `label`'s frame (no-op outside a test the decorator runs, or without a DID)."""
    run = _RUN.get()
    if run is not None and isinstance(did, str) and did:
        run.agents.append((label, did))


def retired(did: Any) -> None:
    """The test retired `did` itself: the close leaves it alone."""
    run = _RUN.get()
    if run is not None and isinstance(did, str) and did:
        run.retired.add(did)


def _soft(r: Any) -> Optional[str]:
    if isinstance(r, dict) and set(r.keys()) == {"_text"} and isinstance(r["_text"], str):
        return r["_text"]
    if isinstance(r, str):
        return r
    return None


async def call(rig: Any, label: str, tool: str, args: Dict[str, Any]) -> Tuple[Any, Optional[str]]:
    """MCP call -> (result, refusal), as test_ironkey_authority_clamp._call: `refusal` non-None means it did not land."""
    try:
        r = await rig.mcp(label).call(tool, args, timeout=60)
    except Exception as e:                                             # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"
    if isinstance(r, dict) and isinstance(r.get("status_code"), int) and r["status_code"] >= 400:
        return r, f"wrapped HTTP {r['status_code']}: {json.dumps(r.get('response'))[:180]}"
    return r, _soft(r)


async def return_balance(rig: Any, did: str, label: str) -> Optional[str]:
    """What `did` holds goes back to its frame's treasury, by the rule of agentvault2-66's Throwaways.close (71de4e40):
    the owner (this label's developer) reads the balance, and the frame's admin bridge returns exactly that through
    tegTreasuryReceive. An entry that carries an error, or a read that failed, is unread and never a zero. Returns None
    when nothing is left behind, else what the cleanup says."""
    r, refused = await call(rig, label, "getBatchAgentBalances", {"agent_dids": [did]})
    balances = r.get("balances") if isinstance(r, dict) and not refused else None
    entry = balances.get(did) if isinstance(balances, dict) else None
    if not isinstance(entry, dict) or entry.get("error"):
        why = entry.get("error") if isinstance(entry, dict) and entry.get("error") else (refused or "no entry for it")
        return f"its balance could not be read ({str(why)[:120]}), nothing returned"
    try:
        held = Decimal(str(entry.get("balance")))
    except (InvalidOperation, ValueError):
        held = None
    if held is None or not held.is_finite():
        return f"its balance could not be read (the read said {entry.get('balance')!r}), nothing returned"
    if held <= 0:
        return None
    amount = format(held, "f")
    admin = label if label.endswith("-admin") else label + "-admin"
    _, refused = await call(rig, admin, "tegTreasuryReceive", {
        "source_agent_did": did, "amount": amount, "reason": "federation_suite_fixture_retired",
        "reference_id": f"fedsuite-retire-{did[-12:]}"})
    if refused:
        return f"{amount} held, not returned (tegTreasuryReceive: {refused[:160]})"
    return None


async def retire(rig: Any, label: str, did: str) -> Tuple[Optional[str], Optional[str]]:
    """Return what `did` holds, then delete it as its owner, and say so here (`retired`). (what was left of its
    balance, the delete's refusal), each None when nothing; never raises. A flow that judges its own cleanup judges the
    delete, as before: a balance left behind is said, never a verdict."""
    owner = label[:-len("-admin")] if label.endswith("-admin") else label
    try:
        left = await return_balance(rig, did, owner)
    except Exception as e:                                             # noqa: BLE001 - cleanup is never a finding
        left = f"its balance was not returned ({type(e).__name__})"
    _, refused = await call(rig, owner, "deleteMyAgentByDev", {"agent_did": did})
    retired(did)
    if left or refused:
        logger.warning("[fedsuite] retiring %s on %s left something behind: %s", did, owner,
                       "; ".join(x for x in (left, f"not deleted ({refused[:160]})" if refused else None) if x))
    return left, (refused[:160] if refused else None)


async def close(run: Optional[Made], budget_sec: Optional[float] = None) -> Dict[str, Any]:
    """Retire every agent `run` names that its test did not retire itself, within `budget_sec`. Never raises.
    {"closed": n, "left": {did: [what was said]}} (closed 0 when the test made nothing)."""
    budget_sec = CLOSE_BUDGET_SEC if budget_sec is None else budget_sec
    out: Dict[str, Any] = {"closed": 0, "left": {}}
    if run is None:
        return out
    todo = run.pending()
    if not todo:
        return out

    done: Set[str] = set()

    async def _all() -> None:
        for label, did in todo:
            left, refused = await retire(run.rig, label, did)
            run.retired.add(did)
            done.add(did)
            out["closed"] += 1
            said = [x for x in (left, f"not deleted ({refused})" if refused else None) if x]
            if said:
                out["left"][did] = said

    try:
        await asyncio.wait_for(_all(), timeout=budget_sec)
    except asyncio.TimeoutError:
        for label, did in todo:
            if did not in done:
                out["left"][did] = [f"not retired: the close's {budget_sec:g} s ran out"]
        logger.warning("[fedsuite] the close ran out of its %g s with %d of %d agent(s) not retired", budget_sec,
                       sum(1 for _l, d in todo if d not in done), len(todo))
    except Exception as e:                                             # noqa: BLE001 - cleanup is never a finding
        logger.warning("[fedsuite] the close stopped: %s", type(e).__name__)
        for label, did in todo:
            if did not in done:
                out["left"][did] = [f"not retired: the close stopped ({type(e).__name__})"]
    return out
