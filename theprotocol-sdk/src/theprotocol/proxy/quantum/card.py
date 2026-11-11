"""tp-proxy generates the quantum workload card extension from the backend's own facts (V0660 (c)).

The whole point of generating it is that a published card should not contain prose a human typed once and
forgot: change the machine and the card changes with it. So this module reads `backend.facts()` and fills
(a)'s models with it, and refuses — by name — anything it cannot read from a machine or from the module
that owns it.

Two refusals carry the design:

* A stub cloud adapter cannot produce a card, because its `facts()` refuses. A card built from a stub
  would advertise device facts nobody read from a device.
* The receipt's schema version and signing algorithm belong to (b), the order that builds receipts. If
  (b)'s module is importable they come from it; otherwise the caller passes them; otherwise this refuses.
  Inventing a version here would put a number on a signed, published card that no receipt builder honours.

Everything about what is a valid extension stays in theprotocol.quantum (a)'s models and schema): this
module builds them and lets them judge the result.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from ...quantum.models import QUANTUM_WORKLOAD_VERSION, QuantumWorkload
from .backends import Backend
from .meter import METERING_CIRCUIT

DEFAULT_ROLES: Sequence[str] = ("provider", "meter")
DEFAULT_RUNGS: Sequence[int] = (1,)
DEFAULT_RESIDENCY: Sequence[str] = ("EU",)
DEFAULT_RETENTION_DAYS = 30


class CardIncomplete(ValueError):
    """The card cannot be generated, and this says which fact is missing and who owns it."""


def _receipt_block(given: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if given:
        block = dict(given)
        missing = [k for k in ("schema_version", "signing_algorithm") if not block.get(k)]
        if missing:
            raise CardIncomplete(f"the receipt block is missing {', '.join(missing)}")
        return {"schema_version": str(block["schema_version"]),
                "signing_algorithm": str(block["signing_algorithm"])}
    try:  # (b) owns these: import them rather than restate them
        from ...quantum.receipts import RECEIPT_SCHEMA_VERSION, RECEIPT_SIGNING_ALGORITHM  # type: ignore
    except Exception:
        raise CardIncomplete(
            "no receipt block: its schema_version and signing_algorithm belong to the receipt builder "
            "(theprotocol.quantum.receipts). Pass receipt={'schema_version': ..., 'signing_algorithm': ...} "
            "until that module is there. A version invented here would be published on a signed card and "
            "honoured by nothing.") from None
    return {"schema_version": str(RECEIPT_SCHEMA_VERSION),
            "signing_algorithm": str(RECEIPT_SIGNING_ALGORITHM)}


def extension_for(backend: Optional[Backend], *,
                  roles: Iterable[str] = DEFAULT_ROLES,
                  receipt: Optional[Mapping[str, Any]] = None,
                  verification_rungs: Iterable[int] = DEFAULT_RUNGS,
                  acceptance_tests: Optional[Sequence[Mapping[str, Any]]] = None,
                  pricing: Optional[Mapping[str, Any]] = None,
                  residency: Iterable[str] = DEFAULT_RESIDENCY,
                  retention_days: int = DEFAULT_RETENTION_DAYS,
                  export_control: Optional[Mapping[str, Any]] = None,
                  description: Optional[str] = None,
                  required: bool = False) -> Dict[str, Any]:
    """Build the extension dict for this backend. Raises when a fact would have to be invented."""
    rungs = [int(r) for r in verification_rungs]
    params: Dict[str, Any] = {
        "version": QUANTUM_WORKLOAD_VERSION,
        "roles": list(roles),
        "evidence": {
            "receipt": _receipt_block(receipt),
            "metering_circuit": METERING_CIRCUIT,
            "verification_rungs": rungs,
        },
        "data": {
            "retention": {"results_days": int(retention_days), "circuits_days": 0},
            "residency": list(residency),
            # the extension's own rule, and the reason the source never yields a circuit
            "ledger_keeps": ["hashes", "verdicts"],
        },
    }
    if 3 in rungs:
        params["evidence"]["rung_3_basis"] = "signed_claims"
    if acceptance_tests:
        params["evidence"]["acceptance_tests"] = [dict(t) for t in acceptance_tests]
    if export_control:
        params["data"]["export_control"] = dict(export_control)
    if pricing:
        params["pricing"] = dict(pricing)
    if backend is not None:
        params["backends"] = [backend.facts()]

    # (a)'s models judge the result: strict, closed, every as_of a real date-time. A card this refuses is
    # a card the registry would refuse, and finding that out here is the cheap place to find it out.
    workload = QuantumWorkload.model_validate(params)
    return workload.to_extension_dict(description=description, required=required)
