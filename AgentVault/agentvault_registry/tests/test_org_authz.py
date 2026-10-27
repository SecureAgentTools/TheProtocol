"""A1 — org-role → permission default map invariants (pure unit, no DB).

These are REAL failure surfaces: each test breaks if someone edits a slice into an
unknown permission, a banned meta-permission, or a non-monotonic shape.
"""
from agentvault_registry.agent_authz import ALL_PERMISSIONS
from agentvault_registry.services.org_authz import (
    NEVER_IN_ORG_SLICES,
    ORG_ROLE_ORDER,
    ORG_ROLE_PERMISSION_DEFAULTS,
    catalog,
    org_role_slice,
)


def test_slices_are_subsets_of_vocabulary():
    for role, s in ORG_ROLE_PERMISSION_DEFAULTS.items():
        assert s <= ALL_PERMISSIONS, f"{role} carries unknown perms: {s - ALL_PERMISSIONS}"


def test_banned_metas_absent_from_every_slice():
    for role, s in ORG_ROLE_PERMISSION_DEFAULTS.items():
        assert not (s & NEVER_IN_ORG_SLICES), f"{role} carries banned perms: {s & NEVER_IN_ORG_SLICES}"


def test_monotonic_guest_member_admin_owner():
    for lo, hi in zip(ORG_ROLE_ORDER, ORG_ROLE_ORDER[1:]):
        assert ORG_ROLE_PERMISSION_DEFAULTS[lo] < ORG_ROLE_PERMISSION_DEFAULTS[hi], \
            f"{lo} must be a strict subset of {hi}"


def test_org_consent_perms_live_in_owner_only():
    # guild.bid_for_org / forge.*_for_org are honored ONLY via org: grants — they belong
    # to the top slice and must not leak downward.
    for p in ("guild.bid_for_org", "forge.evolve_for_org", "forge.verify_for_org"):
        assert p in ORG_ROLE_PERMISSION_DEFAULTS["owner"]
        assert p not in ORG_ROLE_PERMISSION_DEFAULTS["admin"]


def test_catalog_rows_mirror_the_constant_and_adds_partition():
    rows = catalog()
    assert [r["role"] for r in rows] == list(ORG_ROLE_ORDER)
    seen = set()
    for r in rows:
        assert set(r["permissions"]) == set(ORG_ROLE_PERMISSION_DEFAULTS[r["role"]])
        assert set(r["adds"]).isdisjoint(seen), "adds must be new at each level"
        seen |= set(r["adds"])
    assert seen == set(ORG_ROLE_PERMISSION_DEFAULTS["owner"]), "adds must partition the owner slice"


def test_unknown_role_yields_empty_slice():
    assert org_role_slice("chancellor") == set()
