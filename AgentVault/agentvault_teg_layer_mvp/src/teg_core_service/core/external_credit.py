"""§SECFIX-11 (2026-09-25) — the gate in front of /api/v1/admin/treasury/external-credit, as a FastAPI dependency.

That route credits the treasury by the amount the caller states, with a fresh id on every call (no idempotency) and no
source check, and any internal identity of any trusted domain passed its auth: a federated peer's registry reached it
through this frame's nginx-teg (measured on the sandbox pair). Nothing calls it. It is RETIRED: 410 unless
TEG_EXTERNAL_CREDIT_ENABLED is true, and then only for this TEG's own frame (core/internal_auth.local_leg_caller_ok).
A dependency, because FastAPI resolves dependencies before it validates the body: both answers come before the body is
read. A module of its own so it can be tested without importing the treasury router.
"""
import os

from fastapi import HTTPException, Request, status

from .internal_auth import extract_spiffe_from_request, local_leg_caller_ok


def external_credit_gate(http_request: Request) -> None:
    if (os.getenv("TEG_EXTERNAL_CREDIT_ENABLED") or "").strip().lower() not in ("1", "true", "yes", "on"):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="treasury_external_credit_retired: use /api/v1/cross-teg/treasury-fund (TEG_EXTERNAL_CREDIT_ENABLED)",
        )
    if not local_leg_caller_ok(extract_spiffe_from_request(http_request)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="treasury_external_credit_refused: this TEG's own frame only",
        )
