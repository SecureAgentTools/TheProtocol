"""D6-841 (agentvault2-5b, 2026-10-25): whether the Phone Fabric is on here, one predicate for its two readers.

routers/phone_fabric.py refuses every rail with 503 "Phone Fabric is disabled on this registry" when it is off, and
/api/v1/public/registry-config says it (phone_fabric_enabled), so the console asks the owner rail only where the fabric
runs. Found by the console suite's lifecycle 72 in the V0641 proof on sbx-beta: once owned agents act through the session
(V0641), Pocket's approvals asked GET /api/v1/phone/sessions/mine on every visit to a registry without the fabric.

    PHONE_FABRIC_ENABLED   default "false"; only "true" (any case, spaces trimmed) turns the fabric on.
"""
from __future__ import annotations

import os


def phone_fabric_enabled() -> bool:
    return os.getenv("PHONE_FABRIC_ENABLED", "false").strip().lower() == "true"
