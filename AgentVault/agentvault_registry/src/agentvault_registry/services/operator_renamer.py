"""Operator IDENTITY re-slug orchestrator — rename Lane B.

Renames a cloud-operator's load-bearing SLUG (which IS its SPIFFE ID
`spiffe://{td}/operator/{slug}/*`) fleet-wide, preserving the op's DATA
(agents, balances, dev accounts). This is decommission-grade: an 8-phase
ordered cascade with quiesce, snapshot, per-phase status, verify gates and a
rollback path. Design + rationale: PRODUCTION_DOCS/06_OPERATIONS/Operator_Rename.md.

NOT for the common case — operators that just want a new human-facing name use
the zero-downtime DISPLAY rename (Lane A): POST /operator-portal/self-rename.

SAFETY MODEL
- Runs as a BACKGROUND task (the caller gets 202 + a pollable status); the long,
  blocking docker/DB/SPIRE work is wrapped in asyncio.to_thread so it never holds
  a gunicorn worker (the provisioning/teardown event-loop lesson).
- `dry_run=True` runs phases 0-1 (quiesce + snapshot + a connectivity/plan gate)
  and STOPS before any mutation — use this first on any target.
- Every phase is idempotent + updates `RENAME_STATUS[old_slug]`. A phase failure
  halts the cascade and (past the point of no safe return) triggers rollback from
  the Phase-1 snapshot.
- Reuses the proven provisioning/teardown helpers (register_spire_entries,
  _safe_name, the per-frame DB-coords + cross-frame purge, the UPSERT pattern).

STATUS: scaffolding + phases 0-3 implemented; phases 4-6 are structured against
the exact reuse points and gated behind `allow_mutating_phases` until each is
live-validated on qatest16 (Frame-A, smallest blast radius). Do NOT flip that
gate on a production op until the qatest16 dry-run + rollback is green.
"""
import asyncio
import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry.services import cloud_provisioner as _prov

logger = logging.getLogger(__name__)

# Host-vs-container path discipline (mirrors cloud_provisioner). The registry
# process sees the host /opt/theprotocol/stack at the bind mount /host-stack.
#  • In-process file ops (open / makedirs / shutil / os.path.exists) MUST use the
#    MOUNT path (the daemon resolves it for *us* inside the container).
#  • docker:cli sidecar bind-mounts MUST use the HOST path (the host daemon
#    resolves the source). Conflating them is the #1 host/container footgun.
_HOST_STACK = "/opt/theprotocol/stack"        # host path — for sidecar binds
_STACK_MOUNT = _prov.HOST_STACK_MOUNT         # "/host-stack" — for in-process file ops

# In-process status registry (keyed by OLD slug). A production build would back
# this with a DB table so status survives a worker restart; in-process is fine
# for the single-orchestrator-at-a-time model + matches simulation/admin status.
RENAME_STATUS: Dict[str, Dict[str, Any]] = {}

# Master safety gate for the mutating phases (4-6). Stays False until the
# qatest16 dry-run + rollback is proven; flip via env once validated.
_ALLOW_MUTATING = os.getenv("OPERATOR_RENAME_ALLOW_MUTATING", "false").lower() == "true"

# The identity-bearing op services (provisioner-template fixed). On a rename we
# recreate ONLY these under the new env — NEVER the data stores.
_IDENTITY_SERVICES = "registry teg-layer cert-writer nginx-federation"


def _identity_recreate(stack_host: str) -> None:
    """Recreate the identity services under their (already-rewritten) env. Two
    deliberate steps:
      1. STOP them first → releases the host-port bindings. A direct
         --force-recreate RACES on port release under load: the old teg's host
         port isn't freed before the new one binds → 'address already in use' →
         teg fails to start → the registry's `depends_on: teg-layer` never starts
         → op /health refused (the false verify-fail this whole thing chased).
      2. up -d --force-recreate --no-deps → recreate with the new env WITHOUT
         churning the data stores (db/teg-db/pgbouncer/redis/spire-agent stay UP,
         so teg-layer reaches its DB + goes healthy fast).
    Proven live on a frame-b op under load."""
    _compose(stack_host, f"stop {_IDENTITY_SERVICES}")
    _compose(stack_host, f"up -d --force-recreate --no-deps {_IDENTITY_SERVICES}")

_VALID_STATES = (
    "pending", "quiescing", "snapshotting", "plan_gate_ok", "stopping",
    "spire_reissue", "infra_recreate", "db_reidentify", "card_restamp",
    "verifying", "done", "failed", "rolled_back",
)
_TERMINAL_STATES = frozenset({"done", "failed", "rolled_back"})
# States that mean a cascade is actively running — the endpoint refuses a second
# concurrent rename of the same op while in any of these.
IN_FLIGHT_STATES = frozenset(s for s in _VALID_STATES if s not in _TERMINAL_STATES)


def _status_redis():
    """Sync Redis client for cross-worker rename status. The cascade runs as a bg
    task in ONE gunicorn worker; the status GET load-balances to ANOTHER worker —
    an in-process dict is invisible across them (status read 'none' post-success).
    Mirroring to Redis makes the record readable from any worker. Best-effort."""
    url = os.getenv("REDIS_URL")
    if not url:
        return None
    try:
        import redis as _redis
        return _redis.Redis.from_url(url, decode_responses=True,
                                     socket_connect_timeout=3, socket_timeout=3)
    except Exception:
        return None


def _set_status(old: str, state: str, **extra) -> None:
    rec = RENAME_STATUS.setdefault(old, {"old_slug": old, "phases": []})
    rec["state"] = state
    rec["updated_at_epoch"] = time.time()
    rec.update(extra)
    rec["phases"].append({"state": state, **{k: v for k, v in extra.items() if k != "phases"}})
    logger.info(f"[OP-RENAME {old}] → {state} {extra if extra else ''}")
    try:
        r = _status_redis()
        if r is not None:
            r.set(f"rename:status:{old}", json.dumps(rec, default=str), ex=7200)
    except Exception:
        pass


def get_rename_status(old_slug: str) -> Optional[Dict[str, Any]]:
    slug = _prov._safe_name(old_slug)
    st = RENAME_STATUS.get(slug)
    if st is not None:
        return st
    # cross-worker fallback: the cascade ran in a different worker → read Redis
    try:
        r = _status_redis()
        if r is not None:
            raw = r.get(f"rename:status:{slug}")
            if raw:
                return json.loads(raw)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

async def validate_rename(application: models.OperatorApplication, new_slug: str,
                          db: AsyncSession) -> Dict[str, Any]:
    """Pre-flight checks. Returns {ok, errors[], old_slug, new_slug, ...}.

    Cheap pure-Python checks run inline; the blocking docker/dir/psql collision
    probes are pushed off the event loop via asyncio.to_thread (the provision/
    teardown event-loop lesson — never run blocking docker on the loop)."""
    old = _prov._safe_name(application.name or "")
    new = _prov._safe_name(new_slug or "")
    errors: List[str] = []
    if not new or new == old:
        errors.append(f"new_slug must be a different valid slug (got {new!r} vs old {old!r})")
    if len(new) < 3 or len(new) > 40:
        errors.append("new_slug must be 3-40 chars [a-z0-9-]")
    # Only run the expensive collision probes if the cheap checks pass.
    if not errors:
        errors.extend(await asyncio.to_thread(_collision_checks, new))
    return {"ok": not errors, "errors": errors, "old_slug": old, "new_slug": new,
            "port_base": application.cloud_port_base, "operator_did": _prov._cloud_operator_did(application, old)}


def _collision_checks(new: str) -> List[str]:
    """Blocking collision probes (docker, stack dir, cross-frame peer name).
    Runs in a worker thread — never call directly on the event loop."""
    errors: List[str] = []
    try:
        import docker as _dk
        names = {c.name for c in _dk.from_env().containers.list(all=True, ignore_removed=True)}
        if any(n.startswith(f"cloud-op-{new}-") for n in names):
            errors.append(f"containers cloud-op-{new}-* already exist")
    except Exception as e:
        errors.append(f"container collision check failed: {e}")
    if os.path.exists(f"{_STACK_MOUNT}/cloud-op-{new}"):
        errors.append(f"stack dir cloud-op-{new} already exists")
    # New name must be free across all 3 frames' peer_registries
    for spec in _prov._ALL_FRAME_REG_DBS:
        try:
            ct, u, d = spec.strip().split(":")
            out = _dk_exec_psql(ct, u, d, f"select count(*) from peer_registries where name='{new}'")
            if out and out.strip() not in ("0", ""):
                errors.append(f"peer name {new!r} already taken on {ct}")
        except Exception as e:
            errors.append(f"peer-name check on {spec} failed: {e}")
    return errors


def _dk_exec_psql(container: str, user: str, db: str, sql: str) -> str:
    """Run a psql -tAc in a DB container, return stdout (best-effort)."""
    import docker as _dk
    ec, out = _dk.from_env().containers.get(container).exec_run(
        ["psql", "-U", user, "-d", db, "-tAc", sql], demux=True)
    return ((out[0] or b"").decode() if out else "").strip()


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def rename_operator(application: models.OperatorApplication, new_slug: str,
                          db: AsyncSession, *, dry_run: bool = False) -> Dict[str, Any]:
    """Full Lane-B cascade. Caller should run this as a background task.

    Returns the final status record. Raises only on validation; phase failures
    are captured in the status (state=failed|rolled_back).
    """
    pre = await validate_rename(application, new_slug, db)
    old, new = pre["old_slug"], pre["new_slug"]
    if not pre["ok"]:
        _set_status(old, "failed", errors=pre["errors"])
        return RENAME_STATUS[old]

    _set_status(old, "pending", new_slug=new, dry_run=dry_run)

    # ── Phase 0: QUIESCE ────────────────────────────────────────────────
    _set_status(old, "quiescing")
    await asyncio.to_thread(_phase0_quiesce, old)

    # ── Phase 1: SNAPSHOT (rollback point) ──────────────────────────────
    _set_status(old, "snapshotting")
    snap = await _phase1_snapshot(application, old, db)
    RENAME_STATUS[old]["snapshot_dir"] = snap.get("snapshot_dir")

    # ── Plan gate ───────────────────────────────────────────────────────
    _set_status(old, "plan_gate_ok", snapshot=snap)
    if dry_run:
        RENAME_STATUS[old]["note"] = "dry_run — stopped before any mutation. Review snapshot, then run with dry_run=false."
        _phase8_unquiesce(old)  # resume canaries; nothing was mutated
        return RENAME_STATUS[old]

    if not (_ALLOW_MUTATING or os.getenv("OPERATOR_RENAME_ALLOW_MUTATING", "").lower() == "true"):
        _set_status(old, "failed",
                    note="Mutating phases (4-6) are gated OFF until the qatest16 dry-run+rollback is proven. "
                         "Set OPERATOR_RENAME_ALLOW_MUTATING=true to enable (see Operator_Rename.md).")
        _phase8_unquiesce(old)
        return RENAME_STATUS[old]

    try:
        # ── Phase 2: STOP (keep volumes) ────────────────────────────────
        _set_status(old, "stopping")
        await asyncio.to_thread(_phase2_stop, old)

        # ── Phase 3: SPIRE re-issue ─────────────────────────────────────
        _set_status(old, "spire_reissue")
        await asyncio.to_thread(_phase3_spire_reissue, old, new, application)

        # ── Phase 4: infra recreate under new slug ──────────────────────
        _set_status(old, "infra_recreate")
        await asyncio.to_thread(_phase4_infra_recreate, old, new, application)

        # ── Phase 5: cross-frame DB re-identify ─────────────────────────
        _set_status(old, "db_reidentify")
        await _phase5_db_reidentify(application, old, new, db)

        # ── Phase 6: agent-card re-stamp + propagate ────────────────────
        _set_status(old, "card_restamp")
        await asyncio.to_thread(_phase6_restamp_cards, old, new)

        # ── Phase 7: restart + verify ───────────────────────────────────
        _set_status(old, "verifying")
        gate = await asyncio.to_thread(_phase7_verify, new, application)
        RENAME_STATUS[old]["verify"] = gate
        if not gate.get("ok"):
            raise RuntimeError(f"verify gate failed: {gate.get('failures')}")

        _set_status(old, "done", new_slug=new)
    except Exception as e:
        logger.error(f"[OP-RENAME {old}] cascade failed: {e} — attempting rollback")
        try:
            await _rollback(old, new, application, snap)
            _set_status(old, "rolled_back", error=str(e)[:300])
        except Exception as re:
            _set_status(old, "failed", error=str(e)[:200], rollback_error=str(re)[:200],
                        note="ROLLBACK FAILED — manual recovery from snapshot required")
    finally:
        _phase8_unquiesce(old)

    # §dedup-sweep — federation_sync may have re-materialized the transient identity
    # as a NEW peer row on a peer during the cascade window (the rollback-path dup).
    # After settling, wait for any in-flight fed-sync cycle to land, then re-emit the
    # CANONICAL rename ONCE: the reactor fans out apply()+dedup (delete-stale-when-
    # both-exist) → collapses any duplicate to a single canonical row. Idempotent,
    # best-effort, and cheaper/safer than gating federation_sync fleet-wide.
    _final = RENAME_STATUS.get(old, {}).get("state")
    if _final in ("done", "rolled_back"):
        canonical, stale = (new, old) if _final == "done" else (old, new)
        try:
            await asyncio.sleep(12)
            from agentvault_registry.event_emitter import get_event_emitter
            await get_event_emitter().emit_event(
                aggregate_id=f"operator:{old}", event_type="OperatorRenamed",
                event_data={"old_slug": stale, "new_slug": canonical,
                            "new_base_url": f"https://{canonical}.{_prov.CLOUD_DOMAIN_SUFFIX}:8443",
                            "home_frame": os.getenv("SPIRE_TRUST_DOMAIN", ""),
                            "actor": "rename_dedup_sweep"},
            )
            logger.info(f"[OP-RENAME {old}] dedup-sweep re-emitted {stale}->{canonical}")
        except Exception as e:
            logger.warning(f"[OP-RENAME {old}] dedup-sweep failed: {e}")

    return RENAME_STATUS[old]


# ---------------------------------------------------------------------------
# Phase 0-3 (implemented — reuse existing patterns)
# ---------------------------------------------------------------------------

def _phase0_quiesce(old: str) -> None:
    """Pause canaries fleet-wide (so a renamed op doesn't trip dispatch mid-flip).
    Best-effort. The sim, if running, is left to the operator to stop from the FE."""
    try:
        import httpx
        # registry-a master canary pause (in-cluster, internal)
        with httpx.Client(timeout=10.0, verify=False) as c:
            c.post("http://localhost:8000/api/v1/admin/canary/fleet/pause",
                   headers={"X-Internal-Key": os.getenv("INTERNAL_API_KEY", "")})
    except Exception as e:
        logger.warning(f"[OP-RENAME {old}] canary pause best-effort failed: {e}")


def _phase8_unquiesce(old: str) -> None:
    try:
        import httpx
        with httpx.Client(timeout=10.0, verify=False) as c:
            c.post("http://localhost:8000/api/v1/admin/canary/fleet/resume",
                   headers={"X-Internal-Key": os.getenv("INTERNAL_API_KEY", "")})
    except Exception as e:
        logger.warning(f"[OP-RENAME {old}] canary resume best-effort failed: {e}")


async def _phase1_snapshot(application: models.OperatorApplication, old: str,
                           db: AsyncSession) -> Dict[str, Any]:
    """Capture rollback state: identity strings, native agent DIDs, peer/ES rows,
    and pg_dump of the op's registry + teg DBs into a snapshot dir."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    snap_dir_host = f"{_HOST_STACK}/.rename-snapshots/{old}-{ts}"   # host ref (status/rollback)
    snap_dir = f"{_STACK_MOUNT}/.rename-snapshots/{old}-{ts}"        # in-process writes
    snap: Dict[str, Any] = {
        "old_slug": old, "snapshot_dir": snap_dir_host,
        "operator_did": _prov._cloud_operator_did(application, old),
        "cloud_port_base": application.cloud_port_base,
        "cloud_url": application.cloud_url,
        "spire_fingerprint": application.spire_fingerprint,
        "docker_registry_username": application.docker_registry_username,
    }

    def _dump() -> None:
        os.makedirs(snap_dir, exist_ok=True)
        # copy the op's .env.operator + compose for rollback of infra rewrite
        srcdir = f"{_STACK_MOUNT}/cloud-op-{old}"
        for f in (".env.operator", "docker-compose.operator.yml"):
            p = os.path.join(srcdir, f)
            if os.path.exists(p):
                shutil.copy2(p, os.path.join(snap_dir, f))
        # Snapshot ONLY the identity tables the rename actually mutates —
        # registry_self + agent_cards — NOT a full pg_dumpall. A whole-cluster
        # dump (a) buffers the ENTIRE DB in THIS worker's RAM via exec_run(demux)
        # (op-tokyo registry DB = 4GB: agent_requests 2GB + transaction_fee_records
        # 1.3GB → multi-minute hang + a 4GB memory spike on the home worker) and
        # (b) is pointless: the rename never touches the transaction/balance tables
        # or the TEG ledger. The targeted -t dump is small (registry_self=1 row,
        # agent_cards≈native-agent-count) → sub-second, low-memory, and IS the
        # exact recovery artifact for what's at risk.
        import docker as _dk
        cont = f"cloud-op-{old}-db"
        try:
            c = _dk.from_env().containers.get(cont)
            ec, out = c.exec_run(
                ["sh", "-c",
                 "pg_dump -U registry -d agentvault_registry -t registry_self -t agent_cards 2>/dev/null"],
                demux=True)
            with open(os.path.join(snap_dir, "identity_tables.sql"), "wb") as fh:
                fh.write((out[0] or b"") if out else b"")
        except Exception as e:
            logger.warning(f"[OP-RENAME {old}] identity-table snapshot failed: {e}")
        with open(os.path.join(snap_dir, "snapshot.json"), "w") as fh:
            json.dump(snap, fh, indent=1, default=str)

    # native agent DIDs (the cards that will need origin re-stamp)
    try:
        rows = (await db.execute(
            select(models.Agent.did).limit(10000)
        )).scalars().all()
        snap["native_agent_count"] = len(rows)
    except Exception:
        snap["native_agent_count"] = None
    await asyncio.to_thread(_dump)
    return snap


def _phase2_stop(old: str) -> None:
    """In-place re-identify model: do NOT pre-stop the op. Its DB must stay UP so
    Phase-4 can write the op's OWN registry_self + native card origins to a LIVE
    DB — a pre-stop left `cloud-op-{old}-db` down → `psql exec 409 container is
    restarting` → the op's identity was never applied (the bug). Phase-4's
    `up -d --force-recreate` IS the restart that picks up the new env + new SVID.
    Kept as a phase for status/ordering symmetry."""
    logger.info(f"[OP-RENAME {old}] phase2: in-place model — op left UP "
                f"(phase-4 force-recreate restarts it after the op-DB identity writes)")


def _phase3_spire_reissue(old: str, new: str, application: models.OperatorApplication) -> None:
    """Register operator/{new}/{registry,svid-writer,teg} on this frame's SPIRE,
    then delete operator/{old}/* . Reuses operator_provisioner.register_spire_entries."""
    from agentvault_registry.services import operator_provisioner as _op
    fp = application.spire_fingerprint or ""
    # §2026-06-15: cross-frame federation mTLS dials the CURRENT `{slug}.op.theprotocol.cloud`
    # domain (see teg_integration._to_internal_mtls_url) — the legacy `{slug}.{CLOUD_DOMAIN_SUFFIX}`
    # (e.g. frame-b.theprotocol.cloud) is kept ONLY as a 2nd SAN for base_url RC-sync back-compat.
    # Issuing the legacy SAN alone froze every renamed frame-b op's cross-frame card cache
    # (peers got CERTIFICATE_VERIFY_FAILED hostname mismatch). Superset both.
    domain = [f"{new}.op.theprotocol.cloud", f"{new}.{_prov.CLOUD_DOMAIN_SUFFIX}"]
    _op.register_spire_entries(new, fp, domain)   # creates /operator/{new}/*
    # delete old entries (frame-aware via the teardown helper)
    _prov._delete_op_spire_entries(old)


# ---------------------------------------------------------------------------
# Phase 4-6 — EVENT-SOURCED in-place re-identify (§2026-06-14). KEEPS the op's
# container/volume/dir names (cloud-op-{old}-*) — only IDENTITY changes, no data
# move (scout-verified: SPIRE selectors are docker:labels, registry→TEG is the
# `teg-layer` service name — nothing load-bearing binds to the container name).
# Cross-frame convergence is the OperatorRenamed event + reactor fanout (phase 5),
# NOT direct cross-frame SQL.
# ---------------------------------------------------------------------------

def _rewrite_env_keys(env_mount_path: str, kv: Dict[str, str]) -> None:
    """In-process rewrite of specific KEY=value lines in .env.operator (mount path
    under /host-stack). Existing keys replaced; missing keys appended."""
    try:
        with open(env_mount_path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        lines = []
    seen, out = set(), []
    for line in lines:
        parts = line.split("=", 1)
        k = parts[0].strip() if len(parts) == 2 else None
        if k in kv:
            out.append(f"{k}={kv[k]}\n")
            seen.add(k)
        else:
            out.append(line)
    for k, v in kv.items():
        if k not in seen:
            out.append(f"{k}={v}\n")
    with open(env_mount_path, "w") as f:
        f.writelines(out)


def _dk_exec(container: str, cmd: list) -> tuple:
    import docker as _dk
    return _dk.from_env().containers.get(container).exec_run(cmd, demux=True)


def _op_db_write(old: str, sql: str) -> str:
    """Run a psql -c write on the OP's OWN registry DB (cloud-op-{old}-db). This is
    the op's own data (registry_self / its native agent_cards) — LOCAL, not the
    forbidden cross-frame mutation."""
    try:
        ec, out = _dk_exec(f"cloud-op-{old}-db",
                           ["psql", "-U", "registry", "-d", "agentvault_registry", "-c", sql])
        err = (out[1] or b"").decode()[:160] if out and len(out) > 1 and out[1] else ""
        return f"ec={ec} {err}".strip()
    except Exception as e:
        return f"op-db-write failed: {str(e)[:120]}"


def _home_es_coords() -> tuple:
    """(container, user, db) of THIS (home) frame's EventStore DB, from SPIRE_TRUST_DOMAIN."""
    td = (os.getenv("SPIRE_TRUST_DOMAIN", "agentvault.com") or "").strip()
    for spec in _prov._ALL_FRAME_ES_DBS:
        try:
            ct, u, d = spec.strip().split(":")
        except ValueError:
            continue
        if td.startswith("frame-b") and ct.startswith("frame-b"):
            return (ct, u, d)
        if td.startswith("frame-c") and ct.startswith("frame-c"):
            return (ct, u, d)
    return ("agentvault_event_store_db", "postgres", "eventstore")  # frame-a default


def _op_nginx_locations(reg_port: int) -> str:
    """Per-op nginx location blocks (mirrors cloud_provisioner Step 6) — backend
    127.0.0.1:{reg_port}, parent-frame WS event proxy, local WS."""
    ws_host = _prov._frame_ws_events_host()  # parent frame's WS edge, not Frame A's
    return f"""    location /ws/events {{
        proxy_pass https://{ws_host}/ws/events;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host {ws_host};
        proxy_read_timeout 86400s;
        proxy_ssl_server_name on;
    }}
    location /ws/ {{
        proxy_pass http://127.0.0.1:{reg_port}/api/v1/ws/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400s;
    }}
    location /api/v1/ws {{
        proxy_pass http://127.0.0.1:{reg_port}/api/v1/ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400s;
    }}
    location / {{
        proxy_pass http://127.0.0.1:{reg_port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # 🔴 findings row 194 — pin the headers the app treats as proof of identity. A rename
        # REWRITES this vhost, so leaving it out here would silently undo the provisioner's
        # pinning the next time an operator is renamed (§FANOUTFIX: fix every site asking the
        # old question, not just the first one you found).
        proxy_set_header X-SSL-Client-Cert   $ssl_client_escaped_cert;
        proxy_set_header X-SSL-Client-Verify $ssl_client_verify;
        proxy_set_header X-SSL-Client-S-DN   $ssl_client_s_dn;
        proxy_set_header X-Federation-Secret $http_x_federation_secret;
        proxy_set_header X-Federation-SPIFFE-ID $http_x_federation_spiffe_id;
    }}"""


def _update_op_nginx(old: str, new: str, new_domain: str, fed_port: int, reg_port: int) -> None:
    """REGENERATE the op's public HOST nginx vhost for the NEW slug.

    §2026-06-15 (V0098) — the old `content.replace(old_domain,new_domain)` only
    touched the `.{CLOUD_DOMAIN_SUFFIX}` substring and left the `.op.` server block
    (and any missing block) stale → a renamed op's card URL SSL-errored until a
    hand-fix. Now writes a fresh self-contained vhost serving BOTH
    `{new}.op.theprotocol.cloud` (the card's public_url — universal `*.op`
    wildcard cert) AND, for frame-b/c ops, `{new}.{CLOUD_DOMAIN_SUFFIX}` (the frame
    wildcard cert). In-place keeps the filename `cloud-op-{old}`. Backend :reg_port.
    """
    suffix = (_prov.CLOUD_DOMAIN_SUFFIX or "op.theprotocol.cloud").strip()
    loc = _op_nginx_locations(reg_port)
    names = [f"{new}.op.theprotocol.cloud"]
    blocks = [f"""server {{
    listen 443 ssl http2;
    server_name {new}.op.theprotocol.cloud;
    ssl_certificate /etc/letsencrypt/live/op.theprotocol.cloud/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/op.theprotocol.cloud/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    # 🔴 findings row 196 — an operator console served NO security headers at all. One source
    # of truth (§SEOPASS-3); SERVER level because an add_header inside a location wipes every
    # inherited one, so no location in this vhost may set one.
    include snippets/theprotocol-security-headers.conf;
{loc}
}}"""]
    if suffix and suffix != "op.theprotocol.cloud":
        names.append(f"{new}.{suffix}")
        blocks.append(f"""server {{
    listen 443 ssl http2;
    server_name {new}.{suffix};
    ssl_certificate /etc/letsencrypt/live/{_prov.SSL_CERT_NAME}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{_prov.SSL_CERT_NAME}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    # 🔴 findings row 196 — an operator console served NO security headers at all. One source
    # of truth (§SEOPASS-3); SERVER level because an add_header inside a location wipes every
    # inherited one, so no location in this vhost may set one.
    include snippets/theprotocol-security-headers.conf;
{loc}
}}""")
    vhost = (f"# Cloud-op {new} nginx — renamed in-place from {old} "
             f"(§2026-06-15 V0098 regenerated). Backend 127.0.0.1:{reg_port}.\n"
             f"server {{\n    listen 80;\n    server_name {' '.join(names)};\n"
             f"    return 301 https://$host$request_uri;\n}}\n\n"
             + "\n\n".join(blocks) + "\n")
    vhost_path = f"{_prov.HOST_NGINX_MOUNT}/cloud-op-{old}"
    try:
        with open(vhost_path, "w") as f:
            f.write(vhost)
    except Exception as e:
        logger.warning(f"[OP-RENAME {old}] vhost regenerate failed: {e}")
    _prov._run('docker run --rm --network=host --pid=host --privileged '
               'alpine nsenter -t 1 -m -u -n -i sh -c "nginx -t && nginx -s reload"', timeout=20)
    # Stream-SNI map: peers fetch the op's card via base_url
    # `{slug}.{CLOUD_DOMAIN_SUFFIX}:8443` (frame-b/c) or `{slug}.op…:8443` (frame-a),
    # routed by SNI → the op's host fed_port. §2026-06-15 (V0098) — the rename
    # MUST add the NEW-slug routes for BOTH the base_url domain (.{suffix}) AND the
    # .op. alias, and REMOVE the old-slug routes — else peers can't reach the
    # renamed op's card (SNI falls through to default → cert mismatch → the
    # stale-card freeze seen on op-newyork). Script is idempotent + self-reloads.
    _sni = ('docker run --rm --network=host --pid=host --privileged alpine '
            'nsenter -t 1 -m -u -n -i '
            '/opt/theprotocol/stack/Agentvault2/scripts/extend_stream_sni_map.sh ')
    _add = {f"{new}.{suffix}", f"{new}.op.theprotocol.cloud"}
    _del = {f"{old}.{suffix}", f"{old}.op.theprotocol.cloud"} - _add
    for d in _add:
        _prov._run(_sni + f"{d} {fed_port}", timeout=20)
    for d in _del:
        _prov._run(_sni + f"--remove {d}", timeout=20)


def _phase4_infra_recreate(old: str, new: str, application: models.OperatorApplication) -> None:
    """In-place identity re-identify — KEEP container/volume/dir names. Rewrites the
    op's identity env + its OWN DB (registry_self + native card origins) + nginx
    vhost/SNI, then `docker compose up -d --force-recreate` (op re-fetches the new
    /operator/{new}/* SVID; cert-writer serves the new identity)."""
    port_base = int(application.cloud_port_base or 0)
    fed_port = port_base + 43
    new_domain = f"{new}.{_prov.CLOUD_DOMAIN_SUFFIX}"
    stack_mount = f"{_STACK_MOUNT}/cloud-op-{old}"
    stack_host = f"{_HOST_STACK}/cloud-op-{old}"
    # 1) .env.operator identity keys (KEEP REGISTRY_NAME=cloud-op-{old} → containers stay)
    _rewrite_env_keys(f"{stack_mount}/.env.operator", {
        "REGISTRY_FEDERATION_NAME": new,
        "REGISTRY_SAFE_NAME": new,
        # public_url = the :443 web URL (host nginx vhost), NOT :fed_port (mTLS).
        # §2026-06-15 — was f"https://{new_domain}:{fed_port}" → unreachable card
        # link. Use the fleet-standard .op.theprotocol.cloud public domain.
        "PUBLIC_URL": f"https://{new}.op.theprotocol.cloud",
        "TEG_ID": f"teg-{new}",
    })
    # 2) op's OWN registry DB: registry_self.federation_name (env will NOT update it;
    #    migration 0061 is ON CONFLICT DO NOTHING → explicit UPSERT, the provisioner pattern)
    r1 = _op_db_write(old, "INSERT INTO registry_self (id, federation_name) "
                           f"VALUES (1, '{new}') ON CONFLICT (id) DO UPDATE SET "
                           "federation_name = EXCLUDED.federation_name, updated_at = NOW();")
    # 3) op's OWN native agent_cards origin re-stamp (local to the op)
    #    §JSONCAST (2026-09-05, agentvault2-07's sweep): `card_data` is `json` on the four older
    #    Frame-A operators, so an UNCAST jsonb_set over it failed at PARSE time there — forward AND
    #    in the rollback below, which is the worse half. Cast the argument; the jsonb result
    #    assigns into either column type (proved on op-berlin, WHERE false, rolled back).
    r2 = _op_db_write(old, "UPDATE agent_cards SET card_data = jsonb_set(card_data::jsonb, "
                           f"'{{federation_metadata,origin_registry_name}}', to_jsonb('{new}'::text)) "
                           f"WHERE card_data->'federation_metadata'->>'origin_registry_name' = '{old}';")
    logger.info(f"[OP-RENAME {old}] op-DB re-identify: registry_self[{r1}] cards[{r2}]")
    # 4) nginx vhost regenerate (new-slug .op. + .{suffix} blocks) + SNI map (host)
    _update_op_nginx(old, new, new_domain, fed_port, port_base)
    # 5) recreate the identity services (KEEP names; pick up new env + new SVID)
    _identity_recreate(stack_host)


def _update_home_es(old: str, new: str) -> str:
    """UPDATE the HOME frame's ES federation_operators row to the new SPIFFE
    (the op emits balance events to its home ES only)."""
    ct, u, d = _home_es_coords()
    td = (os.getenv("SPIRE_TRUST_DOMAIN", "agentvault.com") or "").strip()
    new_spiffe = f"spiffe://{td}/operator/{new}/registry"
    sql = (f"UPDATE federation_operators SET spiffe_id='{new_spiffe}', operator_name='cloud-op-{new}' "
           f"WHERE spiffe_id LIKE '%/operator/{old}/%' OR operator_name='cloud-op-{old}';")
    try:
        ec, _ = _dk_exec(ct, ["psql", "-U", u, "-d", d, "-c", sql])
        logger.info(f"[OP-RENAME {old}] home ES federation_operators → {new_spiffe} (ec={ec})")
        return f"ec={ec}"
    except Exception as e:
        logger.warning(f"[OP-RENAME {old}] home ES update failed: {e}")
        return f"failed: {str(e)[:100]}"


async def _phase5_db_reidentify(application: models.OperatorApplication, old: str,
                                new: str, db: AsyncSession) -> None:
    """HOME-frame LOCAL apply + EMIT OperatorRenamed. The peer frames converge via
    the event → reactor → fanout (NO direct cross-frame SQL here)."""
    from agentvault_registry.services.operator_rename_apply import apply_operator_rename_local
    new_base_url = f"https://{new}.{_prov.CLOUD_DOMAIN_SUFFIX}:8443"
    # 1) home frame's OWN rows (peer_registries name/base_url in place + agent_cards origin)
    home = await apply_operator_rename_local(
        db, old_slug=old, new_slug=new, new_base_url=new_base_url, actor="rename_trigger_home")
    RENAME_STATUS[old]["home_apply"] = home
    # 2) home ES federation_operators → new SPIFFE
    RENAME_STATUS[old]["home_es"] = await asyncio.to_thread(_update_home_es, old, new)
    # 3) EMIT OperatorRenamed → reactor_operator_renamed fans out to peer frames
    try:
        from agentvault_registry.event_emitter import get_event_emitter
        await get_event_emitter().emit_event(
            aggregate_id=f"operator:{old}",
            event_type="OperatorRenamed",
            event_data={
                "old_slug": old, "new_slug": new, "new_base_url": new_base_url,
                "home_frame": os.getenv("SPIRE_TRUST_DOMAIN", ""), "actor": "rename_trigger",
            },
        )
        RENAME_STATUS[old]["event_emitted"] = True
        logger.info(f"[OP-RENAME {old}] emitted OperatorRenamed → reactor will fan to peers")
    except Exception as e:
        logger.error(f"[OP-RENAME {old}] emit OperatorRenamed FAILED: {e}")
        RENAME_STATUS[old]["event_emitted"] = False


def _phase6_restamp_cards(old: str, new: str) -> None:
    """Trigger a federation-sync round so the op's freshly-served {new} card is
    re-pulled by peers (the reactor already converged peer_registries + origin;
    this refreshes the cached_registry_card). Best-effort."""
    try:
        import httpx
        with httpx.Client(timeout=15.0, verify=False) as c:
            c.post("http://localhost:8000/api/v1/federation/sync/trigger")
    except Exception as e:
        logger.warning(f"[OP-RENAME {old}] fed-sync trigger best-effort failed: {e}")


def _phase7_verify(new: str, application: models.OperatorApplication) -> Dict[str, Any]:
    """Verify the op survived the identity flip — checked via `docker exec` INTO the
    op's OWN registry container.

    CRITICAL (the bug that masked every run): this cascade runs INSIDE the home
    registry container, where `http://localhost:<op-host-port>` is NOT the op — the
    op's port is host-mapped, so the home container's localhost has nothing there →
    Connection refused, regardless of whether the op actually booted. So we exec the
    op's own health/card check inside `cloud-op-{old}-registry` (localhost:8000 THERE
    is the op) — host-context-independent. Container name is KEPT (in-place model)."""
    old = _prov._safe_name(application.name or "")
    op_reg = f"cloud-op-{old}-registry"
    failures: List[str] = []
    _HEALTH = ("import urllib.request,sys;"
               "sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health',timeout=4).getcode()==200 else 1)")
    # readiness — exec the op's own /health until it answers (op boots in ~40-60s)
    ready, last, deadline = False, "", time.time() + 240
    while time.time() < deadline:
        try:
            ec, _ = _dk_exec(op_reg, ["python3", "-c", _HEALTH])
            if ec == 0:
                ready = True
                break
            last = f"op /health exec ec={ec}"
        except Exception as e:
            last = f"op exec err: {str(e)[:80]}"
        time.sleep(3)
    if not ready:
        return {"ok": False, "failures": [f"op did not become ready within 240s ({last})"]}
    # identity gate — the op's served card must reflect the new slug
    _CARD = ("import urllib.request,json;"
             "d=json.load(urllib.request.urlopen('http://localhost:8000/.well-known/registry-card.json',timeout=6));"
             "i=d.get('identity',{});print((i.get('registry_name') or '')+'|'+(i.get('spiffe_id') or ''))")
    try:
        ec, out = _dk_exec(op_reg, ["python3", "-c", _CARD])
        txt = ((out[0] or b"").decode().strip() if out and out[0] else "")
        if new not in txt:
            failures.append(f"card identity not {new}: {txt[:140]}")
    except Exception as e:
        failures.append(f"card identity exec failed: {str(e)[:100]}")
    return {"ok": not failures, "failures": failures}


async def _rollback(old: str, new: str, application: models.OperatorApplication,
                    snap: Dict[str, Any]) -> None:
    """Reverse a failed cascade back to {old} — idempotent + best-effort per step
    (each isolated; rollback never raises). The cascade may have reached Phase 5/6
    (home rows + ES flipped to {new}, OperatorRenamed emitted, peers fanned), so
    this REVERSES the home-side state AND emits a COMPENSATING OperatorRenamed
    (new→old) so the reactor un-fans the peers. Safe even on an early failure: every
    reversal no-ops when there's nothing at {new} to undo."""
    port_base = int(application.cloud_port_base or 0)
    fed_port = port_base + 43
    old_domain = f"{old}.{_prov.CLOUD_DOMAIN_SUFFIX}"
    new_domain = f"{new}.{_prov.CLOUD_DOMAIN_SUFFIX}"
    stack_mount = f"{_STACK_MOUNT}/cloud-op-{old}"
    stack_host = f"{_HOST_STACK}/cloud-op-{old}"

    # 1) op's identity env back to {old}
    try:
        await asyncio.to_thread(_rewrite_env_keys, f"{stack_mount}/.env.operator", {
            "REGISTRY_FEDERATION_NAME": old, "REGISTRY_SAFE_NAME": old,
            "PUBLIC_URL": f"https://{old}.op.theprotocol.cloud", "TEG_ID": f"teg-{old}",
        })
    except Exception as e:
        logger.warning(f"[OP-RENAME {old}] rollback env restore failed: {e}")

    # 2) op's OWN DB back to {old} (in-place model keeps the DB UP)
    try:
        await asyncio.to_thread(_op_db_write, old,
            "INSERT INTO registry_self (id, federation_name) "
            f"VALUES (1, '{old}') ON CONFLICT (id) DO UPDATE SET "
            "federation_name = EXCLUDED.federation_name, updated_at = NOW();")
        await asyncio.to_thread(_op_db_write, old,
            "UPDATE agent_cards SET card_data = jsonb_set(card_data::jsonb, "
            f"'{{federation_metadata,origin_registry_name}}', to_jsonb('{old}'::text)) "
            f"WHERE card_data->'federation_metadata'->>'origin_registry_name' = '{new}';")
    except Exception as e:
        logger.warning(f"[OP-RENAME {old}] rollback op-DB restore failed: {e}")

    # 3) HOME frame's OWN rows back (peer_registries + agent_cards origin) — apply new→old
    try:
        from agentvault_registry.database import AsyncSessionLocal
        from agentvault_registry.services.operator_rename_apply import apply_operator_rename_local
        async with AsyncSessionLocal() as rb_db:
            await apply_operator_rename_local(
                rb_db, old_slug=new, new_slug=old,
                new_base_url=f"https://{old_domain}:8443", actor="rename_rollback_home")
    except Exception as e:
        logger.warning(f"[OP-RENAME {old}] rollback home apply failed: {e}")

    # 4) HOME ES federation_operators back to the old SPIFFE
    try:
        await asyncio.to_thread(_update_home_es, new, old)
    except Exception as e:
        logger.warning(f"[OP-RENAME {old}] rollback home ES restore failed: {e}")

    # 5) COMPENSATING reverse-rename event → reactor un-fans the peers (new→old)
    try:
        from agentvault_registry.event_emitter import get_event_emitter
        await get_event_emitter().emit_event(
            aggregate_id=f"operator:{old}", event_type="OperatorRenamed",
            event_data={"old_slug": new, "new_slug": old,
                        "new_base_url": f"https://{old_domain}:8443",
                        "home_frame": os.getenv("SPIRE_TRUST_DOMAIN", ""),
                        "actor": "rename_rollback"})
        logger.info(f"[OP-RENAME {old}] rollback emitted compensating rename {new}→{old}")
    except Exception as e:
        logger.warning(f"[OP-RENAME {old}] rollback compensating emit failed: {e}")

    # 6) nginx vhost server_name back to the old domain + reload
    def _vhost_back():
        vp = f"{_prov.HOST_NGINX_MOUNT}/cloud-op-{old}"
        with open(vp) as f:
            content = f.read()
        with open(vp, "w") as f:
            f.write(content.replace(new_domain, old_domain))
        _prov._run('docker run --rm --network=host --pid=host --privileged '
                   'alpine nsenter -t 1 -m -u -n -i sh -c "nginx -t && nginx -s reload"', timeout=20)
    try:
        await asyncio.to_thread(_vhost_back)
    except Exception as e:
        logger.warning(f"[OP-RENAME {old}] rollback vhost restore failed: {e}")

    # 7) SPIRE — re-register {old}, delete {new}
    def _spire_back():
        from agentvault_registry.services import operator_provisioner as _op
        try:
            _op.register_spire_entries(old, application.spire_fingerprint or "",
                                       [f"{old}.op.theprotocol.cloud", f"{old}.{_prov.CLOUD_DOMAIN_SUFFIX}"])
        except Exception as e:
            logger.warning(f"[OP-RENAME {old}] rollback SPIRE re-register {old} failed: {e}")
        try:
            _prov._delete_op_spire_entries(new)
        except Exception as e:
            logger.warning(f"[OP-RENAME {old}] rollback SPIRE delete {new} failed: {e}")
    try:
        await asyncio.to_thread(_spire_back)
    except Exception as e:
        logger.warning(f"[OP-RENAME {old}] rollback SPIRE step failed: {e}")

    # 8) recreate the op under the restored {old} env + {old} SVID
    try:
        if os.path.exists(stack_mount):
            await asyncio.to_thread(_identity_recreate, stack_host)
    except Exception as e:
        logger.warning(f"[OP-RENAME {old}] rollback recreate failed: {e}")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _compose(stack_dir_host: str, action: str) -> None:
    """Run `docker compose <action>` for an op stack via the docker:cli sidecar
    (same pattern as cloud_provisioner). action e.g. 'stop' | 'up -d' | 'down'."""
    import docker as _dk
    cmd = (f"sh -c 'export DOCKER_CONFIG={stack_dir_host}/.docker && "
           f"docker compose -f docker-compose.operator.yml --env-file .env.operator {action}'")
    _dk.from_env().containers.run(
        "docker:cli", command=cmd,
        volumes={"/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
                 stack_dir_host: {"bind": stack_dir_host, "mode": "rw"}},
        working_dir=stack_dir_host, remove=True, detach=False)
