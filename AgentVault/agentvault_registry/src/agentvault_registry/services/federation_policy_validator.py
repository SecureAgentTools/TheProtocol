"""
services/federation_policy_validator.py — Federation Policy Admission Validator

Validates a submitted policy JSON against the canonical locked parameter set
(core/base_network_params.py) and returns a structured ValidationResult.

Called by:
  - routers/federation_admission.py  (POST /request-admission, POST /validate-policy)
  - services/federation_compliance_monitor.py (re-validate on drift)

Author: OWL-23 / Phase 1 Implementation
Date: 2026-03-12
"""
import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, List, Literal, Optional

from ..core.base_network_params import (
    BOUNDED_PARAMS,
    GRACE_PERIOD_HOURS,
    LOCKED_PARAMS,
    PARAM_SEVERITY,
    DriftSeverity,
)

logger = logging.getLogger(__name__)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class PolicyViolation:
    path: str
    required: Any                                         # For locked params
    submitted: Any
    bounds: Optional[dict]                                # For bounded params, else None
    violation_type: Literal["locked_mismatch", "out_of_bounds", "enforcement_too_weak"]
    severity: DriftSeverity

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "required": self.required,
            "submitted": self.submitted,
            "bounds": self.bounds,
            "violation_type": self.violation_type,
            "severity": self.severity.value,
        }


@dataclass
class ValidationResult:
    valid: bool
    violations: List[PolicyViolation] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    submitted_hash: str = ""   # SHA-256 of canonical JSON, stored on admission

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "violations": [v.to_dict() for v in self.violations],
            "warnings": self.warnings,
            "submitted_hash": self.submitted_hash,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def deep_get(d: dict, path: str, default: Any = None) -> Any:
    """
    Traverse a nested dict using a dotted-path key.
    Returns `default` if any key in the path is missing.

    Examples:
        deep_get({"a": {"b": 1}}, "a.b")  → 1
        deep_get({"a": {}}, "a.b.c")      → None
    """
    keys = path.split(".")
    current = d
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, None)
        if current is None:
            return default
    return current


def _canonical_hash(policy_json: dict) -> str:
    """Return SHA-256 hex digest of the canonically serialized policy JSON."""
    canonical = json.dumps(policy_json, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── Validator ─────────────────────────────────────────────────────────────────

class FederationPolicyValidator:
    """
    Validates a submitted policy JSON against the Base Network Parameters.

    Algorithm (in validate()):
      1. Check every LOCKED_PARAMS path — mismatch → PolicyViolation(locked_mismatch)
      2. Check every BOUNDED_PARAMS path — out of range → PolicyViolation(out_of_bounds)
      3. Check enforcement escalation levels are not weaker than the minimum
      4. Compute canonical SHA-256 hash of the submitted policy
      5. Return ValidationResult
    """

    def validate(self, policy_json: dict) -> ValidationResult:
        violations: List[PolicyViolation] = []
        warnings: List[str] = []

        # ── Step 1: Locked parameter check ────────────────────────────────
        for path, required_value in LOCKED_PARAMS.items():
            submitted_value = deep_get(policy_json, path, default=None)

            if submitted_value is None:
                # Treat missing locked param as a mismatch
                violations.append(PolicyViolation(
                    path=path,
                    required=required_value,
                    submitted=None,
                    bounds=None,
                    violation_type="locked_mismatch",
                    severity=PARAM_SEVERITY.get(path, DriftSeverity.HIGH),
                ))
                continue

            # Numeric tolerance for float comparisons
            if isinstance(required_value, float) and isinstance(submitted_value, (int, float)):
                if abs(float(submitted_value) - required_value) > 1e-9:
                    violations.append(PolicyViolation(
                        path=path,
                        required=required_value,
                        submitted=submitted_value,
                        bounds=None,
                        violation_type="locked_mismatch",
                        severity=PARAM_SEVERITY.get(path, DriftSeverity.HIGH),
                    ))
            elif submitted_value != required_value:
                violations.append(PolicyViolation(
                    path=path,
                    required=required_value,
                    submitted=submitted_value,
                    bounds=None,
                    violation_type="locked_mismatch",
                    severity=PARAM_SEVERITY.get(path, DriftSeverity.HIGH),
                ))

        # ── Step 2: Bounded parameter check ───────────────────────────────
        for path, bounds in BOUNDED_PARAMS.items():
            submitted_value = deep_get(policy_json, path, default=None)
            if submitted_value is None:
                # Missing bounded params get a warning, not a violation
                # (they'll fall back to defaults at runtime)
                warnings.append(f"Bounded param '{path}' not present in submitted policy — runtime default applies.")
                continue

            try:
                val = float(submitted_value)
            except (TypeError, ValueError):
                violations.append(PolicyViolation(
                    path=path,
                    required=bounds,
                    submitted=submitted_value,
                    bounds=bounds,
                    violation_type="out_of_bounds",
                    severity=DriftSeverity.MEDIUM,
                ))
                continue

            min_val = bounds.get("min")
            max_val = bounds.get("max")
            failed = False

            if min_val is not None and val < min_val:
                failed = True
            if max_val is not None and val > max_val:
                failed = True

            if failed:
                violations.append(PolicyViolation(
                    path=path,
                    required=None,
                    submitted=submitted_value,
                    bounds=bounds,
                    violation_type="out_of_bounds",
                    severity=DriftSeverity.MEDIUM,
                ))
            else:
                # Near-boundary warnings (within 10% of limit)
                if min_val is not None and (val - min_val) < (abs(val) * 0.10):
                    warnings.append(f"'{path}' = {val} is within 10% of minimum bound {min_val}.")
                if max_val is not None and (max_val - val) < (abs(val) * 0.10):
                    warnings.append(f"'{path}' = {val} is within 10% of maximum bound {max_val}.")

        # ── Step 3: Enforcement escalation sanity check ────────────────────
        # Verify that level-1 slash is ≥ 5% and level-4 includes 'suspend'
        dispute_cfg = policy_json.get("dispute_escalation", {})
        levels = dispute_cfg.get("levels", {})

        level_1 = levels.get("1", {})
        l1_slash = level_1.get("slash_percent", 0)
        if l1_slash < 5:
            violations.append(PolicyViolation(
                path="dispute_escalation.levels.1.slash_percent",
                required=">=5",
                submitted=l1_slash,
                bounds=None,
                violation_type="enforcement_too_weak",
                severity=DriftSeverity.HIGH,
            ))

        level_4 = levels.get("4", {})
        l4_actions = level_4.get("action_types", [])
        if "suspend" not in l4_actions and "revoke" not in l4_actions:
            violations.append(PolicyViolation(
                path="dispute_escalation.levels.4.action_types",
                required="must include 'suspend' or 'revoke'",
                submitted=l4_actions,
                bounds=None,
                violation_type="enforcement_too_weak",
                severity=DriftSeverity.HIGH,
            ))

        # ── Step 4: Hash ───────────────────────────────────────────────────
        submitted_hash = _canonical_hash(policy_json)

        # ── Step 5: Return ─────────────────────────────────────────────────
        valid = len(violations) == 0
        result = ValidationResult(
            valid=valid,
            violations=violations,
            warnings=warnings,
            submitted_hash=submitted_hash,
        )

        if valid:
            logger.info(f"[FederationPolicyValidator] Policy VALID. Hash: {submitted_hash[:16]}...")
        else:
            logger.warning(
                f"[FederationPolicyValidator] Policy INVALID — {len(violations)} violation(s). "
                f"Highest severity: {max((v.severity for v in violations), key=lambda s: list(DriftSeverity).index(s))}"
            )

        return result
