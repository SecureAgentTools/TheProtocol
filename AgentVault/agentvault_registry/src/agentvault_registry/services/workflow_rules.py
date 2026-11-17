"""V0663 (agent workflows): the pure rules. No database, no network, nothing to mock.

A workflow ruleset is a declared, versioned JSON document in discovery's own terms. It is checked where a Guild order of a
workflow takes a bid and where it awards one (routers/guild.py calls `services/workflows.py`, which gathers the facts and
calls `evaluate` here). This slice evaluates only what a registry can read about a bidder on its own database:

    bonded_only        true: the bidder holds a reputation bond
    min_reputation     a number: the bidder's reputation score is at least this
    min_proven_orders  an integer: the bidder has settled at least this many Guild orders as the worker
    max_price          a number: the bid price is at most this
    org_ids            a list of organization ids: the bidder belongs to one of them
    independent_of     a list of step keys: the bidder's owner differs from the owner of each of those steps' workers

A rule this slice cannot read (a frame or jurisdiction, a certification, a quantum rung) is REFUSED when the ruleset is
saved, never accepted and ignored: a ruleset that quietly checks less than it says is worse than none.

The receipt chain: each step's receipt hashes the previous receipt, the step key and the hash of that step's output, so
the whole run is one chain anyone can recompute offline (`verify_chain`).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

RULE_KEYS = ("bonded_only", "min_reputation", "min_proven_orders", "max_price", "org_ids", "independent_of")
# Rules named in the design note that this slice cannot evaluate: refused at save time, with this sentence.
LATER_RULES = {
    "frame": "a frame or jurisdiction rule needs the peer registry's answer and is not in this slice",
    "jurisdiction": "a frame or jurisdiction rule needs the peer registry's answer and is not in this slice",
    "certified": "a certification rule is not in this slice",
    "quantum_rung": "a quantum rung rule is not in this slice",
}
GENESIS = "0" * 64
MAX_LIST = 50


class RulesetError(ValueError):
    """A ruleset that cannot be saved: the message names the rule and the reason."""


def _num(v: Any, name: str, *, minimum: float = 0.0) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise RulesetError(f"{name} must be a number")
    if v != v or v in (float("inf"), float("-inf")) or v < minimum:
        raise RulesetError(f"{name} must be a number of at least {minimum:g}")
    return float(v)


def _str_list(v: Any, name: str) -> list[str]:
    if not isinstance(v, list) or not v or len(v) > MAX_LIST:
        raise RulesetError(f"{name} must be a list of 1 to {MAX_LIST} strings")
    out = []
    for item in v:
        if not isinstance(item, str) or not item.strip() or len(item) > 64:
            raise RulesetError(f"{name} holds only non-empty strings of at most 64 characters")
        out.append(item.strip())
    return sorted(set(out))


def normalize(ruleset: Optional[dict], *, step_keys: Optional[list[str]] = None, own_key: Optional[str] = None) -> dict:
    """The ruleset as it is stored: known rules only, values checked, lists sorted. Raises RulesetError.

    step_keys: the keys of the workflow's steps, so `independent_of` can name only a real step; own_key: the step the
    ruleset belongs to, which may not be independent of itself.
    """
    if ruleset is None:
        return {}
    if not isinstance(ruleset, dict):
        raise RulesetError("a ruleset is an object of rule names and values")
    out: dict = {}
    for key, value in ruleset.items():
        if key in LATER_RULES:
            raise RulesetError(f"{key}: {LATER_RULES[key]}")
        if key not in RULE_KEYS:
            raise RulesetError(f"{key}: not a rule (known rules: {', '.join(RULE_KEYS)})")
        if key == "bonded_only":
            if not isinstance(value, bool):
                raise RulesetError("bonded_only must be true or false")
            if value:
                out[key] = True
        elif key in ("min_reputation", "max_price"):
            out[key] = _num(value, key)
        elif key == "min_proven_orders":
            n = _num(value, key)
            if n != int(n):
                raise RulesetError("min_proven_orders must be a whole number")
            out[key] = int(n)
        elif key == "org_ids":
            out[key] = _str_list(value, key)
        elif key == "independent_of":
            keys = _str_list(value, key)
            if own_key is not None and own_key in keys:
                raise RulesetError("independent_of cannot name the step it belongs to")
            if step_keys is not None:
                unknown = [k for k in keys if k not in step_keys]
                if unknown:
                    raise RulesetError(f"independent_of names no such step: {', '.join(unknown)}")
            out[key] = keys
    return out


def merge(workflow_rules: Optional[dict], step_rules: Optional[dict]) -> dict:
    """The rules a step's bidder meets: the workflow's, tightened by the step's. For a number the stricter side wins
    (a higher minimum, a lower ceiling); a list unions for independent_of and intersects for org_ids."""
    a, b = dict(workflow_rules or {}), dict(step_rules or {})
    out = dict(a)
    for key, value in b.items():
        if key not in out:
            out[key] = value
        elif key in ("min_reputation", "min_proven_orders"):
            out[key] = max(out[key], value)
        elif key == "max_price":
            out[key] = min(out[key], value)
        elif key == "bonded_only":
            out[key] = out[key] or value
        elif key == "org_ids":
            out[key] = sorted(set(out[key]) & set(value))
        elif key == "independent_of":
            out[key] = sorted(set(out[key]) | set(value))
    return out


def evaluate(rules: dict, facts: dict) -> list[dict]:
    """Every rule the bidder fails, as [{"rule", "message"}] (empty = passes). Nothing here raises for a missing fact:
    a fact the registry could not read is a refusal that SAYS it could not read it, never a quiet pass.

    facts: bonded (True/False/None), reputation (float/None), proven_orders (int), price (float), org_id (str/None),
    owner (the bidder's owner id), owners_by_step ({step key: owner id of that step's awarded worker, or None}).
    """
    fails: list[dict] = []

    def fail(rule: str, message: str) -> None:
        fails.append({"rule": rule, "message": message})

    if rules.get("bonded_only"):
        b = facts.get("bonded")
        if b is None:
            fail("bonded_only", "this registry cannot see whether the bidder holds a reputation bond")
        elif not b:
            fail("bonded_only", "the bidder holds no reputation bond")
    if "min_reputation" in rules:
        r = facts.get("reputation")
        if r is None:
            fail("min_reputation", "the bidder has no reputation score on this registry")
        elif r < rules["min_reputation"]:
            fail("min_reputation", f"reputation {r:g} is below the minimum {rules['min_reputation']:g}")
    if "min_proven_orders" in rules:
        n = int(facts.get("proven_orders") or 0)
        if n < rules["min_proven_orders"]:
            fail("min_proven_orders", f"{n} settled orders, at least {rules['min_proven_orders']} needed")
    if "max_price" in rules:
        p = facts.get("price")
        if p is None or p > rules["max_price"]:
            fail("max_price", f"price {p if p is not None else 'unknown'} is above the ceiling {rules['max_price']:g}")
    if "org_ids" in rules:
        if facts.get("org_id") not in rules["org_ids"]:
            fail("org_ids", "the bidder's organization is not one the ruleset accepts")
    if "independent_of" in rules:
        owner = facts.get("owner")
        by_step = facts.get("owners_by_step") or {}
        for key in rules["independent_of"]:
            other = by_step.get(key)
            if owner is None:
                fail("independent_of", "this registry cannot see who owns the bidder")
                break
            if other is not None and other == owner:
                fail("independent_of", f"the bidder has the same owner as the worker of step {key}")
    return fails


def refusal_sentence(fails: list[dict]) -> str:
    """One sentence for a 403 body: the rule names first, then each reason."""
    return ("The workflow's ruleset refuses this bid: " + "; ".join(f"{f['rule']} ({f['message']})" for f in fails))


def ruleset_hash(ruleset: dict) -> str:
    """sha256 of the canonical JSON: what a bidder is shown before they bid, and what a run records."""
    return hashlib.sha256(json.dumps(ruleset or {}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def output_hash(deliverable: Any) -> str:
    """The hash of a step's output: sha256 of the delivered output's canonical JSON, always. A `hash` the worker writes inside
    its deliverable is part of what was delivered and is hashed with it, never taken as the answer (security read W3: a receipt
    must attest the output, not the worker's claim about another one)."""
    return hashlib.sha256(json.dumps(deliverable, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def step_receipt(prev: str, step_key: str, out_hash: str) -> str:
    return hashlib.sha256(f"{prev}|{step_key}|{out_hash}".encode()).hexdigest()


def build_chain(steps: list[tuple[str, str]]) -> list[dict]:
    """steps: [(step key, output hash)] in order. Returns [{"step", "output_hash", "prev", "receipt"}]."""
    chain, prev = [], GENESIS
    for key, h in steps:
        r = step_receipt(prev, key, h)
        chain.append({"step": key, "output_hash": h, "prev": prev, "receipt": r})
        prev = r
    return chain


def verify_chain(chain: list[dict]) -> tuple[bool, Optional[str]]:
    """Recompute a chain offline. (True, None) or (False, why). An empty chain verifies: nothing was claimed."""
    prev = GENESIS
    for i, link in enumerate(chain):
        if link.get("prev") != prev:
            return False, f"link {i} ({link.get('step')}) does not follow the one before it"
        if step_receipt(prev, str(link.get("step")), str(link.get("output_hash"))) != link.get("receipt"):
            return False, f"link {i} ({link.get('step')}) does not match its own hash"
        prev = link["receipt"]
    return True, None
