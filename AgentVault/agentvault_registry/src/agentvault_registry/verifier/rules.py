"""The five rules of layer C's first step: the ones that need no new call site (design section 8, step 2)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict

from . import inputs


@dataclass(frozen=True)
class Rule:
    name: str
    rego: str                                   # the rule's path in OPA's data tree
    build: Callable[[Dict[str, Any]], Dict[str, Any]]
    severity: str
    summary: str


def _r(name: str, rego: str, summary: str, severity: str = "critical") -> Rule:
    return Rule(name, rego, inputs.BUILDERS[name], severity, summary)


RULES: Dict[str, Rule] = {r.name: r for r in (
    _r("iron_pairing", "agentvault/invariants/flag_pairing_ok",
       "I1: AGENT_RBAC_MODE enforce with AGENT_DELEGATION_MODE not enforce strips capability-token authority"),
    _r("jurisdiction_coherent", "agentvault/jurisdiction/profile_coherent",
       "I-J2: a feature the declared jurisdiction profile denies is switched on"),
    _r("fiat_buy_only", "agentvault/verifier/fiat_buy_only",
       "fiat is buy-only: a payout route in the API, a purchase that is not an inflow, or a purchase that issued units"),
    _r("merge_needs_the_record", "agentvault/verifier/merge_needs_the_record",
       "a code change merged without its checker record, ballot, reviews, window or paths"),
    _r("deletion_on_schedule", "agentvault/verifier/deletion_on_schedule",
       "an account deletion overdue past its cooling-off and the anonymizer's cycle"),
)}
