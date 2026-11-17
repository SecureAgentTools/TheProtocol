"""V0667 D7 (order gwo_0f317438b7dfc6dfacd3e9b7; DESIGN_2026-11-15_DISTRIBUTIONS.md section 7): a compliance pack, a regulator's rules as policy WITHIN THE ALLOWED SET.

A pack is a content change of kind `compliance_pack` (services/content_changes): proposed, checked by our checker, voted by the line's deciders and applied to the organization's own space
(organizations.settings.compliance_packs[<name>]) exactly as any other content change is, and undone in one step. What a pack may say is a closed set; a rule outside it, a sub-rule outside it, a value
outside its range, is refused by the checker before any vote:

  data_residency       {"regions": [region code, ...]}                  1 to 20 codes, each `de` or `de-by` shaped (lowercase letters, an optional subdivision)
  retention            {"audit_log_days": 90..3650, "chat_message_days": 1..3650}      at least one
  approval_thresholds  {"payment_amount": 0..1e9, "contract_amount": 0..1e9}           at least one; the frame's currency; 0 = every one needs approval
  reporting            {"interval_days": 7 | 30 | 90 | 365, "label": text up to 100}   at least one

The pack is the organization's DECLARATION: its own policy values, stored, voted on by the line's deciders and carried in the signed release report (services/distribution_report). No rail enforces it in this
release: nothing outside services/content_changes reads organizations.settings.compliance_packs (a test pins that), so a pack states what the organization has decided and proves it was decided, and enforcement by
the rails is planned, not built. Never a rule about code, money rails, identity or federation: those are the protected set (D6).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

PACK_NAME = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
REGION = re.compile(r"^[a-z]{2}(-[a-z0-9]{2,12})?$")
RULES = ("data_residency", "retention", "approval_thresholds", "reporting")
INTERVALS = (7, 30, 90, 365)
LABEL_MAX = 100
REGIONS_MAX = 20
RETENTION = {"audit_log_days": (90, 3650), "chat_message_days": (1, 3650)}
THRESHOLDS = ("payment_amount", "contract_amount")
THRESHOLD_MAX = 1_000_000_000


class PackRefused(Exception):
    def __init__(self, sentence: str) -> None:
        super().__init__(sentence)
        self.sentence = sentence


def _number(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _only(rule: str, body: Any, allowed: List[str]) -> Dict[str, Any]:
    if not isinstance(body, dict) or not body:
        raise PackRefused(f"{rule} is an object with at least one of {', '.join(allowed)} (rules.{rule})")
    extra = sorted(k for k in body if k not in allowed)
    if extra:
        raise PackRefused(f"{rule}.{extra[0]} is outside the allowed set: {rule} takes {', '.join(allowed)} (rules.{rule}.{extra[0]})")
    return body


def check_pack(target: Any, content: Dict[str, Any]) -> Dict[str, Any]:
    """The rules of a pack that passes the allowed set (as it will be stored), or PackRefused naming the rule and the field, never a value."""
    if not isinstance(target, str) or not PACK_NAME.match(target):
        raise PackRefused("a pack's name is lowercase letters, digits and '-', 2 to 40 characters, starting with a letter (name)")
    extra = sorted(k for k in content if k != "rules")
    if extra:
        raise PackRefused(f"unknown field {extra[0]!r}: a pack takes rules (field)")
    rules = content.get("rules")
    if not isinstance(rules, dict) or not rules:
        raise PackRefused(f"rules is an object with at least one of {', '.join(RULES)} (rules)")
    out: Dict[str, Any] = {}
    for rule, body in rules.items():
        if rule not in RULES:
            raise PackRefused(f"{rule} is outside the allowed set: a pack takes {', '.join(RULES)} (rules.{rule})")
        if rule == "data_residency":
            _only(rule, body, ["regions"])
            regions = body["regions"] if "regions" in body else None
            if (not isinstance(regions, list) or not 1 <= len(regions) <= REGIONS_MAX
                    or not all(isinstance(r, str) and REGION.match(r) for r in regions)):
                raise PackRefused(f"regions is 1 to {REGIONS_MAX} region codes such as de or de-by (rules.data_residency.regions)")
            out[rule] = {"regions": list(regions)}
        elif rule == "retention":
            _only(rule, body, list(RETENTION))
            for k, v in body.items():
                lo, hi = RETENTION[k]
                if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
                    raise PackRefused(f"{k} is a whole number of days from {lo} to {hi} (rules.retention.{k})")
            out[rule] = dict(body)
        elif rule == "approval_thresholds":
            _only(rule, body, list(THRESHOLDS))
            for k, v in body.items():
                n = _number(v)
                if n is None or not 0 <= n <= THRESHOLD_MAX:
                    raise PackRefused(f"{k} is an amount from 0 to {THRESHOLD_MAX} (rules.approval_thresholds.{k})")
            out[rule] = dict(body)
        else:
            _only(rule, body, ["interval_days", "label"])
            if "interval_days" in body and (not isinstance(body["interval_days"], int) or isinstance(body["interval_days"], bool) or body["interval_days"] not in INTERVALS):
                raise PackRefused(f"interval_days is one of {', '.join(str(i) for i in INTERVALS)} (rules.reporting.interval_days)")
            if "label" in body and (not isinstance(body["label"], str) or not body["label"].strip() or len(body["label"]) > LABEL_MAX):
                raise PackRefused(f"label is 1 to {LABEL_MAX} characters (rules.reporting.label)")
            out[rule] = dict(body)
    return out
