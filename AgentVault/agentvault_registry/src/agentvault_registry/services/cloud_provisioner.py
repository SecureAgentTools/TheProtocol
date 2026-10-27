"""
f051: Cloud-Hosted Operator Provisioner

Provisions a fully functional federated operator registry on the production server.
Adapts the proven sandbox provisioning pattern (scripts/provision_sandbox_operator.py)
into an async service callable from within the registry container.

The registry container needs:
  - Docker socket mount (/var/run/docker.sock)
  - Host stack mount (/opt/theprotocol/stack → /host-stack)
  - Host nginx mount (/etc/nginx/sites-enabled → /host-nginx-sites)
"""
import asyncio
import hashlib
import logging
import os
import re
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from collections import OrderedDict
from typing import List, Optional, Tuple
from ..core.network_profile import money_knob  # §MONEY-M2: the profile owns this amount

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry.core import operator_mail
from agentvault_registry.core.host_reach import host_reach_available
from agentvault_registry.core.operator_compose import (adapt_federation_conf, adapt_operator_compose,
                                                        docker_auth_config, operator_push_host, operator_push_port,
                                                        operator_push_vhost, operator_vhost,
                                                        sni_map_entry, svid_dns_sans)
from agentvault_registry.services import operator_provisioner
from agentvault_registry.event_emitter import get_event_emitter

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────
CLOUD_DOMAIN_SUFFIX = os.getenv("CLOUD_DOMAIN_SUFFIX", "op.theprotocol.cloud")
TRUST_DOMAIN = os.getenv("SPIRE_TRUST_DOMAIN", "agentvault.com")
SSL_CERT_NAME = os.getenv("SSL_CERT_NAME", CLOUD_DOMAIN_SUFFIX)  # Cert dir under /etc/letsencrypt/live/
# §HELLOFRAME lane 6 (2026-09-18): where an operator's images come from. The network's own host pulls them from the
# image registry with a per-operator token; a foreign host stood up from the export loads them as LOCAL tags
# (`agentvault2/<name>:<version>`, the export's own step) and needs no token. ONE prefix, written into the operator's
# env as IMAGES_PREFIX for the compose's `${IMAGES_PREFIX:-images.theprotocol.cloud}/...` image lines.
IMAGES_PREFIX = (os.getenv("OPERATOR_IMAGES_PREFIX") or os.getenv("IMAGE_REGISTRY")
                 or "images.theprotocol.cloud").strip().rstrip("/")
IDENTITY_NETWORK = os.getenv("IDENTITY_NETWORK", "agentvault_identity_network")
# Dual-frame topology: operators are reachable from BOTH frames via the same
# nginx-federation container, but each frame uses its own bridge + per-frame
# DNS alias (e.g. op-X.op.theprotocol.cloud on Frame A, op-X.frame-b.theprotocol.cloud
# on Frame B). The provisioner attaches nginx-federation to the partner identity
# network too, with the partner-suffix alias, when these are set. Empty = single-frame.
PARTNER_IDENTITY_NETWORK = os.getenv("PARTNER_IDENTITY_NETWORK", "")
PARTNER_DOMAIN_SUFFIX = os.getenv("PARTNER_DOMAIN_SUFFIX", "")
CLOUD_PORT_MIN = int(os.getenv("CLOUD_PORT_MIN", "26000"))
CLOUD_PORT_MAX = int(os.getenv("CLOUD_PORT_MAX", "28900"))
CLOUD_PORT_STEP = 100
HOST_STACK_MOUNT = "/host-stack"       # Maps to /opt/theprotocol/stack on host
# §HELLOFRAME: the HOST stack root the operators live under. The network's own host has one; a frame stood up by
# frame-up under --stack-root names its own (the driver writes FRAME_STACK_ROOT into the registry env under own-host)
# and the runner instance provisioning for it is rooted there too, so the registry must record the same directory.
STACK_ROOT_HOST = os.getenv("FRAME_STACK_ROOT", "/opt/theprotocol/stack").rstrip("/") or "/opt/theprotocol/stack"


def operator_image_version(card_version: str) -> str:
    """The tag an operator's compose pulls (`<prefix>/registry:${VERSION}`). On the network's host the docker tag IS
    the card's version string, so the card chain (IMAGE_TAG env -> constant) names a pullable image. Under a LOCAL
    images prefix (§HELLOFRAME: the export's `theprotocol/*:1.0.0-beta.4`) the images are tagged by release while
    the card keeps the constant, so the tag is the frame's own VERSION, the docker tag the standup wrote for its own
    registry; measured 2026-09-18: the first operator compose from a frame-up frame tried to pull
    `theprotocol/cert-writer:MoreCompliant...V0397`, a name that exists nowhere. The network's host is byte-identical."""
    from agentvault_registry.core.operator_compose import images_prefix_is_local
    prefix = (os.getenv("OPERATOR_IMAGES_PREFIX") or os.getenv("IMAGE_REGISTRY") or "").strip()
    own = (os.getenv("VERSION") or "").strip()
    if prefix and images_prefix_is_local(prefix) and own:
        return own
    return card_version


OPERATOR_IMAGE_NAMES = ("registry", "teg-layer", "cert-writer")   # the three the operator compose names by ${VERSION}


def operator_images_preflight(docker_username: str = "", docker_pull_token: str = "") -> List[str]:
    """What the operator's compose will fail to get, in words; [] when every image is here or pullable.

    §OPPROV (2026-09-27), measured on sbx-beta (wp62opb): the frame ran V0462, whose operator images had never been
    pushed, so `compose up` failed on its first pull AFTER the port block, the SPIRE entries, the licence, the stack dir
    and the edge had all been written, and the log blamed host load. An image counts as available when it is on this
    host (compose then pulls nothing) or when the registry serves its manifest to the very credential the stack will
    pull with (the pull token the caller minted and already committed). Anything else is named, before anything is spent.
    """
    import docker as _dk
    from agentvault_registry.core.operator_compose import images_prefix_is_local
    from agentvault_registry.core.registry_identity import get_software_version
    version = operator_image_version(get_software_version())
    client = _dk.from_env()
    local_only = images_prefix_is_local(IMAGES_PREFIX)
    missing: List[str] = []
    for name in OPERATOR_IMAGE_NAMES:
        ref = f"{IMAGES_PREFIX}/{name}:{version}"
        try:
            client.images.get(ref)
            continue
        except _dk.errors.ImageNotFound:
            pass
        except Exception as e:  # noqa: BLE001 — a daemon we cannot ask is a reason, named like any other
            missing.append(f"{ref} (this host's Docker could not be asked: {type(e).__name__})")
            continue
        if local_only or not docker_pull_token:
            missing.append(f"{ref} (not on this host{', and a local prefix has no registry to pull from' if local_only else ', and no pull credential to try the registry with'})")
            continue
        try:
            client.images.get_registry_data(ref, auth_config={"username": docker_username, "password": docker_pull_token})
        except Exception as e:  # noqa: BLE001
            why = re.sub(r"dpt_[0-9a-f]+", "dpt_<redacted>", str(e))[:160]
            missing.append(f"{ref} (not on this host, and the registry refused it to this operator's pull credential: {why})")
    return missing
HOST_NGINX_MOUNT = "/host-nginx-sites"  # Maps to /etc/nginx/sites-enabled on host
REGISTRY_A_CONTAINER = os.getenv("REGISTRY_A_CONTAINER", "agentvault_registry_a")
REGISTRY_A_PUBLIC_URL = os.getenv("BILATERAL_PEER_URL", "https://api.theprotocol.cloud")
# 2026-04-28 fix: default was ":18443" — a port that doesn't exist on the host.
# nginx-a routes /api/v1/federation/ on port 443 with `ssl_verify_client optional_no_ca`
# and forwards X-SSL-Client-Cert to the registry. SPIFFE ID is validated there.
# Override via BILATERAL_PEER_URL env only if your deployment uses a different ingress.
BILATERAL_PEER_NAME = os.getenv("BILATERAL_PEER_NAME", "Registry-A")
PROD_REGISTRY_DB = os.getenv("PROD_REGISTRY_DB", "agentvault_registry_db_a")
BUNDLE_DIR = "/app/operator-bundles"


@dataclass
class CloudProvisionResult:
    cloud_url: str
    cloud_port_base: int
    cloud_stack_dir: str
    registry_port: int
    federation_port: int
    containers_started: int
    federation_license_key: str
    admin_email: str
    admin_password: str  # shown once, not stored


@dataclass
class CloudTeardownResult:
    containers_stopped: bool
    nginx_removed: bool
    peer_deactivated: bool
    stack_archived: bool
    # Option D-light Phase D3 (2026-04-21): snapshot of the PeerRegistry row
    # at deactivation time so the caller can emit PeerRegistryDeactivated
    # AFTER db.commit() (durability guarantee). Keys: peer_id, peer_name,
    # peer_url, prior_status. None if no matching row was found.
    peer_snapshot: Optional[dict] = None
    # §2026-06-14: True when teardown ran in leave-no-traces purge mode
    # (genesis drained, SPIRE revoked, rows DELETEd cross-frame, dir removed).
    purged: bool = False
    # §F6 stage 5 (2026-09-27): the licence step 4 revoked, as {id, operator_name, license_key_hash}, so the caller can
    # carry "revoked" to the store's federation_operators row AFTER its commit (sync_teardown_licence_to_store).
    revoked_licence: Optional[dict] = None


def _run(cmd: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run a shell command, log errors."""
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        logger.warning(f"[CLOUD-PROV] Command failed: {cmd}\n  stderr: {r.stderr[:300]}")
    return r


def _safe_name(name: str) -> str:
    """Sanitize operator name for use in paths and Docker names."""
    return re.sub(r'[^a-z0-9-]', '', name.lower())[:40]


def _cloud_operator_did(application: "models.OperatorApplication", safe: str) -> str:
    """Build the federation DID for a cloud-hosted operator.

    Must match the runtime derivation in federation_license_gate at lookup time:
    `docker_registry_username.removeprefix("operator-")`, which produces a
    HYPHENATED form (spaces → '-'). _safe_name STRIPS spaces, so it produces
    a different key for multi-word names. Use the hyphenated form authored by
    activate_operator so create-path and gate-lookup agree.
    """
    if application and getattr(application, "docker_registry_username", None):
        return f"did:theprotocol:cloud:{application.docker_registry_username.removeprefix('operator-')}"
    return f"did:theprotocol:cloud:{safe}"


# ── Port Allocation ──────────────────────────────────────────────────────

DOCKER_SOCKET = "/var/run/docker.sock"


class _NoHostReach(Exception):
    """This registry holds no docker socket (the frame runner does its host work): a probe that needs one is not run."""


# The host ports one operator's block holds: the registry (base), the federation lane (+43), the TEG (+80) and, since
# §PUSH (2026-10-06), its push relay (+99, core/operator_compose.PUSH_PORT_OFFSET). A block is free only when all are.
_BLOCK_OFFSETS = (0, 43, 80, 99)


async def allocate_port_block(db: AsyncSession) -> int:
    """Allocate the next available 100-port block for a cloud operator.

    §pass65 (2026-05-22) — scan upward from MAX(DB-known port_base)+100 until
    finding a port that is ALSO not bound on the host. The previous logic only
    consulted Frame A's DB, but on multi-frame hosts (Frame A + Frame B share
    one Docker daemon), Frame B's cloud-ops bind ports that Frame A's DB
    doesn't track. Without this check, provision returns a port that's
    already-bound, then `docker compose up` fails with "port already
    allocated" mid-startup leaving a half-provisioned operator.

    The scan stops at CLOUD_PORT_MAX and raises if no free block is found.
    Host-side check uses `psutil.net_connections` (also non-blocking).

    §OPPROV (2026-09-27): the scan starts at CLOUD_PORT_MIN, not above the highest live block. Measured on sbx-alpha: its
    range 31100-31499 held its own operator at 31100 and, above it, three blocks published by OTHER frames' operators on
    this host (sbxbetaop 31200, amsterdam 31300, lisbon 31400); the scan began at 31200 and refused the provision, and a
    block freed below the highest live one was never handed out again. The highest-live rule stood in for "never hand out
    a block this frame's own operators hold"; that is now asked directly: this frame's live blocks (cloud-hosted, not torn
    down) are USED from its database, whether their containers run or not, and every container's CONFIGURED bindings count
    too, a stopped one's included, where the running-only probe saw nothing. The refusal names why each block was taken.
    """
    result = await db.execute(
        select(models.OperatorApplication.cloud_port_base).where(
            models.OperatorApplication.cloud_hosted == True,
            models.OperatorApplication.cloud_torn_down_at.is_(None),
            models.OperatorApplication.cloud_port_base.isnot(None),
        )
    )
    live_bases = sorted({int(b) for (b,) in result.all() if b})
    candidate = CLOUD_PORT_MIN
    why: dict = {}   # block -> the reason it was not handed out (the refusal names them)

    # Probe host for actual port availability — try block-base + 0/43/80 ports
    # (registry / federation / nginx), since the compose template binds those.
    # The registry container runs in its own netns so psutil.net_connections
    # would only see container-local ports. Use the Docker SDK to enumerate
    # every running container's host port bindings — that's the authoritative
    # view of which host ports the daemon has allocated.
    used: set = set()
    holder: dict = {}   # host port -> the container publishing or configured to publish it
    for _b in live_bases:
        used.update({_b + off for off in _BLOCK_OFFSETS})
    # §F6 (2026-09-27, his words "i approve to finish f6 implementation on sandbox"): a registry with NO docker socket is
    # F6's posture, not a fault. The frame runner does its host work, and the runner's one-shot binds the block for real
    # and refuses loudly if it is held. Here the host-wide census and the bind probe cannot run; this frame's own live
    # blocks, the cool-down below and the frame's own CLOUD_PORT range decide, which the log says ONCE per allocation
    # instead of a warning per failed probe. A socket that exists and fails is still a warning (host reach this registry
    # is meant to have, broken).
    _host_reach = os.path.exists(DOCKER_SOCKET)
    if not _host_reach:
        logger.info(f"[CLOUD-PROV] no docker socket on this registry (the frame runner holds its host reach): the host-wide "
                    f"port census and the bind probe are not run here; this frame's live blocks, the teardown cool-down "
                    f"and its range {CLOUD_PORT_MIN}-{CLOUD_PORT_MAX} decide, and the runner's one-shot binds for real")
    try:
        if not _host_reach:
            raise _NoHostReach()
        import docker as _docker_port_probe
        _dp_client = _docker_port_probe.from_env()
        # §OPPROV: all=True, and the CONFIGURED bindings (HostConfig.PortBindings) beside the published ones: a stopped
        # container publishes nothing, and starting it again would collide with a block handed out meanwhile
        for _c in _dp_client.containers.list(all=True, ignore_removed=True):
            _attrs = _c.attrs or {}
            _maps = [((_attrs.get("NetworkSettings") or {}).get("Ports") or {}),
                     ((_attrs.get("HostConfig") or {}).get("PortBindings") or {})]
            for _ports in _maps:
                for _mapping in _ports.values():
                    if not _mapping:
                        continue
                    for _bind in _mapping:
                        _host_port = (_bind or {}).get("HostPort")
                        if _host_port:
                            try:
                                used.add(int(_host_port))
                                holder.setdefault(int(_host_port), getattr(_c, "name", "?"))
                            except (TypeError, ValueError):
                                pass
    except _NoHostReach:
        pass
    except Exception as _e:
        logger.warning(f"[CLOUD-PROV] Host port probe via docker SDK failed: {_e!r}")

    # §FRAMELIC (2026-09-07, findings rows 133 + 49) — A FREE-LOOKING PORT IS NOT A BINDABLE PORT.
    # The probe above asks "is a running container binding this?", which is not the question the
    # bind will ask. When an operator is torn down, dockerd keeps its own reservation on the host
    # port for a while: measured on this box, `ss -ltnp` showed no LISTEN, `/proc/net/tcp` showed no
    # LISTEN, none of 171 `docker-proxy` processes carried the port, and an exhaustive
    # `docker inspect` of every container found no claimant — and `docker compose up` still answered
    # `failed to bind host port 0.0.0.0:31300/tcp: address already in use`, three times, for a
    # quarter of an hour. Only a daemon restart clears it, and that is not available on a box
    # running ~295 containers.
    #
    # We cannot query dockerd's allocator, so we do the next honest thing: treat a RECENTLY torn
    # down block as still occupied. This costs a port block per teardown for the cool-down window
    # and buys a provision that does not half-succeed — a container that runs, reports `healthy`
    # from its in-container healthcheck, and is unreachable because it has no published port.
    try:
        _cooldown_min = int(os.getenv("CLOUD_PORT_TEARDOWN_COOLDOWN_MINUTES", "120"))
        if _cooldown_min > 0:
            _since = datetime.now(timezone.utc) - timedelta(minutes=_cooldown_min)
            _recent = await db.execute(
                select(models.OperatorApplication.cloud_port_base).where(
                    models.OperatorApplication.cloud_port_base.isnot(None),
                    models.OperatorApplication.cloud_torn_down_at.isnot(None),
                    models.OperatorApplication.cloud_torn_down_at >= _since,
                )
            )
            _recent_bases = [int(b) for (b,) in _recent.all() if b]
            for _b in _recent_bases:
                used.update({_b + off for off in _BLOCK_OFFSETS})
            if _recent_bases:
                logger.info(
                    f"[CLOUD-PROV] port blocks torn down in the last {_cooldown_min}m are still "
                    f"reserved by dockerd and treated as USED: {sorted(set(_recent_bases))}"
                )
    except Exception as _cd_err:  # noqa: BLE001 — a cool-down we cannot compute must not block a provision
        logger.warning(f"[CLOUD-PROV] teardown cool-down probe failed: {_cd_err!r}")

    # §FRAMELIC (2026-09-07, findings row 133) — THE ONLY HONEST TEST OF "can I bind it" IS TO BIND IT.
    # Everything above asks a DIFFERENT question ("is a container binding this?", "was this torn
    # down recently?"), and dockerd's own allocator answers neither. Measured: `ss -ltnp`,
    # `/proc/net/tcp`, 171 `docker-proxy` cmdlines and an exhaustive `docker inspect` ALL said 31300
    # was free while `docker compose up` refused it as `address already in use` for a quarter of an
    # hour. A cool-down on our own DB cannot help either, because a rebuilt frame has a fresh
    # database and no memory of the block its predecessor wedged.
    #
    # So: ask the daemon that will do the real bind, by making it do a throwaway one. A few seconds
    # per candidate at provision time, against a half-provisioned operator that runs, reports
    # `healthy` from inside its own netns, and is unreachable because it has no published port.
    # ⚠ AND THE PROBE CLEANS UP AFTER A REFUSAL TOO. It used `containers.run`, which CREATES and then STARTS: a start
    # the daemon refuses raises out of `run` with the created container still there, so every refused block left one
    # `Created` alpine container behind, unnamed and unlabelled (four on this host by 2026-09-27, one per refusal).
    # Created and started separately now, removed in `finally` whatever the start did, and labelled so a probe
    # that outlives its process anyway says what it was.
    def _daemon_can_bind(port_base: int) -> bool:
        if not _host_reach:
            return True   # said once above: the runner's one-shot binds for real
        try:
            import docker as _dk
            _c = _dk.from_env()
            _probe_kw = dict(labels={"theprotocol.purpose": "operator-port-bind-probe",
                                     "theprotocol.port-base": str(port_base)},
                             ports={f"{p}/tcp": port_base + off
                                    for off, p in ((0, 8000), (43, 8443), (80, 8080))})
            try:
                _probe = _c.containers.create("alpine", "true", **_probe_kw)
            except _dk.errors.ImageNotFound:
                _c.images.pull("alpine", tag="latest")   # what `containers.run` did on its own
                _probe = _c.containers.create("alpine", "true", **_probe_kw)
            try:
                _probe.start()
            finally:
                try:
                    _probe.remove(force=True)
                except Exception as _rm_err:  # noqa: BLE001 — named, so a leftover is findable by its label
                    logger.warning(f"[CLOUD-PROV] the port bind probe for {port_base} could not be removed "
                                   f"({_rm_err!r}); it carries label theprotocol.purpose=operator-port-bind-probe")
            return True
        except Exception as _bind_err:  # noqa: BLE001
            if "address already in use" in str(_bind_err).lower() or "port is already allocated" in str(_bind_err).lower():
                return False
            # Any OTHER failure (no alpine image, docker unreachable) must not veto a port:
            # refusing every block because the probe itself is broken would be worse than the bug.
            logger.warning(f"[CLOUD-PROV] port bind probe inconclusive for {port_base}: {_bind_err!r}")
            return True

    while candidate <= CLOUD_PORT_MAX:
        if not any((candidate + offset) in used for offset in _BLOCK_OFFSETS):
            if _daemon_can_bind(candidate):
                return candidate
            logger.warning(
                f"[CLOUD-PROV] Port {candidate} looks free but the DAEMON refuses to bind it "
                f"(a reservation left by a torn-down stack) — skipping"
            )
            why[candidate] = "the daemon refuses to bind it"
            candidate += CLOUD_PORT_STEP
            continue
        _taken = next((candidate + off for off in _BLOCK_OFFSETS if (candidate + off) in used), candidate)
        why[candidate] = ("this frame's operator" if candidate in live_bases else
                          f"bound by {holder[_taken]}" if _taken in holder else "torn down within the cool-down")
        logger.info(
            f"[CLOUD-PROV] Port {candidate} (or +43/+80/+99) in use ({why[candidate]}) — skipping"
        )
        candidate += CLOUD_PORT_STEP

    raise RuntimeError(
        f"Cloud operator port range exhausted: CLOUD_PORT_MIN..CLOUD_PORT_MAX = {CLOUD_PORT_MIN}..{CLOUD_PORT_MAX} "
        f"({(CLOUD_PORT_MAX - CLOUD_PORT_MIN) // CLOUD_PORT_STEP + 1} blocks) holds no free block: "
        + "; ".join(f"{b} {w}" for b, w in sorted(why.items()))
        + ". Widen or move this frame's range (ranges of frames on one host must not overlap)."
    )


async def count_active_cloud_operators(db: AsyncSession) -> int:
    """Count cloud operators that are active (not torn down)."""
    result = await db.execute(
        select(func.count(models.OperatorApplication.id)).where(
            models.OperatorApplication.cloud_hosted == True,
            models.OperatorApplication.cloud_torn_down_at.is_(None),
        )
    )
    return result.scalar() or 0


# ── Provisioning ─────────────────────────────────────────────────────────

def _frame_public_es_url() -> str:
    """Frame-aware PUBLIC EventStore URL for a generated cloud-op. Its balance
    outbox + reactors emit to the PARENT frame's ES (cloud-ops have no own ES),
    keyed by the PARENT registry's SPIRE trust domain. For a KNOWN prod frame the
    map is AUTHORITATIVE — it deliberately IGNORES any (possibly clone-bug)
    EVENT_STORE_PUBLIC_URL env so a frame-c-registry can NEVER stamp Frame-B's
    `events-b` into a frame-c op (the §pass78c clone-bug that silently sent every
    telaviv financial event to Frame B's ES → 403 → un-ledgered balances). Unknown
    / custom domains (sandbox, new frames) fall back to the explicit override or
    Frame A. New sovereign frames: add `<frame>.theprotocol.cloud → events-<x>`."""
    _td = (os.getenv("SPIRE_TRUST_DOMAIN", "agentvault.com") or "agentvault.com").strip()
    _PROD_FRAME_ES = {
        "agentvault.com": "https://events.theprotocol.cloud",
        "frame-b.theprotocol.cloud": "https://events-b.theprotocol.cloud",
        "frame-c.theprotocol.cloud": "https://events-c.theprotocol.cloud",
    }
    if _td in _PROD_FRAME_ES:
        return _PROD_FRAME_ES[_td]
    return os.getenv("EVENT_STORE_PUBLIC_URL", "https://events.theprotocol.cloud")


def _frame_ws_events_host() -> str:
    """Host a generated cloud-op's `/ws/events` (live event ledger) proxies to.

    An operator has no EventStore of its own, so the live ledger is proxied to
    its PARENT FRAME's public vhost, which already terminates TLS and forwards
    `/ws/events` to that frame's ES. The frame's own identity is `BASE_URL`, so
    derive from it — the old `api.theprotocol.cloud` default silently pointed
    every operator at FRAME A, which is correct only for Frame A's own ops. An
    op under a standalone frame got the cluster's ledger (or, once a standup
    template "fixed" it with a loopback port, a 502).

    `WS_EVENTS_PROXY_HOST` stays as an explicit override for a frame whose WS
    edge is not its BASE_URL — but a bare host only, never a scheme or path:
    the caller emits `https://<host>/ws/events`, so a value like
    `localhost:8150` yields `https://localhost:8150/…` against a plaintext
    port. Values carrying a scheme are normalised here rather than trusted.
    """
    def _host_only(v: str) -> str:
        v = v.strip()
        if "://" in v:
            v = v.split("://", 1)[1]
        return v.split("/", 1)[0].strip().rstrip(":")

    explicit = _host_only(os.getenv("WS_EVENTS_PROXY_HOST", "") or "")
    # §FEFRAME W2 (2026-10-01): an override must be a PUBLIC DNS name. The frame template shipped
    # `localhost:<registry port>` (frame-test.env.tmpl FT_REG_WS_EVENTS_PROXY_HOST), and every operator provisioned or
    # renamed under a runner-built frame got `https://localhost:<port>/ws/events`: TLS against the parent REGISTRY's
    # plaintext port, which does not serve /ws/events at all (measured 2026-09-30: all six operator consoles' ledger
    # lanes 502). A loopback, an IP or a bare container name is refused here and the frame's public host stands in.
    from agentvault_registry.core.federation_view import host_of as _public_host
    if explicit and _public_host(f"https://{explicit.split(':', 1)[0]}"):
        return explicit
    if explicit:
        logger.warning("[CloudProvisioner] WS_EVENTS_PROXY_HOST=%r is not a public DNS name: the operator's ledger "
                       "lane uses the frame's BASE_URL host instead", explicit)
    base = _host_only(os.getenv("BASE_URL", "") or "")
    if base and _public_host(f"https://{base.split(':', 1)[0]}"):
        return base
    return "api.theprotocol.cloud"


def derived_fx_gateway(
    trust_domain: str, own_registry_name: Optional[str], fx_router_did: str,
) -> Tuple[str, str, str, Optional[str]]:
    """The FX route gateway a NON-cluster frame hands its own operators.

    Returns `(registry_id, router_did, teg_id, gateway_url)`, or four empties when
    this frame cannot name itself — an operator must never inherit another frame's
    gateway (§SBXFXROUTE 2026-09-06: every frame outside the hardcoded
    frame-b/frame-c/Frame-A branches was handing its operators `registry-a`,
    `teg-layer-a` and Frame A's @fx_router DID, EU/ASIA's four included).

    `registry_id` is the slug of the frame's CARD name, because that is what the
    operator's peer ROW is named and what `_fx_route_find_active_peer` matches on —
    not REGISTRY_NAME, which is the container-facing name and differs (measured:
    card "Sandbox Alpha" → `sandbox-alpha`, REGISTRY_NAME `sbx-alpha`).
    """
    from ..core.registry_slug import registry_slug

    did = (fx_router_did or "").strip()
    reg = registry_slug(own_registry_name) if (own_registry_name or "").strip() else ""
    if not (did and reg):
        return ("", "", "", None)
    td = (trust_domain or "").strip()
    return (reg, did, f"teg-layer-{reg}", f"https://{td}:8443" if td else None)


def _federates_with_from_entry_show(stdout: str) -> list:
    """§MONEY-R49 (2026-09-04, agentvault2-07's B0b): the trust domains an existing SPIRE entry
    already federates with, read off `spire-server entry show` text ("FederatesWith    : td"),
    order-preserving, deduplicated, `spiffe://` stripped (the CLI takes the bare domain).

    `spire-server entry update` is a REPLACE: an update that does not re-pass `-federatesWith`
    drops every federation relationship the entry had. Harmless at first provision (there are
    none yet); destructive on a re-run against an operator that has since been federated.
    """
    out: list = []
    for line in (stdout or "").splitlines():
        key, _, val = line.partition(":")
        if key.strip() != "FederatesWith":
            continue
        td = val.strip()
        if td.startswith("spiffe://"):
            td = td[len("spiffe://"):]
        td = td.strip("/")
        if td and td not in out:
            out.append(td)
    return out



async def federation_trust_domains(
    db: AsyncSession,
    *,
    own_td: str,
    partner_td: str,
    declared: str,
) -> list:
    """The SPIFFE trust domains a cloud operator this frame provisions must accept.

    §MTLSGAP row 199 (2026-09-08). THE LITERAL DEFAULT NAMES THE FEDERATION WE USED TO HAVE.
    The 2026-07-24 note above `FRAME_TRUST_DOMAINS` already said "an operator must trust EVERY
    frame in the federation, not a hardcoded pair" — and then encoded that federation as three
    literals (`agentvault.com`, `frame-b…`, `frame-c…`). When EU and ASIA were stood up nobody
    set `FRAME_TRUST_DOMAINS`, so every operator was born trusting its own frame plus three
    RETIRING ones, and **not the peer frame it is actually federated with**.

    Measured on amsterdam before the fix: `spiffe://asia.theprotocol.cloud/service/registry`
    refused as an untrusted domain once a minute since standup. The refusal then falls through
    to the licence rail, so the visible answer was *"Invalid or revoked federation license"* —
    a 403 blaming the wrong half, which is why nobody looked. `GET /federation/contracts-for-peer`
    has never worked between a frame and its peer's operators.

    So derive it. This frame's live `peer_registries` rows ARE the federation, and they are the
    same rows the cert-writer's federated bundle was built from — every operator's
    `bundle.0.pem` already carries the peer root (measured: 2 roots on all four), so the
    app-side allowlist was the only thing refusing.

    ⚠ THIS ONLY EVER WIDENS. The declared literals stay as a floor, so an operator can never be
    born trusting less than it does today; where their roots are absent they are inert anyway
    (nginx refuses an unverifiable cert at the handshake, and since V0273 the app re-checks the
    chain itself). And UNKNOWN IS NOT EMPTY: if the peer rows cannot be read at all we keep the
    declared set rather than silently narrowing an operator to its own frame.
    """
    derived: list = []
    try:
        rows = (await db.execute(
            select(models.PeerRegistry.trust_domain).where(
                models.PeerRegistry.peer_type == "frame",
                models.PeerRegistry.status == "ACTIVE",
                models.PeerRegistry.trust_domain.isnot(None),
            )
        )).scalars().all()
        derived = [str(t).strip() for t in rows if t and str(t).strip()]
        logger.info("[provision] federated trust domains derived from live peer rows: %s",
                    derived or "(none)")
    except Exception as e:
        logger.warning("[provision] could not derive peer trust domains (%s) — keeping declared set", e)

    ordered = [own_td, partner_td] + derived + [d.strip() for d in (declared or "").split(",") if d.strip()]
    seen: set = set()
    return [d for d in ordered if d and not (d in seen or seen.add(d))]


class HostStepsNotWired(RuntimeError):
    """The runner route cannot finish this provision yet, and says exactly which steps have no path.

    §OPDIST (2026-09-16). The alternative was to run the steps that ARE wired and stop where the first one is not,
    which leaves a frame carrying a stack dir, a licence and half an operator that someone has to reason about
    later. A clean refusal leaves nothing behind, and this one names the work rather than the symptom.
    """


class _EnvSink:
    """Collects the operator's env lines, then puts them where they belong.

    §OPDIST (2026-09-16): four hundred lines below decide what a cloud operator is born knowing, and every one of
    them uses exactly one property of the file handle — `.write`. Collecting first lets the SAME computation serve a
    frame that owns this filesystem (EU and ASIA: the lines are appended to .env.operator in order, byte for byte as
    before) and one that does not (a runner-built frame: the lines cross to the one-shot that owns it). The
    alternative was a second copy of that computation, and a second copy of what an operator is born with is how two
    frames quietly stop being the same product.

    ⚠ It writes on the way out EVEN IF the block raised, because a real file handle does: today a half-written env
    survives a mid-block failure, and a refactor that quietly changed that would be changing behaviour under cover of
    moving code.
    """

    def __init__(self, path: Optional[str] = None):
        self.path = path
        self.lines: List[str] = []

    def write(self, s: str) -> int:
        self.lines.append(s)
        return len(s)

    def __enter__(self) -> "_EnvSink":
        return self

    def __exit__(self, *exc) -> bool:
        if self.path and self.lines:
            with open(self.path, "a") as fh:
                fh.write("".join(self.lines))
        return False

    def as_pairs(self) -> "OrderedDict[str, str]":
        """The KEY=VALUE lines, in order, for a spec that crosses to the one-shot.

        Comments and blank lines are for the file and mean nothing to a caller; a later line for the same key wins,
        which is what an env file appended in this order already means to the reader of it.
        """
        pairs: "OrderedDict[str, str]" = OrderedDict()
        for line in "".join(self.lines).splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key:
                pairs[key] = value
        return pairs


def _operator_container_census(safe: str, client_factory=None) -> Tuple[Optional[dict], str]:
    """({status: count} of the cloud-op-<safe>-* containers, "") or (None, why) when the daemon could not be asked.

    Every state is counted (all=True): a container left `created` or `exited` is what the reconcile is for, and a list of
    running ones only cannot say which. An unreadable daemon is None, never an empty dict: it used to count as
    "0 running" and read exactly like a stack that had not started."""
    try:
        if client_factory is None:
            import docker as _docker_sdk
            client_factory = _docker_sdk.from_env
        states: dict = {}
        for c in client_factory().containers.list(all=True, ignore_removed=True):
            if c.name.startswith(f"cloud-op-{safe}-"):
                states[c.status] = states.get(c.status, 0) + 1
        return states, ""
    except Exception as exc:  # noqa: BLE001  the caller says the daemon was unreadable, and why
        return None, f"{type(exc).__name__}: {str(exc)[:160]}"


def _reconcile_shortfall_line(safe: str, census: Optional[dict], why: str, want: int = 9,
                              load1: Optional[float] = None) -> Optional[str]:
    """The reconcile's closing warning, or None when `want` containers run. It says what it saw: the running count, every
    other state by name, how many were never created, the host's load as a number, or that the daemon could not be read.
    It names no cause it did not measure: the line used to blame the host's load whatever it saw (the §F6 WP6.2 finding:
    it did so for an image-pull failure), and an unreadable daemon read as zero running."""
    if census is None:
        return (f"[CLOUD-PROV] {safe}: the containers could not be read after reconcile ({why}), so how many run is "
                f"unknown; see 'docker ps -a --filter name=cloud-op-{safe}-'")
    running = census.get("running", 0)
    if running >= want:
        return None
    others = [f"{k} {v}" for k, v in sorted(census.items()) if k != "running"]
    missing = max(0, want - sum(census.values()))
    if missing:
        others.append(f"{missing} not created")
    load = f"load1 {load1:.1f}" if load1 is not None else "load unread"
    return (f"[CLOUD-PROV] {safe}: {running}/{want} running after reconcile ({', '.join(others) or 'no other state'}; "
            f"{load}); may need 'docker compose up -d --force-recreate'")


async def provision_cloud_operator(
    operator_name: str,
    application: models.OperatorApplication,
    db: AsyncSession,
    latitude: Optional[float] = None,
    # §LOCTRUTH (2026-09-06) — was this location DECLARED by whoever provisioned, or auto-picked for
    # globe legibility? It decides whether the admin developer is stamped with it: see below.
    location_is_declared: bool = True,
    longitude: Optional[float] = None,
    location_label: Optional[str] = None,
    docker_pull_token: Optional[str] = None,
    docker_username: Optional[str] = None,
    worker_count: int = 8,
) -> CloudProvisionResult:
    """
    Provision a cloud-hosted operator registry.

    This is the async equivalent of scripts/provision_sandbox_operator.py,
    running from within the registry container with host filesystem access
    via volume mounts.
    """
    safe = _safe_name(operator_name)
    domain = f"{safe}.{CLOUD_DOMAIN_SUFFIX}"
    dir_name = f"cloud-op-{safe}"
    stack_dir_host = f"{STACK_ROOT_HOST}/{dir_name}"
    stack_dir_container = f"{HOST_STACK_MOUNT}/{dir_name}"
    # ⚠ A RE-PROVISION OF ONE APPLICATION KEEPS ITS OWN PORTS. The allocator hands out the next free block, and
    # counts dead applications while doing it, so re-provisioning jelgava moved it 31500 -> 31600 (agentvault2-6a,
    # 2026-09-16). The edge is written from the job result so nothing broke, but the ports an operator is reached
    # on are part of its identity: a block that moves on every retry leaves stale firewall notes, stale SNI lines
    # nobody removed, and a monitoring target pointing at a port that is now somebody else's.
    if application.cloud_port_base:
        port_base = int(application.cloud_port_base)
        logger.info(f"[CLOUD-PROV] {safe}: reusing this application's own port block {port_base}")
    else:
        port_base = await allocate_port_block(db)
    reg_port = port_base
    fed_port = port_base + 43
    # TEG host port (added 2026-04-30 wave 6) — exposes operator TEG to host so
    # Prometheus can scrape it via 172.17.0.1:<teg_port>. Internal port stays
    # 8080; service-to-service traffic still goes via container DNS.
    teg_port = port_base + 80

    # §OPDIST (2026-09-16): WHICH HALF DOES THE HOST WORK, asked the same way the activation route asks it. A frame
    # whose registry holds the docker socket (EU, ASIA) does everything below itself, byte for byte as before. A
    # runner-built frame has no socket on purpose, so the file writing, the compose edits and `up` happen in the
    # runner's one-shot; everything that is DATABASE work — the licence, the peer rows, the ES upsert — stays here,
    # because a thing issued once must not sit on the far side of a boundary that can fail after issuing it.
    # §F6 WP6.0 (2026-09-26): the route is host_route()'s (HOST_REACH_PREFER included; unset = the order above, byte for
    # byte), and no route is a refusal here rather than a runner call that fails later
    from agentvault_registry.core.host_reach import host_route
    _route, _direct_why = host_route()
    if _route is None:
        raise RuntimeError(f"no route for this operator's host work: {_direct_why}")
    _direct_ok = _route == "direct"
    _through_runner = not _direct_ok
    if _direct_ok:
        # §OPPROV: the images first, before a bundle is rebuilt, a licence rotated or a stack dir written
        _missing_images = await asyncio.to_thread(operator_images_preflight, docker_username or "",
                                                  docker_pull_token or "")
        if _missing_images:
            raise RuntimeError("the operator's images cannot be had, so nothing was provisioned: "
                               + "; ".join(_missing_images))
    # §HELLOFRAME lane 6 (2026-09-18): the EDGE the host work ends in. "nginx" = this host's nginx vhost and SNI line
    # (every frame on the network's own host, and every runner too old to say otherwise); "caddy" = a frame stood up
    # by frame-up on its own host, whose own edge container serves the operator under `<safe>.<CLOUD_DOMAIN_SUFFIX>`
    # on the operator's own federation port, with the registry and TEG ports bound to the docker bridge gateway.
    from agentvault_registry.core.host_reach import runner_edge
    from agentvault_registry.core.operator_compose import (
        images_prefix_is_local, operator_public_urls, plain_port_bind, port_line,
    )
    _edge_mode = runner_edge() if _through_runner else "nginx"
    # §SECFIX-8: loopback under this host's nginx edge (it was every interface), the bridge gateway under a Caddy edge
    _bind_address = plain_port_bind(_edge_mode, os.getenv("DOCKER_BRIDGE_GATEWAY", "172.17.0.1"), os.getenv("OPERATOR_PLAIN_PORT_BIND"))
    _images_local = images_prefix_is_local(IMAGES_PREFIX)
    _public = operator_public_urls(safe=safe, suffix=CLOUD_DOMAIN_SUFFIX,
                                   lane_port=(fed_port if _edge_mode == "caddy" else 8443))

    logger.info(f"[CLOUD-PROV] Provisioning {safe}: domain={domain}, "
                f"ports={reg_port}/{fed_port}/{teg_port}, dir={stack_dir_host}, "
                f"host work={'the frame runner' if _through_runner else 'this registry'}")


    # ── Step 1: Extract bundle ────────────────────────────────────────
    bundle_path = application.bundle_path
    if not bundle_path or not os.path.exists(bundle_path):
        # ⚠ ACTIVATION'S PROMISE, KEPT HERE. `/operators/activate` spends the one-time code, answers 200 and logs
        # that the operator "can get a bundle re-generated later" when the bundle fails — and until 2026-09-16
        # nothing anywhere re-generated one, so an application in that state was finished: the code was spent, the
        # row had no bundle, and this line answered 500 forever. Two of them existed on beacon within a day.
        # The token is THIS call's, already minted by the caller and about to be recorded on the row below, so the
        # operator's compose and the row agree about the credential it will pull with.
        from agentvault_registry.core.frame_slug import frame_slug as _fs
        from agentvault_registry.services import operator_provision_client as _opc
        _ok, _why = _opc.may_rebundle(application.status, application.activated_at)
        if not _ok:
            raise RuntimeError(f"this application {_why}. Nothing was built.")
        logger.warning(f"[CLOUD-PROV] {safe}: the application carries no readable bundle "
                       f"({application.bundle_path!r}); rebuilding it through "
                       f"{'the runner' if _through_runner else 'this registry'} before provisioning")
        if _through_runner:
            _rb = await _opc.bundle_through_runner(
                frame=_fs(), operator_name=application.name or safe, safe_name=safe,
                operator_did=f"did:theprotocol:operator:{safe}", application_id=str(application.id),
                docker_pull_token=docker_pull_token or "", docker_username=docker_username or "")
        else:
            # §OPPROV (2026-09-27): the SOCKET route keeps the same promise. Until now only the runner route rebuilt,
            # so on EU, ASIA and the sandbox pair a failed activation bundle (measured on sbx-beta: wp62op, the 640
            # template) ended every later provision at "Bundle not found ... Run activation first", and activation
            # cannot run again once its code is spent. Rebuilt in-process exactly as activation's own direct branch
            # builds it, with THIS call's pull token so the row and the compose agree. The failed attempt's entries
            # hang from a node that never attested, so they are swept first rather than left beside the new ones.
            _left = await asyncio.to_thread(_delete_op_spire_entries, safe)
            if _left:
                raise RuntimeError(
                    (f"this frame's SPIRE server could not be asked for operator {safe}'s old entries"
                     if _left < 0 else f"{_left} SPIRE entries of operator {safe} could not be removed")
                    + ", so its bundle was not rebuilt; nothing was built")
            _r = await asyncio.to_thread(operator_provisioner.provision_operator, safe,
                                         f"did:theprotocol:operator:{safe}", docker_pull_token or "")
            _rb = {"bundle_path": _r.bundle_path, "fingerprint": _r.fingerprint,
                   "docker_username": _r.docker_username, "docker_pull_token_hash": _r.docker_pull_token_hash,
                   "docker_pull_token_prefix": _r.docker_pull_token_prefix,
                   "entries_registered": _r.entries_registered,
                   "bundle_filename": os.path.basename(_r.bundle_path or ""), "where": "this registry"}
        _now = datetime.now(timezone.utc)
        application.bundle_path = _rb["bundle_path"]
        application.bundle_generated_at = _now
        application.bundle_expires_at = _now + timedelta(days=30)
        application.spire_fingerprint = _rb["fingerprint"]
        application.docker_registry_username = _rb["docker_username"]
        application.docker_pull_token_hash = _rb["docker_pull_token_hash"]
        application.docker_pull_token_prefix = _rb["docker_pull_token_prefix"]
        application.docker_pull_token_issued_at = _now
        await db.flush()
        bundle_path = _rb["bundle_path"]
        logger.info(f"[CLOUD-PROV] {safe}: rebuilt bundle {_rb['bundle_filename']} "
                    f"({_rb['entries_registered']} SPIRE entries) via {_rb['where']}")
    if not bundle_path or not os.path.exists(bundle_path):
        raise RuntimeError(f"Bundle not found at {bundle_path}. Run activation first.")

    if _through_runner:
        # The one-shot makes the stack dir, extracts into it and writes every file. This registry cannot: it holds no
        # host filesystem and no docker socket, which is the point of the split rather than a limitation of it.
        logger.info(f"[CLOUD-PROV] the one-shot will extract {os.path.basename(bundle_path)} into {stack_dir_host}")
    else:
        os.makedirs(stack_dir_container, exist_ok=True)
        # §pass66 (2026-05-22) — bundle-storage dir for §pass51 Bundles feature.
        # Compose has `./bundle-storage:/app/bundle-storage` bind mounts on
        # registry + nginx-federation; without the dir, docker creates it as
        # root-owned which the operator's UID can't write to. Pre-create with
        # the same UID the registry container runs as (1000 = agentvault).
        os.makedirs(f"{stack_dir_container}/bundle-storage", exist_ok=True)
        # _run OK: local shell invocation of `tar` (bundled in registry image base, not a docker CLI dep).
        # §OPDIST (2026-09-16): _run LOGS a failure and returns, so a discarded result is a step that can fail
        # silently. This is the one that everything after it assumes: a failed extract leaves an empty stack dir and
        # the provision continues against nothing. Read the status here rather than discovering it as a missing file
        # four steps later.
        _extract = _run(f"tar xzf {bundle_path} -C {stack_dir_container}")
        if _extract.returncode != 0:
            raise RuntimeError(
                f"the operator bundle did not extract into {stack_dir_container} "
                f"(tar exit {_extract.returncode}): {(_extract.stderr or '').strip()[:200]}"
            )
        logger.info(f"[CLOUD-PROV] Bundle extracted to {stack_dir_container}")

    # ── Step 2: Generate .env.operator ────────────────────────────────
    env_path = f"{stack_dir_container}/.env.operator"
    if not _through_runner:
        env_script = f"{stack_dir_container}/generate-operator-env.sh"
        if os.path.exists(env_script):
            # _run OK: local shell invocation of `bash` (no docker CLI needed).
            _run(f"cd {stack_dir_container} && bash generate-operator-env.sh cloud-op-{safe}")

        if not os.path.exists(env_path):
            # Generate minimal env if script didn't produce one
            _generate_env_file(env_path, safe)

    # §MTLSHOPS (2026-09-16): the four values this operator is born with — one marker per terminator, so each app counts
    # a forwarded certificate only beside its own proxy's, and one Redis password per client, so nothing reaches Redis as
    # the default user. Generated OUTSIDE the file handle and before it, because Step 5b renders the confs and the ACL
    # file from this same dict a thousand lines below: a name bound inside a block someone later makes conditional is a
    # NameError at provision time.
    op_secrets = operator_provisioner.generate_operator_secrets()

    with _EnvSink(None if _through_runner else env_path) as f:
        f.write(f"\n# Cloud hosting overrides (f051)\n")
        # REGISTRY_NAME stays `cloud-op-<safe>` because container_name tokens
        # in the operator compose expand from it.
        f.write(f"REGISTRY_NAME=cloud-op-{safe}\n")
        f.write(f"REGISTRY_SAFE_NAME={safe}\n")
        f.write("\n# §MTLSHOPS: this operator's terminator markers and per-client Redis passwords (never print)\n")
        for _name in operator_provisioner.OPERATOR_SECRET_NAMES:
            f.write(f"{_name}={op_secrets[_name]}\n")
        # §pass34 (2026-05-17) — canonical federation identity. Seeded into
        # the `registry_self` singleton by migration 0061 at first boot, AND
        # written directly to the table by this provisioner (later in this
        # function) for redundancy. The env var is the seed source if the
        # provisioner-side INSERT raced the migration.
        f.write(f"REGISTRY_FEDERATION_NAME={safe}\n")
        # §pass66 (2026-05-22) — Path 3 / Bug A. ALWAYS pin fresh cloud-ops to
        # a known-good image tag. Previously this was env-conditional → prod
        # never set OPERATOR_DEFAULT_IMAGE_VERSION → every fresh provision fell
        # through to compose-side `${VERSION:-stable}` → pulled whatever was
        # last manually tagged `:stable` (still the 2026-05-04 image at handover
        # time, missing every fix since §pass63). Symptom on qatest6: Astraeus
        # code still present, no custom-theme picker, alembic 51 migrations
        # behind — all because the cloud-op ran a 2-week-old binary against
        # a current-day DB schema.
        #
        # Resolution chain matches Registry Card v0.3 `identity.software_version`
        # (the central reg's card publishes the same value), so what the new
        # op pulls is exactly what the parent reg is running:
        #   IMAGE_TAG env → OPERATOR_DEFAULT_IMAGE_VERSION env (legacy) →
        #   BUNDLED_IMAGE_TAG constant (`core/registry_identity.py`).
        from agentvault_registry.core.registry_identity import get_software_version
        _pinned_version = operator_image_version(get_software_version())
        if _pinned_version:
            # VERSION → consumed by docker-compose `${VERSION:-stable}` to pull
            # the right image at boot. IMAGE_TAG → consumed by the operator's
            # registry container at runtime so `identity.software_version` in
            # its Registry Card v0.3 reports the actual deploy tag (rather
            # than falling through to BUNDLED_IMAGE_TAG, which is a stale
            # source-baked literal that lags fleet rollouts by 1-N passes).
            # Both must be written; they're conceptually distinct (one is
            # pull-time, the other runtime) but always equal in practice.
            f.write(f"VERSION={_pinned_version}\n")
            f.write(f"IMAGE_TAG={_pinned_version}\n")
            logger.info(
                f"[CLOUD-PROV] Pinned operator image tag: {_pinned_version} "
                f"(via Registry Card v0.3 identity.software_version chain; "
                f"VERSION + IMAGE_TAG both written)"
            )
        else:
            # Configuration regression — all 3 sources empty. Cloud-op will
            # fall through to `${VERSION:-stable}`; flag it so it's visible.
            logger.warning(
                "[CLOUD-PROV] No IMAGE_TAG / OPERATOR_DEFAULT_IMAGE_VERSION / "
                "BUNDLED_IMAGE_TAG set — fresh operator will fall through to "
                ":stable. Set IMAGE_TAG in central registry env to pin."
            )
        # §HELLOFRAME lane 6: the image namespace the compose's `${IMAGES_PREFIX:-...}` lines pull from, or the local
        # tag namespace a foreign host loaded. The network's own value is the compose default, so this line changes
        # nothing on the network's own host and everything on a stranger's.
        f.write(f"IMAGES_PREFIX={IMAGES_PREFIX}\n")

        # Phase A (2026-04-28): if the central registry is in jwt-svid mode for
        # /ws/events handshake, propagate the same to provisioned operators so
        # they mint their OWN JWT-SVIDs (signed by the same trust domain SPIRE).
        # Production unset → operators stay on shared-secret path. Sandbox sets
        # both envs so EVENTSTORE_WS_AUTH_REQUIRED can be true on the central ES.
        _ws_auth_mode = os.getenv("EVENTSTORE_WS_AUTH_MODE", "")
        _ws_audience = os.getenv("EVENTSTORE_JWT_AUDIENCE", "")
        if _ws_auth_mode:
            f.write(f"EVENTSTORE_WS_AUTH_MODE={_ws_auth_mode}\n")
        if _ws_audience:
            f.write(f"EVENTSTORE_JWT_AUDIENCE={_ws_audience}\n")
        # IRONHAND proxy: operator registry delegates SPIRE admin (register/delete
        # entries) to the central registry that owns our SPIRE server, since
        # operator containers don't mount /var/run/docker.sock.
        _central_url = os.getenv("CENTRAL_REGISTRY_URL_FOR_OPERATORS", "http://agentvault_registry_a:8000")
        f.write(f"CENTRAL_REGISTRY_URL={_central_url}\n")
        # §MTLSGAP row 203 (2026-09-08) — AND THE FALLBACK THAT LINE DEPENDS ON.
        # `CENTRAL_REGISTRY_URL` is an INTERNAL docker name, and an operator does not share a
        # network with its frame — so it does not resolve, and `operator_portal_actions` falls
        # back to `MAINFRAME_PUBLIC_URL`. That key was never written by any standup, so the
        # fallback took its hardcoded default `https://api.theprotocol.cloud`: every operator in
        # the EU/ASIA cluster pointed its portal actions and its fiat mainframe lookup at
        # **FRAME A**, a frame that is being retired and was never their parent. The comment on
        # that fallback says it exists precisely "so a non-production frame's operator falls back
        # to ITS OWN frame rather than the production apex" — the mechanism was right and the key
        # that makes it true was missing. §FXSTRAND's class: a fallback whose precondition the
        # standup never supplies, and nobody finds out because a wrong parent still answers.
        # Written from the provisioning frame's OWN public URL, so it can never name another frame.
        _mainframe_public = (os.getenv("MAINFRAME_PUBLIC_URL_FOR_OPERATORS", "")
                             or os.getenv("PUBLIC_UI_URL", "")
                             or os.getenv("BASE_URL", "")).strip().rstrip("/")
        if _mainframe_public.startswith("https://"):
            f.write(f"MAINFRAME_PUBLIC_URL={_mainframe_public}\n")
            # §OPDIST (2026-09-16) — THE DIRECTORY LANE, his first-named item ("connected to everything the frame
            # provides ... DIRECTORY, es, kafka, redis ... auditor"), and measured to be ONE env pair rather than
            # the four halves it first looked like.
            #
            # An operator reads the frame's federated index THROUGH ITS PARENT'S REGISTRY, at the same public path
            # the frame's own console uses since §MTLSGAP moved that lane off the host vhost. Proven from inside
            # cloud-op-amsterdam-registry BEFORE this was written: GET .../public/directory/health 200 and POST
            # .../public/directory/graphql 200, unauthenticated. There is no new lane to build.
            #
            # ⚠ WHAT THIS DELIBERATELY IS NOT: the first shape had the operator's registry dial the frame's index
            # through the operator's OWN nginx-federation. That sidecar is an INBOUND terminator with
            # `ssl_verify_client on` whose every location proxies to LOCAL upstreams; an outbound `/directory/`
            # would have made it an egress relay into the frame's private index, with the index's reader gate
            # checking the SIDECAR's identity rather than the caller's. A confused deputy that reads as fine in a
            # diff. It would also have required the operator's SPIFFE ID in the frame's DIRECTORY_READERS — a
            # per-operator frame-side write that this pair removes entirely.
            #
            # `MAINFRAME_PUBLIC_URL` is the base and not `CENTRAL_REGISTRY_URL`, because row 203 measured that the
            # latter is an internal docker name an operator cannot resolve.
            f.write(f"DIRECTORY_PUBLIC_URL={_mainframe_public}/api/v1/public/directory\n")
            f.write("DISCOVERY_VIA_DIRECTORY=true\n")
        else:
            # NAMED, not silently omitted: without this the operator falls back to a literal that
            # names someone else's frame, and the symptom is a portal action that "works".
            logger.warning(
                "[provision] MAINFRAME_PUBLIC_URL not written for %s — no https public URL known "
                "for this frame (tried MAINFRAME_PUBLIC_URL_FOR_OPERATORS, PUBLIC_UI_URL, "
                "BASE_URL). The operator will fall back to the hardcoded api.theprotocol.cloud, "
                "which is FRAME A. Set one of those on the provisioning registry.", safe)
        if application.spire_fingerprint:
            f.write(f"OPERATOR_SPIRE_AGENT_FINGERPRINT={application.spire_fingerprint}\n")
        f.write(f"MINTING_AUTHORITY=disabled\n")
        f.write(f"CROSS_TEG_ENABLED=true\n")
        f.write(f"GENESIS_GRANT_ENABLED=true\n")
        # §MONEY-M2 (R7): the grant an operator hands out is a profile knob, not a literal.
        # The fallback is the 5000.0 this line always wrote, so an unprofiled provision
        # renders byte-identically to before.
        f.write(f"GENESIS_GRANT_AMOUNT={money_knob('GENESIS_GRANT_AMOUNT', '5000.0')}\n")
        # §FRAMEMAIL-3 (2026-08-01) — mail posture, shared with the frame
        # provisioner via core/operator_mail.py so the two paths cannot drift.
        #
        # This replaces a bare `BETA_INVITE_REQUIRED=false`, which combined with
        # the template's placeholder `smtp.example.com` and the default
        # REQUIRE_EMAIL_VERIFICATION=true to produce the §OPGUIDE-2 lockout:
        # measured live on 13 of 14 cloud operators on 2026-08-01, every
        # self-registered account permanently dead.
        #
        # A node listed in OPERATOR_MAIL_HANDED_OVER never receives the token:
        # a submission credential inside a container somebody else administers
        # is a credential we have given away (PART 11b).
        _handed_over = {
            s.strip().lower()
            for s in (os.getenv("OPERATOR_MAIL_HANDED_OVER") or "").split(",")
            if s.strip()
        }
        _first_party = safe.lower() not in _handed_over
        _op_label = (application.name or safe).strip()
        # §FRAMEMAIL-4 — a handed-over node still needs to SEND, or turning
        # verification on locks out everyone it invites. It gets a parent relay
        # instead of the token: no credential of ours lands in its container, and
        # the parent owns the From:, the templates and the rate limit.
        # Registration gating is now an independent axis (rule 3 in operator_mail):
        # handed-over => invite-only, first-party => open. Same call, both axes.
        _relay = operator_mail.provisioned_relay(safe) if not _first_party else None
        for _line in operator_mail.mail_env_lines(
            _op_label, first_party=_first_party, relay=_relay
        ):
            f.write(_line + "\n")
        logger.info(
            "[cloud-provision] %s mail posture: %s",
            safe,
            operator_mail.posture(first_party=_first_party, relay=_relay),
        )
        f.write(f"EVENT_STORE_ENABLED=true\n")
        f.write(f"EVENTSTORE_MTLS_REQUIRED=true\n")
        # §pass68 (2026-05-23) — per-tool MCP audit logging. Every /mcp/rpc and
        # /mcp/admin/rpc tools/call lands in security_audit_logs with sanitized
        # args + outcome + latency. Fire-and-forget; never blocks response path.
        # Operators can query their own dev-scoped rows via GET /api/v1/me/mcp-audit-log.
        # Kill switch: flip to "false" in .env.operator + recreate registry container.
        f.write(f"MCP_AUDIT_LOGGING_ENABLED=true\n")
        _es_url = _frame_public_es_url()  # §pass78c frame-aware (no events-b clone-bug)
        f.write(f"EVENT_STORE_URL={_es_url}\n")
        # §pass78c — inherit the PARENT FRAME's settlement currency. A Frame-C (BVT)
        # op provisioned by frame-c-registry (FRAME_CURRENCY=BVT) was previously left
        # to default AVT → its registry card claimed fees.settlement_currency=AVT →
        # cross-frame FX egress to that op LOOPED (the parent frame resolved the op
        # as AVT, not BVT, via the op's own card, and bounced it back to the AVT
        # gateway → hop budget exhausted). Propagate the provisioning frame's own
        # FRAME_CURRENCY so the op self-identifies + prices FX correctly.
        f.write(f"FRAME_CURRENCY={(os.getenv('FRAME_CURRENCY', 'AVT') or 'AVT').strip().upper()}\n")
        # 2026-06-02 — Balance outbox: journal→LedgerBalanceChanged→parent frame ES.
        # Cloud-ops have NO own ES; their balance changes reconcile into the parent
        # frame's ES ONLY via this leader-elected flusher. Prod ops (e.g. op-london)
        # have it on; the template previously omitted it, so a freshly-provisioned
        # cloud-op's balances never reached the parent ES (transit_net stuck non-zero,
        # treasury funding looked "inflight forever"). Surfaced building the first
        # Frame-C (BVT) cloud-op. The operator's SVID authenticates the emit at the
        # parent ES's mTLS edge (§SOVKIT-2 R2: no store key in the operator env).
        f.write(f"TEG_BALANCE_OUTBOX_ENABLED=true\n")
        # ── Fleet-baseline operator env (§2026-06-14) ──────────────────────
        # A freshly-clicked op must boot PRODUCTION-READY, identical to the live
        # fleet (op-london / op-tokyo / op-doha), not a minimal stub. These keys
        # were historically backfilled onto existing ops by per-feature rollout
        # scripts; the base template never wrote them, so a fresh op lagged ~40
        # lines behind — no PUBLIC_URL (card showed the FRAME url, not the op's own
        # subdomain), no FX routing, no AGORA exchange, no admission backstop, no
        # self-monitoring, no cross-frame ES visibility. Baking them here makes
        # "click → fully-fledged operator" true. Per-frame values key off the
        # provisioning mainframe's OWN frame (SPIRE_TRUST_DOMAIN). NOTE: this is the
        # current fleet baseline — when a future feature adds operator env, add it
        # HERE too (don't rely on a later rollout to backfill fresh ops).
        _bl_td = (TRUST_DOMAIN or "agentvault.com").strip()
        _parent_fx_override = True   # cleared only when a derived gateway cannot be named
        if _bl_td.startswith("frame-b"):
            # Frame-B (JDAY). FX gateway = registry-frame-b/teg-layer; no AGORA passport.
            _fx_reg, _fx_did, _fx_teg, _bl_passport = "registry-frame-b", "did:theprotocol:065e2052-5341-2dd2-3422", "teg-layer", False
            _fx_gw_url, _es_a_url = f"https://{_bl_td}:8443", None
        elif _bl_td.startswith("frame-c"):
            # Frame-C (BVT). FX gateway = registry-frame-c/teg-layer; passport on; and
            # C ops also carry EVENT_STORE_A_URL (they surface Frame-A's ES too).
            _fx_reg, _fx_did, _fx_teg, _bl_passport = "registry-frame-c", "did:theprotocol:dcc3b8b3-04a8-862b-0979", "teg-layer", True
            _fx_gw_url, _es_a_url = f"https://{_bl_td}:8443", "https://events.theprotocol.cloud"
        elif _bl_td == "agentvault.com":  # Frame-A — gateway is local registry-a; no GATEWAY_URL/ES-A needed
            _fx_reg, _fx_did, _fx_teg, _bl_passport = "registry-a", "did:theprotocol:16968217-03a0-e909-5026", "teg-layer-a", True
            _fx_gw_url, _es_a_url = None, None
        else:
            # ── ANY OTHER FRAME (§SBXFXROUTE 2026-09-06) ──────────────────────
            # This used to be the Frame-A branch's `else`, so EVERY frame that is
            # not frame-b/frame-c handed its operators PRODUCTION Frame A's
            # identity: `registry-a`, `teg-layer-a`, and Frame A's @fx_router DID.
            # Measured on this box: amsterdam, lisbon, shenzhen and hochiminh —
            # the four operators of the EU/ASIA cluster being rehearsed for
            # production — all carry FX_ROUTE_ENABLED=true pointing at registry-a,
            # and so did the JUICE/BRRR pair's operators. A cross-currency transfer
            # originated on one of them would have ingressed 1:1 to a FOREIGN
            # frame's transit account. Δ cannot see that: both legs are ordinary
            # transfers, and the money simply ends up on the wrong frame.
            #
            # Derive from THIS frame's own identity instead. The registry_id must
            # be what the operator's peer ROW will be named (the card's
            # registry_name, slugged by the one shared rule), because
            # `_fx_route_find_active_peer` matches on exactly that.
            _own_name = None
            try:
                _own_card = (await db.execute(select(models.RegistryCard))).scalars().first()
                _own_name = ((_own_card.card_json or {}).get("identity") or {}).get("registry_name") if _own_card else None
            except Exception as _e:            # noqa: BLE001
                logger.warning(f"[PROVISION] own registry card unreadable for the FX gateway: {_e!r}")
            _fx_reg, _fx_did, _fx_teg, _fx_gw_url = derived_fx_gateway(
                _bl_td, _own_name, os.getenv("FX_ROUTER_DID", "") or "")
            _es_a_url = None
            _bl_passport = True
            if not (_fx_did and _fx_reg):
                # An operator cannot route through a gateway with no transit account
                # or no resolvable peer row. OFF is strictly better than pointing at
                # someone else's frame — the failure is then a refusal, not a
                # misdelivery. Names nothing rather than naming the wrong thing.
                _parent_fx_override = False
                _fx_reg = _fx_did = _fx_teg = ""
                _fx_gw_url = None
                logger.warning(
                    "[PROVISION] this frame has no FX_ROUTER_DID or no readable card name — "
                    "the operator is provisioned with FX_ROUTE_ENABLED=false and NO gateway "
                    "identity (it must never inherit another frame's)")
        # PUBLIC_URL — the op's OWN subdomain (drives identity.public_url, the
        # browser 'full card' link). MUST be the :443 web URL served by the host
        # nginx vhost — NOT the :fed_port (port_base+43, the nginx-federation
        # mTLS port a browser can't reach). §2026-06-15 fix (was :fed_port →
        # broke the card link fleet-wide; the builder also strips any port now).
        # §HELLOFRAME lane 6: the three from ONE rule (operator_public_urls) — `<safe>.<CLOUD_DOMAIN_SUFFIX>`, the
        # federation lane on 8443 behind the host SNI router or on the operator's own port under a Caddy edge.
        f.write(f"PUBLIC_URL={_public['PUBLIC_URL']}\n")
        # §FRAMELIC (2026-09-07, findings row 154) — the address a FOREIGN frame must dial.
        # `FEDERATION_BASE_URL` on an operator is `https://nginx-federation:8443`, an internal
        # docker name that is correct for its own stack and meaningless on a signed card. A peer
        # frame that learns this operator through the registry-card fan-out therefore could not
        # derive a federation address, fell back to the :443 console, and never synced from it
        # (four `peer_url_misconfigured` drift events on the EU/ASIA pair). The card builder now
        # prefers BILATERAL_PEER_URL, so give every operator one: its own public host on the
        # federation port the host SNI router serves.
        f.write(f"BILATERAL_PEER_URL={_public['BILATERAL_PEER_URL']}\n")
        # §FIRSTHOUR / V0216: every human-facing node names its CONSOLE (PUBLIC_URL may carry the mTLS port);
        # the V0216 roll wrote this into 13 files by hand — the provisioner now writes it for every new operator.
        f.write(f"PUBLIC_UI_URL={_public['PUBLIC_UI_URL']}\n")
        # cross-frame EventStore visibility — PUBLIC events-b/c (NOT the mainframe's
        # internal nginx-event-store names, which an op cannot reach). Frame-C ops
        # additionally surface Frame-A's ES (events.theprotocol.cloud).
        # §HETZNERLOCK-16 (2026-07-30) — these are THIS CLUSTER's frames, so they may
        # only be written when the provisioning registry is actually part of it. A
        # sovereign frame that provisions its own operator was handing that operator
        # the CLUSTER's ledgers: op-demo (child of the standalone Hetzner frame) streamed
        # frame-b/frame-c and rendered three panes, because it inherited our shape.
        # The parent decides: if THIS registry has no B/C EventStore configured, its
        # children must not either. Same rule for FX below.
        _parent_auditor = (os.getenv("EXTERNAL_AUDITOR_ENDPOINT", "") or "").strip()
        if _parent_auditor:
            f.write(f"EXTERNAL_AUDITOR_ENDPOINT={_parent_auditor}\n")
        _parent_es_b = (os.getenv("EVENT_STORE_B_URL", "") or "").strip()
        _parent_es_c = (os.getenv("EVENT_STORE_C_URL", "") or "").strip()
        if _parent_es_b:
            f.write(f"EVENT_STORE_B_URL={_parent_es_b}\n")
        if _parent_es_c:
            f.write(f"EVENT_STORE_C_URL={_parent_es_c}\n")
        if _es_a_url:
            f.write(f"EVENT_STORE_A_URL={_es_a_url}\n")
        # FX routing via the frame's gateway
        # FX only exists for a child if the PARENT frame has an FX rail at all.
        _parent_fx = (os.getenv("FX_ENABLED", "") or "").strip().lower() == "true" or \
                     (os.getenv("FX_ROUTE_ENABLED", "") or "").strip().lower() == "true"
        # a derived-gateway frame that could not name itself refuses the route outright
        if not _parent_fx_override:
            _parent_fx = False
        f.write(f"FX_ROUTE_ENABLED={'true' if _parent_fx else 'false'}\n")
        f.write(f"FX_ROUTE_GATEWAY_REGISTRY_ID={_fx_reg}\n")
        f.write(f"FX_ROUTE_GATEWAY_ROUTER_DID={_fx_did}\n")
        f.write(f"FX_ROUTE_GATEWAY_TEG_ID={_fx_teg}\n")
        if _fx_gw_url:  # B/C ops reach their frame's FX gateway by URL; Frame-A is local
            f.write(f"FX_ROUTE_GATEWAY_URL={_fx_gw_url}\n")
        # AGORA exchange settlement throughput (§V0071 fleet baseline)
        f.write("EXCHANGE_SETTLE_BATCH=40\n")
        f.write("EXCHANGE_SETTLE_CYCLE_SEC=0\n")
        if _bl_passport:
            f.write("EXCHANGE_PASSPORT_ENABLED=true\n")
            # §BATCH3 item 1: the passport map is THIS network's topology, not code. The provisioning
            # node carries it in PROVISION_PASSPORT_URL_MAP (registry-a's compose environment: the
            # former literal, verbatim); unset => the line is not written and the operator inherits
            # nothing it was not told about.
            _passport_map = (os.getenv("PROVISION_PASSPORT_URL_MAP") or "").strip()
            if _passport_map:
                f.write(f"EXCHANGE_PASSPORT_URL_MAP={_passport_map}\n")
        # admission load-shed backstop (§V0040 fleet baseline)
        f.write("REGISTRY_ADMISSION_ENABLED=true\n")
        f.write("REGISTRY_ADMISSION_CLIENT_LIMIT=6\n")
        f.write("REGISTRY_ADMISSION_INTERNAL_LIMIT=6\n")
        f.write("REGISTRY_ADMISSION_RETRY_AFTER=2\n")
        # self-monitoring (cluster prometheus basic-auth)
        # self-monitoring: the Prometheus this frame NAMES for its operators (OPERATOR_PROMETHEUS_URL); UNSET means
        # the network's own, SET AND EMPTY means none (a stranger's host has no reason to point its operators at
        # ours, and an in-stack <name>-prometheus is a name an operator cannot resolve either). The basic-auth pair
        # only when this frame carries one: it used to fall back to a credential literal in source, and PROMETHEUS_URL
        # on our own registries is a docker-internal name, so neither is inherited blindly (§HELLOFRAME lane 6).
        if "OPERATOR_PROMETHEUS_URL" in os.environ:
            _prom_url = os.environ["OPERATOR_PROMETHEUS_URL"].strip()
        else:
            _prom_url = "https://prometheus.theprotocol.cloud"
        if _prom_url:
            f.write(f"PROMETHEUS_URL={_prom_url}\n")
        if os.getenv("PROMETHEUS_BASIC_AUTH", "").strip():
            f.write(f"PROMETHEUS_BASIC_AUTH={os.getenv('PROMETHEUS_BASIC_AUTH', '').strip()}\n")
        # canary fabric — ops are FOLLOWERS (registry-a master dispatches paths)
        f.write("CANARY_RUNNER_MODE=follower\n")
        # escrow reconciler self-heal (phantom pure-escrow lock release)
        f.write("ESCROW_RECONCILER_ENABLED=true\n")
        f.write("ESCROW_RECONCILER_DRY_RUN=false\n")
        # ── end fleet-baseline ─────────────────────────────────────────────
        f.write(f"SPIRE_TRUST_DOMAIN={TRUST_DOMAIN}\n")
        # Both frames' trust domains must be trusted for cross-frame cross-TEG
        # calls. Bug fix 2026-04-17: when provisioning on Frame B (TRUST_DOMAIN
        # = frame-b.theprotocol.cloud) the old expression produced
        # "frame-b.theprotocol.cloud,frame-b.theprotocol.cloud" and Frame-B
        # operators rejected TEG-A's cross-TEG prepare calls (403 "Invalid
        # cross-TEG authorization").
        # Sandbox-aware (2026-04-22): partner frame trust domain is env-overridable
        # so sandbox test provisioning can pair sandbox-a.test with sandbox-b.test
        # instead of the prod frame-b.theprotocol.cloud.
        _partner_frame_td = os.getenv("PARTNER_FRAME_TRUST_DOMAIN", "frame-b.theprotocol.cloud")
        _trust_other = _partner_frame_td if TRUST_DOMAIN != _partner_frame_td else ("frame-b.theprotocol.cloud" if TRUST_DOMAIN == "agentvault.com" else "agentvault.com")
        # §2026-07-24 FRAME-C FEDERATION GAP — the two-domain form above dates from the
        # two-frame era and was never updated when Frame C graduated sandbox→prod. Every
        # operator provisioned by Frame A or Frame B therefore got a TRUSTED_SPIFFE_DOMAINS
        # without `frame-c.theprotocol.cloud`, so `core/mtls_auth.py` rejected frame-c's
        # client SVID ("Client SPIFFE ID from untrusted domain") and frame-c could never
        # federate with those 9 operators — silently, for seven weeks, because a peer that
        # has NEVER synced is indistinguishable from a healthy one in peer_registries.
        # An operator must trust EVERY frame in the federation, not a hardcoded pair.
        # FRAME_TRUST_DOMAINS lets a deployment declare the full set; the two legacy
        # values stay in as a floor so nothing narrows on upgrade.
        _all_frames = os.getenv(
            "FRAME_TRUST_DOMAINS",
            "agentvault.com,frame-b.theprotocol.cloud,frame-c.theprotocol.cloud",
        )
        # §MTLSGAP row 199 (2026-09-08) — see federation_trust_domains() for why this is derived.
        _trusted = await federation_trust_domains(
            db, own_td=TRUST_DOMAIN, partner_td=_trust_other, declared=_all_frames
        )
        f.write(f"TRUSTED_SPIFFE_DOMAINS={','.join(_trusted)}\n")
        f.write(f"TEG_ID=teg-{safe}\n")
        _partner_teg_id = os.getenv("PARTNER_TEG_ID", "teg-layer-a")
        _partner_reg_id = os.getenv("PARTNER_REGISTRY_ID", "registry-a")
        # §pass66 (2026-05-22) — default port :8443 (not :18443 — that port
        # doesn't exist on the host). Per paris's working env: api.theprotocol.cloud:8443
        # routes federation traffic through host nginx with mTLS termination.
        # The earlier `:18443` default was sandbox-mode leftover that leaked
        # into prod provisioning.
        # §frame-c (2026-06-02) — frame-aware sandbox default. In sandbox mode the
        # partner mainframe TEG is fronted by its frame's nginx-test-{a,b,c}:8443
        # mTLS sidecar, reachable from the cloud-op TEG on agentvault_identity_network
        # (container :8443 direct). The prod default (api.theprotocol.cloud:8443) is
        # wrong for sandbox; a plain http://teg-layer-test-c:8080 (no mTLS) makes
        # cross-TEG 2pc fail 403 — the TEG client only presents its SVID for https://
        # URLs (Mode-1 mTLS), so a plain-http partner silently falls back to a Bearer
        # key the partner mainframe TEG does not trust. Explicit PARTNER_TEG_URL still
        # overrides. Verified live on sandboxcharlie (Frame C): prepare/commit 200.
        _partner_teg_default = "https://api.theprotocol.cloud:8443"
        if os.getenv("SPIRE_SERVER_ADDRESS") == "host.docker.internal":
            _nginx = {
                "sandbox-a.test": "nginx-test-a",
                "sandbox-b.test": "nginx-test-b",
                "sandbox-c.test": "nginx-test-c",
            }.get(os.getenv("SPIRE_TRUST_DOMAIN", "") or TRUST_DOMAIN, "nginx-test-a")
            _partner_teg_default = f"https://{_nginx}:8443"
        _partner_teg_url = os.getenv("PARTNER_TEG_URL", _partner_teg_default)
        # §REDERIVE (2026-09-12) — NEVER WRITE A PARTNER THAT NAMES A TEG WITH NO ADDRESS.
        # `PARTNER_TEG_URL` is inherited from the PARENT FRAME's env, so whatever the frame carries
        # is copied verbatim into every operator it provisions. Measured on the live cluster: EU and
        # ASIA carry PARTNER_TEG_ID=teg-layer-test / PARTNER_REGISTRY_ID=registry-test with an EMPTY
        # PARTNER_TEG_URL (Frame-A sandbox literals straight out of frame-test.env.tmpl), so every
        # cloud operator's TEG holds a partner entry for a TORN-DOWN sandbox node with no URL at all.
        # It is inert only because `resolve_partner_url` prefers the registry's `url_hint` and
        # self-heals — but a broken entry READS AS CONFIGURATION to the next person, and an empty
        # list does not. Ship it empty until the precondition exists (the R9/§FXSTRAND rule).
        if _partner_teg_url.strip():
            f.write(f'PARTNER_TEGS=[{{"teg_id":"{_partner_teg_id}","registry_id":"{_partner_reg_id}","url":"{_partner_teg_url}","api_key":"none"}}]\n')
        else:
            logger.warning(
                "[CLOUD-PROV] PARTNER_TEG_URL is empty (inherited from this frame's env) — writing "
                "PARTNER_TEGS=[] rather than a partner entry naming %s with no address. Cross-TEG "
                "resolution still works: the registry supplies an authoritative url_hint per call.",
                _partner_teg_id)
            f.write("PARTNER_TEGS=[]\n")

        # §pass66 (2026-05-22) — feature flags that paris's working env has but
        # fresh provisions were missing. Without these the cloud-op runs in a
        # "default off" mode that lacks canary fires (Mission Control empty)
        # and an explicit Astraeus disable (was already removed in §pass63 but
        # the env flag pin matters for reactor visibility).
        f.write(f"ASTRAEUS_ENABLED=false\n")
        # §BATCH5 (2026-09-05, D5): the canary flags FOLLOW THE PARENT — registry-a runs them (true, as before), a fresh
        # frame stood up with canaries OFF must not hand its operators a runner that fires real currency at nothing.
        for _ck in ("CANARY_ENABLED", "CANARY_RUNNER_ENABLED", "CANARY_JUDGE_ENABLED", "CANARY_VALIDATOR_ENABLED"):
            f.write(f"{_ck}={_parent_or(_ck, 'true')}\n")
        f.write(f"CANARY_RUNNER_INTERVAL_SEC=5\n")
        # §BATCH5: the operator INHERITS its parent's posture (each key only when the parent carries it). A child of a frame
        # that enforces the bond and propagates enforcement must do the same, or the parent's gates end at its own door.
        _inherited = _inherit_parent_posture(f)
        if _inherited:
            logger.info(f"[PROVISION] operator {safe}: inherited parent posture {_inherited}")
        # §FESUITE V0595: what the applicant chose (operator_applications.env_choices, mig 0186), written AFTER the
        # inherited posture so it wins (later lines win in a compose env_file)
        _chosen = _write_env_choices(f, getattr(application, "env_choices", None) or {})
        if _chosen:
            logger.info(f"[PROVISION] operator {safe}: applicant-chosen settings {_chosen}")

    # ── Step 2b: Update SPIRE svid-writer entry with domain DNS SAN ──
    # The activation step created entries with DNS SAN "nginx-federation" only.
    # Cloud operators also need the external domain for mTLS hostname verification.
    # SPIRE entry create fails on duplicate, so we find + update the svid-writer entry.
    if application.spire_fingerprint and _through_runner:
        # The one-shot does this one: it holds the socket, and doing it here would only log a failure for work that
        # is deliberately elsewhere. The SAN LIST itself is shared (core.operator_compose.svid_dns_sans), so both
        # paths give the SVID the same hostnames.
        logger.info(f"[CLOUD-PROV] SPIRE DNS SANs: the one-shot updates the svid-writer entry for {safe}")
    elif application.spire_fingerprint:
        try:
            # §pass66 (2026-05-22) — `_spire_container()` is a FUNCTION in
            # operator_provisioner (resolves env var → container name). The
            # prior `from .operator_provisioner import SPIRE_CONTAINER` was a
            # bug — that name doesn't exist as a module constant → ImportError
            # → silently caught by the except below → entry NEVER updated →
            # cert SAN missing the operator domain → cross-TEG mTLS hostname
            # mismatch on every fresh op (paris worked only because its
            # entry was manually fixed at some point — revision_number=2 vs
            # qatest13 revision_number=0).
            from .operator_provisioner import _spire_container as _resolve_spire_container
            import docker as _dk
            _client = _dk.from_env()
            _spire = _client.containers.get(_resolve_spire_container())
            svid_spiffe = f"spiffe://{TRUST_DOMAIN}/operator/{safe}/svid-writer"
            # Find existing entry ID
            _ec, _out = _spire.exec_run(
                ["/opt/spire/bin/spire-server", "entry", "show",
                 "-spiffeID", svid_spiffe],
                demux=True,
            )
            _stdout = (_out[0] or b"").decode()
            entry_id = None
            for line in _stdout.splitlines():
                if line.strip().startswith("Entry ID"):
                    entry_id = line.split(":")[-1].strip()
                    break
            if entry_id:
                parent_id = f"spiffe://{TRUST_DOMAIN}/spire/agent/x509pop/{application.spire_fingerprint}"
                # Build a DEDUPLICATED, order-preserving DNS SAN list. SPIRE enforces
                # UNIQUE(registered_entry_id, dns value) — emitting the same host twice
                # makes `entry update` fail (UNIQUE constraint) → the SVID never gets
                # its hostname SAN → cross-TEG mTLS hostname-mismatch on every fresh op.
                # This fires whenever CLOUD_DOMAIN_SUFFIX == PARTNER_DOMAIN_SUFFIX (e.g.
                # both 'op.theprotocol.cloud'), where `domain` and the partner alias
                # `{safe}.{PARTNER_DOMAIN_SUFFIX}` collapse to the SAME string.
                # 2026-06-05 §pass78c RCA: op-riyadh failed (exit 1, no SAN, revision 0)
                # vs op-telaviv (worked only because it was provisioned while the two
                # suffixes still differed — domain '.frame-c' vs partner '.op').
                #
                # 2026-06-02 — Dual-frame rationale (still applies): when the op is also
                # attached to a PARTNER identity network, the partner frame reaches it via
                # `{safe}.{PARTNER_DOMAIN_SUFFIX}`. The svid-writer SVID MUST be valid for
                # THAT hostname too, or cross-frame cross-TEG mTLS fails CERTIFICATE_VERIFY_
                # FAILED hostname-mismatch. Mirrors the network-alias logic so the SVID
                # SANs match the aliases the op is actually reachable by.
                # §MONEY-R48 (2026-09-04, found by agentvault2-07 running the cloud-op MCP
                # flows): `nginx-teg` was NEVER in this list. Every operator ships
                # `TEG_API_BASE_URL=https://nginx-teg:8443` and ONE svid-writer SVID serves
                # both sidecars, so the registry dialled nginx-teg with a cert valid only for
                # nginx-federation/<op>.op.theprotocol.cloud → CERTIFICATE_VERIFY_FAILED
                # "Hostname mismatch" → every treasury/balance/tokenomics call 500'd. Δ cannot
                # see it: no money moves, the rail is simply dead from birth. Production ops
                # carry `nginx-teg` only because someone hand-repaired their entries once
                # (op-berlin at revision 4); the provisioner was never fixed, so every NEW
                # operator was born broken — the 2+4 standup would have been.
                _dns_sans = svid_dns_sans(domain=domain, safe=safe,
                                          partner_identity_network=PARTNER_IDENTITY_NETWORK,
                                          partner_domain_suffix=PARTNER_DOMAIN_SUFFIX)
                _entry_cmd = [
                    "/opt/spire/bin/spire-server", "entry", "update",
                    "-entryID", entry_id,
                    "-spiffeID", svid_spiffe,
                    "-parentID", parent_id,
                    "-selector", "docker:label:com.agentvault.service:svid-writer-operator",
                    "-x509SVIDTTL", "14400",
                ]
                for _d in _dns_sans:
                    _entry_cmd += ["-dns", _d]
                # §MONEY-R49: `entry update` REPLACES the entry, so the federation the entry
                # already carries must be re-passed or it is silently dropped. Read from the
                # same `entry show` output the entry id came from — never assumed.
                _federates_with = _federates_with_from_entry_show(_stdout)
                for _td in _federates_with:
                    _entry_cmd += ["-federatesWith", _td]
                _ec2, _ = _spire.exec_run(_entry_cmd, demux=True)
                if _ec2 == 0:
                    logger.info(
                        f"[CLOUD-PROV] SPIRE svid-writer updated with DNS SANs: {_dns_sans} "
                        f"federatesWith preserved: {_federates_with or 'none'}"
                    )
                else:
                    logger.warning(f"[CLOUD-PROV] SPIRE entry update exit code: {_ec2}")
            else:
                logger.warning(f"[CLOUD-PROV] Could not find SPIRE entry for {svid_spiffe}")
        except Exception as e:
            logger.warning(f"[CLOUD-PROV] SPIRE DNS SAN update failed (non-fatal): {e}")

    # ── Step 3: Federation license ────────────────────────────────────
    from agentvault_registry.routers.federation_licenses import _generate_federation_license_key

    plain_key, key_hash, key_prefix = _generate_federation_license_key()
    op_display = application.name or f"Cloud {safe.title()}"

    # Store license in DB. §FRAMELIC (2026-09-07, findings row 139) — RE-PROVISIONING THE SAME
    # OPERATOR NAME MUST NOT DIE ON ITS OWN PREDECESSOR'S LICENCE. `operator_did` is UNIQUE, and
    # teardown deactivates the peer row and REVOKES the licence but never removes it — so the
    # second provision of `amsterdam` INSERTed a duplicate `did:theprotocol:cloud:amsterdam` and
    # took the whole provision down with a 500 mid-flight, after the SPIRE entry and the pull
    # token had already been written. Rotate the existing row in place instead: same identity,
    # new key, revocation lifted, and the operator's env gets the key it can actually present.
    # The frame path (`_issue_frame_license`) has always been idempotent by DID; this is the
    # operator half catching up.
    _op_did = _cloud_operator_did(application, safe)
    _existing_lic = (await db.execute(
        select(models.FederationLicense).where(
            models.FederationLicense.operator_did == _op_did
        )
    )).scalar_one_or_none()
    if _existing_lic is not None:
        logger.info(
            f"[CLOUD-PROV] licence for {_op_did} already exists (status={_existing_lic.status}) — "
            f"rotating it in place rather than inserting a duplicate"
        )
        _existing_lic.operator_name = op_display
        _existing_lic.license_key_hash = key_hash
        _existing_lic.license_key_prefix = key_prefix
        _existing_lic.status = "active"
        _existing_lic.revoked_at = None
        _existing_lic.revoked_reason = None
        # ⚠ AND THE PEER ROW THE TEARDOWN DEACTIVATED, for THIS operator and no other. A teardown marks the row
        # INACTIVE with reason "teardown" and nothing revived it, so a re-provisioned operator came up with its
        # parent still holding it inactive: federated with nobody, from the side that decides (measured on beacon
        # after jelgava's teardown, 2026-09-16). "Never auto-revived" is a rule about WORKERS — a background pass
        # must not resurrect what an admin took down — and this is the admin provisioning the same application
        # again, which is the intent the rule exists to protect. Keyed on the licence's own operator_did so it can
        # revive exactly the operator being provisioned and nothing else, and only from the teardown state.
        try:
            _peer_q = await db.execute(
                select(models.PeerRegistry).where(models.PeerRegistry.name == op_display))
            _peer_row = _peer_q.scalar_one_or_none()
            from agentvault_registry.crud.crud_peer_registry import update_peer_registry_status as _ups
            from agentvault_registry.services.operator_provision_client import peer_row_action as _pra
            _action, _revive_why = (_pra(_peer_row.status, _peer_row.deactivated_reason)
                                    if _peer_row is not None else ("", "no row"))
            if _action in ("revive", "clear_stale"):
                # ⚠ THROUGH THE ONE CHOKE POINT, not by setting three fields here. update_peer_registry_status is
                # the single writer that keeps status and its deactivation metadata together (RCA 2026-07-10), and
                # the row this had to fix was ACTIVE with the teardown fields still on it — proof that a rail
                # writing the status alone already exists and that a second one here would be the third.
                await _ups(db, _peer_row, "ACTIVE", reason="reprovisioned", emit=(_action == "revive"))
                logger.info(f"[CLOUD-PROV] peer row for {op_display}: {_action} "
                            f"(same application, same operator_did)")
            elif _revive_why and _revive_why != "nothing to do":
                logger.warning(f"[CLOUD-PROV] peer row for {op_display} left alone: {_revive_why}")
        except Exception as _e:  # noqa: BLE001 — reported, never fatal to a provision
            logger.error(f"[CLOUD-PROV] could not read the peer row for {op_display}: {_e}")
        _existing_lic.suspended_at = None
        _existing_lic.suspended_reason = None
        license_id = _existing_lic.id
    else:
        license_id = str(__import__('uuid').uuid4())
        db.add(models.FederationLicense(
            id=license_id,
            operator_name=op_display,
            operator_did=_op_did,
            license_key_hash=key_hash,
            license_key_prefix=key_prefix,
            status="active",
            max_agents=100,
            max_events_per_minute=1000,
            federation_tier="standard",
        ))
    await db.flush()
    # ⚠ COMMIT HERE, BEFORE THE LONG HOST WORK AND BEFORE THE OPERATOR IS HANDED THIS KEY. Measured on sbx-beta
    # 2026-09-27 (wp62opb): the provision held this transaction idle through compose up and the health wait, the
    # registry's own idle_txn_reaper (IDLE_TXN_REAPER_IDLE_SEC, 120 s) terminated it at 01:45:09Z, and the route
    # answered 500 AFTER the operator had come up: the licence row, the bundle fields and the route's own writes
    # (cloud_hosted, the peer row) were rolled back, while the operator's env already held the plain key whose hash
    # the parent never kept. Committing here makes the licence durable before its key leaves this function and ends
    # the transaction before any wait; every later statement opens a fresh one. Safe to repeat: the licence step
    # rotates an existing row for this operator_did, and expire_on_commit=False keeps `application` usable.
    await db.commit()

    with _EnvSink(None if _through_runner else env_path) as f2:
        f2.write(f"FEDERATION_LICENSE_KEY={plain_key}\n")

    logger.info(f"[CLOUD-PROV] License generated: {key_prefix}...")

    # Sync the license to the central EventStore's federation_operators table
    # at provisioning time so the row carries the REAL license_key_hash from
    # day one. Without this, the row gets created later by federation_sync's
    # trust path (with `peer-{id}` placeholder until the 2026-04-27 fix), and
    # the operator can't license-auth against ES on the HTTP path. mTLS-only
    # operators (production) don't notice; HTTP operators (sandbox) break.
    # Best-effort — failure here doesn't block provisioning. The operator can
    # still emit via mTLS once SPIRE bundles are exchanged.
    try:
        from agentvault_registry.routers.federation_licenses import _sync_license_to_eventstore
        # §pass78c — register BOTH the /registry SVID and the /svid-writer SVID. The
        # TEG balance OUTBOX emits as .../operator/{safe}/svid-writer (NOT .../registry),
        # so a /registry-only row never matches the emitter on the ES mTLS path → the
        # parent ES 403s every cloud-op balance event ("Unknown SPIFFE ID … register as
        # a federation operator first") until the outbox falls back to auto-trust.
        _synced = []
        for _svid_role in ("registry", "svid-writer"):
            spiffe_id = f"spiffe://{TRUST_DOMAIN}/operator/{safe}/{_svid_role}"
            if await _sync_license_to_eventstore(
                license_id=license_id,
                operator_name=op_display,
                license_key_hash=key_hash,
                op_status="active",
                max_events_per_minute=1000,
                spiffe_id=spiffe_id,
            ):
                _synced.append(_svid_role)
        # §TESTBED: say what landed; the line used to claim both whatever the store answered
        if len(_synced) == 2:
            logger.info(f"[CLOUD-PROV] License synced to EventStore: {op_display} (registry + svid-writer SVIDs)")
        else:
            logger.warning(f"[CLOUD-PROV] License NOT fully synced to EventStore for {op_display}: "
                           f"landed {_synced or 'none'} of registry + svid-writer (the [FedLicense] line says why)")
    except Exception as e:
        logger.warning(f"[CLOUD-PROV] EventStore license sync failed (non-fatal): {e}")

    # ── The runner route: everything below this line needs the host, and this frame does not have it ──────────
    # The registry has now done all of ITS work — the ports, every env VALUE, the licence row and its EventStore
    # sync — and what remains is host work: files, the SPIRE entry, the compose edits and `up`. On a runner-built
    # frame that goes to the one-shot in ONE job, and this function returns its facts. EU and ASIA fall through to
    # the path they have always taken, unchanged.
    if _through_runner:
        from agentvault_registry.core.frame_slug import frame_slug
        from agentvault_registry.services import operator_provision_client as opc

        _frame = frame_slug()
        if not _frame:
            raise HostStepsNotWired("this frame cannot name itself to the runner (no TEG_LAYER_URL and no "
                                    "REGISTRY_NAME), so the host work cannot be asked for. Nothing was brought up.")
        _env_pairs = dict(f.as_pairs())
        _env_pairs.update(f2.as_pairs())
        _spec = opc.build_operator_spec(
            operator_name=op_display, safe_name=safe, operator_did=f"did:theprotocol:operator:{safe}",
            frame=_frame, docker_pull_token=("" if _images_local else (docker_pull_token or "")),
            operator_secrets=op_secrets, local_images=_images_local,
            phase="stack", env=_env_pairs, stack_dir=stack_dir_host,
            application_id=str(getattr(application, "id", "") or ""),
        )
        if _edge_mode != "caddy":
            _spec.update({
                # The edge, rendered HERE because this side holds the one definition of it and every value; the
                # runner holds the /etc/nginx this frame's registry deliberately does not have, and does the
                # privileged write. Both are also passed as plain values below (spec.edge), so the far side can
                # render and compare rather than trust. Under a frame's own Caddy edge (§HELLOFRAME lane 6) there is
                # no host vhost and no SNI line to write: the runner renders the operator's site from spec.edge.
                "host_vhost": operator_vhost(domain=domain, reg_port=reg_port, ssl_cert_name=SSL_CERT_NAME,
                                             ws_events_host=_frame_ws_events_host()),
                "sni_entry": sni_map_entry(domain=domain, fed_port=fed_port),
                # §PUSH: the push relay's public, subscribe-only door. host_work hands it back only with the relay it
                # fronts (a frame whose templates carry no push override writes neither half).
                "push_vhost": operator_push_vhost(push_host=operator_push_host(domain),
                                                  push_port=operator_push_port(reg_port), ssl_cert_name=SSL_CERT_NAME),
            })
        if not _images_local:
            # the pull identity, only where there is something to pull (a local tag namespace has none)
            _spec["docker_username"] = docker_username or f"operator-{safe}"
        _spec.update({
            "edge": {"domain": domain, "reg_port": reg_port, "fed_port": fed_port,
                     "ssl_cert_name": SSL_CERT_NAME, "ws_events_host": _frame_ws_events_host(),
                     # §PUSH: what the push vhost may serve and where it may send traffic (the runner checks both)
                     "push_host": operator_push_host(domain), "push_port": operator_push_port(reg_port),
                     # §HELLOFRAME lane 6: the posture the runner applies, and the host address the operator's
                     # registry and TEG ports bind under it (empty = every interface, the network's own host)
                     "mode": _edge_mode, "bind_address": _bind_address},
            "bundle_filename": os.path.basename(bundle_path),
            "spire_fingerprint": application.spire_fingerprint or "",
            "spire_container": os.getenv("SPIRE_CONTAINER", ""),
            "spire_trust_domain": TRUST_DOMAIN,
            "compose": {
                "domain": domain, "reg_port": reg_port, "fed_port": fed_port, "teg_port": teg_port,
                "worker_count": worker_count, "identity_network": IDENTITY_NETWORK,
                "partner_identity_network": PARTNER_IDENTITY_NETWORK,
                "partner_domain_suffix": PARTNER_DOMAIN_SUFFIX,
                "spire_addr": os.getenv("SPIRE_SERVER_ADDRESS", ""),
                "spire_trust_domain": os.getenv("SPIRE_TRUST_DOMAIN", ""),
                "es_url": _frame_public_es_url(),
                "bind_address": _bind_address,
            },
            "identity_stamps": {
                "display_name": safe, "federation_name": safe,
                # §LOCTRUTH: only a DECLARED location is stamped onto the developer row, because that row's
                # coordinates are what federation_sync publishes onto every exported agent card.
                "location_is_declared": bool(location_is_declared),
                "latitude": latitude, "longitude": longitude, "location_label": location_label,
            },
            "parent_peer": {
                "name": BILATERAL_PEER_NAME, "base_url": REGISTRY_A_PUBLIC_URL,
                "admin_contact_email": "commander@theprotocol.cloud", "trust_domain": TRUST_DOMAIN,
            },
        })
        _result = await opc.provision_through_runner(frame=_frame, spec=_spec)
        for _note in (_result.get("notes") or []):
            logger.info(f"[CLOUD-PROV] runner: {_note}")
        logger.info(f"[CLOUD-PROV] the one-shot finished: {_result.get('container_count')} containers, "
                    f"registry healthy={_result.get('registry_healthy')}, "
                    f"parent peer={_result.get('parent_peer_registered')}")
        return CloudProvisionResult(
            cloud_url=f"https://{domain}",
            cloud_port_base=port_base,
            cloud_stack_dir=_result.get("stack_dir") or stack_dir_host,
            registry_port=reg_port,
            federation_port=fed_port,
            # The same convention the socket path uses: 9 when the registry came healthy, -1 when it did not.
            containers_started=9 if _result.get("registry_healthy") else -1,
            federation_license_key=plain_key,
            admin_email=f"admin@cloud-op-{safe}.dev",
            admin_password=_result.get("admin_password") or "",
        )

    # ── Step 4: Adapt docker-compose ──────────────────────────────────
    # Every edit lives in adapt_operator_compose() now, with no hidden inputs, because the one-shot that provisions an
    # operator on a runner-built frame must make the SAME edits from a different container (§OPDIST). Two copies of
    # "what a provisioned operator's compose looks like" is how two frames stop being the same product.
    compose_path = f"{stack_dir_container}/docker-compose.operator.yml"
    with open(compose_path) as f:
        compose = f.read()

    _es_url = _frame_public_es_url()  # §pass78c frame-aware (no events-b clone-bug)
    _spire_addr = os.getenv("SPIRE_SERVER_ADDRESS", "")
    if _spire_addr == "host.docker.internal":
        _trust_domain = os.getenv("SPIRE_TRUST_DOMAIN", "")
        if _trust_domain == "sandbox-b.test":
            _canonical_sandbox_es = "https://nginx-test-b:30943"
        elif _trust_domain == "sandbox-c.test":
            _canonical_sandbox_es = "https://nginx-test-c:8443"
        else:
            _canonical_sandbox_es = "https://nginx-test-a:30843"
        if ("event-store-test:8200" in _es_url or "event-store-test-b:8200" in _es_url
                or "event-store-test-c:8200" in _es_url):
            logger.info(
                f"[CLOUD-PROV] Sandbox mode (trust_domain={_trust_domain!r}) — "
                f"rewriting EVENT_STORE_URL '{_es_url}' → '{_canonical_sandbox_es}'"
            )
            _es_url = _canonical_sandbox_es

    compose, _adapt_notes = adapt_operator_compose(
        compose, safe=safe, domain=domain, reg_port=reg_port, fed_port=fed_port, teg_port=teg_port,
        bind_address=_bind_address,
        worker_count=worker_count, identity_network=IDENTITY_NETWORK,
        partner_identity_network=PARTNER_IDENTITY_NETWORK, partner_domain_suffix=PARTNER_DOMAIN_SUFFIX,
        spire_addr=_spire_addr, spire_trust_domain=os.getenv("SPIRE_TRUST_DOMAIN", ""), es_url=_es_url,
    )
    for _note in _adapt_notes:
        logger.info(f"[CLOUD-PROV] compose: {_note}")

    with open(compose_path, 'w') as f:
        f.write(compose)

    logger.info(f"[CLOUD-PROV] Compose adapted: ports {reg_port}/{fed_port}")

    # §pass66 (2026-05-22) — Bug B defensive verification. The string-based
    # `compose.replace(...)` patches above are silently no-op when a literal
    # search string changes (e.g., template renamed a service, indentation
    # drifted, escape sequence subtly differs). On §pass65 op-qatest6 this
    # produced a compose with port-replace applied but workers + nginx-fed
    # network + legacy-cmd patches all SILENTLY missed → operator booted
    # on 4 workers with stale schema. Now we re-read and assert each required
    # transformation. Fail-fast > fail-silent.
    #
    # NOTE: the template was hardened in §pass66 to ship `migration_bridge +
    # workers 8` natively, so for newly-built bundles the assertions for those
    # two are tautological. Kept anyway so OLD cached bundles don't slip
    # through silently — verification is now the single point of truth for
    # "compose is correctly customized for this operator".
    with open(compose_path) as _f:
        _written = _f.read()
    _required = {
        f"registry port {reg_port}:8000": port_line(_bind_address, reg_port, 8000) in _written,
        f"federation port {fed_port}:8443": f'"{fed_port}:8443"' in _written,
        "no leftover 12000 port": '"12000:8000"' not in _written and '"127.0.0.1:12000:8000"' not in _written,
        "no leftover 12443 port": '"12443:8443"' not in _written,
        "migration_bridge (not stamp heads)": (
            "agentvault_registry.migration_bridge" in _written
            and "Base.metadata.create_all" not in _written
        ),
        # §2026-06-14 — supervisor-agnostic worker-count check. The bundle template
        # migrated uvicorn→GUNICORN (V0041/V0049: `gunicorn … --workers 8 -c
        # /app/gunicorn_conf.py`, NO `--proxy-headers`). The old uvicorn-only string
        # match (`--workers 8 --proxy-headers`) therefore failed EVERY provision on
        # the current image. Match the worker count itself, supervisor-agnostic.
        # §2026-06-14 — verify the adaptation set the INTENDED worker count
        # (prod=8 or lite=2), supervisor-agnostic. The old uvicorn-only string
        # match (`--workers 8 --proxy-headers`) failed every provision after the
        # gunicorn migration (`--workers N -c /app/gunicorn_conf.py`).
        f"registry/teg worker count = {max(2, int(worker_count))}": (
            f"--workers {max(2, int(worker_count))}" in _written
        ),
        f"identity network ({IDENTITY_NETWORK}) attached": (
            f"{IDENTITY_NETWORK}:" in _written
        ),
        # §pass66 (2026-05-22) — additional structural checks added after
        # qatest8/10 ended up with `EVENT_STORE_URL: http://event-store:8200`
        # (DNS-unresolvable on cloud-op stacks → Mission Control empty), wrong
        # PARTNER_TEGS port, and missing performance envs.
        # §pass73.3 (2026-05-27) — broadened to accept ANY non-docker-internal
        # ES URL. Sandbox mode rewrites to `https://nginx-test-a:30843`
        # (line ~629 above), which was failing the strict prod-URL-only check.
        # The original protection was against `http://event-store:8200`
        # leaking through — that's what we still reject.
        # §pass78c — frame-aware: assert the compose carries the EXACT frame-aware
        # ES URL we computed (_frame_public_es_url → events / events-b / events-c /
        # sandbox nginx-test-*), never the docker-internal one. The old hardcoded
        # allowlist silently rejected events-c (frame-c) → misleading "ES URL not
        # docker-internal" 500 on every frame-c op provision.
        "ES URL is the frame-aware public endpoint (no http://event-store:8200)": (
            "EVENT_STORE_URL: http://event-store:8200" not in _written
            and f"EVENT_STORE_URL: {_es_url}" in _written
        ),
        "TEG_BULK_PROXY enabled (perf envs)": "TEG_BULK_PROXY:" in _written,
        "REACTOR_HANDLER_CONCURRENCY set": "REACTOR_HANDLER_CONCURRENCY:" in _written,
        "bundle-storage volume mount": "./bundle-storage:/app/bundle-storage" in _written,
    }
    _missing = [name for name, ok in _required.items() if not ok]
    if _missing:
        # Caller's try/except will catch + log + return 500. Application row
        # stays in DB so admin can investigate + manually finish via the
        # legacy admin path. Better than silent partial provision.
        logger.error(
            f"[CLOUD-PROV] Compose verification FAILED for {safe}. "
            f"Missing transformations: {_missing}. "
            f"Compose preview (first 400 chars): {_written[:400]!r}"
        )
        raise RuntimeError(
            f"Compose adapt verification failed for operator {safe}: {_missing}. "
            f"See [CLOUD-PROV] error log for the as-written compose preview."
        )
    logger.info(
        f"[CLOUD-PROV] Compose verification PASSED for {safe} "
        f"({len(_required)} transformations confirmed)"
    )

    # ── Step 5: Adapt nginx-federation.conf ───────────────────────────
    # The edits live in core/operator_compose.adapt_federation_conf so the one-shot makes the same ones.
    nginx_path = f"{stack_dir_container}/nginx/nginx-federation.conf"
    if os.path.exists(nginx_path):
        with open(nginx_path) as f:
            nginx = f.read()
        nginx, _nginx_notes = adapt_federation_conf(nginx, safe=safe, domain=domain)
        with open(nginx_path, 'w') as f:
            f.write(nginx)
        for _note in _nginx_notes:
            logger.info(f"[CLOUD-PROV] {_note}")

    # ── Step 5b: render this operator's markers and its Redis ACL ──────
    # After Step 5, so the last writer of nginx-federation.conf is the one that also PROVES no placeholder survived.
    # It raises rather than provisioning an operator whose terminators forward certificates its apps refuse.
    operator_provisioner.apply_operator_secrets(stack_dir_container, op_secrets, safe)
    # ⚠ AND THE ACL MUST BELONG TO REDIS BEFORE `up`, OR THE OPERATOR NEVER STARTS. write_redis_acl writes it 0600 as
    # this process (uid 1000) and can only WARN when its chown to 999 is refused, which it always is here; Redis then
    # exits at startup, `up` waits on its health forever, and the operator reconciles to 0/9 (measured on sbx-beta
    # 2026-09-27, wp62opb). The one-shot has always fixed this through the socket (host_work._fix_redis_acl_owner);
    # this route now does the same, with the bind source on the HOST path, and refuses before anything starts.
    from agentvault_registry import host_work as _hw
    _acl_notes: List[str] = []
    _acl = _hw._fix_redis_acl_owner(f"{stack_dir_container}/redis-users.acl", _acl_notes, host_dir=stack_dir_host)
    for _note in _acl_notes:
        logger.info(f"[CLOUD-PROV] {safe}: {_note}")
    if _acl.get("redis_acl_chown_needed"):
        raise RuntimeError(
            f"the operator's Redis ACL is owned by uid {_acl.get('redis_acl_uid')}, not the redis uid (999), and the "
            f"chown through the Docker socket failed, so its Redis could not start; nothing was started")

    # ── Step 6: Create host nginx vhost (HTTPS with wildcard cert) ──
    # Sandbox-aware (2026-04-22): SKIP_NGINX_VHOST=true skips this step entirely
    # for sandbox test provisioning where no external HTTPS is needed
    # (internal /health verification is sufficient for the lifecycle test).
    if os.getenv("SKIP_NGINX_VHOST", "false").lower() == "true":
        logger.info(f"[CLOUD-PROV] SKIP_NGINX_VHOST=true — skipping nginx vhost creation for {safe}")
    else:
        vhost = operator_vhost(domain=domain, reg_port=reg_port, ssl_cert_name=SSL_CERT_NAME,
                               ws_events_host=_frame_ws_events_host())
        vhost_path = f"{HOST_NGINX_MOUNT}/cloud-op-{safe}"
        with open(vhost_path, 'w') as f:
            f.write(vhost)

        # _run OK: already inside `else` of SKIP_NGINX_VHOST guard (L386), so
        # sandbox never reaches here. In prod the registry image DOES have
        # `docker` available on $PATH via /var/run/docker.sock passthrough
        # (the `alpine nsenter` container runs on host PID namespace to exec
        # nginx reload). Do NOT convert to docker-py SDK — the nsenter
        # privileged + host-PID combo is the whole point.
        _run(
            'docker run --rm --network=host --pid=host --privileged '
            'alpine nsenter -t 1 -m -u -n -i sh -c "nginx -t && nginx -s reload"',
            timeout=15
        )
        logger.info(f"[CLOUD-PROV] nginx HTTPS vhost created: {domain} → localhost:{reg_port}")

        # ── T2.1 (2026-05-23) — Extend nginx stream-SNI map ─────────────
        # Map the new cloud-op's canonical hostname → its nginx-federation
        # sidecar host port. Without this entry, cross-cloud-op federation
        # calls (which arrive at host stream:8443 from outside the identity
        # network) fall through to the default route and hit Frame A's
        # nginx-a sidecar instead of the intended peer's. nginx-a's SVID
        # has DNS SAN nginx-a/api.theprotocol.cloud/registry.theprotocol.cloud —
        # NOT op-X.* — so the caller's TLS verify would fail on subject
        # mismatch. This insert plus the per-op sidecar's existing DNS SAN
        # (set by Step 2b above) closes the routing gap. Helper script lives
        # at /host-stack/Agentvault2/scripts/extend_stream_sni_map.sh (idempotent).
        try:
            _run(
                'docker run --rm --network=host --pid=host --privileged '
                'alpine nsenter -t 1 -m -u -n -i '
                f'/opt/theprotocol/stack/Agentvault2/scripts/extend_stream_sni_map.sh '
                f'{domain} {fed_port}',
                timeout=15
            )
            logger.info(
                f"[CLOUD-PROV] nginx stream SNI map updated: "
                f"{domain} → 127.0.0.1:{fed_port}"
            )
        except Exception as e:
            # Non-fatal: the provisioned op still works for direct
            # internal-network callers (Frame A registry-a, mainframe TEGs).
            # Only cross-cloud-op direct calls from outside the identity
            # network would degrade — and those route via TEG hub today
            # anyway. Surface as warning so operators can fix manually
            # via `bash scripts/extend_stream_sni_map.sh <domain> <fed_port>`.
            logger.warning(
                f"[CLOUD-PROV] stream SNI map update failed (non-fatal): {e}. "
                f"Manual fix: bash scripts/extend_stream_sni_map.sh "
                f"{domain} {fed_port}"
            )

    # ── Step 6.5: Write per-stack docker config for image-registry auth ─
    # §pass65 (2026-05-22) — the docker:cli sidecar that runs `compose up`
    # below uses the HOST daemon (via /var/run/docker.sock) but its DOCKER
    # CLIENT looks for auth in its OWN ~/.docker/config.json, which is empty
    # in a freshly-spawned container. The host's auth config is NOT auto-
    # inherited. Without this step, `docker compose pull` against
    # images.theprotocol.cloud/<image>:tag returns 401 "Missing or invalid
    # Authorization header" and the entire stack fails to start.
    #
    # Fix: write the operator's OWN dpt_ pull token to a per-stack
    # docker config.json (using Docker's standard "auth" base64 blob), then
    # point the sidecar at it via DOCKER_CONFIG. The operator's token is
    # validated by /api/v1/docker-registry/token (Basic auth) and minted as
    # a JWT for the registry to consume per the Docker Distribution v2
    # token-auth flow. Per-stack scope means revocation = rm -rf the stack.
    #
    # If the caller didn't supply credentials (legacy callers haven't been
    # updated yet), skip the auth-config step and let the original code path
    # try its luck — this preserves backward compat for any admin-driven
    # path that's already established auth via another route.
    if docker_pull_token and docker_username:
        _docker_cfg_dir_container = f"{stack_dir_container}/.docker"
        os.makedirs(_docker_cfg_dir_container, exist_ok=True)
        _docker_cfg_path = f"{_docker_cfg_dir_container}/config.json"
        with open(_docker_cfg_path, "w") as _f:
            _f.write(docker_auth_config(username=docker_username, token=docker_pull_token))
        try:
            os.chmod(_docker_cfg_path, 0o600)
        except Exception:
            pass
        logger.info(
            f"[CLOUD-PROV] Per-stack docker config written: "
            f"{_docker_cfg_path} (user={docker_username})"
        )
    else:
        logger.warning(
            "[CLOUD-PROV] No docker_pull_token/docker_username supplied — "
            "compose pull will likely 401 against images.theprotocol.cloud"
        )

    # ── Step 7: Docker compose up ───────────────────────────────────
    # The registry container has Docker socket but no docker CLI binary.
    # Use the Docker Python SDK to run a docker:cli container that executes
    # docker compose from the host path context.
    #
    # §pass65 — DOCKER_CONFIG points at the per-stack .docker dir we wrote
    # above so `docker pull` finds the operator's image-registry credentials.
    # The dir lives at <stack>/.docker on the HOST and is mounted into the
    # sidecar at the same path, so the env var works either way.
    import docker as docker_sdk
    _compose_cmd = (
        f"sh -c 'export DOCKER_CONFIG={stack_dir_host}/.docker && "
        f"docker compose -f docker-compose.operator.yml --env-file .env.operator up -d'"
    )

    # §2026-06-14 — EVENT-LOOP SAFETY. This function is `async def`; the SDK
    # `containers.run(detach=False)` and the nsenter `_run()` BLOCK until the
    # sidecar exits. Run them via `asyncio.to_thread` so the ASGI event loop
    # keeps yielding — otherwise the Uvicorn worker stalls, misses gunicorn's
    # 60s arbiter heartbeat, and is SIGKILLed mid-provision (dropped connection,
    # empty response, abandoned bring-up → registry/nginx stuck in `Created`).
    def _compose_up_blocking() -> None:
        """Single idempotent `up -d` pass (blocking; called via to_thread)."""
        try:
            dk = docker_sdk.from_env()
            dk.containers.run(
                "docker:cli",
                command=_compose_cmd,
                volumes={
                    "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
                    stack_dir_host: {"bind": stack_dir_host, "mode": "rw"},
                },
                working_dir=stack_dir_host,
                remove=True,
                detach=False,
            )
            logger.info(f"[CLOUD-PROV] Docker compose up completed")
        except Exception as e:
            logger.error(f"[CLOUD-PROV] Docker compose up failed: {e}")
            # _run OK: safety-net fallback only fires when the primary docker-py
            # SDK path fails. Same `alpine nsenter` pattern as the nginx reload —
            # converting to SDK would lose the host-PID context needed to run
            # `docker compose` from the host's working directory.
            # §pass65 — fallback also gets DOCKER_CONFIG so it doesn't 401.
            _run(
                "docker run --rm --pid=host --privileged "
                "-v /var/run/docker.sock:/var/run/docker.sock "
                f"-v {stack_dir_host}:{stack_dir_host} "
                "alpine nsenter -t 1 -m -u -n -i sh -c "
                f"'cd {stack_dir_host} && DOCKER_CONFIG={stack_dir_host}/.docker docker compose -f docker-compose.operator.yml "
                f"--env-file .env.operator up -d'",
                timeout=120
            )

    await asyncio.to_thread(_compose_up_blocking)

    # §2026-06-14 — RECONCILE PASS. Under host load, the first `up -d` can abort
    # on a transient-unhealthy dependency (compose creates every container up
    # front, then starts in dependency order, aborting the dependents whose
    # `depends_on: service_healthy` gate fired "unhealthy" during the start
    # window) → registry + nginx-federation left in `Created`. A 2nd idempotent
    # `up -d` a few seconds later — deps now healthy — STARTS the stragglers;
    # it's a no-op when everything is already running. Deterministic cure that
    # replaces the previous "manual docker start" recovery.
    await asyncio.sleep(8)
    await asyncio.to_thread(_compose_up_blocking)

    # §2026-06-14 — extra reconcile passes for moderate load. Each pass is a real
    # `docker compose up -d` (NOT `docker start`): compose attaches networks +
    # respects dep-health, so retries converge as the dependency healthchecks
    # stabilize. We do NOT `docker start` individual stragglers — under heavy load
    # compose can leave a container `Created` WITHOUT its network attached, and a
    # bare `docker start` would bring it up network-less (DNS-dead, crash-loop on
    # `pgbouncer`); only a compose recreate fixes that. So: count running op
    # containers, and while short of 9, re-run `up -d` with backoff. Under extreme
    # host load (≳45, e.g. provisioning during a fleet recreate) a straggler may
    # still need a manual `docker compose up -d --force-recreate <svc>` — logged.
    def _count_running() -> Optional[int]:
        census, _why = _operator_container_census(safe, docker_sdk.from_env)
        return None if census is None else census.get("running", 0)
    for _backoff in (12, 18):
        _n = await asyncio.to_thread(_count_running)
        if _n is not None and _n >= 9:
            break
        await asyncio.sleep(_backoff)
        await asyncio.to_thread(_compose_up_blocking)
    _census, _census_why = await asyncio.to_thread(_operator_container_census, safe, docker_sdk.from_env)
    try:
        _load1 = os.getloadavg()[0]
    except OSError:
        _load1 = None
    _shortfall = _reconcile_shortfall_line(safe, _census, _census_why, 9, _load1)
    if _shortfall:
        logger.warning(_shortfall)

    # Wait for healthy — uses docker-py SDK since registry image has no docker CLI.
    # Patched 2026-04-22 after sandbox provisioner lifecycle test revealed the
    # subprocess `docker ps` pattern was silently failing. SDK read of
    # Health.Status is the portable equivalent.
    containers_started = 0
    try:
        import docker as _dk_health
        _hc_client = _dk_health.from_env()
    except Exception as _e:
        _hc_client = None
        logger.warning(f"[CLOUD-PROV] Health-check docker SDK init failed: {_e}")
    # 2026-04-22: bumped 18→36 iterations (90s→180s) after the sandbox
    # lifecycle test started failing intermittently once additional sandbox
    # containers (sample-workloads + provisioner stacks) were added to the
    # Docker daemon's workload. 9-container operator startup can exceed 90s
    # under load when pgbouncer + DB + migrations all race on disk IO.
    # 2026-04-22 Pass 2: further bumped 36→48 iterations (180s→240s). With
    # Pass 2's additional sandbox containers (sandbox sample-workloads +
    # synthetic frame-invitation fixtures) the host Docker daemon can take
    # 200s+ to finish starting all 9 operator containers under disk pressure.
    # Test body's default timeout_seconds=240 matches; if Commander wants faster
    # lifecycle runs, reduce daemon load (stop sample-workloads) instead.
    # 2026-04-22 Pass 3 (PC3): bumped 48→72 (240s→360s) because Pass 2's dual
    # lifecycle runs both hit the 240s cap under host load=140+ (sustained
    # sandbox rebuilds). Root cause is host contention, not code defect —
    # containers do eventually come healthy, just past the previous window.
    # 360s is a generous ceiling; normal idle-host runs finish in ~75-100s.
    _hc_iterations = 72
    for i in range(_hc_iterations):
        # §2026-06-14 — `await asyncio.sleep` (was blocking `time.sleep`): this
        # 360s ceiling on the event loop is what tripped gunicorn's 60s arbiter
        # timeout and got the worker SIGKILLed mid-provision. Yielding here keeps
        # the worker heartbeating so the request survives to completion.
        await asyncio.sleep(5)
        try:
            if _hc_client is None:
                break
            _c = _hc_client.containers.get(f"cloud-op-{safe}-registry")
            _health = _c.attrs.get("State", {}).get("Health", {}).get("Status", "")
            if _health == "healthy":
                containers_started = 9
                logger.info(f"[CLOUD-PROV] Registry healthy after {(i+1)*5}s")
                break
        except Exception as _e:
            # Container may not yet exist (docker compose up still finishing) — retry
            logger.debug(f"[CLOUD-PROV] Health poll {i+1}/{_hc_iterations}: {_e}")
    else:
        logger.warning(f"[CLOUD-PROV] Registry not healthy after {_hc_iterations*5}s, continuing")
        containers_started = -1

    # BL-1 (2026-05-11): REMOVED — Phase 12.3 attached the operator's REGISTRY container
    # to IDENTITY_NETWORK to give the reactor framework reachability to the central
    # EventStore. That attach VIOLATED Commander's rule (verified live: canonical
    # sandboxalpha/beta/gamma + op-london have registry ONLY on operator-net) and
    # caused alias collision / round-robin per `feedback_canary_url_internal_dns.md`.
    #
    # The correct mechanism: registry reaches EventStore via the operator's nginx-federation
    # sidecar (mTLS-routed) OR via extra_hosts (sandbox-mode nginx-test-a:host-gateway,
    # which DNATs through host port 30843 → sandbox-A nginx → EventStore). Both
    # patterns keep registry off the shared identity network.
    #
    # TEG stays on operator-net only — cross-TEG calls already route via mTLS through
    # nginx-federation. Adding TEG to identity network causes DNS-alias collision
    # (all operators would register the same `teg-layer` alias).

    # ── Step 8: Capture first-boot admin credentials ─────────────────
    # §pass65 (2026-05-22) — the FIRST-BOOT banner is emitted by operator_seed
    # very early in container boot (before the registry's main.py event-loop
    # finishes spinning up workers). By the time wait-for-healthy returns at
    # step 7, the registry has produced thousands of log lines and the
    # banner can be well past the previous tail=200 cap → admin_password
    # came back as empty string in the provision response. Bumped tail=200
    # to tail=5000 to cover the worst-case boot sequence width.
    admin_email = f"admin@cloud-op-{safe}.dev"
    admin_password = ""
    try:
        import docker as _dk_logs
        _dk_client = _dk_logs.from_env()
        _reg_container = _dk_client.containers.get(f"cloud-op-{safe}-registry")
        _logs = _reg_container.logs(tail=5000).decode(errors="replace")
        match = re.search(r'FIRST-BOOT ADMIN PASSWORD:\s*(\S+)', _logs)
        if match:
            admin_password = match.group(1)
            logger.info(f"[CLOUD-PROV] Admin credentials captured: {admin_email}")
        else:
            logger.warning("[CLOUD-PROV] Could not parse first-boot password from logs")
    except Exception as e:
        logger.warning(f"[CLOUD-PROV] Credential capture failed: {e}")

    # Note: Forward peer registration (operator as peer on Registry A) + sync trigger
    # done by the router (needs DB session context which the service doesn't have).

    # Reverse peer: register Registry-A as a peer on the OPERATOR's DB (bilateral federation)
    # Uses Docker SDK to exec psql on the operator's DB container (shell docker not available).
    try:
        import docker as _dk_peer
        _dk_client = _dk_peer.from_env()
        _db_container = _dk_client.containers.get(f"cloud-op-{safe}-db")
        # §pass73.3.5 — include approved_at + approved_by_developer_id so the
        # bilateral peer row ships in fully-approved terminal state. The parent-
        # provisioned cloud-op IS trusted by definition (the mainframe spawned
        # it), so requiring a downstream manual approval step is ceremony, not
        # a security boundary. Without these fields, the row reaches ACTIVE but
        # approved_at stays NULL, which causes asymmetry — e.g. §pass73.3 where
        # sandboxalpha got manually approved post-provision (status stayed ACTIVE)
        # but sandboxdelta did not (status drifted to INACTIVE silently).
        # The ON CONFLICT clause uses COALESCE so a row that was already
        # approved by an admin retains its original approval audit trail.
        _sql = (
            "INSERT INTO peer_registries (name, base_url, status, owner_developer_id, "
            "admin_contact_email, registered_at, approved_at, approved_by_developer_id, "
            "discovery_auth_info, health_check_failure_count, total_interactions, "
            "disputes_lost_with, bayesian_discount, trust_domain, peer_type) "
            f"VALUES ('{BILATERAL_PEER_NAME}', '{REGISTRY_A_PUBLIC_URL}', 'ACTIVE', 1, "
            f"'commander@theprotocol.cloud', NOW(), NOW(), 1, '{{}}'::jsonb, 0, 0, 0, 1.0, '{TRUST_DOMAIN}', 'frame') "
            f"ON CONFLICT (name) DO UPDATE SET base_url = '{REGISTRY_A_PUBLIC_URL}', "
            "status = 'ACTIVE', "
            # §BATCH5 — the parent IS a frame by construction. Without the column the row
            # landed on the default ('direct_peer'); the startup reclassify pass (main.py,
            # "cloud-op: legit parent frame") only runs at boot, and this row is written
            # ~20 s AFTER the operator booted, so it stayed 'direct_peer' until the next
            # restart (measured on the JUICE pair, 2026-09-05). Write the type at creation.
            "peer_type = 'frame', "
            # §2026-06-01 — seed the parent's trust_domain so cross-frame transfer
            # target_frame resolution (teg_integration.py) doesn't fall back to BFS.
            # Empty trust_domain here was the root cause of sb-alpha→parent :async
            # CrossFrameTransferRefunded (timeout_5min_no_settled_event): the leg
            # locked at the wrong target frame so no settle ever arrived. Prod
            # populates this via RegistryCardFanout from the parent's full fleet;
            # sandbox children never did. COALESCE keeps an admin-set value.
            "trust_domain = COALESCE(peer_registries.trust_domain, EXCLUDED.trust_domain), "
            "approved_at = COALESCE(peer_registries.approved_at, NOW()), "
            "approved_by_developer_id = COALESCE(peer_registries.approved_by_developer_id, 1);"
        )
        _ec, _out = _db_container.exec_run(
            ["psql", "-U", "registry", "-d", "agentvault_registry", "-c", _sql],
            demux=True,
        )
        if _ec == 0:
            logger.info(f"[CLOUD-PROV] Bilateral peer registered: Registry-A → {REGISTRY_A_PUBLIC_URL}")
        else:
            _stderr = (_out[1] or b"").decode()
            logger.warning(f"[CLOUD-PROV] Bilateral peer psql exit {_ec}: {_stderr[:200]}")
    except Exception as e:
        logger.warning(f"[CLOUD-PROV] Bilateral peer registration failed (non-fatal): {e}")

    # §pass73.3.6 — Cross-frame peer seeding for sandbox cloud-ops.
    #
    # The single bilateral peer above only registers the operator's parent
    # mainframe. For cross-frame transfers to work (e.g. a sandbox cloud-op
    # on Frame A sending to a sandbox cloud-op on Frame B), the cloud-op
    # also needs:
    #   (1) the cross-frame mainframe (e.g. Frame A op → Registry-Test-B)
    #   (2) the cross-frame sibling cloud-ops (e.g. sandboxalpha → sandboxdelta)
    #
    # Without these, `_resolve_receiver_registry` in teg_integration.py
    # rejects the receiver as "not a federated agent from an active peer
    # registry" because the resolver's `peer.status='ACTIVE'` gate filters
    # everything outside the local peer_registries table.
    #
    # SANDBOX_CROSS_FRAME_PEERS env (JSON list of {name, base_url,
    # trust_domain} entries) opts a sandbox cloud-op provisioner into
    # seeding the full multi-hop set. Prod cloud-ops don't need this — they
    # learn peers via federation_sync's RegistryCardFanout from a
    # well-connected parent mainframe whose own peer_registries already
    # has the full fleet.
    _cross_frame_peers_json = os.getenv("SANDBOX_CROSS_FRAME_PEERS", "").strip()
    if _cross_frame_peers_json:
        try:
            import json as _json_cfp
            _cross_peers = _json_cfp.loads(_cross_frame_peers_json)
            if isinstance(_cross_peers, list):
                import docker as _dk_xfp
                _dk_client = _dk_xfp.from_env()
                _db_container = _dk_client.containers.get(f"cloud-op-{safe}-db")
                for _peer in _cross_peers:
                    if not isinstance(_peer, dict) or not _peer.get("name") or not _peer.get("base_url"):
                        continue
                    # §pass73.3.6 — validate peer name slug-compatibility.
                    # The resolver (`_resolve_receiver_registry` in
                    # teg_integration.py) matches against `_slug(peer.name)`.
                    # `_slug` converts space → dash, so "Sandbox Alpha" → slug
                    # "sandbox-alpha" while the federated card's SPIFFE source
                    # path part is "sandboxalpha" (no dash) — they DON'T match.
                    # The resolver has a dash-insensitive compact fallback now,
                    # but the canonical recommendation is to use names that
                    # _slug doesn't transform. Warn if the provided name will
                    # be normalized by _slug, and store the normalized form.
                    _orig_name = _peer["name"]
                    _canonical = _orig_name.lower().replace(" ", "").strip()
                    if _canonical != _orig_name:
                        logger.warning(
                            f"[CLOUD-PROV] Cross-frame peer name {_orig_name!r} "
                            f"will be slug-normalized to {_canonical!r} for resolver "
                            f"compatibility. Future provisioning runs should pass the "
                            f"canonical form directly."
                        )
                    _peer_name = _canonical.replace("'", "''")
                    _peer_url = _peer["base_url"].replace("'", "''")
                    _peer_td = (_peer.get("trust_domain") or "").replace("'", "''")
                    _peer_type = _peer.get("peer_type", "discovered").replace("'", "''")
                    _xfp_sql = (
                        "INSERT INTO peer_registries (name, base_url, status, peer_type, "
                        "trust_domain, owner_developer_id, admin_contact_email, registered_at, "
                        "approved_at, approved_by_developer_id, discovery_auth_info, "
                        "health_check_failure_count, total_interactions, disputes_lost_with, "
                        "bayesian_discount) "
                        f"VALUES ('{_peer_name}', '{_peer_url}', 'ACTIVE', '{_peer_type}', "
                        f"NULLIF('{_peer_td}', ''), 1, 'commander@theprotocol.cloud', NOW(), "
                        "NOW(), 1, '{}'::jsonb, 0, 0, 0, 1.0) "
                        "ON CONFLICT (name) DO UPDATE SET base_url = EXCLUDED.base_url, "
                        "status = 'ACTIVE', peer_type = EXCLUDED.peer_type, "
                        "trust_domain = COALESCE(peer_registries.trust_domain, EXCLUDED.trust_domain), "
                        "approved_at = COALESCE(peer_registries.approved_at, NOW()), "
                        "approved_by_developer_id = COALESCE(peer_registries.approved_by_developer_id, 1);"
                    )
                    _ec, _out = _db_container.exec_run(
                        ["psql", "-U", "registry", "-d", "agentvault_registry", "-c", _xfp_sql],
                        demux=True,
                    )
                    if _ec == 0:
                        logger.info(f"[CLOUD-PROV] Cross-frame peer seeded: {_peer_name} → {_peer_url}")
                    else:
                        _stderr = (_out[1] or b"").decode()
                        logger.warning(f"[CLOUD-PROV] Cross-frame peer {_peer_name} psql exit {_ec}: {_stderr[:200]}")
        except Exception as e:
            logger.warning(f"[CLOUD-PROV] Cross-frame peer seeding failed (non-fatal): {e}")

    # Stamp the admin developer's display_name so federation_sync's
    # _get_display_name() returns the peer-friendly slug (e.g. 'op-tokyo')
    # instead of falling through to REGISTRY_NAME. This makes
    # `origin_registry_name` on exported agent cards match the peer row
    # on the parent frame exactly, removing the need for fuzzy matching
    # in _resolve_receiver_registry.
    #
    # If lat/lng are provided, also stamp them so /agents/locations/operator
    # returns real coordinates — the Cesium globe reads this to place the
    # operator's glyph at its landmark instead of defaulting to the mainframe.
    try:
        import docker as _dk_dn
        _dk_client = _dk_dn.from_env()
        _db_container = _dk_client.containers.get(f"cloud-op-{safe}-db")
        _set_parts = [f"display_name='{safe}'"]
        # §LOCTRUTH — an AUTO-PICKED location never reaches the developer row. `pick_default_location`
        # exists for one purpose: spreading operator glyphs across the Cesium globe so they do not stack
        # on the mainframe (§pass66). But the DEVELOPER's lat/lng is what `federation_sync` stamps onto
        # every agent card it exports ("developer location for agent-level positioning"), so a curated
        # city became a published geographic FACT on a signed, federated card. Measured on the EU/ASIA
        # pair: hochiminh's agents claimed Lagos, Nigeria; shenzhen's Chicago; lisbon's Madrid;
        # amsterdam's Vancouver — while each operator's own registry card carried its real city. His
        # report: "the location of the agent is made up". The operator still gets its glyph (its own
        # coordinates are stamped elsewhere); what stops is publishing a guess as an agent's address.
        if latitude is not None and longitude is not None and location_is_declared:
            _set_parts.append(f"latitude={float(latitude)}")
            _set_parts.append(f"longitude={float(longitude)}")
            if location_label:
                _safe_label = location_label.replace("$", "")  # dollar-quote hygiene
                _set_parts.append(f"location_label=$tag${_safe_label}$tag$")
        _sql_dn = f"UPDATE developers SET {', '.join(_set_parts)} WHERE is_admin = true;"
        _ec, _out = _db_container.exec_run(
            ["psql", "-U", "registry", "-d", "agentvault_registry", "-c", _sql_dn],
            demux=True,
        )
        if _ec == 0:
            logger.info(
                f"[CLOUD-PROV] Admin display_name='{safe}' "
                f"lat/lng={latitude}/{longitude} label={location_label!r}"
            )
        else:
            _stderr = (_out[1] or b"").decode()
            logger.warning(f"[CLOUD-PROV] display_name update exit {_ec}: {_stderr[:200]}")
    except Exception as e:
        logger.warning(f"[CLOUD-PROV] Admin display_name update failed (non-fatal): {e}")

    # §pass34 (2026-05-17) — Stamp the canonical federation identity into the
    # new registry_self singleton. This is the AUTHORITATIVE source for
    # `_get_display_name()` going forward; the display_name stamp above stays
    # for backwards compatibility during the transition (and because devs
    # legitimately use display_name as a personal handle on mainframes).
    #
    # `safe` is the slug derived from OperatorApplication.name — same slug
    # already in peer_registries.name, container_name, DB name, etc. Aligning
    # registry_self with this slug ensures origin_registry_name stamps on
    # this operator's native cards match peer rows on every other registry.
    try:
        import docker as _dk_rs
        _dk_rs_client = _dk_rs.from_env()
        _rs_container = _dk_rs_client.containers.get(f"cloud-op-{safe}-db")
        _rs_sql = (
            "INSERT INTO registry_self (id, federation_name) "
            f"VALUES (1, '{safe}') "
            "ON CONFLICT (id) DO UPDATE SET federation_name = EXCLUDED.federation_name, updated_at = NOW();"
        )
        _ec, _out = _rs_container.exec_run(
            ["psql", "-U", "registry", "-d", "agentvault_registry", "-c", _rs_sql],
            demux=True,
        )
        if _ec == 0:
            logger.info(f"[CLOUD-PROV] registry_self.federation_name='{safe}' seeded")
        else:
            _stderr = (_out[1] or b"").decode()
            # Common pre-migration case: table doesn't exist on this operator's
            # DB yet. Migration 0061 will seed from REGISTRY_FEDERATION_NAME
            # env (preferred) or from developer.display_name (legacy) at first
            # boot. This insert just races ahead to make new operators correct
            # from cycle zero.
            logger.warning(f"[CLOUD-PROV] registry_self seed exit {_ec}: {_stderr[:200]}")
    except Exception as e:
        logger.warning(f"[CLOUD-PROV] registry_self seed failed (non-fatal — migration will catch): {e}")

    # Register operator SPIFFE ID in EventStore's federation_operators table
    # so the EventStore nginx mTLS can authenticate the operator's event emissions.
    try:
        _es_db = os.getenv("EVENT_STORE_DB_CONTAINER", "agentvault_event_store_db")
        _es_dbname = os.getenv("EVENT_STORE_DB_NAME", "eventstore")
        _es_dbuser = os.getenv("EVENT_STORE_DB_USER", "postgres")
        import docker as _dk_es
        _dk_es_client = _dk_es.from_env()
        _es_db_container = _dk_es_client.containers.get(_es_db)
        _spiffe_id = f"spiffe://{TRUST_DOMAIN}/operator/{safe}/registry"
        # §2026-06-14 — UPSERT (was a bare UPDATE that no-op'd when the row was
        # absent). The HTTP sync to /events/operators/sync is mTLS/auth-gated and
        # has been failing for fresh provisions (no federation_operators row created
        # since 2026-06-04), so a freshly-provisioned op lacked the ES-side row that
        # established ops (e.g. op-london) carry. This direct-DB write bypasses the
        # nginx mTLS / verify_event_auth path entirely (the provisioner holds the
        # docker socket), creating the row to match op-london's shape (registry SVID
        # + license_key_hash + ACTIVE) if missing, then refreshing the SVID. Idempotent
        # via WHERE NOT EXISTS on spiffe_id — re-provision won't duplicate.
        _es_op_name = (application.name or safe).replace("'", "''")
        _es_sql = (
            "INSERT INTO federation_operators "
            "(id, operator_name, license_key_hash, status, spiffe_id, max_events_per_minute) "
            f"SELECT '{license_id}', '{_es_op_name}', '{key_hash}', 'ACTIVE', '{_spiffe_id}', 1000 "
            f"WHERE NOT EXISTS (SELECT 1 FROM federation_operators WHERE spiffe_id='{_spiffe_id}'); "
            f"UPDATE federation_operators SET spiffe_id='{_spiffe_id}', status='ACTIVE' "
            f"WHERE operator_name='cloud-op-{safe}' OR operator_name='{_es_op_name}';"
        )
        _ec, _out = _es_db_container.exec_run(
            ["psql", "-U", _es_dbuser, "-d", _es_dbname, "-c", _es_sql],
            demux=True,
        )
        if _ec == 0:
            logger.info(f"[CLOUD-PROV] EventStore federation_operators row upserted: {_spiffe_id}")
        else:
            logger.warning(f"[CLOUD-PROV] EventStore federation_operators upsert failed: {(_out[1] or b'').decode()[:200]}")
    except Exception as e:
        logger.warning(f"[CLOUD-PROV] EventStore SPIFFE sync failed (non-fatal): {e}")

    # §NOTIFV2 operator.provisioned (audience=admin). This is the ONE success return of
    # provision_cloud_operator — every provisioning path that succeeds passes through here, and
    # every failing one raises before it, so a notification here cannot report a phantom operator.
    try:
        import asyncio as _aio_n
        from agentvault_registry.background_tasks.push_notify import notify_audience
        _aio_n.create_task(notify_audience(
            "operator.provisioned",
            title="Cloud operator provisioned",
            message=(f"{domain} is live — {containers_started} containers, "
                     f"registry port {reg_port}."),
            tags="rocket", priority="default", click="/ui/#/admin/cloud-operators"))
    except Exception:  # noqa: BLE001
        logger.debug("[NOTIFY] operator.provisioned emit failed", exc_info=True)

    return CloudProvisionResult(
        cloud_url=f"https://{domain}",
        cloud_port_base=port_base,
        cloud_stack_dir=stack_dir_host,
        registry_port=reg_port,
        federation_port=fed_port,
        containers_started=containers_started,
        federation_license_key=plain_key,
        admin_email=admin_email,
        admin_password=admin_password,
    )


# ── Teardown ─────────────────────────────────────────────────────────────

# §2026-06-14 — leave-no-traces teardown helpers (purge=True path). A cloud-op's
# records PROPAGATE cross-frame via federation_sync: peer_registries + ES
# federation_operators land on ALL THREE frames, so a home-only delete leaves
# stale ACTIVE peers polluting the topology / AgentWorld. These helpers purge
# every frame + drain the genesis grant + revoke SPIRE — all docker-exec / HTTP
# (the mainframe registry holds the docker socket), all fail-safe (never block
# teardown). DB coords are env-overridable with proven prod defaults.
#   reg:  "container:psql_user:dbname"   es: "container:psql_user:dbname"
_ALL_FRAME_REG_DBS = os.getenv(
    "TEARDOWN_FRAME_REG_DBS",
    "agentvault_registry_db_a:postgres:agentvault_registry_a,"
    "frame-b-db:registry:frame_b_registry,"
    "frame-c-db:registry:frame_c_registry",
).split(",")
_ALL_FRAME_ES_DBS = os.getenv(
    "TEARDOWN_FRAME_ES_DBS",
    "agentvault_event_store_db:postgres:eventstore,"
    "frame-b-es-db:eventstore:frame_b_events,"
    "frame-c-es-db:eventstore:frame_c_events",
).split(",")


def _op_home_frame_ctx() -> tuple:
    """(spire_container, mainframe_teg_id) for the frame this mainframe belongs to,
    derived from SPIRE_TRUST_DOMAIN (same env the provision side keys off)."""
    _td = (os.getenv("SPIRE_TRUST_DOMAIN", "agentvault.com") or "agentvault.com").strip()
    if _td.startswith("frame-b"):
        return (os.getenv("SPIRE_CONTAINER", "frame-b-spire-server"), "teg-layer")
    if _td.startswith("frame-c"):
        return (os.getenv("SPIRE_CONTAINER", "frame-c-spire-server"), "teg-layer")
    return (os.getenv("SPIRE_CONTAINER", "agentvault-spire-server"), "teg-layer-a")


def _drain_op_treasury(safe: str) -> dict:
    """The genesis drain before a SOCKET-route purge destroys the operator's ledger: services/operator_drain.py, the frame
    runner's rule on this route (read and send through the operator's registry and its SVID, to its one partner, every
    send recorded in its stack dir first, an unconfirmed one re-sent before the balance is trusted). {"ok": bool, ...};
    the purge refuses unless ok. §OPPROV (2026-09-27): it replaces _drain_op_genesis, whose key-era read met a 403 on
    every operator TEG since §SECFIX, parsed it as a zero, and let every socket purge destroy an undrained treasury."""
    from agentvault_registry.services.operator_drain import drain_operator_treasury
    return drain_operator_treasury(safe, f"{HOST_STACK_MOUNT}/cloud-op-{safe}")


def _delete_op_spire_entries(safe: str) -> int:
    """Delete the op's SPIRE workload entries (operator/{safe}/{registry,svid-writer,
    teg}) on this frame's SPIRE server. Returns count remaining (0 = clean)."""
    _spire, _ = _op_home_frame_ctx()
    try:
        import docker as _dk
        _c = _dk.from_env().containers.get(_spire)
        _ec, _out = _c.exec_run(["/opt/spire/bin/spire-server", "entry", "show"], demux=True)
        _txt = (_out[0] or b"").decode()
        _ids, _cur = [], None
        for _line in _txt.splitlines():
            _ls = _line.strip()
            if _ls.startswith("Entry ID"):
                _cur = _ls.split(":")[-1].strip()
            elif f"operator/{safe}/" in _ls and _cur:
                _ids.append(_cur)
        for _eid in sorted(set(_ids)):
            _c.exec_run(["/opt/spire/bin/spire-server", "entry", "delete", "-entryID", _eid])
        _ec, _out = _c.exec_run(["/opt/spire/bin/spire-server", "entry", "show"], demux=True)
        return (_out[0] or b"").decode().count(f"operator/{safe}/")
    except Exception as e:
        logger.warning(f"[CLOUD-TEARDOWN] SPIRE purge failed: {e}")
        return -1


def _purge_op_rows_all_frames(safe: str, op_display: str) -> None:
    """Purge the op's peer_registries + operator_applications (registry DBs) and
    federation_operators (ES DBs) on ALL THREE frames — they propagate cross-frame,
    so a home-only delete leaves stale ACTIVE peers. Fail-safe per frame."""
    import docker as _dk
    _cli = _dk.from_env()
    _safe_disp = (op_display or safe).replace("'", "''")
    # RP6 (2026-07-24): ANCHORED name forms only. The old `%slug%` substring
    # match collaterally deleted overlapping ops (slug 'tel' wiped 'telaviv').
    # Every known naming shape is matched exactly (case-insensitive):
    #   {slug} · op-{slug} · cloud-op-{slug} · cloud-op-op-{slug} · display name
    # base_url stays a pattern but is anchored to the subdomain boundary.
    _forms = sorted({safe, f"op-{safe}", f"cloud-op-{safe}", f"cloud-op-op-{safe}", _safe_disp})
    _in_list = ", ".join(f"lower('{f}')" for f in _forms)
    _name_pred = f"lower(name) in ({_in_list})"
    _opname_pred = f"lower(operator_name) in ({_in_list})"
    for _spec in _ALL_FRAME_REG_DBS:
        try:
            _ct, _u, _d = _spec.strip().split(":")
            _sql = (f"delete from peer_registries where {_name_pred} "
                    f"or base_url ilike '%://{safe}.%'; "
                    f"delete from operator_applications where {_name_pred};")
            _cli.containers.get(_ct).exec_run(["psql", "-U", _u, "-d", _d, "-c", _sql])
        except Exception as e:
            logger.warning(f"[CLOUD-TEARDOWN] reg purge on {_spec} failed: {e}")
    for _spec in _ALL_FRAME_ES_DBS:
        try:
            _ct, _u, _d = _spec.strip().split(":")
            _sql = (f"delete from federation_operators where {_opname_pred} "
                    f"or spiffe_id ilike '%operator/{safe}/%';")
            _cli.containers.get(_ct).exec_run(["psql", "-U", _u, "-d", _d, "-c", _sql])
        except Exception as e:
            logger.warning(f"[CLOUD-TEARDOWN] ES purge on {_spec} failed: {e}")


async def _purge_op_rows_by_api(db: AsyncSession, safe: str) -> dict:
    """§F6 WP6.2 slice 2, the runner route of a purge's step 4.5. `_purge_op_rows_all_frames` ran psql DELETEs inside
    OTHER frames' databases (by default the legacy Frame A/B/C containers, from any frame), a cross-frame state change
    outside every rail. Here each ACTIVE peer frame is asked, over its mTLS federation address, to purge ITS OWN copies
    of this operator (`POST /api/v1/federation/operators/{op}/purge-rows`, which deletes only rows that carry the CALLER's
    trust domain), and this frame's own event store has the operator's federation_operators rows SUSPENDED through its
    API (it serves no delete). Every answer is reported; none raises, because the host half is already done."""
    from agentvault_registry.services.exchange_passport import PassportError, peer_request
    from agentvault_registry.services import frame_data_plane_sync as _dps
    out: dict = {"peers": {}, "store_suspended": [], "store_errors": []}
    peers = (await db.execute(
        select(models.PeerRegistry).where(models.PeerRegistry.peer_type == "frame", models.PeerRegistry.status == "ACTIVE")
    )).scalars().all()
    for peer in peers:
        try:
            code, body = await peer_request(db, peer.name, "POST", f"/api/v1/federation/operators/{safe}/purge-rows", {})
            out["peers"][peer.name] = {"http": code, "deleted": (body or {}).get("deleted") if isinstance(body, dict) else None,
                                       **({} if code == 200 else {"detail": str((body or {}).get("detail") or body)[:200]})}
        except PassportError as exc:
            out["peers"][peer.name] = {"error": str(exc)[:200]}
    ok, detail, body = await _dps.list_federation_operators()
    if not ok:
        out["store_errors"].append(f"list: {detail}"[:200])
    for row in ((body or {}).get("operators") or []) if ok else []:
        sid = str(row.get("spiffe_id") or "")
        if f"/operator/{safe}/" in sid and row.get("status") != "suspended":
            s_ok, s_detail, _ = await _dps._post(f"/api/v1/admin/federation-operators/{row.get('id')}/suspend", {})
            (out["store_suspended"] if s_ok else out["store_errors"]).append(sid if s_ok else f"{sid}: {s_detail}"[:200])
    return out


async def _purge_rows_elsewhere(db: AsyncSession, safe: str, op_display: str, via_runner: bool) -> dict:
    """Step 4.5 of a purge, ONE rule for both routes (§OPPROV 2026-09-27): every ACTIVE peer frame purges ITS OWN copies of
    the operator through its own API (`_purge_op_rows_by_api`, the runner route's rail since §F6 WP6.2 slice 2), and on the
    socket route this frame's own configured databases are also cleaned by psql as before (`_purge_op_rows_all_frames`).
    Measured on sbx-alpha: its socket purge of opprovs left sbx-beta's copy (discovered, INACTIVE) behind while logging
    "cross-frame peer/app/ES rows purged", because only the psql loop ran on that route and TEARDOWN_FRAME_REG_DBS named
    this frame's own database alone (one entry: a frame does not write into another frame's database, rightly). The same
    held for EU and ASIA, which purge on the socket route. Returns what each half did; neither raises (the host half is
    already done when this runs)."""
    out: dict = {"route": "runner" if via_runner else "socket"}
    if not via_runner:
        try:
            await asyncio.to_thread(_purge_op_rows_all_frames, safe, op_display)
            out["own_databases"] = "purged by psql (TEARDOWN_FRAME_REG_DBS / TEARDOWN_FRAME_ES_DBS)"
        except Exception as e:  # noqa: BLE001 — reported, like every answer of the API half
            out["own_databases"] = f"failed: {e}"[:200]
    out.update(await _purge_op_rows_by_api(db, safe))
    return out


async def teardown_cloud_operator(
    application: models.OperatorApplication,
    reason: str,
    db: AsyncSession,
    purge: bool = False,
) -> CloudTeardownResult:
    """Tear down a cloud-hosted operator.

    purge=False (default, SAFE decommission): stop containers + remove config,
      DEACTIVATE the federation peer (kept for audit), ARCHIVE the stack dir.
    purge=True (LEAVE-NO-TRACES, for test ops): additionally drain the genesis
      grant back to the mainframe, revoke SPIRE entries, DELETE (not deactivate)
      the peer + operator_application + ES federation_operators row on ALL THREE
      frames (cross-frame propagation), and DELETE (not archive) the stack dir.
      Result = zero traces fleet-wide, Δ=0.
    """
    safe = _safe_name(application.name or "unknown")
    stack_dir = application.cloud_stack_dir or f"{STACK_ROOT_HOST}/cloud-op-{safe}"
    domain = (application.cloud_url or "").replace("http://", "").replace("https://", "")

    logger.info(f"[CLOUD-TEARDOWN] Tearing down {safe}: reason={reason} purge={purge}")

    # §F6 WP6.2 slice 2: a PURGE on OPERATOR_LIFECYCLE_VIA=runner hands its host half to the frame runner (operator_purge:
    # the genesis drain inside the operator's own TEG, then its stack, edge and dirs), its SPIRE half to
    # operator_revoke_spire, and its rows elsewhere to each peer frame's own API. An unknown flag value raises here,
    # before anything is changed. A non-purge teardown keeps its route (host_route) either way.
    _purge_via_runner = bool(purge) and operator_lifecycle_via() == "runner"

    # 0. (purge only) Drain the genesis grant op-treasury → mainframe TEG BEFORE
    # the op TEG container is removed. Δ-neutral (transfer, not burn). On the runner route the runner drains first.
    # §OPPROV (2026-09-27): and a drain that did not move the value STOPS the purge here, before anything is removed,
    # exactly as the runner's operator_purge does; the old drain was best-effort and the purge went on regardless. A
    # frame with no docker socket cannot drain on this route at all, so its purge must go through the runner.
    # §F6 WP6.0: the route by host_route() (HOST_REACH_PREFER included); no route raises before anything is written
    from agentvault_registry.core.host_reach import host_route as _hr
    if purge and not _purge_via_runner:
        if _hr()[0] != "direct":
            raise RuntimeError(f"[CLOUD-TEARDOWN] {safe}: a purge drains the operator's treasury before its ledger is "
                               f"destroyed, and this frame has no docker socket to drain it with; set "
                               f"{OPERATOR_LIFECYCLE_VIA_ENV}=runner so the runner's purge drains it. Nothing was removed.")
        _drain = await asyncio.to_thread(_drain_op_treasury, safe)
        logger.info(f"[CLOUD-TEARDOWN] genesis drain: {_drain}")
        if not _drain.get("ok"):
            raise RuntimeError(f"[CLOUD-TEARDOWN] {safe}: {_drain.get('note')}; nothing was removed")

    # 1. Stop and remove all operator containers + volumes (by name prefix).
    # §2026-06-14 — run OFF the event loop (asyncio.to_thread): removing 9
    # containers + volumes is blocking docker-SDK work that can take 20-40s; on
    # the loop it (with step 2's nginx subprocess) trips gunicorn's 60s arbiter
    # timeout → worker SIGKILL mid-teardown → HTTP 000 + half-done purge. Same
    # event-loop class fixed on the provision side.
    def _remove_op_containers() -> bool:
        try:
            prefix = f"cloud-op-{safe}"
            import docker as _dk_teardown
            _td_client = _dk_teardown.from_env()
            _containers = [c for c in _td_client.containers.list(all=True, ignore_removed=True) if c.name.startswith(prefix)]
            for _c in _containers:
                try:
                    _c.remove(force=True, v=True)   # force=stop, v=remove attached volumes
                except Exception as _e:
                    logger.warning(f"[CLOUD-TEARDOWN] failed to remove {_c.name}: {_e}")
            if _containers:
                logger.info(f"[CLOUD-TEARDOWN] Removed {len(_containers)} containers")
            _vols = [v for v in _td_client.volumes.list() if v.name.startswith(prefix)]
            for _v in _vols:
                try:
                    _v.remove(force=True)
                except Exception as _e:
                    logger.warning(f"[CLOUD-TEARDOWN] failed to remove volume {_v.name}: {_e}")
            if _vols:
                logger.info(f"[CLOUD-TEARDOWN] Removed {len(_vols)} volumes")
            for _net in _td_client.networks.list(names=[f"{prefix}_operator-net"]):
                try:
                    _net.remove()
                except Exception:
                    pass
            return True
        except Exception as e:
            logger.error(f"[CLOUD-TEARDOWN] Container stop failed: {e}")
            return False
    # ⚠ THE HOST HALF FIRST, AND A FAILURE RAISES. Every database write in this function is below this line, and
    # on a runner-built frame the SDK path cannot do any of it: no docker socket, so _remove_op_containers returns
    # False and only logs, after which the route stamped cloud_torn_down_at, deactivated the peer and revoked the
    # licence anyway. The database would read "torn down" while the operator kept serving (agentvault2-6a,
    # beacon, V0390). Raising here means nothing below runs and nothing is written.
    if _purge_via_runner:
        # the runner refuses (and this raises before any database write) when the operator's treasury holds value
        # the drain could not move, or when the operator is not this frame's
        _pr = await _operator_lifecycle_through_runner("operator_purge", _RUNNER_PURGE_TIMEOUT_S, operator=safe)
        _td_route, _td_why = "runner", "OPERATOR_LIFECYCLE_VIA=runner (purge)"
    else:
        _td_route, _td_why = _hr()
    if _td_route is None:
        raise RuntimeError(f"[CLOUD-TEARDOWN] {safe}: no route for the host half ({_td_why}); nothing was written")
    _td_direct = _td_route == "direct"
    host_teardown_ok = True
    if _purge_via_runner:
        _sweep = (_pr.get("sweep") or {}).get("containers") or {}
        containers_stopped = _sweep.get("left") == 0
        _runner_nginx_removed = any((e or {}).get("nginx_removed") for e in (_pr.get("edge") or []))
        logger.info(f"[CLOUD-TEARDOWN] {safe}: purged through the frame runner: drain={_pr.get('drain')}, "
                    f"compose rc={_pr.get('compose_rc')}, containers left={_sweep.get('left')}, "
                    f"edge removed={_runner_nginx_removed}, stack={(_pr.get('stack') or {}).get('stack_removed')}, "
                    f"archives removed={len(_pr.get('archives_removed') or [])}")
    elif _td_direct:
        containers_stopped = await asyncio.to_thread(_remove_op_containers)
    else:
        from agentvault_registry.core.frame_slug import frame_slug as _fs2
        from agentvault_registry.services import operator_provision_client as _opc2
        logger.info(f"[CLOUD-TEARDOWN] {safe}: no docker socket here ({_td_why}); through the frame runner")
        _td = await _opc2.teardown_through_runner(frame=_fs2(), safe_name=safe,
                                                  application_id=str(application.id))
        containers_stopped = bool(_td.get("containers_removed") or _td.get("network_removed"))
        _runner_nginx_removed = bool(_td.get("nginx_removed"))
        notes = _td.get("notes") or []
        logger.info(f"[CLOUD-TEARDOWN] {safe}: the runner reports {notes}")

    # 2. Remove nginx vhost (+ SNI map + reload) — also OFF the loop (the nsenter
    # `_run` subprocesses block up to 15s each).
    def _remove_op_nginx() -> bool:
        vhost_path = f"{HOST_NGINX_MOUNT}/cloud-op-{safe}"
        try:
            if os.path.exists(vhost_path):
                os.remove(vhost_path)
                if domain:
                    _run(
                        'docker run --rm --network=host --pid=host --privileged '
                        'alpine nsenter -t 1 -m -u -n -i '
                        f'/opt/theprotocol/stack/Agentvault2/scripts/extend_stream_sni_map.sh '
                        f'--remove {domain}',
                        timeout=15
                    )
                _run(
                    'docker run --rm --network=host --pid=host --privileged '
                    'alpine nsenter -t 1 -m -u -n -i sh -c "nginx -t && nginx -s reload"',
                    timeout=15
                )
                return True
        except Exception as e:
            logger.error(f"[CLOUD-TEARDOWN] nginx removal failed: {e}")
        return False
    # The edge is the runner's on a socketless frame: it holds the /etc/nginx this registry deliberately does not
    # have, and it removed the vhost and the SNI line as part of the same job. Running the nsenter path here would
    # be a privileged container this frame cannot start anyway, and its False would read as "the edge is still up".
    nginx_removed = (_runner_nginx_removed if not _td_direct
                     else await asyncio.to_thread(_remove_op_nginx))

    # 2.5 (purge only) Revoke the op's SPIRE workload entries (frame-aware).
    if purge:
        if _purge_via_runner:
            try:
                # with the node's fingerprint the runner also BANS the operator's node (never evicts it: an evict erases
                # the ban, 9a20c46), so a purged operator's bundle cannot re-attest; the sweep of /operator/<op>/ runs
                # either way
                _fp = (getattr(application, "spire_fingerprint", None) or "").strip().lower()
                _rs = await _operator_lifecycle_through_runner("operator_revoke_spire", 120.0, operator=safe,
                                                               **({"fingerprint": _fp} if _fp else {}))
                _spire_left = int(_rs.get("entries_found") or 0) - int(_rs.get("entries_deleted") or 0)
            except RuntimeError as exc:
                logger.warning(f"[CLOUD-TEARDOWN] {safe}: SPIRE entries through the frame runner refused: {exc}")
                _spire_left = -1
        else:
            # §OPPROV (2026-09-27): the socket purge did only the sweep, so the operator's node stayed attested and
            # unbanned after its stack was gone, and the x509pop key in the operator's bundle could attest it again.
            # The same cascade the runner runs now: ban the node (with the row's fingerprint), delete its entries.
            _fp = (getattr(application, "spire_fingerprint", None) or "").strip().lower()
            if _fp:
                from agentvault_registry.services.operator_revoker import revoke_operator_spire as _ros
                _rr = await asyncio.to_thread(_ros, safe, _fp)
                logger.info(f"[CLOUD-TEARDOWN] {safe}: node banned={_rr.spire_agent_banned} "
                            f"(listed={_rr.node_listed}), entries deleted={_rr.spire_entries_deleted}")
                for _e in _rr.errors:
                    logger.warning(f"[CLOUD-TEARDOWN] {safe}: SPIRE: {_e}")
            _spire_left = await asyncio.to_thread(_delete_op_spire_entries, safe)
        logger.info(f"[CLOUD-TEARDOWN] SPIRE entries remaining for {safe}: {_spire_left}")

    # 3. Federation peer.
    # Option D-light Phase D3 (2026-04-21): swapped raw `docker exec psql` for
    # a SQLAlchemy write on the shared session — transactional with rest of
    # teardown, no docker-socket dependency, parameterised. Also emits
    # PeerRegistryDeactivated so the audit trail lands in EventStore.
    # purge=True DELETEs the local row (vs INACTIVE) AND purges the cross-frame
    # propagated copies (see step 4.5).
    peer_deactivated = False
    op_display = application.name or f"Cloud {safe.title()}"
    peer_snapshot = None  # captured for the event after commit
    try:
        peer_result = await db.execute(
            select(models.PeerRegistry).where(models.PeerRegistry.name == op_display)
        )
        peer_row = peer_result.scalar_one_or_none()
        if peer_row:
            peer_snapshot = {
                "peer_id": peer_row.id,
                "peer_name": peer_row.name,
                "peer_url": peer_row.base_url,
                "prior_status": peer_row.status,
            }
            if purge:
                await db.delete(peer_row)
                logger.info(f"[CLOUD-TEARDOWN] PeerRegistry {peer_snapshot['peer_id']} ({op_display}) DELETED (purge)")
            else:
                peer_row.status = "INACTIVE"
                peer_row.deactivated_reason = "teardown"  # guard-set: never auto-revived
                peer_row.deactivated_at = datetime.now(timezone.utc)
                logger.info(
                    f"[CLOUD-TEARDOWN] PeerRegistry {peer_row.id} ({op_display}) marked INACTIVE "
                    f"(prior={peer_snapshot['prior_status']})"
                )
            peer_deactivated = True
        else:
            logger.warning(
                f"[CLOUD-TEARDOWN] No PeerRegistry row found matching name='{op_display}' — skipped"
            )
    except Exception as e:
        logger.error(f"[CLOUD-TEARDOWN] Peer deactivation failed: {e}")

    # 4. Revoke federation license
    revoked_licence = None
    try:
        result = await db.execute(
            select(models.FederationLicense).where(
                models.FederationLicense.operator_did == _cloud_operator_did(application, safe)
            )
        )
        license_rec = result.scalar_one_or_none()
        if license_rec:
            license_rec.status = "revoked"
            license_rec.revoked_at = datetime.now(timezone.utc)
            license_rec.revoked_reason = reason
            revoked_licence = {"id": license_rec.id, "operator_name": license_rec.operator_name,
                               "license_key_hash": license_rec.license_key_hash}
    except Exception as e:
        logger.error(f"[CLOUD-TEARDOWN] License revocation failed: {e}")

    # 4.5 (purge only) Cross-frame purge of the propagated copies (peer_registries
    # + operator_applications on every registry DB; federation_operators on every
    # ES). The step-3 db.delete only reaches THIS frame; federation_sync replicated
    # the op to the other two, so without this a stale ACTIVE peer lingers there.
    # Run after the local db.delete is flushed so the local row is gone first.
    purged = False
    if purge:
        try:
            await db.flush()
        except Exception:
            pass
        _rows = await _purge_rows_elsewhere(db, safe, op_display, _purge_via_runner)
        logger.info(f"[CLOUD-TEARDOWN] {safe}: rows elsewhere purged by each frame's own API: {_rows}")
        purged = True

    # 5. Stack directory — purge DELETEs, default ARCHIVEs.
    stack_archived = False
    stack_dir_container = f"{HOST_STACK_MOUNT}/cloud-op-{safe}"
    archive_name = f"cloud-op-{safe}-archived-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}"
    archive_dir = f"{HOST_STACK_MOUNT}/{archive_name}"
    try:
        if not _purge_via_runner and os.path.exists(stack_dir_container):
            if purge:
                shutil.rmtree(stack_dir_container, ignore_errors=True)
                # also sweep any older archived copies + the in-image bundle
                for _old in __import__("glob").glob(f"{HOST_STACK_MOUNT}/cloud-op-{safe}-archived*"):
                    shutil.rmtree(_old, ignore_errors=True)
                logger.info(f"[CLOUD-TEARDOWN] stack dir DELETED (purge): {stack_dir_container}")
            else:
                shutil.move(stack_dir_container, archive_dir)
                stack_archived = True
                logger.info(f"[CLOUD-TEARDOWN] Archived to {archive_dir}")
    except Exception as e:
        logger.error(f"[CLOUD-TEARDOWN] stack dir teardown failed: {e}")

    return CloudTeardownResult(
        containers_stopped=containers_stopped,
        nginx_removed=nginx_removed,
        peer_deactivated=peer_deactivated,
        stack_archived=stack_archived,
        peer_snapshot=peer_snapshot,
        purged=purged,
        revoked_licence=revoked_licence,
    )


# §pass66.6 (2026-05-23) — Web-action surface for cloud-hosted operators.
# Cloud-hosted ops have NO shell access to Frame A's host, so they can't run
# `tp-operator restart` from a terminal like a self-hosted Level-3 operator
# would. This helper exposes the equivalent action via a Frame A admin
# endpoint so Commander (or any admin_federation holder) can click "Restart"
# from OperatorManagement.vue and have the op's service bounced cleanly.
#
# Allowlist of services that can be restarted — must match the service names
# in the operator bundle's `docker-compose.operator.yml`. The `all` token
# restarts the whole stack (`docker compose restart` with no service arg).
# Anything outside this list is rejected at the endpoint layer to prevent
# arbitrary `docker compose restart <attacker_input>` shell injection.
CLOUD_OP_RESTARTABLE_SERVICES = {
    "registry", "teg-layer", "nginx-federation", "redis",
    "db", "teg-db", "pgbouncer", "spire-agent", "cert-writer",
    "all",
}


# §F6 WP6.2 (2026-09-26, agentvault2-a1's go on his "do it fully autonomously"): an operator's restart and logs can be
# asked of the frame runner (ops operator_restart / operator_logs on its operator socket) instead of a docker:cli sidecar
# run with the host Docker socket. The runner binds the operator to the CALLING frame from the operator's own container
# (compose project, working dir, compose files, env file, the frame's trust domain), runs the same two compose verbs
# with the service and tail from the same closed sets, and audits each act without its output.
#   OPERATOR_LIFECYCLE_VIA   local (default: today's sidecar, byte for byte) | runner
# A frame set to runner FAILS CLOSED: no socket, no answer or a refusal is a RuntimeError carrying the runner's sentence
# (the routes' 500), never a fallback to the socket this flag exists to take away.
OPERATOR_LIFECYCLE_VIA_ENV = "OPERATOR_LIFECYCLE_VIA"
_RUNNER_RESTART_TIMEOUT_S = 330.0     # above the runner's own 300 s ceiling for a compose restart
_RUNNER_LOGS_TIMEOUT_S = 90.0         # above its 60 s for compose logs
_RUNNER_PURGE_TIMEOUT_S = 480.0       # above its drain (60 s) and compose down (300 s) together


def operator_lifecycle_via() -> str:
    """ "local" or "runner"; any other value raises (a flag this code does not understand is refused, never guessed)."""
    v = (os.getenv(OPERATOR_LIFECYCLE_VIA_ENV) or "local").strip().lower()
    if v not in ("local", "runner"):
        raise RuntimeError(f"{OPERATOR_LIFECYCLE_VIA_ENV}={v!r} is neither 'local' nor 'runner'")
    return v


async def _operator_lifecycle_through_runner(op: str, timeout: float, **fields) -> dict:
    from agentvault_registry.services import spire_ops_client as _soc
    try:
        return await _soc.acall(op, timeout=timeout, **fields)
    except _soc.SpireOpsUnavailable as exc:
        raise RuntimeError(f"through the frame runner: {exc}")


async def fetch_cloud_logs(
    application: "models.OperatorApplication", service: str, tail: int = 200
) -> dict:
    """§pass66.9 — Fetch logs from one service in a cloud-op's compose stack.

    Returns: { service, tail, lines, output, fetched_at }. Output is raw
    `docker compose logs` text (mixed stdout+stderr, prefixed with container
    timestamps).

    Same docker-py SDK + `docker:cli` sidecar pattern as `restart_cloud_service`.
    """
    import time as _time
    if service not in CLOUD_OP_RESTARTABLE_SERVICES:
        raise ValueError(
            f"service {service!r} not in allowlist {sorted(CLOUD_OP_RESTARTABLE_SERVICES)}"
        )
    if service == "all":
        # `docker compose logs` with no service shows ALL services interleaved
        # — fine for diagnostic dumps but `tail` is per-service so output can
        # exceed expected size. Keep allowed for power users; document in UI.
        pass
    if not (10 <= tail <= 2000):
        raise ValueError(f"tail must be 10-2000, got {tail}")

    safe = _safe_name(application.name or "")
    if operator_lifecycle_via() == "runner":
        t0 = _time.time()
        res = await _operator_lifecycle_through_runner("operator_logs", _RUNNER_LOGS_TIMEOUT_S,
                                                       operator=safe, service=service, tail=tail)
        output = str(res.get("output") or "")
        duration_ms = int((_time.time() - t0) * 1000)
        logger.info(
            f"[CLOUD-OP-LOGS] {application.name} service={service} tail={tail} "
            f"duration={duration_ms}ms bytes={len(output)} via=runner rc={res.get('rc')}"
        )
        from datetime import datetime as _dt, timezone as _tz
        return {
            "service": service,
            "tail": tail,
            "output": output,
            "lines": output.count("\n"),
            "duration_ms": duration_ms,
            "fetched_at": _dt.now(_tz.utc).isoformat(),
        }
    dir_name = f"cloud-op-{safe}" if not safe.startswith("op-") else f"cloud-op-{safe}"
    stack_dir_host = f"{STACK_ROOT_HOST}/{dir_name}"
    stack_dir_container = f"{HOST_STACK_MOUNT}/{dir_name}"
    if not os.path.exists(stack_dir_container):
        alt = f"{HOST_STACK_MOUNT}/cloud-op-{application.name}"
        if os.path.exists(alt):
            stack_dir_container = alt
            stack_dir_host = f"{STACK_ROOT_HOST}/cloud-op-{application.name}"
        else:
            raise RuntimeError(f"compose dir not found: {stack_dir_container}")

    svc_arg = "" if service == "all" else service
    t0 = _time.time()
    import docker as docker_sdk
    _logs_cmd = (
        "sh -c 'docker compose "
        f"-f docker-compose.operator.yml --env-file .env.operator logs "
        f"--no-color --tail={tail} {svc_arg}'"
    )
    try:
        dk = docker_sdk.from_env()
        out = dk.containers.run(
            "docker:cli",
            command=_logs_cmd,
            volumes={
                "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
                stack_dir_host: {"bind": stack_dir_host, "mode": "rw"},
            },
            working_dir=stack_dir_host,
            remove=True,
            detach=False,
            stdout=True,
            stderr=True,
        )
        output = out.decode("utf-8", errors="replace") if isinstance(out, bytes) else str(out)
    except docker_sdk.errors.ContainerError as e:
        # Compose may exit non-zero if the service hasn't logged anything yet;
        # still capture whatever logs flowed.
        output = (e.stderr or b"").decode("utf-8", errors="replace") if e.stderr else ""
    except Exception as e:
        raise RuntimeError(f"docker compose logs failed: {str(e)[:500]}")

    duration_ms = int((_time.time() - t0) * 1000)
    logger.info(
        f"[CLOUD-OP-LOGS] {application.name} service={service} tail={tail} "
        f"duration={duration_ms}ms bytes={len(output)}"
    )
    from datetime import datetime as _dt, timezone as _tz
    return {
        "service": service,
        "tail": tail,
        "output": output,
        "lines": output.count("\n"),
        "duration_ms": duration_ms,
        "fetched_at": _dt.now(_tz.utc).isoformat(),
    }


async def restart_cloud_service(
    application: "models.OperatorApplication", service: str
) -> dict:
    """Restart one service (or all) in a cloud-hosted operator's compose stack.

    Mirrors `teardown_cloud_operator`'s host-escape pattern: docker-py SDK is
    fast-path; alpine+nsenter is the safety-net fallback when the SDK can't
    run compose from the host's filesystem context.

    Returns: dict with `service`, `restarted`, `output_tail`, `duration_ms`.
    Raises ValueError on unknown service (caller turns into 400) or RuntimeError
    on docker failure (caller turns into 500).
    """
    import time as _time
    if service not in CLOUD_OP_RESTARTABLE_SERVICES:
        raise ValueError(
            f"service {service!r} not in allowlist {sorted(CLOUD_OP_RESTARTABLE_SERVICES)}"
        )
    safe = _safe_name(application.name or "")
    if operator_lifecycle_via() == "runner":
        t0 = _time.time()
        res = await _operator_lifecycle_through_runner("operator_restart", _RUNNER_RESTART_TIMEOUT_S,
                                                       operator=safe, service=service)
        output = str(res.get("output_tail") or "")
        if res.get("rc") != 0:
            raise RuntimeError(f"docker compose restart failed (exit {res.get('rc')}): {output[:500]}")
        duration_ms = int((_time.time() - t0) * 1000)
        logger.info(
            f"[CLOUD-OP-RESTART] {application.name} service={service} "
            f"duration={duration_ms}ms via=runner"
        )
        return {
            "service": service,
            "restarted": True,
            "output_tail": output[-400:],
            "duration_ms": duration_ms,
        }
    dir_name = f"cloud-op-{safe}" if not safe.startswith("op-") else f"cloud-op-{safe}"
    # Honor the same dir convention as provisioner (it writes to
    # /opt/theprotocol/stack/cloud-op-<safe>). Fall back to scanning for
    # cloud-op-qatestX (without op- prefix) which §pass66.3 fresh provisions use.
    stack_dir_host = f"{STACK_ROOT_HOST}/{dir_name}"
    stack_dir_container = f"{HOST_STACK_MOUNT}/{dir_name}"
    if not os.path.exists(stack_dir_container):
        # qatest16-style naming: `name=qatest16` → dir `cloud-op-qatest16` (no op-)
        alt = f"{HOST_STACK_MOUNT}/cloud-op-{application.name}"
        if os.path.exists(alt):
            stack_dir_container = alt
            stack_dir_host = f"{STACK_ROOT_HOST}/cloud-op-{application.name}"
        else:
            raise RuntimeError(f"compose dir not found: {stack_dir_container}")

    svc_arg = "" if service == "all" else service
    t0 = _time.time()
    # Same docker-py SDK pattern as `provision_cloud_operator` step 7: registry
    # container has the docker socket but no docker CLI, so we spawn a
    # transient `docker:cli` sidecar that runs compose against the op's stack
    # dir. Volumes mount both the docker socket (so the sidecar talks to the
    # host daemon) and the op's stack dir at the SAME path (so compose's
    # working-dir + relative file paths resolve correctly).
    import docker as docker_sdk
    _compose_cmd = (
        "sh -c 'export DOCKER_CONFIG="
        f"{stack_dir_host}/.docker && docker compose "
        f"-f docker-compose.operator.yml --env-file .env.operator restart {svc_arg}'"
    )
    try:
        dk = docker_sdk.from_env()
        sidecar = dk.containers.run(
            "docker:cli",
            command=_compose_cmd,
            volumes={
                "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
                stack_dir_host: {"bind": stack_dir_host, "mode": "rw"},
            },
            working_dir=stack_dir_host,
            remove=True,
            detach=False,
            stdout=True,
            stderr=True,
        )
        output = sidecar.decode("utf-8", errors="replace") if isinstance(sidecar, bytes) else str(sidecar)
    except docker_sdk.errors.ContainerError as e:
        # Non-zero exit from compose restart — capture stderr.
        raise RuntimeError(
            f"docker compose restart failed (exit {e.exit_status}): "
            f"{(e.stderr or b'').decode('utf-8', errors='replace')[:500]}"
        )
    except Exception as e:
        raise RuntimeError(f"docker compose restart failed: {str(e)[:500]}")

    duration_ms = int((_time.time() - t0) * 1000)
    logger.info(
        f"[CLOUD-OP-RESTART] {application.name} service={service} "
        f"duration={duration_ms}ms"
    )
    return {
        "service": service,
        "restarted": True,
        "output_tail": output[-400:],
        "duration_ms": duration_ms,
    }


async def sync_teardown_licence_to_store(td_result: "CloudTeardownResult", purge: bool) -> Optional[bool]:
    """Carry a non-purge teardown's licence revoke to the store's federation_operators row, after the caller's commit.

    §F6 stage 5 (2026-09-27): the teardown revokes the operator's licence in THIS database only, so the store kept the row
    "active"; and the operator revoke that usually follows then finds no licence left to revoke, so its own sync
    (_sync_operator_licence_status) never fires either (measured on sbx-beta on V0474: b1ope torn down, then revoked, its
    store row still active). A purge is left alone: it suspends or deletes the store rows itself, and a sync after it
    would write a row back. Best-effort: True/False is the sync's answer, None when nothing was to be synced."""
    lic = td_result.revoked_licence
    if purge or not lic:
        return None
    try:
        from agentvault_registry.routers.federation_licenses import _sync_license_to_eventstore
        return await _sync_license_to_eventstore(license_id=lic["id"], operator_name=lic["operator_name"],
                                                 license_key_hash=lic["license_key_hash"], op_status="revoked")
    except Exception as exc:  # noqa: BLE001  the teardown already happened and was committed
        logger.warning(f"[CLOUD-TEARDOWN] syncing the revoked licence {lic.get('id')} to the store failed (non-fatal): "
                       f"{type(exc).__name__}: {exc}")
        return False


async def emit_peer_registry_deactivated(
    application: models.OperatorApplication,
    td_result: "CloudTeardownResult",
    reason: str,
    actor_developer_id: Optional[int] = None,
    actor_email: Optional[str] = None,
) -> None:
    """Emit the PeerRegistryDeactivated audit event after a teardown commit.

    Called by both the router teardown handler AND lifecycle / sandbox tests
    so the audit trail (and the Phase 1 reactor) fires consistently regardless
    of which surface invoked the teardown. Best-effort — exceptions are logged
    but never raised; the durable DB state is the source of truth.

    Convention: teg_id matches `cloud_provisioner.py:_generate_env_file` line
    `TEG_ID=teg-{safe}` so the reactor can call /cross-teg/config/remove-partner
    without re-deriving the slug.
    """
    if not td_result.peer_snapshot:
        return
    try:
        emitter = get_event_emitter()
        torn_down_teg_id = f"teg-{_safe_name(application.name or 'unknown')}"
        await emitter.emit(
            event_type="PeerRegistryDeactivated",
            aggregate_id=f"peer_registry:{td_result.peer_snapshot['peer_id']}",
            aggregate_type="PeerRegistry",
            data={
                "peer_id": td_result.peer_snapshot["peer_id"],
                "peer_name": td_result.peer_snapshot["peer_name"],
                "peer_url": td_result.peer_snapshot["peer_url"],
                "prior_status": td_result.peer_snapshot["prior_status"],
                "trigger": "cloud_teardown",
                "application_id": application.id,
                "operator_name": application.name,
                "teg_id": torn_down_teg_id,
                "reason": reason,
                "actor_developer_id": actor_developer_id,
                "actor_email": actor_email or "system",
            },
        )
    except Exception as exc:
        logger.error(
            f"Failed to emit PeerRegistryDeactivated for peer "
            f"{td_result.peer_snapshot.get('peer_id')}: {exc}"
        )

    # §NOTIFV2 federation.peer_deactivated (audience=operator). This helper is already THE choke
    # point — its own docstring says the router teardown handler and the lifecycle/sandbox tests
    # both call it "so the audit trail fires consistently" — so the notification belongs here for
    # exactly the same reason. Outside the try above on purpose: a failed audit emit must not also
    # swallow the human-facing notice.
    try:
        import asyncio as _aio_n
        from agentvault_registry.background_tasks.push_notify import notify_audience
        _aio_n.create_task(notify_audience(
            "federation.peer_deactivated",
            title="Federation peer deactivated",
            message=(f"{td_result.peer_snapshot.get('peer_name') or 'peer'} "
                     f"({application.name}) was deactivated: {reason}"),
            tags="warning", priority="high", click="/ui/#/admin/federation-topology"))
    except Exception:  # noqa: BLE001
        logger.debug("[NOTIFY] federation.peer_deactivated emit failed", exc_info=True)


# ── Helpers ──────────────────────────────────────────────────────────────

# ── §BATCH5: a child operator inherits its parent frame's POSTURE (the keys the fresh-network template pins) ──
PARENT_POSTURE_KEYS = (
    "REPUTATION_BOND_MODE", "REPUTATION_BOND_TREASURY_BACKSTOP", "ENFORCEMENT_SLASH_MODE", "ENFORCEMENT_PROPAGATION_MODE",
    "GATEWAY_REARM_ABANDONED_BATCH", "CANARY_REBALANCER_ENABLED", "CANARY_REFILL_ENABLED", "NETWORK_PROFILE",
    # §PROXYKEY 2026-09-11: API_TEST_EXECUTION_ENABLED LEFT this list. It is a ROLE (this node is a tester
    # console or target), not posture: EU runs it on as the sandbox tester's console, so amsterdam and lisbon
    # were born with execution on, no target (a run targets the operator itself) and the shared key at its
    # source literal. An operator now starts with the tester off unless someone turns it on deliberately.
    "TREASURY_MM_ENABLED", "LEGACY_CONTRACTS_ENABLED", "TOKEN_BRIDGE_ENABLED",
    "ARENA_BETTING_ENABLED", "REGISTRY_STAKING_CLAIM_REWARDS_ENABLED", "TEG_ONBOARDING_MINT_ENABLED",
    "TEG_STAKING_REWARD_CYCLE_ENABLED", "AGENT_RBAC_DEFAULT_ROLES", "LIABILITY_MODE",
    # §BATCH5 — the sync cadence is posture too: the source default is 600 s and the fleet runs 120
    # (§FEDTUNE); a fresh operator without the key waited ten minutes per cycle (JUICE pair, 2026-09-05).
    "FEDERATION_SYNC_INTERVAL_SECONDS",
    # §DIDWIDEN item 1 (2026-09-06): an operator mints under its parent's issuer namespace (= the shared
    # SPIFFE trust domain); an operator without the key would mint two-segment DIDs beside its parent's
    # three-segment ones.
    "DID_ISSUER_NAMESPACE",
    # §BATCH9 (2026-09-06, measured on the fresh pair): AUTHORITY is posture too. The three fresh operators ran with
    # AGENT_RBAC_MODE / AGENT_DELEGATION_MODE UNSET — the source default is `off`, byte-inert — so no agent on them was
    # authorized at all while their parent frames enforced IRONKEY; the same for spawn, the wallet anchor, inline SVIDs,
    # the guild, contracts and the venue flags every production operator carries. The pair moves together (PART 14).
    "AGENT_RBAC_MODE", "AGENT_DELEGATION_MODE", "AGENT_SPAWN_ENABLED", "AGENT_XREG_DELEGATION_ENABLED",
    "SPAWN_WALLET_ANCHOR_MODE", "IRONHAND_INLINE_SVID_ENABLED",
    # §DOCSFIX CB-222 (2026-10-16): the IRONKEY posture's circuit breaker travels with it (a kit frame runs it on).
    "CAPABILITY_CIRCUIT_BREAKER_ENABLED",
    "GUILD_ENABLED", "GUILD_ORG_BID_MODE", "GUILD_ZK_CREDENTIAL_ENABLED", "CONTRACTS_V2_ENABLED", "CONTRACT_TEMPLATES_ENABLED",
    "EXCHANGE_ENABLED", "EXCHANGE_MARKET_CARD_ENABLED", "EXCHANGE_CROSSFRAME_VOTE_ENABLED", "STOCK_CARD_SYNC_ENABLED",
    "JURISDICTION_MODE",
    # §DOCSFIX CB-236 (2026-10-16): the frame's governance binds its operators (services/env_catalog.py keeps these
    # frame-scoped and refuses them as an applicant's choice), and provisioning never wrote them: a new operator under
    # a member-mode frame voted by locked units, with no ballots, no commons and no presence check. The commons budget
    # cap travels with the commons (unset there means no cap).
    "GOVERNANCE_WEIGHT_MODE", "GOVERNANCE_PRESENCE_MODE", "FEDERATION_BALLOT_MODE", "COMMONS_ENABLED", "COMMONS_MAX_BUDGET",
    # §MCPTEST30 (V0644): what the registry states it is (core/registry_environment.py) travels from the frame, so a
    # sandbox frame's operators state "sandbox" without a hand edit and a production frame never gives birth to one
    # that does (the MCP tester stages money-moving fixtures only where the target itself says "sandbox").
    "REGISTRY_ENVIRONMENT",
)


def _parent_or(key: str, default: str) -> str:
    """The parent frame's own value (this process IS the parent), else the historical default."""
    v = os.getenv(key)
    return v if v not in (None, "") else default


def _inherit_parent_posture(f) -> list:
    """Write every posture key the parent carries into the child's env (later lines win in a compose env_file, so
    an inherited value overrides an earlier literal). Returns the keys written."""
    written = []
    for k in PARENT_POSTURE_KEYS:
        v = os.getenv(k)
        if v not in (None, ""):
            f.write(f"{k}={v}\n"); written.append(k)
    return written


def _write_env_choices(f, choices) -> list:
    """Write the env lines an applicant's choices mean (services/env_catalog.py) and return the names written.

    Validated again here, not trusted from the row: a choice the catalog refuses now (frame scope, an unknown key, an
    option a later catalog dropped) is logged and skipped, never written, so a hand-edited row cannot hand an operator
    a frame-exclusive switch."""
    from agentvault_registry.services.env_catalog import env_lines, validate_choices
    clean, errors = validate_choices(choices, "operator")
    for err in errors:
        logger.warning(f"[PROVISION] an applicant-chosen setting was not applied: {err}")
    written = []
    if clean:
        f.write("\n# §FESUITE V0595: the settings the applicant chose (operator_applications.env_choices)\n")
    for name, value in env_lines(clean):
        f.write(f"{name}={value}\n")
        written.append(name)
    return written


def _generate_env_file(path: str, safe_name: str):
    """Generate a minimal .env.operator if the bundle script didn't produce one."""
    import secrets as _s
    with open(path, 'w') as f:
        f.write(f"REGISTRY_NAME=cloud-op-{safe_name}\n")
        f.write(f"PG_PASS_REGISTRY={_s.token_hex(16)}\n")
        f.write(f"PG_PASS_TEG={_s.token_hex(16)}\n")
        f.write(f"JWT_SECRET_KEY={_s.token_hex(32)}\n")
        f.write(f"API_KEY_SECRET={_s.token_hex(32)}\n")
        f.write(f"TEG_ADMIN_API_KEY={_s.token_hex(32)}\n")
        f.write(f"TEG_TOKEN_SIGNING_KEY={_s.token_hex(32)}\n")
        # §RELEASECHANNEL (2026-09-21): a new operator hears about stable releases and hotfixes on the signed channel
        # (its admin schedules the rollout; `tp update` applies it). The check is a plain GET; false opts out.
        f.write("RELEASE_CHANNEL_CHECK_ENABLED=true\n")
        # §SOVKIT-2 R2 (2026-09-14): no EVENT_STORE_INTERNAL_API_KEY. A cloud operator writes to its parent frame's
        # store by SVID through the parent's mTLS edge, where nginx clears X-Internal-Key; the key only ever opened a
        # second, unused origin path (measured 12:35Z: 0 requests from an operator container on it). The literal
        # fallback that stood here was a retired sandbox store's value.
