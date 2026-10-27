"""
Operator Revocation Engine — Phase 3

Cascading revocation of operator access:
  1. Ban the operator's SPIRE node (it cannot re-attest; NEVER evicted, since an evict erases the ban)
  2. Delete its SPIRE workload entries: every one under /operator/<name>/, and the node's agent entries
  3. Remove Docker image registry credentials (DB-side since f050)

All Docker SDK calls go through the mounted /var/run/docker.sock.
Each step is best-effort — errors are collected but do not halt the cascade.
"""
import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

# §2026-06-14 — frame-aware: a Frame-B/C operator's SPIRE entries live on THAT
# frame's SPIRE server + trust domain, not Frame-A's. Resolve from env (the
# provision side already uses env-resolved _spire_container()/SPIRE_TRUST_DOMAIN).
# Module-level literals here silently no-op'd entry deletion for B/C operators.
SPIRE_CONTAINER = os.getenv("SPIRE_CONTAINER", "agentvault-spire-server")
SPIRE_BINARY = "/opt/spire/bin/spire-server"
TRUST_DOMAIN = os.getenv("SPIRE_TRUST_DOMAIN", "agentvault.com")


@dataclass
class RevokeResult:
    """Outcome of a cascading operator revocation."""
    spire_agent_banned: bool = False
    spire_entries_deleted: int = 0
    spire_agent_evicted: bool = False
    docker_creds_removed: bool = False
    errors: List[str] = field(default_factory=list)
    node_listed: Optional[bool] = None   # None = no fingerprint to look for; the runner's answer carries the same
    agent_entries: int = 0               # IRONHAND agent entries the operator's node parented, deleted with it


def _get_docker_client():
    """Get a Docker SDK client connected to the local socket."""
    try:
        import docker
        return docker.DockerClient(base_url="unix:///var/run/docker.sock")
    except ImportError:
        raise RuntimeError("Docker SDK (docker package) is not installed")
    except Exception as e:
        raise RuntimeError(f"Failed to connect to Docker socket: {e}")


def _revoke_through_runner(operator_name: str, fingerprint: str, result: RevokeResult,
                           sweep_path: bool = True) -> RevokeResult:
    from agentvault_registry.services import spire_ops_client as _soc
    try:
        r = _soc.call("operator_revoke_spire", timeout=120.0, operator=operator_name, fingerprint=fingerprint,
                      **({} if sweep_path else {"sweep_path": False}))
    except _soc.SpireOpsUnavailable as exc:
        result.errors.append(f"through the frame runner: {exc}")
        logger.error(f"[revoke:{operator_name}] SPIRE revocation through the frame runner refused: {exc}")
        return result
    result.spire_agent_banned = bool(r.get("banned"))
    result.spire_entries_deleted = int(r.get("entries_deleted") or 0)
    result.spire_agent_evicted = bool(r.get("evicted"))
    result.errors.extend(str(e) for e in (r.get("errors") or []))
    if not sweep_path and r.get("sweep_path") is not False:
        # a runner older than §OPPROV ignores the field and sweeps the whole path: say so, loudly, in the result
        result.errors.append("the frame runner did not confirm it withheld the path sweep (a runner older than §OPPROV "
                             "sweeps /operator/<name>/ whatever it is asked): check a namesake operator's entries")
    # a node that is not attested is a fact about the operator (a never-started one has none), not a failure of the
    # revoke: both halves report it the same way now, as node_listed, and neither counts it as an error
    result.node_listed = r.get("node_listed")
    result.agent_entries = int(r.get("agent_entries") or 0)
    logger.info(
        f"[revoke:{operator_name}] SPIRE revocation through the frame runner: banned={result.spire_agent_banned}, "
        f"entries_deleted={result.spire_entries_deleted}/{r.get('entries_found')}, evicted={result.spire_agent_evicted}, "
        f"errors={len(result.errors)}"
    )
    return result


def revoke_operator_spire(operator_name: str, fingerprint: str, sweep_path: bool = True) -> RevokeResult:
    """
    Revoke all SPIRE access for an operator: ban its node (never evict), delete its entries.

    `fingerprint` may be empty (an operator whose bundle failed after its entries were registered): the entries under
    /operator/<operator_name>/ are still deleted, and there is no node to ban. `sweep_path=False` withholds that sweep
    (only the node's own children go): the caller's answer when another live application holds the same name. Errors
    are collected, not raised.
    """
    result = RevokeResult()
    # §F6 WP6.2 slice 2: OPERATOR_LIFECYCLE_VIA=runner asks the frame runner's operator_revoke_spire, which runs the
    # same cascade (ban, delete; since 9a20c46 no evict) on THIS frame's SPIRE server and refuses a node that parents any
    # identity outside /operator/<operator_name>/ and /agent/. A refusal or a missing runner is an error in the result,
    # never the docker socket. §OPPROV: the socket half below now follows the same rule.
    from agentvault_registry.services.cloud_provisioner import operator_lifecycle_via
    try:
        via = operator_lifecycle_via()
    except RuntimeError as exc:
        result.errors.append(str(exc))
        return result
    if not sweep_path and not fingerprint:
        result.errors.append("neither a node nor the path to revoke: nothing was changed")
        return result
    if via == "runner":
        return _revoke_through_runner(operator_name, fingerprint, result, sweep_path)
    return _revoke_through_socket(operator_name, fingerprint, result, sweep_path)


def _revoke_through_socket(operator_name: str, fingerprint: str, result: RevokeResult,
                           sweep_path: bool = True) -> RevokeResult:
    """The same cascade as the runner's operator_revoke_spire, on this frame's SPIRE server through the docker socket.

    §OPPROV (2026-09-27), the legacy half brought to the runner's rule, because the two answered differently for one
    operator. Measured on sbx-beta (wp62opb): the order ban -> delete -> EVICT revoked nothing at the node, because an
    evict erases the ban on this SPIRE (1.10.4) and an x509pop node re-attests within 30 s ("Can re-attest: true"). So:
      * the node (from the row's fingerprint) is BANNED and never evicted; its banned record is the revocation;
      * every entry under spiffe://<td>/operator/<operator>/ is deleted, with or without a fingerprint, which is what
        a revoke of an operator whose bundle failed half-way needs (its entries were registered, its fingerprint never
        stored, and the route used to skip SPIRE entirely: wp62op's three entries outlived its revoke);
      * the node's IRONHAND agent entries (spiffe://<td>/agent/...) go with it only when the node also parents the
        operator's own entries, and a node that parents ANY other identity is refused with nothing changed, so a wrong
        fingerprint on a row can ban neither the frame's own node nor another operator's.
    """
    from agentvault_registry.services.frame_test_provisioner import parse_entry_show

    prefix = f"spiffe://{TRUST_DOMAIN}/operator/{operator_name}/"
    agent_prefix = f"spiffe://{TRUST_DOMAIN}/agent/"
    node = f"spiffe://{TRUST_DOMAIN}/spire/agent/x509pop/{fingerprint}" if fingerprint else None
    logger.info(f"[revoke:{operator_name}] Starting SPIRE revocation (node={node or 'none: no fingerprint on the row'})")

    try:
        container = _get_docker_client().containers.get(SPIRE_CONTAINER)
    except Exception as e:
        result.errors.append(f"Cannot connect to SPIRE container '{SPIRE_CONTAINER}': {e}")
        logger.error(f"[revoke:{operator_name}] {result.errors[-1]}")
        return result

    def _run(args):
        code, output = container.exec_run([SPIRE_BINARY] + args, demux=True)
        return (code, (output[0] or b"").decode(errors="replace"), (output[1] or b"").decode(errors="replace"))

    try:
        code, out, err = _run(["entry", "show"])
    except Exception as e:
        code, out, err = -1, "", str(e)
    if code != 0:
        result.errors.append(f"entry show failed (exit={code}): {err.strip()[:160]}; nothing was changed")
        logger.error(f"[revoke:{operator_name}] {result.errors[-1]}")
        return result
    entries = parse_entry_show(out)
    children = [e for e in entries if node and e.get("parent_id") == node]
    foreign = [e for e in children if not e["spiffe_id"].startswith((prefix, agent_prefix))]
    if foreign:
        result.errors.append(f"node {node} parents {len(foreign)} identities outside {prefix} and {agent_prefix}: it "
                             f"is not operator {operator_name}'s alone, so nothing was changed")
        logger.error(f"[revoke:{operator_name}] {result.errors[-1]}")
        return result
    agents = [e for e in children if e["spiffe_id"].startswith(agent_prefix)]
    if agents and not any(e["spiffe_id"].startswith(prefix) for e in children):
        result.errors.append(f"node {node} parents {len(agents)} agent identities and none of operator "
                             f"{operator_name}'s own, so they cannot be attributed to it; nothing was changed")
        logger.error(f"[revoke:{operator_name}] {result.errors[-1]}")
        return result
    targets = sorted({e["entry_id"] for e in (entries if sweep_path else children) if e["spiffe_id"].startswith(prefix)}
                     | {e["entry_id"] for e in agents})
    result.agent_entries = len(agents)

    if node:
        try:
            code, out, err = _run(["agent", "list"])
            result.node_listed = code == 0 and node in out
            if code != 0:
                result.errors.append(f"agent list failed (exit={code}): {err.strip()[:160]}")
            elif result.node_listed:
                code, out, err = _run(["agent", "ban", "-spiffeID", node])
                result.spire_agent_banned = code == 0
                if code != 0:
                    result.errors.append(f"Agent ban failed (exit={code}): {err.strip()[:160]}")
            else:
                logger.info(f"[revoke:{operator_name}] node {node} is not attested on this SPIRE server: "
                            f"nothing to ban")
        except Exception as e:
            result.errors.append(f"Agent ban exception: {e}")

    for entry_id in targets:
        try:
            code, out, err = _run(["entry", "delete", "-entryID", entry_id])
            if code == 0:
                result.spire_entries_deleted += 1
            else:
                result.errors.append(f"Entry delete failed for {entry_id} (exit={code}): {err.strip()[:160]}")
        except Exception as e:
            result.errors.append(f"Entry delete exception for {entry_id}: {e}")
    # no evict: it would erase the ban (see the docstring); spire_agent_evicted stays False

    logger.info(
        f"[revoke:{operator_name}] SPIRE revocation complete: node_listed={result.node_listed}, "
        f"banned={result.spire_agent_banned}, entries_deleted={result.spire_entries_deleted}/{len(targets)} "
        f"(agent entries {result.agent_entries}), evicted=False, errors={len(result.errors)}"
    )
    return result


def remove_docker_credentials(operator_name: str) -> bool:
    """
    Revoke Docker image registry access for the operator.

    f050: With token auth, revocation is handled at the DB layer by nullifying
    docker_pull_token_hash in the calling endpoint. The token auth server checks
    operator status on every token request, so revoked/suspended operators are
    immediately blocked. This function is kept for the revoke_operator()
    orchestrator but no longer manipulates htpasswd files.

    Returns True always (actual revocation is DB-side).
    """
    logger.info(
        f"[revoke:{operator_name}] Docker pull token revocation "
        f"delegated to DB layer (f050 token auth)"
    )
    return True


def revoke_operator(operator_name: str, fingerprint: str, reason: str, sweep_path: bool = True) -> RevokeResult:
    """
    Master revocation function: cascading revocation of all operator access.

    Steps:
      1. Revoke SPIRE access (ban + delete entries + evict)
      2. Remove Docker image registry credentials

    Returns a combined RevokeResult.
    """
    logger.info(
        f"[revoke:{operator_name}] === Starting cascading operator revocation === "
        f"(reason: {reason})"
    )

    # Step 1: SPIRE revocation
    result = revoke_operator_spire(operator_name, fingerprint, sweep_path)

    # Step 2: Docker credential removal
    result.docker_creds_removed = remove_docker_credentials(operator_name)

    logger.info(
        f"[revoke:{operator_name}] === Revocation complete === "
        f"banned={result.spire_agent_banned}, entries_deleted={result.spire_entries_deleted}, "
        f"evicted={result.spire_agent_evicted}, docker_removed={result.docker_creds_removed}, "
        f"errors={len(result.errors)}"
    )

    return result
