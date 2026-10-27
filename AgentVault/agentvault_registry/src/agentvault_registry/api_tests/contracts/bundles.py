"""Agent Bundles contracts (AAA+ Phase II-B — §pass51 endpoints, 2026-05-21).

Signed .tpb archives with manifest+README. Three modes (snapshot/template/migration).
Marketplace + admin moderation queue.
"""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


# ── Public marketplace ───────────────────────────────────────────────────
@Endpoint(
    method="GET",
    path="/bundles/marketplace/featured",
    auth="none",
    category="bundles",
    idempotent=True,
)
class BundleMarketplaceFeatured:
    """Public featured templates. No auth required."""
    expected_status = 200


# ── Developer-tier bundle management ─────────────────────────────────────
@Endpoint(method="GET", path="/bundles", auth="developer", category="bundles", idempotent=True)
class BundleList:
    """List visible bundles (own + public + official)."""
    expected_status = 200


@Endpoint(method="POST", path="/bundles", auth="developer", category="bundles", idempotent=False)
class BundleCreate:
    """Create a bundle (snapshot/template/migration)."""
    def body(self, ctx):
        return {
            "kind": "snapshot",
            "visibility": "private",
            "agent_dids": [],
            "name": "AAA+ contract test bundle",
            "description": "Auto-created",
        }
    expected_status = [200, 201, 400, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (400, 422) and ("agent" in r.detail_lower() or "did" in r.detail_lower()),
            reason="No agents provided for snapshot bundle",
        ),
    ]


@Endpoint(
    method="GET",
    path="/bundles/{bundle_id}/manifest",
    auth="developer",
    category="bundles",
    idempotent=True,
)
class BundleManifest:
    """Cheap manifest preview. Templated path."""
    expected_status = [200, 404, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (404, 422),
            reason="No bundle with placeholder ID — prereq not yet wired",
        ),
    ]


@Endpoint(
    method="GET",
    path="/bundles/{bundle_id}/download",
    auth="developer",
    category="bundles",
)
class BundleDownload:
    """Stream the .tpb binary."""
    expected_status = [200, 404, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (404, 422),
            reason="No bundle with placeholder ID — prereq not yet wired",
        ),
    ]


@Endpoint(method="POST", path="/bundles/{bundle_id}/restore", auth="developer", category="bundles", idempotent=False)
class BundleRestore:
    """Restore bundle as fresh agent (copy or mirror mode)."""
    def body(self, ctx):
        return {"mode": "copy"}
    expected_status = [200, 201, 404, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (404, 422),
            reason="No bundle with placeholder ID",
        ),
    ]


@Endpoint(method="POST", path="/bundles/restore-from-upload", auth="developer", category="bundles", idempotent=False)
class BundleRestoreUpload:
    """Upload a .tpb (or legacy .json) and restore."""
    def body(self, ctx):
        return {}  # multipart upload, not JSON — will 422
    expected_status = [200, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 422,
            reason="Endpoint expects multipart upload, not JSON body",
        ),
    ]


@Endpoint(method="POST", path="/bundles/{bundle_id}/fork", auth="developer", category="bundles", idempotent=False)
class BundleFork:
    """Fork a template bundle."""
    def body(self, ctx):
        return {"name": "Forked bundle"}
    expected_status = [200, 201, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="No bundle with placeholder ID",
        ),
    ]


@Endpoint(method="PATCH", path="/bundles/{bundle_id}", auth="developer", category="bundles", idempotent=False)
class BundleUpdate:
    """Edit bundle metadata (owner only)."""
    def body(self, ctx):
        return {"name": "Updated bundle", "description": "Updated"}
    expected_status = [200, 403, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (403, 404),
            reason="Bundle ID placeholder OR caller is not owner",
        ),
    ]


@Endpoint(method="DELETE", path="/bundles/{bundle_id}", auth="developer", category="bundles", idempotent=True)
class BundleDelete:
    """Owner soft-delete."""
    expected_status = [200, 204, 403, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (403, 404),
            reason="Bundle ID placeholder OR not owner",
        ),
    ]


@Endpoint(method="POST", path="/bundles/{bundle_id}/rating", auth="developer", category="bundles", idempotent=False)
class BundleRating:
    """Rate a bundle 1-5 stars."""
    def body(self, ctx):
        return {"stars": 5, "comment": "AAA+ contract rating"}
    expected_status = [200, 201, 404, 409]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Bundle ID placeholder",
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status == 409,
            reason="Already rated this bundle",
        ),
    ]


# ── Admin moderation ─────────────────────────────────────────────────────
@Endpoint(
    method="GET",
    path="/admin/bundles/reports",
    auth="developer",
    category="admin_bundles_moderation",
    idempotent=True,
)
class AdminBundleReports:
    """Bundle moderation queue."""
    expected_status = 200
