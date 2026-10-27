"""A native card's bond, enforcement and listing are stated by its HOME at every read (§TWOAGENT #10, V0437).

Measured before V0437 on the sandbox (the proof agents' own cards) and on the live index: the single-card read
(`GET /api/v1/agent-cards/{id}`, `getAgentCardById`, the read the federated Directory trusts) served stored card_data and
derived nothing, so a bonded native agent read as unbonded (`locked` at its registry, no block on the read), and every
native card on EU and ASIA indexed as unbonded. Stored card_data is owner content and nothing kept the three blocks out
of it: an owner could write a bond its registry never granted. V0437 derives them on every read of a native card, from
the registry's own rows, and strips them from every owner write.

The claims here are what a reader of the card SEES, which is what the Directory and a counterparty act on; the storage
half (the strip at write) is pinned by the unit tests in `tests/test_twoagent_home_extensions.py`, since no MCP tool reads
a raw row.

⚠ Writes: two throwaway agents named `fedsuite-he-*` on sandbox-A (soft-deleted at the end), a treasury-backstopped bond
on one (moves no money), and two owner edits of those agents' own cards. No money moves.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.federation_suite import throwaways
from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet, ensure_bonded,
)

_TAG = "fedsuite-he"
_A, _ADMIN_A = "sandbox-A", "sandbox-A-admin"
_BOND = "https://theprotocol.cloud/extensions/v1/reputation-bond"
_ENF = "https://theprotocol.cloud/extensions/v1/enforcement"
_LST = "https://theprotocol.cloud/extensions/v1/listing"
_BONDED = ("locked", "matured")


def _soft(r: Any) -> Optional[str]:
    if isinstance(r, dict) and set(r.keys()) == {"_text"} and isinstance(r["_text"], str):
        return r["_text"]
    if isinstance(r, str):
        return r
    return None


async def _call(rig, label: str, tool: str, args: Dict[str, Any]) -> Tuple[Any, Optional[str]]:
    try:
        r = await rig.mcp(label).call(tool, args, timeout=60)
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"
    if isinstance(r, dict) and r.get("error"):
        return r, str(r.get("error"))
    return r, _soft(r)


async def _rest(rig, method: str, endpoint: str, body: Optional[Dict[str, Any]] = None) -> Tuple[int, Any]:
    args: Dict[str, Any] = {"method": method, "endpoint": endpoint}
    if body is not None:
        args["body"] = body
    try:
        r = await rig.mcp(_ADMIN_A).call("adminRequest", args, timeout=60)
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}"
    if not isinstance(r, dict):
        return -1, r
    code = r.get("status_code")
    return (code if isinstance(code, int) else -1), r.get("response")


class _Legs:
    def __init__(self, planned: List[str]):
        self.planned, self.got, self.evidence = list(planned), {}, {}

    def check(self, name: str, ok: bool, evidence: Any = None) -> bool:
        assert name in self.planned, f"unplanned leg {name}"
        self.got[name] = bool(ok)
        self.evidence[name] = evidence
        return bool(ok)

    def result(self, description: str, t0: float) -> AssertionResult:
        missing = [n for n in self.planned if n not in self.got]
        failed = [n for n, ok in self.got.items() if not ok]
        passed = not missing and not failed
        detail = None if passed else json.dumps({"failed": failed, "not_run": missing,
                                                 "evidence": {n: self.evidence.get(n) for n in failed}},
                                                default=str)[:700]
        return AssertionResult(passed=passed, description=description, budget_sec=0.0,
                               elapsed_sec=time.monotonic() - t0, polling_attempts=1,
                               last_state={"legs": self.got, "not_run": missing, "evidence": self.evidence},
                               failure_detail=detail)


async def _agent(rig, tag: str, made: List[str]) -> Dict[str, str]:
    name = f"{_TAG}-{tag}-{uuid.uuid4().hex[:8]}"
    r, refused = await _call(rig, _A, "createAgent", {"name": name, "description": "federation suite home-extension probe"})
    if refused or not isinstance(r, dict):
        raise PreconditionUnmet(f"createAgent refused on {_A}: {refused}")
    did = r.get("did") or r.get("agent_did") or (r.get("agent") or {}).get("did")
    throwaways.made(_A, did)  # V0641: retired once its test's verdict is in (throwaways)
    if not did:
        raise PreconditionUnmet(f"createAgent on {_A}: no DID (keys={sorted(r)[:8]})")
    made.append(did)
    return {"did": did, "name": name}


def _ext(card_data: Any, uri: str) -> Optional[Dict[str, Any]]:
    for e in ((card_data or {}).get("extensions") or []) if isinstance(card_data, dict) else []:
        if isinstance(e, dict) and e.get("uri") == uri:
            return e.get("params") or {}
    return None


async def _read(rig, did: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    r, refused = await _call(rig, _A, "getAgentCardById", {"card_id": did})
    if refused or not isinstance(r, dict):
        return None, refused or "no card"
    return (r.get("card_data") if isinstance(r.get("card_data"), dict) else {}), None


def _forged(bond_amount: str = "999999") -> List[Dict[str, Any]]:
    return [{"uri": _BOND, "required": False, "params": {"version": 1, "status": "matured", "amount": bond_amount}},
            {"uri": _ENF, "required": False, "params": {"version": 1, "status": "suspended"}},
            {"uri": _LST, "required": False, "params": {"version": 1, "unlisted": True}}]


@federation_test(
    name="card_read_states_the_bond_its_home_holds_and_never_an_owners_claim",
    category="discovery_cards",
    budget_sec=150.0,
    severity="high",
    requires=[_A, _ADMIN_A],
    tags=["cards", "reputation_bond", "directory", "v0437"],
)
async def test_card_home_extensions(rig: FederationTestRig) -> AssertionResult:
    """A bonded native agent's card read carries the bond block its registry holds; an owner's own copies of the three
    blocks (bond, enforcement, listing) never reach a reader, bonded or not."""
    t0 = time.monotonic()
    planned = ["the_read_states_the_bond_its_home_holds", "the_same_bond_on_the_list_read",
               "the_discovery_read_states_it_too",
               "an_owners_forged_blocks_are_accepted_and_not_believed", "an_unbonded_card_never_reads_as_bonded",
               "the_flow_removed_what_it_made"]
    legs = _Legs(planned)
    made: List[str] = []
    ran = False
    try:
        bonded = await _agent(rig, "bonded", made)
        plain = await _agent(rig, "plain", made)
        status = await ensure_bonded(rig, _A, bonded["did"])
        if status not in _BONDED:
            raise PreconditionUnmet(f"{_A} does not enforce the bond ({status}): there is no bond for the read to state")
        code, own = await _rest(rig, "GET", f"/api/v1/developers/me/agents/{bonded['did']}/reputation-bond")
        truth = ((own or {}).get("bond") or {}).get("status") if isinstance(own, dict) else None
        cd, err = await _read(rig, bonded["did"])
        b = _ext(cd, _BOND)
        legs.check("the_read_states_the_bond_its_home_holds", bool(truth) and (b or {}).get("status") == truth,
                   {"the_registry_holds": truth, "on_the_read": b, "read_error": err})
        code, page = await _rest(rig, "GET", f"/api/v1/agent-cards/?search={bonded['name']}&include_card_data=true&include_unlisted=true&limit=5")
        items = (page or {}).get("items") if isinstance(page, dict) else None
        row = next((i for i in items or [] if isinstance(i, dict) and i.get("name") == bonded["name"]), None)
        legs.check("the_same_bond_on_the_list_read", bool(row) and (_ext(row.get("card_data"), _BOND) or {}).get("status") == truth,
                   {"status": code, "found": bool(row)})
        # Discovery's form of the list: the federated branch rebuilds the local rows (V0438 carries the stated card_data
        # into them instead of deriving the page twice), so the bond must still be on the local row it answers with.
        code, page = await _rest(rig, "GET", f"/api/v1/agent-cards/?search={bonded['name']}&include_card_data=true"
                                              "&include_federated=true&include_unlisted=true&limit=5")
        items = (page or {}).get("items") if isinstance(page, dict) else None
        row = next((i for i in items or [] if isinstance(i, dict) and i.get("name") == bonded["name"]), None)
        legs.check("the_discovery_read_states_it_too",
                   bool(row) and row.get("origin_registry_name") == "Local"
                   and (_ext(row.get("card_data"), _BOND) or {}).get("status") == truth,
                   {"status": code, "found": bool(row), "origin": (row or {}).get("origin_registry_name"),
                    "bond": _ext((row or {}).get("card_data"), _BOND)})
        code, put = await _rest(rig, "PUT", f"/api/v1/agent-cards/{bonded['did']}", body={"card_data": {"extensions": _forged()}})
        cd2, err2 = await _read(rig, bonded["did"])
        b2 = _ext(cd2, _BOND)
        legs.check("an_owners_forged_blocks_are_accepted_and_not_believed",
                   code == 200 and (b2 or {}).get("status") == truth and str((b2 or {}).get("amount")) != "999999"
                   and _ext(cd2, _ENF) is None and _ext(cd2, _LST) is None
                   and str((_ext((put or {}).get("card_data") if isinstance(put, dict) else None, _BOND) or {}).get("amount")) != "999999",
                   {"put": code, "bond_read": b2, "enforcement_read": _ext(cd2, _ENF), "listing_read": _ext(cd2, _LST)})
        code, _ = await _rest(rig, "PUT", f"/api/v1/agent-cards/{plain['did']}", body={"card_data": {"extensions": _forged("250")}})
        cd3, err3 = await _read(rig, plain["did"])
        legs.check("an_unbonded_card_never_reads_as_bonded",
                   code == 200 and cd3 is not None and _ext(cd3, _BOND) is None and _ext(cd3, _ENF) is None
                   and _ext(cd3, _LST) is None, {"put": code, "read": [e.get("uri") for e in (cd3 or {}).get("extensions") or []],
                                                 "read_error": err3})
        ran = True
    finally:
        left = []
        for did in made:
            _, refused = await throwaways.retire(rig, _A, did)      # V0641: what it holds goes back first
            if refused:
                left.append(f"agent {did}: {refused[:120]}")
        if ran:
            legs.check("the_flow_removed_what_it_made", not left, {"left": left})
    return legs.result("a native card's home extensions, as a reader sees them", t0)
