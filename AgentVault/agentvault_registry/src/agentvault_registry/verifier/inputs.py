"""The ONE builder of each rule's input (V0666 layer C, design section 5).

A rule counts only when each fact it judges is read from a record, never from a literal: a builder takes the facts the verifier read
and returns the input, and tests/test_opa_verifier_v0666.py moves every fact and sees its key move (and the AST lint refuses a
dict literal whose value is a constant). Nothing here asks the registry what it thinks; no function of the registry is called.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, Iterable, List, Optional

from .facts import FLAG_OF, FIAT_OUT

_ON = ("1", "true", "yes", "on")


def _mode(v: Any) -> str:
    return str(v if v not in (None, "") else "off").strip().lower()


def _flag(v: Any) -> bool:
    return str(v if v is not None else "").strip().lower() in _ON


def _epoch(v: Any) -> Optional[float]:
    if isinstance(v, dt.datetime):
        return (v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)).timestamp()
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str) and v:
        try:
            return _epoch(dt.datetime.fromisoformat(v.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _seconds(env: Dict[str, Any], name: str, per: int, default: float) -> float:
    try:
        return float(env.get(name) or default) * per
    except (TypeError, ValueError):
        return default * per


def _inside(touched: str, declared: Iterable[str]) -> bool:
    for d in declared:
        d = str(d).rstrip("/")
        if touched == d or touched.startswith(d + "/"):
            return True
    return False


def iron_pairing(facts: Dict[str, Any]) -> Dict[str, Any]:
    """I1: the node's two IRONKEY modes, read from its environment."""
    env = facts["env"]
    return {"rbac_mode": _mode(env.get("AGENT_RBAC_MODE")), "delegation_mode": _mode(env.get("AGENT_DELEGATION_MODE"))}


def jurisdiction_coherent(facts: Dict[str, Any]) -> Dict[str, Any]:
    """I-J2: the declared profile and the live switch of each feature it can deny."""
    env = facts["env"]
    return {"profile": facts["profile"], "live_flags": {f: _flag(env.get(name)) for f, name in FLAG_OF.items()}}


def fiat_buy_only(facts: Dict[str, Any]) -> Dict[str, Any]:
    """The node's published routes that could pay fiat out, and what its purchase rows and ledger say."""
    return {"out_routes": sorted(p for p in facts["paths"] if FIAT_OUT.search(p)),
            "not_in": facts["purchases_not_in"], "issued": facts["purchases_issued"]}


def merge_needs_the_record(facts: Dict[str, Any]) -> Dict[str, Any]:
    """One merged change: the checker's kept record, the ballot, the veto and the go, the window, the independent reviews of the
    voted commit (the proposer's own word never counts), and the paths the checker saw against the paths declared."""
    ch, reviews, env = facts["change"], facts["reviews"], facts["env"]
    acc = ch.get("acceptance") if isinstance(ch.get("acceptance"), dict) else {}
    rec = acc.get("record") if isinstance(acc.get("record"), dict) else {}
    go = ch.get("go") if isinstance(ch.get("go"), dict) else {}
    merged = ch.get("merged") if isinstance(ch.get("merged"), dict) else {}
    line = ch.get("code_distribution_id")
    status = (ch.get("ballot_result") or {}).get("status") if line else ch.get("proposal_status")
    latest: Dict[Any, Dict[str, Any]] = {}
    for r in reviews:
        who = r.get("reviewer_developer_id")
        if r.get("commit") != ch.get("commit") or who is None or who == ch.get("proposer_developer_id"):
            continue
        if who not in latest or (r.get("at") or 0) >= (latest[who].get("at") or 0):
            latest[who] = r
    touched: List[str] = [t for t in (rec.get("touched") or []) if isinstance(t, str)]
    return {
        "acceptance_ok": acc.get("ok") is True,
        "read_from_checker": rec.get("read_from") == "checker" and bool(rec.get("checker_kid")),
        "accepted_commit": rec.get("commit"),
        "voted_commit": ch.get("commit"),
        "merged_commit": merged.get("commit"),
        "ballot_passed": status == "PASSED",
        "bootstrap_go": bool(go.get("bootstrap")),
        "go_present": bool(go),
        "veto_present": ch.get("veto") is not None,
        "passed_at": _epoch(ch.get("passed_at")),
        "merged_at": _epoch(merged.get("at")),
        "window_seconds": _seconds(env, "CODE_CHANGE_VETO_HOURS", 3600, 24),
        "approvals": sum(1 for r in latest.values() if r.get("verdict") == "approve"),
        "blockers": sum(1 for r in latest.values() if r.get("verdict") == "changes"),
        "approvals_needed": 2 if ch.get("sensitive") else 1,
        "paths_outside_scope": sum(1 for t in touched if not _inside(t, ch.get("paths") or [])),
    }


def deletion_on_schedule(facts: Dict[str, Any]) -> Dict[str, Any]:
    """One account: its status, when the person asked, the cooling-off and the anonymizer's cycle (the grace), and the time now."""
    acct, env = facts["account"], facts["env"]
    return {"pending": acct.get("deletion_status") == "pending_deletion",
            "requested_at": _epoch(acct.get("deletion_requested_at")),
            "cooling_off_seconds": _seconds(env, "ACCOUNT_DELETION_COOLING_OFF_DAYS", 86400, 14),
            "grace_seconds": _seconds(env, "ACCOUNT_DELETION_INTERVAL_SECONDS", 1, 86400),
            "now": _epoch(facts["now"])}


BUILDERS = {f.__name__: f for f in (iron_pairing, jurisdiction_coherent, fiat_buy_only, merge_needs_the_record, deletion_on_schedule)}
