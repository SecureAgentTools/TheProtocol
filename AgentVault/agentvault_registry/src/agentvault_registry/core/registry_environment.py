"""§MCPTEST30 (V0644, agentvault2-66 with agentvault2-aa, 2026-10-26): what this registry states it is.

/api/v1/public/registry-config says it (`environment`), so the MCP tester stages a money-moving fixture only where the
target itself states "sandbox" (api_tests/contracts/earned_agent_public.py, the local guild lifecycle), never on a guess
from a URL or a sweep's name. An unset registry reads "production", so a run pointed at the wrong target fails closed.
A sandbox frame's operators inherit the value (services/cloud_provisioner.PARENT_POSTURE_KEYS), so a production frame
can never give birth to a "sandbox" operator; the frame template and the kit leave it unset
(.forgejo/checks/frame_template_contract.py in the stack refuses a template that sets it to sandbox).

    REGISTRY_ENVIRONMENT   unset or empty: "production"; otherwise the value, spaces trimmed and case kept (the
                           tester's check is exact, so "Sandbox" is not "sandbox").
"""
from __future__ import annotations

import os

DEFAULT = "production"


def registry_environment() -> str:
    return (os.getenv("REGISTRY_ENVIRONMENT") or "").strip() or DEFAULT
