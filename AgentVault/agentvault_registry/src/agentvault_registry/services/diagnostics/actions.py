"""Remediation actions for the Command Center.

Each action is read-validated, idempotent where possible, and re-runs the
triggering check after apply. All actions emit a CommandCenterAction event
for the audit trail. Each acts on THIS frame's own operators only.

  - nginx-reload  — validate, then re-read the config in an operator's nginx-federation sidecar
  - teg-restart   — restart an operator's TEG through the operator lifecycle's one rule (~20s downtime)

§F6 group 4 (2026-09-27, his decision "retire frame a actions", and his words "i approve to finish f6 implementation
on sandbox"): two Frame-A-era actions are RETIRED, not ported, because each reached into Frame A or Frame B from
whichever frame ran it. `spire-bundle-refresh` ran `bundle set` on agentvault-spire-server and frame-b-spire-server by
constant and restarted agentvault-cert-writer-a; `identity-network-reconnect` joined the target's TEG and sidecar to
agentvault_identity_network, Frame A's network (and teg-restart did the same join after every restart). A frame's
federation is the invitation rail's (approve and finalize set the relationship and the peer's bundle; the cert-writers
carry the peer root to every sidecar), and an operator's networks are its compose's.
"""

import logging
import time
from types import SimpleNamespace
from typing import Awaitable, Callable, Optional

from .audit import emit_action
from .probe import probe_failed
from .schemas import ActionResult, CheckResult

logger = logging.getLogger(__name__)


# ─── helpers ─────────────────────────────────────────────────────────────


def _result(
    action_id: str,
    target: str,
    status: str,
    summary: str,
    evidence: str = "",
    dry_run: bool = False,
    triggered: Optional[CheckResult] = None,
) -> ActionResult:
    return ActionResult(
        action_id=action_id,
        target=target,
        status=status,  # type: ignore[arg-type]
        summary=summary,
        evidence=evidence,
        dry_run=dry_run,
        triggered_check=triggered,
    )


# ─── individual actions ─────────────────────────────────────────────────


async def nginx_reload(target: dict, probe, dry_run: bool, actor: Optional[str]) -> ActionResult:
    container = target.get("containers", {}).get("nginx_federation")
    # §MCPTEST30 (V0562): this registry itself (an operator registry lists itself as "operator") is never acted on here
    if target.get("role") != "operator" or target.get("self"):
        return _result(
            "nginx-reload",
            target["operator_id"],
            "skipped",
            "only this frame's own operators' sidecars are reloaded here",
            dry_run=dry_run,
        )
    if not container:
        return _result(
            "nginx-reload",
            target["operator_id"],
            "skipped",
            "no nginx-federation container on this target (Frame A uses host nginx)",
            dry_run=dry_run,
        )

    # Always validate first
    rc, validate_out = await probe.exec_in(container, ["nginx", "-t"], timeout=4)
    if probe_failed(rc):
        # §F6 (2026-09-27): the PROBE failed (rc 124/127), not the config: on a registry with no docker socket there is
        # no exec at all, and the frame runner offers none. Saying "nginx -t rejected" here blamed a healthy sidecar.
        return _result(
            "nginx-reload",
            target["operator_id"],
            "fail",
            "the probe could not reach the sidecar (a registry with no docker socket has no exec; the frame runner "
            "offers none): nothing was validated or reloaded",
            evidence=validate_out[-512:],
            dry_run=dry_run,
        )
    if rc != 0:
        return _result(
            "nginx-reload",
            target["operator_id"],
            "fail",
            "nginx -t rejected the current config — refusing to reload",
            evidence=validate_out[-1024:],
            dry_run=dry_run,
        )
    if dry_run:
        return _result(
            "nginx-reload",
            target["operator_id"],
            "ok",
            "dry-run: nginx -t passed, skipping reload",
            evidence=validate_out[-512:],
            dry_run=True,
        )
    rc, reload_out = await probe.exec_in(container, ["nginx", "-s", "reload"], timeout=4)
    status = "ok" if rc == 0 else "fail"
    summary = "reloaded successfully" if rc == 0 else f"reload failed (rc={rc})"
    return _result(
        "nginx-reload",
        target["operator_id"],
        status,
        summary,
        evidence=(validate_out + "\n" + reload_out)[-1024:],
        dry_run=dry_run,
    )


async def teg_restart(target: dict, probe, dry_run: bool, actor: Optional[str]) -> ActionResult:
    """Restart this frame's own operator's TEG through the operator lifecycle's one rule, restart_cloud_service: the
    frame runner when OPERATOR_LIFECYCLE_VIA=runner, the registry's own compose restart otherwise (the operator page's
    restart). §F6 group 4 (2026-09-27): it used `docker restart` on the container and then joined it to Frame A's
    identity network whatever frame ran it; a compose restart keeps the operator's own networks and aliases, so nothing
    is re-joined. A frame's own TEG is restarted on its own host, never from a Command Center: such targets are skipped."""
    container = (target.get("containers") or {}).get("teg") or ""
    # §MCPTEST30 (V0562): this registry itself (an operator registry lists itself as "operator") is never acted on here
    if (target.get("role") != "operator" or target.get("self")
            or not (container.startswith("cloud-op-") and container.endswith("-teg"))):
        return _result(
            "teg-restart",
            target["operator_id"],
            "skipped",
            "only this frame's own operators' TEGs are restarted here; a frame's TEG is restarted on its own host",
            dry_run=dry_run,
        )
    slug = container[len("cloud-op-"):-len("-teg")]
    from agentvault_registry.services.cloud_provisioner import operator_lifecycle_via, restart_cloud_service
    via = operator_lifecycle_via()
    if dry_run:
        return _result(
            "teg-restart",
            target["operator_id"],
            "ok",
            f"dry-run: would restart {slug}'s teg-layer through the operator lifecycle (via {via})",
            dry_run=True,
        )
    try:
        res = await restart_cloud_service(SimpleNamespace(name=slug), "teg-layer")
    except Exception as e:  # noqa: BLE001 (the lifecycle's own sentence is the result)
        return _result(
            "teg-restart",
            target["operator_id"],
            "fail",
            f"restart of {slug}'s teg-layer failed (via {via}): {str(e)[:200]}",
            evidence=str(e)[-2048:],
            dry_run=dry_run,
        )
    return _result(
        "teg-restart",
        target["operator_id"],
        "ok",
        f"{slug}'s teg-layer restarted via {via} (~20s downtime); its networks and aliases are its compose's",
        evidence=str((res or {}).get("output_tail") or "")[-2048:],
        dry_run=dry_run,
    )


# ─── registry ────────────────────────────────────────────────────────────


ActionRunner = Callable[[dict, object, bool, Optional[str]], Awaitable[ActionResult]]


_ACTIONS: dict[str, dict] = {
    "nginx-reload": {
        "runner": nginx_reload,
        "description": "Validate + reload nginx-federation config",
        "destructive": False,
        "post_check": "nginx-config-valid",
    },
    "teg-restart": {
        "runner": teg_restart,
        "description": "Restart this operator's TEG container (~20s of downtime)",
        "destructive": True,
        "post_check": "identity-network-aliases",
    },
}


def known_action_ids() -> list[str]:
    return list(_ACTIONS.keys())


def get_action(action_id: str) -> Optional[dict]:
    return _ACTIONS.get(action_id)


async def run_action(
    action_id: str,
    target: dict,
    probe,
    dry_run: bool,
    actor: Optional[str],
) -> ActionResult:
    """Run a registered action, emit audit event, return ActionResult."""
    entry = _ACTIONS.get(action_id)
    if not entry:
        return _result(
            action_id,
            target["operator_id"],
            "fail",
            f"unknown action_id {action_id!r}",
            dry_run=dry_run,
        )
    started = time.monotonic()
    try:
        result = await entry["runner"](target, probe, dry_run, actor)
    except Exception as e:
        logger.warning(f"[diag-action] {action_id} raised: {e}")
        result = _result(
            action_id,
            target["operator_id"],
            "fail",
            f"action raised: {str(e)[:120]}",
            evidence=str(e)[:512],
            dry_run=dry_run,
        )
    emit_action(
        target=target["operator_id"],
        action_id=action_id,
        status=result.status,
        dry_run=dry_run,
        summary=result.summary,
        actor_email=actor,
    )
    logger.info(
        f"[diag-action] {action_id}@{target['operator_id']} "
        f"status={result.status} dry_run={dry_run} elapsed={(time.monotonic()-started)*1000:.0f}ms"
    )
    return result
