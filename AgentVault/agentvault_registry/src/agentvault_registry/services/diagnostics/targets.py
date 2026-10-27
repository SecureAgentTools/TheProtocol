"""Target enumeration for the Command Center.

Source of truth is `docker ps` — the Command Center can only diagnose what
is actually running. The OperatorApplication table is consulted for
display-name and cloud_url enrichment but never gates inclusion.

This means:
  * Stopped operators (containers removed) are NOT shown — no ghost tiles.
  * Operators whose containers are running but whose DB row says
    `cloud_hosted=False` (manual provisioning, etc.) ARE shown.

Environment filter (2026-04-21 sandbox rebuild):
  * `CC_TARGET_ENVIRONMENT` env var (default "all") scopes which targets a
    given registry's CC view sees. Set to "prod" on registry-a, "sandbox" on
    registry-test / registry-test-b. Default "all" = no filter (back-compat).
  * Mainframe entries carry an `environment` key; cloud operators are
    filtered by the `com.agentvault.environment` Docker label on their
    `cloud-op-*-registry` container.
  * If a container has no label, it counts as "prod" (pre-existing behaviour
    before any labels were added).
"""

import asyncio
import logging
import os
import re
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models

from .probe import get_probe
from .schemas import TargetSummary

logger = logging.getLogger(__name__)


# "all" (default) | "prod" | "sandbox". Read once at import time — registry
# restart is cheap and this avoids inconsistent views inside a single request.
TARGET_ENVIRONMENT = os.getenv("CC_TARGET_ENVIRONMENT", "all").lower().strip()


def _env_matches(candidate: Optional[str]) -> bool:
    """True if a target whose env label is `candidate` should be shown under
    the current TARGET_ENVIRONMENT filter. None/empty → treated as "prod"."""
    if TARGET_ENVIRONMENT == "all":
        return True
    return (candidate or "prod").lower() == TARGET_ENVIRONMENT


# §FEFRAME W4 residue (V0521, his "improvements also approved" 2026-10-01): the five hardcoded mainframes this list
# carried (registry-a, frame-b, frame-c and the old sandbox-a/sandbox-b tier) are retired or torn down. Only a node
# whose own name matched an entry ever enumerated one (scope_mainframes), and no current frame does, so the list was
# inert everywhere: EU, ASIA and the sandbox pair enumerate their operators. Left empty rather than deleted, so a
# frame that is ever deliberately added as a mainframe target goes through the same scoping.
MAINFRAME_TARGETS: list[dict] = []


_OPERATOR_NAME_RE = re.compile(r"^cloud-op-(?P<slug>.+)-registry$")
_ENV_LABEL = "com.agentvault.environment"



def _own_frame_label() -> str:
    """This registry's own name (REGISTRY_FEDERATION_NAME, else REGISTRY_NAME), lower case; "local" when unset."""
    return (os.getenv("REGISTRY_FEDERATION_NAME") or os.getenv("REGISTRY_NAME") or "local").strip().lower() or "local"


def _safe_name(raw: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9-]", "", (raw or "operator").lower())[:40]


def _operator_target(slug: str, display_name: Optional[str], cloud_url: Optional[str]) -> dict:
    """Build a target dict for a cloud operator from its container-name slug."""
    operator_id = slug if slug.startswith("op-") else f"op-{slug}"
    # Chained-test operators (provisioned INSIDE frame-test) live on the
    # frame-test network, not the main sandbox network. Tag them frame=T so
    # the CC groups them with their parent ephemeral frame.
    chained_test_op = slug.startswith("api-test-operator-")
    return {
        "operator_id": operator_id,
        "display_name": display_name or operator_id,
        # the frame the operator belongs to: THIS registry, by its own name (it was the letter "A" on every frame, the
        # retired Frame A's); chained-test operators keep "T", their ephemeral frame-test parent
        "frame": "T" if chained_test_op else _own_frame_label(),
        "role": "operator",
        "cloud_url": cloud_url,
        "svid_witness": "registry",
        "containers": {
            "registry": f"cloud-op-{slug}-registry",
            "teg": f"cloud-op-{slug}-teg",
            "db": f"cloud-op-{slug}-db",
            "teg_db": f"cloud-op-{slug}-teg-db",
            "redis": f"cloud-op-{slug}-redis",
            "pgbouncer": f"cloud-op-{slug}-pgbouncer",
            "nginx_federation": f"cloud-op-{slug}-nginx-federation",
            "spire_agent": f"cloud-op-{slug}-spire-agent",
            "cert_writer": f"cloud-op-{slug}-cert-writer",
        },
    }


async def _discover_operator_slugs() -> list[str]:
    """Return the slug for every cloud-op-*-registry container that's running,
    filtered by the `com.agentvault.environment` label if TARGET_ENVIRONMENT
    is set to something other than "all"."""
    probe = get_probe()

    def _sync():
        try:
            client = probe._client_sync()
            slugs = []
            for c in client.containers.list(ignore_removed=True):
                m = _OPERATOR_NAME_RE.match(c.name)
                if not m:
                    continue
                env_label = (c.labels or {}).get(_ENV_LABEL)
                # Chained-test operators (cloud-op-api-test-operator-*) have no
                # env label because they're provisioned by a frame-test nested
                # lifecycle that doesn't stamp labels. Treat them as sandbox so
                # they surface under CC_TARGET_ENVIRONMENT=sandbox alongside
                # their parent frame-test.
                if env_label is None and c.name.startswith("cloud-op-api-test-operator-"):
                    env_label = "sandbox"
                if not _env_matches(env_label):
                    continue
                slugs.append(m.group("slug"))
            return sorted(set(slugs))
        except Exception as e:
            logger.warning(f"[diag-targets] docker discovery failed: {e}")
            return []

    return await asyncio.to_thread(_sync)


async def _enrichment_map(db: AsyncSession) -> dict[str, dict]:
    """Map operator slug → {display_name, cloud_url} from OperatorApplication."""
    out: dict[str, dict] = {}
    try:
        result = await db.execute(select(models.OperatorApplication))
        for app in result.scalars().all():
            slug = _safe_name(app.name)
            normalised = slug if slug.startswith("op-") else f"op-{slug}"
            out[normalised] = {"display_name": app.name, "cloud_url": app.cloud_url}
            # Also index by raw safe-name for legacy cases where the OperatorApplication
            # row has an "Original Format Name" instead of the safe slug used in compose.
            if slug != normalised:
                out[slug] = {"display_name": app.name, "cloud_url": app.cloud_url}
    except Exception as e:
        logger.warning(f"[diag-targets] OperatorApplication enrichment failed: {e}")
    return out


def fleet_scope_enabled() -> bool:
    """True only where cross-node enumeration is deliberately switched on.

    §EXCISION — `MAINFRAME_TARGETS` names every mainframe with its container
    names and public EventStore URLs, and operator discovery walks `docker ps`.
    Today no cloud-op or sovereign frame can reach a docker socket, so this
    already returns nothing there — but that is a SIDE EFFECT of §HETZNERLOCK
    removing the socket, not a decision, and a re-provision restores mounts
    (PART 11b rule 2). This makes the property hold by construction instead.

    Dark by default, mirroring `COMMAND_RELAY_SCOPE`. Deliberately NOT gated on
    `IS_CENTRAL_REGISTRY`: the Hetzner frame sets that true, so it would not
    have darkened the one node this exists to protect.
    """
    return (os.getenv("DIAGNOSTICS_FLEET_SCOPE") or "local").strip().lower() in ("fleet", "fleet-all")


def scope_operator_slugs(slugs: list[str], enrichment: dict, own_operator_names: set[str]) -> list[str]:
    """§RESIDUES C2 (2026-09-13): the operators THIS frame knows, out of every `cloud-op-*` container on the host.

    Under fleet scope the discovery walks `docker ps`, and a host that runs several frames hands every frame's
    operators to every frame's Command Center: sbx-alpha listed EU's amsterdam/lisbon and ASIA's shenzhen/
    hochiminh as its own targets (measured 2026-09-12). A frame KNOWS an operator by an OperatorApplication
    row (the admission flow) or by its own `cloud_operator` peer row; chained-test operators are the frame's
    own ephemeral children and stay. Everything else is another frame's, however near on the host.
    """
    keep: list[str] = []
    for slug in slugs:
        operator_id = slug if slug.startswith("op-") else f"op-{slug}"
        known = operator_id in enrichment or slug in enrichment or slug in own_operator_names \
            or operator_id in own_operator_names or slug.startswith("api-test-operator-")
        if known:
            keep.append(slug)
    return sorted(set(keep))


def scope_mainframes(entries: list[dict], self_names: set[str], fleet_all: bool = False) -> list[dict]:
    """The hardcoded mainframe entries (Frame A/B/C + the old sandbox tier) belong to the frame that IS one of
    them; a sovereign frame on the same host is not their Command Center. `DIAGNOSTICS_FLEET_SCOPE=fleet-all`
    keeps the legacy behaviour (registry-a's centre listing B and C) where a frame deliberately asks for it."""
    if fleet_all:
        return list(entries)
    names = {str(n).strip().lower() for n in self_names if n}
    return [e for e in entries if str(e.get("operator_id", "")).lower() in names
            or str(e.get("display_name", "")).lower() in names]


def _self_names() -> set[str]:
    return {(os.getenv(k) or "").strip().lower() for k in ("REGISTRY_NAME", "REGISTRY_FEDERATION_NAME", "REGISTRY_DISPLAY_NAME", "HOSTNAME")}


async def _own_operator_names(db: AsyncSession) -> set[str]:
    """This frame's own operators: `peer_registries` rows typed cloud_operator (a peer frame's operators arrive typed
    `discovered` and are not ours)."""
    try:
        rows = await db.execute(select(models.PeerRegistry.name).where(models.PeerRegistry.peer_type == "cloud_operator"))
        return {str(n).strip().lower() for (n,) in rows.all() if n}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[diag-targets] own-operator read failed: {e}")
        return set()


async def list_targets(db: AsyncSession) -> list[dict]:
    """This registry itself (V0562), then mainframes + ephemeral frame-test(s) + every running cloud operator under
    fleet scope."""
    probe = get_probe()
    targets: list[dict] = [self_target()]

    # §MCPTEST30 (V0562): this frame's own operators, from its own peer rows, whatever the fleet scope: their checks read
    # the row's federation record and the signed card the fan-out already fetched (nothing of another node's that this
    # registry does not already hold). The scope still governs reaching into containers.
    own_rows = await _own_operator_rows(db)
    if not fleet_scope_enabled():
        logger.info(
            "[diag-targets] DIAGNOSTICS_FLEET_SCOPE != fleet — no container enumeration; "
            f"this registry and its {len(own_rows)} operator row(s)"
        )
        return targets + [peer_operator_target(p) for p in sorted(own_rows, key=lambda p_: p_.name or "")]

    # Mainframes — only include if their registry container actually exists
    # AND their declared environment matches the TARGET_ENVIRONMENT filter.
    fleet_all = (os.getenv("DIAGNOSTICS_FLEET_SCOPE") or "").strip().lower() == "fleet-all"
    for mf in scope_mainframes(MAINFRAME_TARGETS, _self_names(), fleet_all):
        if not _env_matches(mf.get("environment")):
            continue
        if await probe.container_exists(mf["containers"]["registry"]):
            targets.append(mf)
        else:
            logger.info(
                f"[diag-targets] mainframe {mf['operator_id']} registry container "
                f"({mf['containers']['registry']}) not running — skipping"
            )

    # Operators — derive from running containers, enrich from DB.
    slugs = await _discover_operator_slugs()
    enrichment = await _enrichment_map(db)
    slugs = scope_operator_slugs(slugs, enrichment, await _own_operator_names(db))
    rows_by_id = {peer_operator_target(p)["operator_id"]: p for p in own_rows}
    for slug in slugs:
        operator_id = slug if slug.startswith("op-") else f"op-{slug}"
        meta = enrichment.get(operator_id) or enrichment.get(slug) or {}
        t = _operator_target(
            slug=slug,
            display_name=meta.get("display_name"),
            cloud_url=meta.get("cloud_url"),
        )
        row = rows_by_id.pop(t["operator_id"], None)
        if row is not None:
            t["peer_registry_id"] = row.id   # V0562: the Docker target keeps its containers and gains the row's checks
        targets.append(t)
    # V0562: an operator this frame's rows name and Docker does not show (its containers on another host, or stopped)
    targets.extend(peer_operator_target(p) for p in sorted(rows_by_id.values(), key=lambda p_: p_.name or ""))

    return targets


SELF_ROLE = "frame"   # this registry itself when it is a frame; an operator registry lists itself as "operator"


def self_target() -> dict:
    """§MCPTEST30 (V0562): this registry itself, a target every frame has, with or without a Docker socket. Its checks
    read only what the registry reaches on its own: its event store's supply audit, its Redis leader keys, its own SVID,
    its own trust bundle, its TEG's health. Listed whatever DIAGNOSTICS_FLEET_SCOPE says: that flag governs enumerating
    OTHER nodes (§EXCISION), and nothing here is another node."""
    from agentvault_registry.core import federation_view as fv
    me = fv.self_entry()
    name = me.get("name") or _own_frame_label()
    return {
        "operator_id": fv.key_of(name) or "self",
        "display_name": me.get("display_name") or name,
        "frame": _own_frame_label(),
        # an operator registry (MINTING_AUTHORITY=disabled) is no frame: it has no store of its own (it writes to its
        # parent frame's), so its own Command Center must not show the parent's supply audit as its own
        "role": "operator" if me.get("role") == fv.ROLE_OPERATOR else SELF_ROLE,
        "cloud_url": me.get("public_url"),
        "containers": {},
        "self": True,
    }


async def _own_operator_rows(db: AsyncSession) -> list:
    """This frame's own operators as its peer rows say (ACTIVE, typed cloud_operator; a peer frame's operators arrive
    typed `discovered` and are not ours). [] when the rows cannot be read, said in the log."""
    try:
        rows = await db.execute(select(models.PeerRegistry).where(
            models.PeerRegistry.status == "ACTIVE", models.PeerRegistry.peer_type == "cloud_operator"))
        return list(rows.scalars().all())
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[diag-targets] this frame's operator rows unreadable: {e}")
        return []


def peer_operator_target(peer) -> dict:
    """§MCPTEST30 (V0562): one of this frame's operators, from its peer row, measured without Docker: the row's own
    federation record and the operator's signed card as the fan-out last fetched it. It names no container (on a frame
    without a Docker socket there are none to name); a Docker-discovered operator of the same name keeps its containers
    and gains the row's id."""
    card = peer.cached_registry_card if isinstance(peer.cached_registry_card, dict) else {}
    ident = card.get("identity") if isinstance(card.get("identity"), dict) else {}
    slug = _safe_name(peer.name)
    return {
        "operator_id": slug if slug.startswith("op-") else f"op-{slug}",
        "display_name": ident.get("display_name") or peer.name,
        "frame": _own_frame_label(),
        "role": "operator",
        "cloud_url": ident.get("public_url") or None,
        "containers": {},
        "peer_registry_id": peer.id,
    }


def why_no_targets() -> tuple[str, str]:
    """§MCPTEST30 (V0561, V0562): (code, sentence) for a list that holds no operator; the console translates the code.
    V0561 named the fleet scope and the socket here; since V0562 a frame's operators come from its own peer rows whatever
    either says, so the one cause left is that it has none. Why container checks cannot run is why_no_containers()."""
    return ("no_operators", "no operator belongs to this frame: it holds no cloud operator peer row")


def why_no_containers() -> Optional[tuple[str, str]]:
    """(code, sentence) when this registry cannot read its operators' containers, or None when it can. The operators are
    listed and measured from their rows either way; this says why the container checks (identity network, nginx,
    pgbouncer, SPIRE rotation, DNS errors) do not run here."""
    if not fleet_scope_enabled():
        return ("scope_off", "this registry does not reach into its operators' containers (DIAGNOSTICS_FLEET_SCOPE is "
                             "not fleet): their container checks do not run here")
    if not (os.getenv("DOCKER_HOST") or os.path.exists("/var/run/docker.sock")):
        return ("no_socket", "this registry holds no Docker socket (F6): its operators' container checks cannot run here")
    return None


async def get_target(db: AsyncSession, operator_id: str) -> Optional[dict]:
    for t in await list_targets(db):
        if t["operator_id"] == operator_id:
            return t
    return None


def empty_summary(target: dict) -> TargetSummary:
    return TargetSummary(
        operator_id=target["operator_id"],
        display_name=target["display_name"],
        frame=target["frame"],
        role=target["role"],
        cloud_url=target.get("cloud_url"),
        is_self=bool(target.get("self")),
    )
