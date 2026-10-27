"""Sanity contract — proves the framework end-to-end (AAA+ refactor 2026-05-21).

Registers a single trivial contract against /health (the always-available probe).
Used to validate the contract framework wiring before Phase II-B's 50 real contracts.
"""
from __future__ import annotations

from ..core.contract import Endpoint


@Endpoint(method="GET", path="/health", auth="none", category="status", idempotent=True)
class HealthProbe:
    """Public health endpoint — should always 200 with {status:'ok'}."""
    expected_status = 200
