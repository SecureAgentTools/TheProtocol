"""FailureMode taxonomy (AAA+ refactor 2026-05-21).

Replaces the free-text `expected_failure_reason` strings scattered across 4002 LOC
of inline EF rules in admin_api_test.py.

Three buckets per the predecessor's handover doc
(PRODUCTION_DOCS/09_DEVELOPER_GUIDES/Testing/HANDOVER_Make_API_Tests_Really_Pass.md):

    BUCKET_1: genuinely impossible from the harness (keep)
    BUCKET_2: lazy stamp masking a missing prereq (fix with prereq)
    BUCKET_3: known backend bug masquerading as EF (file as bug, fix code)
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional


class FailureBucket(str, enum.Enum):
    BUCKET_1_IMPOSSIBLE = "bucket_1_impossible"
    """Genuinely impossible from the harness (mTLS, real TOTP, email round-trip)."""

    BUCKET_2_PREREQ_GAP = "bucket_2_prereq_gap"
    """Missing prereq — should be fixed with a fixture, not stamped."""

    BUCKET_3_KNOWN_BUG = "bucket_3_known_bug"
    """Backend has a real bug. EF is a TODO with a target fix."""

    BUSINESS_RULE = "business_rule"
    """4xx because a business rule correctly fired (e.g., self-transfer rejection)."""

    INTENTIONALLY_NOT_IMPLEMENTED = "intentionally_not_implemented"
    """501 — endpoint is intentionally not implemented (e.g., /teg/transactions/batch)."""

    CAPABILITY_ABSENT = "capability_absent"
    """The NODE deliberately does not host this capability, and the refusal IS the
    documented contract — not a harness limit (bucket 1), not a bug (bucket 3).

    Examples (verified 2026-08-06 on sandbox-A):
      • /admin/mail/* 404s wholesale unless the node holds OPERATOR_MAIL_PASSWORD
        or MAIL_RELAY_CALLERS — §FRAMEMAIL-5 chose 404-not-403 precisely so the
        console "only exists where it can actually be acted on".
      • /admin/simulation/* 503s unless ADMIN_SIMULATION_ENABLED=true (§EXCISION
        shipped it dark and opted in on registry-a alone).

    Distinct from the other buckets on purpose: a run on a node WITH the
    capability must still exercise the happy path, so this must never be
    silently upgraded to a plain PASS."""


@dataclass
class ResponseProbe:
    """Lightweight response wrapper passed to FailureMode predicates."""
    status: int
    body_text: str
    body_json: Optional[Dict[str, Any]] = None
    headers: Dict[str, str] = field(default_factory=dict)

    @property
    def detail(self) -> str:
        if self.body_json is None:
            return self.body_text
        d = self.body_json
        if isinstance(d, dict):
            return str(d.get("detail") or d.get("message") or "")
        return str(d)

    def detail_lower(self) -> str:
        return self.detail.lower()


@dataclass
class FailureMode:
    """Declarative expected-failure rule.

    Example:
        FailureMode.business_rule(
            condition=lambda r: r.status == 400 and "self" in r.detail_lower(),
            reason="self-transfer protection",
        )
    """
    bucket: FailureBucket
    condition: Callable[[ResponseProbe], bool]
    reason: str
    bug_id: Optional[str] = None  # for BUCKET_3
    target_fix: Optional[str] = None  # for BUCKET_3

    # ── Convenience constructors ─────────────────────────────────────────
    @classmethod
    def business_rule(cls, condition: Callable[[ResponseProbe], bool], reason: str) -> "FailureMode":
        return cls(bucket=FailureBucket.BUSINESS_RULE, condition=condition, reason=reason)

    @classmethod
    def impossible(cls, condition: Callable[[ResponseProbe], bool], reason: str) -> "FailureMode":
        return cls(bucket=FailureBucket.BUCKET_1_IMPOSSIBLE, condition=condition, reason=reason)

    @classmethod
    def known_bug(
        cls,
        condition: Callable[[ResponseProbe], bool],
        reason: str,
        bug_id: str,
        target_fix: Optional[str] = None,
    ) -> "FailureMode":
        return cls(
            bucket=FailureBucket.BUCKET_3_KNOWN_BUG,
            condition=condition,
            reason=reason,
            bug_id=bug_id,
            target_fix=target_fix,
        )

    @classmethod
    def not_implemented(cls, reason: str = "Endpoint intentionally not implemented (501)") -> "FailureMode":
        return cls(
            bucket=FailureBucket.INTENTIONALLY_NOT_IMPLEMENTED,
            condition=lambda r: r.status == 501,
            reason=reason,
        )

    @classmethod
    def mtls_required(cls) -> "FailureMode":
        return cls(
            bucket=FailureBucket.BUCKET_1_IMPOSSIBLE,
            condition=lambda r: r.status in (401, 403),
            reason="mTLS / SPIFFE SVID required — harness can't synthesize a real peer cert",
        )

    @classmethod
    def totp_required(cls) -> "FailureMode":
        return cls(
            bucket=FailureBucket.BUCKET_1_IMPOSSIBLE,
            condition=lambda r: r.status in (400, 401, 403),
            reason="Real-time TOTP code required — harness can't generate wall-clock-aligned codes",
        )

    @classmethod
    def email_roundtrip(cls) -> "FailureMode":
        return cls(
            bucket=FailureBucket.BUCKET_1_IMPOSSIBLE,
            condition=lambda r: r.status in (400, 401, 404),
            reason="Real email round-trip required (token only arrives in inbox)",
        )

    @classmethod
    def stripe_signature(cls) -> "FailureMode":
        return cls(
            bucket=FailureBucket.BUCKET_1_IMPOSSIBLE,
            condition=lambda r: r.status in (400, 401, 403),
            reason="Stripe webhook signature required — harness can't sign as Stripe",
        )

    # ── Apply ────────────────────────────────────────────────────────────
    def matches(self, response: ResponseProbe) -> bool:
        try:
            return bool(self.condition(response))
        except Exception:
            return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bucket": self.bucket.value,
            "reason": self.reason,
            "bug_id": self.bug_id,
            "target_fix": self.target_fix,
        }


def classify(response: ResponseProbe, failures: list[FailureMode]) -> Optional[FailureMode]:
    """Return the first matching FailureMode or None."""
    for fm in failures or ():
        if fm.matches(response):
            return fm
    return None
