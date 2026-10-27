"""RBAC 5-cluster access matrix tests (§pass73.3.15 — separate batch).

Tests the 5 granular admin flags (admin_treasury, admin_support,
admin_enforcement, admin_federation, admin_platform). Creates 5 test
developers, each with EXACTLY one cluster flag set + is_admin=False.
Then sweeps the 5×5 access matrix:
  - Owner dev calls owner-cluster endpoint  → expect 200 (or non-4xx)
  - Owner dev calls foreign-cluster endpoint → expect 403

This exposes any router with the wrong require_admin_flag(...) gate
that commander's is_admin=True would otherwise sidestep.

NOTE: idempotent bootstrap — re-running the suite reuses existing
test devs. Test dev passwords are deterministic + sandbox-only.
"""
from __future__ import annotations
import asyncio
import base64
import json
from typing import Optional


def _decode_jwt_sub(jwt: str) -> Optional[int]:
    """Extract the `sub` claim (developer_id) from a JWT — base64url payload."""
    try:
        payload = jwt.split(".")[1]
        # base64url padding
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        sub = claims.get("sub")
        return int(sub) if sub is not None else None
    except Exception:
        return None

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, jwt_usable,
)


# 5 clusters → 1 representative GET endpoint each
CLUSTER_ENDPOINTS = {
    "admin_treasury":    "/api/v1/admin/fee-collector/info",
    "admin_support":     "/api/v1/admin/broadcasts/overview",
    "admin_enforcement": "/api/v1/admin/bundles/reports",
    "admin_federation":  "/api/v1/admin/federation/peers/all",
    "admin_platform":    "/api/v1/admin/canary-judge/status",
}
ALL_CLUSTERS = list(CLUSTER_ENDPOINTS.keys())

RBAC_PASSWORD = "RbacTestDev2026!"

# Module-level cache: cluster → (dev_id, dev_jwt). Populated lazily.
# §MCPTEST30 (2026-09-30): this cache lives as long as the gunicorn WORKER, not the run, so its tokens are re-minted
# once they come within five minutes of their own `exp` (jwt_usable), and a token the registry refuses is dropped
# (`_forget`). Before that, a run landing on a worker used 90+ minutes earlier presented five expired tokens and
# reported every 401 as an RBAC leak (the 03:10Z nightly: five of its seven hard failures).
_DEV_CACHE: dict = {}
_BOOTSTRAP_LOCK = asyncio.Lock()


def _forget(cluster: str) -> None:
    """Drop a cached credential the registry refused, so the next attempt mints a fresh one."""
    _DEV_CACHE.pop(cluster, None)


def _email_for(cluster: str) -> str:
    return f"rbac_{cluster.replace('admin_', '')}@test.sandbox"


def _is_silent_or_error(r):
    if isinstance(r, str):
        return True
    if isinstance(r, dict):
        if not r:
            return True
        if "_text" in r:
            return isinstance(r["_text"], str)
    return False


async def _ensure_rbac_dev(rig: FederationTestRig, cluster: str) -> tuple[int, str]:
    """Idempotently provision a test dev with EXACTLY this cluster flag.

    Returns (dev_id, dev_jwt). Cached per process while the token is usable (its own `exp` more than five minutes
    away); an expiring or refused token is re-minted by the login path below, which is also the idempotent path.
    Bootstrap is serialized by a global asyncio lock.
    """
    cached = _DEV_CACHE.get(cluster)
    if cached and jwt_usable(cached[1]):
        return cached

    async with _BOOTSTRAP_LOCK:
        cached = _DEV_CACHE.get(cluster)
        if cached and jwt_usable(cached[1]):
            return cached
        _forget(cluster)

        email = _email_for(cluster)
        admin = rig.mcp("sandbox-A-admin")

        # Try login first (idempotent path). The MCP wrapper passes the
        # underlying /auth/login response through; that endpoint doesn't
        # populate `developer_id` so we decode the JWT's `sub` claim ourselves.
        dev_jwt: Optional[str] = None
        dev_id: Optional[int] = None
        try:
            tok = await admin.call(
                "adminGetDeveloperToken",
                {"email": email, "password": RBAC_PASSWORD},
            )
            if isinstance(tok, dict):
                dev_jwt = tok.get("access_token")
                if dev_jwt:
                    dev_id = _decode_jwt_sub(dev_jwt)
        except Exception:
            dev_jwt = None

        if not dev_jwt or not dev_id:
            # Register fresh via adminRequest → /auth/register
            # (MCP authRegister wrapper drops `name` field; bypass it).
            try:
                await admin.call(
                    "adminRequest",
                    {
                        "method": "POST",
                        "endpoint": "/api/v1/auth/register",
                        "body": {
                            "name": f"RBAC-{cluster.replace('admin_', '')}",
                            "email": email,
                            "password": RBAC_PASSWORD,
                        },
                    },
                )
            except Exception:
                pass  # may already exist or rate-limited, continue

            # Login post-register and decode dev_id from JWT.
            tok = await admin.call(
                "adminGetDeveloperToken",
                {"email": email, "password": RBAC_PASSWORD},
            )
            if not isinstance(tok, dict) or not tok.get("access_token"):
                raise RuntimeError(
                    f"rbac: login after register failed for {email}: {tok}"
                )
            dev_jwt = tok["access_token"]
            dev_id = _decode_jwt_sub(dev_jwt)
            if not dev_id:
                raise RuntimeError(
                    f"rbac: JWT sub decode failed for {email}"
                )

            # Force-verify email (sandbox shortcut, idempotent)
            try:
                await admin.call("forceEmailVerify", {"developer_id": int(dev_id)})
            except Exception:
                pass  # may already be verified

        # Set exactly this cluster flag (idempotent — clears all other flags +
        # is_admin to ensure no superadmin bypass)
        flags = {c: (c == cluster) for c in ALL_CLUSTERS}
        flags["is_admin"] = False
        try:
            await admin.call(
                "updateDeveloperAdminFlags",
                {"developer_id": int(dev_id), "admin_flags": flags},
            )
        except Exception as e:
            # Non-fatal — log and continue. If flags aren't set the test
            # will surface 403 from owner cluster (a meaningful failure).
            print(f"[rbac] flag-set warning for {cluster}: {e}")

        _DEV_CACHE[cluster] = (int(dev_id), dev_jwt)
        return _DEV_CACHE[cluster]


async def _probe_with_dev(
    rig: FederationTestRig, dev_jwt: str, endpoint: str
) -> int:
    """Call adminRequest with developer_jwt override; return HTTP status code."""
    admin = rig.mcp("sandbox-A-admin")
    r = await admin.call(
        "adminRequest",
        {
            "method": "GET",
            "endpoint": endpoint,
            "developer_jwt": dev_jwt,
        },
    )
    if isinstance(r, dict):
        return int(r.get("status_code") or 0)
    return 0


def _make_rbac_test(owner_cluster: str):
    """Factory: build a federation_test for one owner cluster.

    Verifies owner=200 (or non-4xx) on own endpoint; 403 on the 4 foreign
    endpoints.
    """
    owner_endpoint = CLUSTER_ENDPOINTS[owner_cluster]
    foreign_clusters = [c for c in ALL_CLUSTERS if c != owner_cluster]

    @federation_test(
        name=f"rbac_{owner_cluster}_owner_matrix",
        category="rbac_5cluster_matrix",
        budget_sec=60.0,
        severity="high",
        requires=["sandbox-A", "sandbox-A-admin"],
        tags=["rbac", owner_cluster, "matrix"],
    )
    async def _test(rig: FederationTestRig) -> AssertionResult:
        state: dict = {"owner": owner_cluster}

        async def predicate():
            try:
                # Bootstrap owner dev (idempotent + cached)
                dev_id, dev_jwt = await _ensure_rbac_dev(rig, owner_cluster)
                state["dev_id"] = dev_id

                # Probe own endpoint — expect 2xx
                own_code = await _probe_with_dev(rig, dev_jwt, owner_endpoint)
                state["own_code"] = own_code
                if own_code == 401:
                    # §MCPTEST30: a 401 is the registry refusing the TEST'S OWN CREDENTIAL, before any admin-flag
                    # gate ran, so it says nothing about RBAC. Re-mint and let the next attempt measure.
                    _forget(owner_cluster)
                    state["fail"] = (
                        "the test developer's own token was refused (401) before any RBAC gate ran; "
                        "an instrument state, not an RBAC verdict (re-minted for the next attempt)")
                    return False
                if own_code == 403:
                    state["fail"] = (
                        f"owner {owner_cluster} blocked from own endpoint "
                        f"{owner_endpoint}"
                    )
                    return False
                if not 200 <= own_code < 300:
                    # §MCPTEST30: the owner criterion was `!= 403`, so a dead credential (401), a missing route (404)
                    # or a server error all read as "owner allowed". The owner must be SERVED; anything else polls
                    # again and, if it lasts, fails naming the code.
                    state["fail"] = f"owner {owner_cluster} not served on its own endpoint: HTTP {own_code}"
                    return False
                state.pop("fail", None)

                # Probe foreign endpoints — expect 403 on each
                foreign_results = {}
                for fc in foreign_clusters:
                    fc_endpoint = CLUSTER_ENDPOINTS[fc]
                    code = await _probe_with_dev(rig, dev_jwt, fc_endpoint)
                    foreign_results[fc] = code
                state["foreign_codes"] = foreign_results
                if any(c == 401 for c in foreign_results.values()):
                    _forget(owner_cluster)
                    state["fail"] = (
                        "the test developer's token was refused (401) on a foreign endpoint after its own endpoint "
                        f"served it: {foreign_results}; an instrument state, not an RBAC verdict (re-minted)")
                    return False

                # Pass criteria: owner served AND all foreigners == 403
                foreign_ok = all(c == 403 for c in foreign_results.values())
                if not foreign_ok:
                    state["fail"] = (
                        f"foreign cluster(s) returned non-403: {foreign_results}"
                    )
                return foreign_ok
            except Exception as e:
                state["error"] = repr(e)[:300]
                return False

        return await rig.assert_within(
            budget_sec=60.0, predicate=predicate,
            description=(
                f"RBAC: dev with only {owner_cluster} flag must succeed on "
                f"{owner_endpoint} and 403 on all 4 foreign cluster endpoints"
            ),
            capture_state=lambda: state,
        )

    # Decorator pins the test to the registry; rename for stable inspection.
    _test.__name__ = f"test_rbac_{owner_cluster}_owner_matrix"
    return _test


# Build & expose 5 tests at import time (one per owner cluster)
test_rbac_admin_treasury    = _make_rbac_test("admin_treasury")
test_rbac_admin_support     = _make_rbac_test("admin_support")
test_rbac_admin_enforcement = _make_rbac_test("admin_enforcement")
test_rbac_admin_federation  = _make_rbac_test("admin_federation")
test_rbac_admin_platform    = _make_rbac_test("admin_platform")
