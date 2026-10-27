"""Diagnostic check registry.

Each check exposes:
  CHECK_ID, TITLE, DESCRIPTION, CATEGORY, COST_MS, applies(target) -> bool, run(target, probe) -> CheckResult

Phase 1A ships the 6 cheapest. Phase 1C adds the remaining 6.
"""

from typing import Awaitable, Callable

from ..probe import LocalDockerProbe
from ..schemas import CheckDescriptor, CheckResult

from . import (
    supply_audit,
    spire_federation,
    teg_cross_frame,
    identity_network,
    leader_election,
    kafka_lag,
    eventstore_batch,
    operator_dns,
    spire_rotation,
    nginx_valid,
    pgbouncer_pin,
    svid_expiry,
    frame_trust_bundle,
    frame_teg_health,
    operator_federation_reach,
    operator_card,
)


CheckRunner = Callable[[dict, LocalDockerProbe], Awaitable[CheckResult]]


_REGISTRY: dict[str, dict] = {}


def _register(module) -> None:
    _REGISTRY[module.CHECK_ID] = {
        "descriptor": CheckDescriptor(
            check_id=module.CHECK_ID,
            title=module.TITLE,
            description=module.DESCRIPTION,
            cost_ms=module.COST_MS,
            category=module.CATEGORY,
        ),
        "applies": module.applies,
        "run": module.run,
    }


for _m in (
    supply_audit,
    spire_federation,
    teg_cross_frame,
    identity_network,
    leader_election,
    kafka_lag,
    eventstore_batch,
    operator_dns,
    spire_rotation,
    nginx_valid,
    pgbouncer_pin,
    svid_expiry,
    frame_trust_bundle,     # §MCPTEST30 V0562: this registry itself, measured without Docker
    frame_teg_health,
    operator_federation_reach,   # V0562: this frame's operators, from its own peer rows
    operator_card,
):
    _register(_m)


def all_descriptors() -> list[CheckDescriptor]:
    return [entry["descriptor"] for entry in _REGISTRY.values()]


def get_runner(check_id: str) -> CheckRunner | None:
    entry = _REGISTRY.get(check_id)
    return entry["run"] if entry else None


def applies_to(check_id: str, target: dict) -> bool:
    entry = _REGISTRY.get(check_id)
    return entry["applies"](target) if entry else False


def known_check_ids() -> list[str]:
    return list(_REGISTRY.keys())
