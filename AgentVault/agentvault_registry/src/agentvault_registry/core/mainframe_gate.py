"""Scalable mainframe-only feature gate (§pass66 — 2026-05-22).

Single source of truth for "is this feature available on a cloud-operator
or only on a sovereign-mainframe registry?". Both backend endpoints and
the frontend permission composable read from the same primitives so the
policy stays consistent.

Adding a NEW mainframe-only feature is 1 line on each side:
  backend:  `dependencies=[Depends(require_mainframe_only)]` on the router
  frontend: `const canX = isMainframe` in usePermissions.ts

Examples of mainframe-only features today (§pass66):
  - Cross-frame bridge management (frame invitations + frame-management view)
  - Federation license issuance + revocation
  - Cloud-operator provisioning (self-service + admin)
  - AVT minting (already blocked via MINTING_AUTHORITY env)
  - Fiat onramp (already gated via FIAT_GENESIS_REGISTRY)

Cloud-operators answer 404 with a detail that starts with the code word
`mainframe_only:` and keeps the sentence telling the user the feature is
mainframe-only (D6-820, V0640: a 503 read as an outage to a client, to
monitoring and to the testers; this is a deliberate refusal, so a 4xx with a
code word a reader can branch on). The seeded operator-admin's own admin sub-flags
(admin_treasury / admin_federation / etc.) still gate WHICH admin features
they can touch on their OWN registry — this gate is layered ON TOP for
features that should never run anywhere except a mainframe.

Tier check mirrors `core.registry_identity._build_tier()` (used by Registry
Card v0.3) — so the gate decision agrees with what the card publishes:
- sovereign-mainframe (Registry-A on agentvault.com w/ IS_CENTRAL_REGISTRY,
  Frame-B on frame-b.theprotocol.cloud w/ IS_CENTRAL_REGISTRY,
  Registry-Test and Registry-Test-B w/ IS_CENTRAL_REGISTRY in sandbox tier) → ALLOW
- cloud-operator / standalone / regional-mainframe → DENY (404, `mainframe_only:`)
"""
import logging
import os

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)


def is_mainframe() -> bool:
    """True iff THIS registry process is a sovereign-mainframe.

    Allowlist + IS_CENTRAL_REGISTRY=true pattern:
      - `registry-a` (Frame A prod)
      - `frame-b` (Frame B prod)
      - `registry-test` (sandbox-A — counts as full mainframe so sandbox
        iteration of mainframe-only features works; §pass73 2026-05-26)
      - `registry-test-b` (sandbox-B — same rationale; mirrors Frame B in
        sandbox tier)

    Future regional-mainframes append their names here when added to the catalog.
    """
    from agentvault_registry.config import settings
    name = (getattr(settings, "REGISTRY_NAME", "") or "").lower()
    is_central = (os.environ.get("IS_CENTRAL_REGISTRY", "false").lower() == "true")
    builtin = ("registry-a", "frame-b", "frame-c", "registry-test", "registry-test-b", "registry-test-c")
    # §2026-07-26 — the allowlist is now ENV-EXTENSIBLE so a NEW sovereign frame
    # (the docstring's "future regional-mainframes append their names here") no
    # longer needs a code change + fleet rebuild just to mint its own currency or
    # provision its own operators. Belt-and-braces: `IS_CENTRAL_REGISTRY=true` is
    # still required, so adding a name alone grants nothing on a cloud-op.
    extra = tuple(
        n.strip().lower()
        for n in (os.environ.get("MAINFRAME_REGISTRY_NAMES", "") or "").split(",")
        if n.strip()
    )
    return name in (builtin + extra) and is_central


# D6-820 (V0640): the code word a reader branches on, and the sentence every reader before V0640 matched (the testers'
# GATE_SENTENCE is its first clause); a refusal is 404 with "<code word>: <sentence>" (the RFC 7807 layer stringifies a
# dict detail, so the code word goes first in a plain string). An older registry answered 503 with the bare sentence:
# a reader one release apart accepts both.
MAINFRAME_ONLY_CODE = "mainframe_only"
MAINFRAME_ONLY_SENTENCE = (
    "This feature runs on sovereign mainframes only. "
    "Cloud-operators federate with the mainframe via the bilateral "
    "trust chain: they don't independently provision sub-operators, "
    "issue federation licenses, configure cross-frame bridges, or "
    "mint units. Use your federated mainframe's UI for these actions."
)


def mainframe_only_refusal(sentence: str = MAINFRAME_ONLY_SENTENCE) -> HTTPException:
    """The answer of a registry that is not a sovereign mainframe to a mainframe-only rail: 404 with the code word
    first and the sentence after it. Raise it; never answer 503 for this refusal (503 says "try again later")."""
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{MAINFRAME_ONLY_CODE}: {sentence}")


# The reverse guard, the same class: a route that runs on a cloud operator only, called on a mainframe.
OPERATOR_ONLY_CODE = "operator_only"


def operator_only_refusal(sentence: str) -> HTTPException:
    """A mainframe's answer to a route that runs on a cloud operator only: 404 with the code word first and the route's
    own sentence after it ("... is for cloud-ops only. Mainframe admins use ..."); a registry before V0640 answered 503
    with the bare sentence."""
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{OPERATOR_ONLY_CODE}: {sentence}")


async def require_mainframe_only():
    """FastAPI dependency — 404 `mainframe_only:` if this registry isn't a sovereign mainframe.

    Usage:
        @router.post(
            "/admin/some-mainframe-only-endpoint",
            dependencies=[Depends(require_mainframe_only)],
        )
        def my_endpoint(...): ...

    Async-flavored so it composes cleanly with the other Security/Depends
    dependencies on admin routes.
    """
    if not is_mainframe():
        raise mainframe_only_refusal()


__all__ = ["MAINFRAME_ONLY_CODE", "MAINFRAME_ONLY_SENTENCE", "OPERATOR_ONLY_CODE", "is_mainframe",
           "mainframe_only_refusal", "operator_only_refusal", "require_mainframe_only"]
