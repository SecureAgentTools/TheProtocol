"""EventStore audit emission for Command Center probe + action events.

Both event types are seeded as audit-only in event_emission_policies:
  emit_from_registry=true, emit_from_teg=false, skip_in_projection=true
"""

import logging
import time
from typing import Any

from agentvault_registry.event_emitter import get_event_emitter

logger = logging.getLogger(__name__)


def _idem(prefix: str, target: str, key: str) -> str:
    return f"{prefix}-{target}-{key}-{int(time.time() * 1000)}"


def emit_probe(target: str, check_id: str, status: str, summary: str, actor_email: str | None = None) -> None:
    """Fire-and-forget audit emission for a single probe execution."""
    try:
        emitter = get_event_emitter()
        data: dict[str, Any] = {
            "check_id": check_id,
            "target": target,
            "status": status,
            "summary": summary,
        }
        if actor_email:
            data["actor"] = actor_email
        emitter.emit_background(
            event_type="CommandCenterProbe",
            aggregate_id=target,
            aggregate_type="CommandCenterTarget",
            data=data,
            idempotency_key=_idem("cc-probe", target, check_id),
        )
    except Exception as e:
        logger.debug(f"[diag-audit] probe emit skipped: {e}")


def emit_action(target: str, action_id: str, status: str, dry_run: bool, summary: str, actor_email: str | None = None) -> None:
    """Fire-and-forget audit emission for a remediation action invocation."""
    try:
        emitter = get_event_emitter()
        data: dict[str, Any] = {
            "action_id": action_id,
            "target": target,
            "status": status,
            "dry_run": dry_run,
            "summary": summary,
        }
        if actor_email:
            data["actor"] = actor_email
        emitter.emit_background(
            event_type="CommandCenterAction",
            aggregate_id=target,
            aggregate_type="CommandCenterTarget",
            data=data,
            idempotency_key=_idem("cc-action", target, action_id),
        )
    except Exception as e:
        logger.debug(f"[diag-audit] action emit skipped: {e}")
