"""ORG AUTHZ — the org-role → agent-permission default map (RBAC-plan Track A, unit A1).

An organization applies authority to its agents through IRONKEY org-delegation grants
(`agent_delegation_grants`, `principal_type='org'`), which only bite when the agent presents an
org-acting token (`act.sub = org:<slug>`, see PRODUCTION_DOCS/05_API_REFERENCE/Org_Acting_Tokens.md).
This module gives orgs a COHERENT default slice per authority level instead of hand-picking from
the full permission vocabulary (``agent_authz.ALL_PERMISSIONS`` — count it there, prose numbers
here have drifted before). It is a code-constant SSOT in the exact style of
``agent_authz.ROLE_PERMISSIONS`` and is served verbatim by ``GET /organizations/{id}/authz/catalog``.

Slices are MONOTONIC BY CONSTRUCTION (guest ⊆ member ⊆ admin ⊆ owner) — each level is defined as
the previous level plus additions, so the invariant cannot drift by edit.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, List

from agentvault_registry.agent_authz import ALL_PERMISSIONS

# Permissions NO org slice may ever contain, however senior the level. Granting these must stay a
# deliberate per-agent act (explicit grant / legacy-full), never a side effect of a role slice:
#   authz.delegate            — the meta-permission (may hand keys onward); PART 15 never-delegatable
#   contract.template.publish — marketplace act; PART 15 never-delegatable
#   phone.use                 — computer-use blast radius; explicit-grant-only by design
#   teg.system_transfer       — grandfathered over-permission (legacy-full only, see agent_authz)
#   cicd.deploy               — RESERVED: no agent-tier gate consults it yet (2026-07-24 audit S7)
#   forge.royalty_admin       — RESERVED: royalty surface is dev/org-admin-tier, no agent gate yet
NEVER_IN_ORG_SLICES: FrozenSet[str] = frozenset({
    "authz.delegate",
    "contract.template.publish",
    "phone.use",
    "teg.system_transfer",
    "cicd.deploy",
    "forge.royalty_admin",
})

_GUEST: FrozenSet[str] = frozenset({
    # observe + price: own-state reads and FX quoting, nothing that moves value
    "read.profile", "enforcement.self", "fx.quote",
})

_MEMBER: FrozenSet[str] = _GUEST | {
    # the working agent: transact locally, serve and consume A2A, engage contracts,
    # defend itself in disputes, hold a SPIFFE identity, trade on the local venue
    "teg.transfer", "a2a.pay", "a2a.collect",
    "contracts.engage", "disputes.file", "reputation.signal",
    "identity.mtls", "exchange.trade",
}

_ADMIN: FrozenSet[str] = _MEMBER | {
    # the operating agent: cross-frame value, staking, market issuance and both
    # governance surfaces
    "teg.transfer_xreg", "staking.manage",
    "exchange.ipo", "exchange.vote",
    "gov.propose", "gov.vote",
    # §ORGSPEND — commission work in the org's name (the CLIENT half; the WORKER half,
    # guild.bid_for_org, stays owner-tier). Only honored via org: grants like its sibling,
    # and every treasury draw it authorizes still passes the procurement cap.
    "guild.post_for_org",
}

_OWNER: FrozenSet[str] = _ADMIN | {
    # org-consent acts — these permissions are BY DESIGN only honored via org: grants
    # (a role, even legacy-full, never suffices for the *_for_org pair / guild bid),
    # so the top slice is exactly where they belong
    "guild.bid_for_org", "forge.evolve_for_org", "forge.verify_for_org",
    # lineage self-evolution under birth-token caveats
    "cicd.version", "bundle.write",
}

ORG_ROLE_ORDER: tuple[str, ...] = ("guest", "member", "admin", "owner")

ORG_ROLE_PERMISSION_DEFAULTS: Dict[str, FrozenSet[str]] = {
    "guest": _GUEST,
    "member": _MEMBER,
    "admin": _ADMIN,
    "owner": _OWNER,
}


def org_role_slice(role: str) -> set[str]:
    """The default permission slice for an org authority level ('' set for unknown roles)."""
    return set(ORG_ROLE_PERMISSION_DEFAULTS.get(role, frozenset()))


def catalog() -> List[dict]:
    """The catalog rows served by GET /organizations/{id}/authz/catalog — role, full slice,
    and what each level ADDS over the previous (the FE renders adds as the story)."""
    rows: List[dict] = []
    prev: FrozenSet[str] = frozenset()
    for role in ORG_ROLE_ORDER:
        slice_ = ORG_ROLE_PERMISSION_DEFAULTS[role]
        rows.append({
            "role": role,
            "permissions": sorted(slice_),
            "adds": sorted(slice_ - prev),
        })
        prev = slice_
    return rows


async def grant_org_slice(db, *, org_slug: str, agent_dids: list, role: str,
                          granted_by: int) -> int:
    """THE one writer for org→agent slice grants (bulk route, assign hook, onboarding
    hook — never copy this INSERT). UPSERTs the org delegation grant for each DID with
    the A1 slice for `role`; idempotent via the table's principal+delegate conflict key.
    Caller owns the transaction (no commit here). Returns how many rows were written."""
    from sqlalchemy import text  # local: keep this module import-light for the CI boot gate
    perms = sorted(org_role_slice(role))
    if not perms or not agent_dids:
        return 0
    principal = f"org:{org_slug}"
    for did in agent_dids:
        await db.execute(text("""
            INSERT INTO agent_delegation_grants
                (principal_type, principal_ref, delegate_agent_did, permissions, may_redelegate,
                 max_depth, granted_by_dev_id, expires_at)
            VALUES ('org', :pr, :did, :perms, false, 1, :dev, NULL)
            ON CONFLICT (principal_type, principal_ref, delegate_agent_did) DO UPDATE SET
                permissions = EXCLUDED.permissions, may_redelegate = EXCLUDED.may_redelegate,
                max_depth = EXCLUDED.max_depth, expires_at = EXCLUDED.expires_at,
                revoked_at = NULL, revoke_reason = NULL
        """), {"pr": principal, "did": did, "perms": perms, "dev": granted_by})
    return len(agent_dids)


# Import-time self-checks — a wrong edit fails the boot-import CI gate, not a runtime request.
for _r, _s in ORG_ROLE_PERMISSION_DEFAULTS.items():
    _unknown = _s - ALL_PERMISSIONS
    assert not _unknown, f"org_authz: slice '{_r}' carries unknown permissions {_unknown}"
    _banned = _s & NEVER_IN_ORG_SLICES
    assert not _banned, f"org_authz: slice '{_r}' carries never-included permissions {_banned}"
for _a, _b in zip(ORG_ROLE_ORDER, ORG_ROLE_ORDER[1:]):
    assert ORG_ROLE_PERMISSION_DEFAULTS[_a] <= ORG_ROLE_PERMISSION_DEFAULTS[_b], \
        f"org_authz: monotonicity broken between '{_a}' and '{_b}'"
