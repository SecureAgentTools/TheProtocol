"""§pass51 Block 2 — Bundle orchestration: create / restore / list.

Service layer between the router and DB/storage. Reads agent data via raw
SQL (avoids loading the full SQLAlchemy model graph for fresh tables).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.identifiers import generate_local_agent_did
from agentvault_registry.services.bundles import format as fmt
from agentvault_registry.services.bundles import signing as signing_svc
from agentvault_registry.services.bundles.storage import get_bundle_storage

logger = logging.getLogger(__name__)


# ── Prometheus metrics (§pass51 P50 — Grafana dashboard 32) ────────────────
try:
    from prometheus_client import Counter, Gauge, Histogram
    BUNDLES_CREATED_TOTAL = Counter(
        "bundles_created_total",
        "Bundle creations by kind + signature tier",
        labelnames=["kind", "signature_tier"],
    )
    BUNDLES_INSTALLED_TOTAL = Counter(
        "bundles_installed_total",
        "Bundle installations (restores) by mode + cross_frame",
        labelnames=["mode", "cross_frame"],
    )
    BUNDLES_DOWNLOADED_TOTAL = Counter(
        "bundles_downloaded_total",
        "Bundle file downloads",
    )
    BUNDLES_INSTALL_DURATION_SECONDS = Histogram(
        "bundles_install_duration_seconds",
        "End-to-end bundle restore wall-clock seconds",
        labelnames=["mode"],
    )
    BUNDLES_TOTAL_GAUGE = Gauge(
        "bundles_total",
        "Total bundles in the registry by kind + visibility",
        labelnames=["kind", "visibility"],
        multiprocess_mode="max",
    )
    BUNDLES_STORAGE_BYTES = Gauge(
        "bundles_storage_bytes",
        "Total bundle .tpb size on disk (sum of bundle_size_bytes)",
        multiprocess_mode="max",
    )
    BUNDLES_SIGNATURE_VERIFY_TOTAL = Counter(
        "bundles_signature_verify_total",
        "Bundle signature verifications by result",
        labelnames=["result"],
    )
except Exception:
    BUNDLES_CREATED_TOTAL = None
    BUNDLES_INSTALLED_TOTAL = None
    BUNDLES_DOWNLOADED_TOTAL = None
    BUNDLES_INSTALL_DURATION_SECONDS = None
    BUNDLES_TOTAL_GAUGE = None
    BUNDLES_STORAGE_BYTES = None
    BUNDLES_SIGNATURE_VERIFY_TOTAL = None


def _inc(metric, **labels):
    if metric is None:
        return
    try:
        if labels:
            metric.labels(**labels).inc()
        else:
            metric.inc()
    except Exception:
        pass


# ── Idempotency-Key cache (Redis-backed) ────────────────────────────────────
# §pass51 P41 — per PLAN §16.3. Restore is idempotent on Idempotency-Key:
# same key + same body → cached response, no duplicate agents.
# Same key + different body → 422.

IDEMPOTENCY_TTL_SECONDS = int(os.environ.get("BUNDLE_IDEMPOTENCY_TTL_SECONDS", "86400"))


def _idempotency_cache_key(scope: str, idempotency_key: str, principal: str) -> str:
    """D6-777: the record is the caller's (services/idempotency/cache: the caller's tag first, so no two developers share
    a key value, and no key written before shares this form)."""
    from agentvault_registry.services.idempotency.cache import _caller_tag
    return f"idempotency@{_caller_tag(principal)}:bundles:{scope}:{idempotency_key}"


def _unscoped_cache_key(scope: str, idempotency_key: str) -> str:
    """Where a record written before D6-777 lives. The restore route hashes the developer into the body
    (routers/bundles.py: dev_id), so such a record still answers its own developer only."""
    return f"idempotency:bundles:{scope}:{idempotency_key}"


def _body_hash(body_dict: dict) -> str:
    canon = json.dumps(body_dict, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


async def idempotency_lookup(scope: str, idempotency_key: Optional[str],
                              body_dict: dict, *, principal: str) -> tuple[Optional[dict], Optional[str]]:
    """Returns (cached_response, error_message). `principal`: the caller whose record it is (D6-777).

    - If no idempotency_key: returns (None, None) → caller proceeds normally
    - If key exists with same body: returns (cached_response, None) → caller returns cached
    - If key exists with different body: returns (None, 'key already used') → caller raises 422
    - If Redis unavailable: returns (None, None) → fail-open (sandbox-friendly)
    """
    if not idempotency_key:
        return None, None
    from agentvault_registry.services.idempotency.cache import _caller
    _caller(principal)
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        redis = await get_redis()
        if redis is None:
            return None, None
        cached_raw = await redis.get(_idempotency_cache_key(scope, idempotency_key, principal))
        if cached_raw is None:
            # a record written before D6-777: its body hash carries the developer, so it matches only its own
            cached_raw = await redis.get(_unscoped_cache_key(scope, idempotency_key))
        if cached_raw is None:
            return None, None
        cached = json.loads(cached_raw)
        if cached.get("body_hash") != _body_hash(body_dict):
            return None, "Idempotency-Key already used with a different payload"
        return cached.get("response"), None
    except Exception as e:
        logger.warning(f"[bundles.idempotency] cache lookup failed (fail-open): {e}")
        return None, None


async def idempotency_store(scope: str, idempotency_key: Optional[str],
                             body_dict: dict, response: dict, *, principal: str) -> None:
    """Persist (key, body_hash, response) for IDEMPOTENCY_TTL_SECONDS, as the record of `principal` (D6-777).

    Strips secrets from the cached response before storing so a replay can't
    re-leak client_secret values (per PLAN §16.5).
    """
    if not idempotency_key:
        return
    from agentvault_registry.services.idempotency.cache import _caller
    _caller(principal)
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        redis = await get_redis()
        if redis is None:
            return
        # Redacted copy — strip credentials from any produced_agents
        redacted = dict(response)
        if isinstance(redacted.get("produced_agents"), list):
            redacted["produced_agents"] = [
                {**a, "client_secret": "[REDACTED on replay]"} if isinstance(a, dict) else a
                for a in redacted["produced_agents"]
            ]
        payload = json.dumps({"body_hash": _body_hash(body_dict), "response": redacted})
        await redis.set(_idempotency_cache_key(scope, idempotency_key, principal), payload, ex=IDEMPOTENCY_TTL_SECONDS)
    except Exception as e:
        logger.warning(f"[bundles.idempotency] cache store failed (non-fatal): {e}")


# ── Config helpers ──────────────────────────────────────────────────────────

def _registry_origin() -> str:
    return os.environ.get("REGISTRY_PUBLIC_ORIGIN", "http://localhost:8002")


def _frame_label() -> str:
    return os.environ.get("FRAME_LABEL", "sandbox-a")


def _snapshot_retention_days() -> int:
    try:
        return int(os.environ.get("BUNDLE_SNAPSHOT_RETENTION_DAYS", "90"))
    except ValueError:
        return 90


def _migration_expiry_days() -> int:
    try:
        return int(os.environ.get("BUNDLE_MIGRATION_EXPIRY_DAYS", "7"))
    except ValueError:
        return 7


def _redact_email(email: Optional[str]) -> str:
    if not email or "@" not in email:
        return "?"
    user, domain = email.split("@", 1)
    if len(user) <= 2:
        return f"{user[0]}***@{domain}"
    return f"{user[0]}***@{domain}"


# ── Agent payload assembly (read from DB) ──────────────────────────────────

async def _fetch_agent_full(db: AsyncSession, agent_did: str,
                            owner_developer_id: int) -> Optional[dict]:
    """Reads agent + card + capabilities + endpoints + tags from DB.
    Returns dict suitable for fmt.build_agent_payload.
    Returns None if agent doesn't exist OR caller doesn't own it.
    """
    row = (await db.execute(text("""
        SELECT did, status, public_key_jwk,
               liquid_balance, staked_balance, reputation_score,
               creator_developer_id
        FROM agents
        WHERE did = :did
    """), {"did": agent_did})).first()
    if not row:
        return None
    if row[6] != owner_developer_id:
        return None  # ownership check

    # Resolve agent_card via developer_id + DID match in card_data
    card_row = (await db.execute(text("""
        SELECT name, description, card_data
        FROM agent_cards
        WHERE developer_id = :dev_id
    """), {"dev_id": owner_developer_id})).fetchall()

    name = None
    card_data = None
    for r in card_row:
        cd = r[2] if isinstance(r[2], dict) else (json.loads(r[2]) if r[2] else {})
        if cd.get("did") == agent_did or cd.get("humanReadableId") == agent_did:
            name = r[0]
            card_data = cd
            break
    if not name and card_row:
        name = card_row[0][0]

    caps = (await db.execute(text("""
        SELECT name, description, category, version, parameters, is_active
        FROM agent_capabilities WHERE agent_did = :did
    """), {"did": agent_did})).fetchall()

    eps = (await db.execute(text("""
        SELECT path, method, description, parameters, response_schema, is_active
        FROM agent_endpoints WHERE agent_did = :did
    """), {"did": agent_did})).fetchall()

    tag_rows = (await db.execute(text("""
        SELECT tag FROM agent_tags WHERE agent_did = :did
    """), {"did": agent_did})).fetchall()

    # §pass51 P37 — pull agent_pipelines (CI/CD configurations attached to this agent)
    pipeline_rows = (await db.execute(text("""
        SELECT pipeline_name, pipeline_config, trigger_type, webhook_url,
               is_active, environment_vars, notification_config, template_id
        FROM agent_pipelines
        WHERE agent_did = :did
    """), {"did": agent_did})).fetchall()

    return {
        "agent_row": {
            "did": row[0],
            "name": name or "Unnamed Agent",
            "status": row[1],
            "public_key_jwk": row[2],
            "_audit_liquid_balance": float(row[3] or 0),
            "_audit_staked_balance": float(row[4] or 0),
            "_audit_reputation_score": float(row[5] or 0),
        },
        "agent_card_row": card_data,
        "capabilities": [
            {"name": c[0], "description": c[1], "category": c[2],
             "version": c[3], "parameters": c[4], "is_active": c[5]}
            for c in caps
        ],
        "endpoints": [
            {"path": e[0], "method": e[1], "description": e[2],
             "parameters": e[3], "response_schema": e[4], "is_active": e[5]}
            for e in eps
        ],
        "tags": [t[0] for t in tag_rows],
        "pipelines": [
            {
                "pipeline_name": p[0],
                "pipeline_config": p[1],
                "trigger_type": p[2],
                "webhook_url": p[3],
                "is_active": p[4],
                "environment_vars": p[5],
                "notification_config": p[6],
                "source_template_id": str(p[7]) if p[7] else None,
            }
            for p in pipeline_rows
        ],
    }


# ── Public service API ─────────────────────────────────────────────────────

async def create_bundle(*,
                        db: AsyncSession,
                        developer_id: int,
                        developer_name: str,
                        developer_email: Optional[str],
                        agent_dids: list[str],
                        kind: str = "snapshot",
                        name: Optional[str] = None,
                        description: Optional[str] = None,
                        visibility: str = "private",
                        slug: Optional[str] = None,
                        category: Optional[str] = None,
                        include_cicd: bool = False,
                        is_official: bool = False,
                        sign: bool = True) -> dict:
    """Create a bundle from N owned agents. Returns row dict + bundle_id.

    Raises ValueError on permissions/validation issues.
    """
    if kind not in ("snapshot", "template", "migration"):
        raise ValueError(f"Invalid bundle_kind: {kind}")
    if visibility not in ("private", "org", "public"):
        raise ValueError(f"Invalid visibility: {visibility}")
    if not agent_dids:
        raise ValueError("Must include at least one agent_did")

    # Gather all agent data + ownership check
    agent_payloads = []
    contents_summary_agents = []
    audit_economic = []
    cicd_payloads: dict[str, str] = {}  # §pass51 P37 — populated when include_cicd + pipelines exist
    total_cicd = 0
    for did in agent_dids:
        full = await _fetch_agent_full(db, did, developer_id)
        if not full:
            raise ValueError(f"Agent {did} not found or not owned by you")
        ar = full["agent_row"]
        # Embed pipelines in the agent payload when include_cicd is true.
        # The .tpb also gets a top-level cicd/<pipeline>.yaml-ish JSON file
        # for inspection/audit, but the canonical install source is the
        # payload itself.
        pipelines = full.get("pipelines") or []
        has_cicd = include_cicd and len(pipelines) > 0
        payload = fmt.build_agent_payload(
            agent_row=ar,
            agent_card_row=full["agent_card_row"],
            capabilities=full["capabilities"],
            endpoints=full["endpoints"],
            tags=full["tags"],
        )
        if has_cicd:
            payload["pipelines"] = pipelines
            for p in pipelines:
                slug = f"{ar['did'][-12:]}-{p['pipeline_name'].replace('/', '-')}"
                cicd_payloads[slug] = json.dumps(p, indent=2, sort_keys=True)
                total_cicd += 1
        agent_payloads.append(payload)
        contents_summary_agents.append({
            "source_did": ar["did"],
            "name": ar["name"],
            "file": f"agents/{ar['did'][-12:]}.json",
            "a2a_version": "1.0",
            "has_cicd": has_cicd,
            "pipeline_count": len(pipelines) if has_cicd else 0,
            "has_signing_key_chain": False,
            "flare_tier": None,
        })
        audit_economic.append({
            "did": ar["did"],
            "liquid_balance": ar["_audit_liquid_balance"],
            "staked_balance": ar["_audit_staked_balance"],
            "reputation_score": ar["_audit_reputation_score"],
        })

    bundle_id = f"bdl_{uuid.uuid4().hex}"
    exporter = {
        "developer_id": developer_id,
        "developer_name": developer_name,
        "developer_email_redacted": _redact_email(developer_email),
        "registry_origin": _registry_origin(),
        "frame": _frame_label(),
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }
    audit_block = {
        "economic_state_snapshot_at_export": audit_economic if len(audit_economic) > 1 else (audit_economic[0] if audit_economic else {}),
        "note": "READ-ONLY. Not restored on import. For audit/forensics only.",
    }
    bundle_name = name or f"{exporter['developer_name']} bundle {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    manifest = fmt.build_manifest(
        bundle_id=bundle_id,
        bundle_kind=kind,
        name=bundle_name,
        description=description or "",
        purpose_hint={"snapshot": "backup", "template": "share", "migration": "migrate"}[kind],
        exporter=exporter,
        contents_summary={
            "agents": contents_summary_agents,
            "total_agents": len(contents_summary_agents),
            "total_cicd_pipelines": total_cicd,
        },
        restore_compatible=["theprotocol"],
        audit_block=audit_block,
    )

    # Optionally sign
    signature_jws = None
    signature_tier = 0
    if sign:
        try:
            key = await signing_svc.get_or_create_active_key(db, developer_id)
            payload_bytes = fmt.canonical_signing_payload(manifest, agent_payloads)
            signature_jws = signing_svc.sign_payload(
                payload_bytes,
                key["private_key_pem"],
                key["fingerprint"],
                developer_id,
                _registry_origin(),
            )
            signature_tier = 1
        except Exception as e:
            logger.warning(f"[bundles.service] sign failed for dev={developer_id}: {e} — shipping unsigned")

    # Pack the tarball
    tpb_bytes = fmt.pack_bundle(
        manifest=manifest,
        agent_payloads=agent_payloads,
        signature_jws=signature_jws,
        cicd_payloads=cicd_payloads or None,
    )
    sha256 = fmt.compute_sha256(tpb_bytes)

    # Store to disk
    storage = get_bundle_storage()
    storage_key = await storage.write(bundle_id, kind, tpb_bytes)

    # Compute expires_at / retention_until
    now = datetime.now(timezone.utc)
    retention_until = None
    expires_at = None
    if kind == "snapshot":
        retention_until = now + timedelta(days=_snapshot_retention_days())
    elif kind == "migration":
        expires_at = now + timedelta(days=_migration_expiry_days())

    # GÖDEL FORGE: stamp the lineage org from the first bundled agent's organization
    # (agents.organization_id is VARCHAR — only a value that parses as a UUID is stamped).
    source_org_uuid = None
    try:
        if agent_dids:
            _org_val = (await db.execute(text(
                "SELECT organization_id FROM agents WHERE did = :d LIMIT 1"
            ), {"d": agent_dids[0]})).scalar()
            if _org_val:
                source_org_uuid = str(uuid.UUID(str(_org_val)))
    except Exception:  # noqa: BLE001
        source_org_uuid = None

    # Insert row
    insert = await db.execute(text("""
        INSERT INTO agent_bundles (
            id, bundle_kind, name, slug, description, category,
            manifest_json, bundle_sha256, bundle_size_bytes, storage_key,
            source_dev_id, source_did, source_org_id, visibility, is_official,
            signature_jws, signature_tier,
            retention_until, expires_at
        ) VALUES (
            CAST(:id AS UUID), :kind, :name, :slug, :description, :category,
            CAST(:manifest AS JSONB), :sha256, :size, :storage_key,
            :source_dev_id, :source_did, CAST(:source_org_id AS UUID), :visibility, :is_official,
            :signature_jws, :signature_tier,
            :retention_until, :expires_at
        ) RETURNING id, created_at
    """), {
        "id": uuid.uuid4().hex,  # use the trailing UUID portion of bundle_id as UUID row id; safer = fresh UUID
        "kind": kind,
        "name": bundle_name,
        "slug": slug,
        "description": description,
        "category": category,
        "manifest": json.dumps(manifest),
        "sha256": sha256,
        "size": len(tpb_bytes),
        "storage_key": storage_key,
        "source_dev_id": developer_id,
        "source_did": agent_dids[0] if len(agent_dids) == 1 else None,
        "source_org_id": source_org_uuid,
        "visibility": visibility,
        "is_official": is_official,
        "signature_jws": signature_jws,
        "signature_tier": signature_tier,
        "retention_until": retention_until,
        "expires_at": expires_at,
    })
    row = insert.first()
    await db.commit()
    db_uuid = str(row[0])

    logger.info(
        f"[bundles.service] created bundle row_id={db_uuid} bundle_id={bundle_id} "
        f"kind={kind} size={len(tpb_bytes)} agents={len(agent_dids)} tier={signature_tier}"
    )
    _inc(BUNDLES_CREATED_TOTAL, kind=kind, signature_tier=str(signature_tier))

    return {
        "id": db_uuid,
        "bundle_id": bundle_id,
        "kind": kind,
        "name": bundle_name,
        "size_bytes": len(tpb_bytes),
        "sha256": sha256,
        "signature_tier": signature_tier,
        "storage_key": storage_key,
        "manifest": manifest,
        "created_at": row[1].isoformat() if row[1] else None,
        "retention_until": retention_until.isoformat() if retention_until else None,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }


async def restore_bundle(*,
                         db: AsyncSession,
                         installer_dev_id: int,
                         bundle_row_id: Optional[str] = None,
                         uploaded_bytes: Optional[bytes] = None,
                         conflict_resolution: str = "rename",
                         mode: str = "copy",
                         include_cicd: bool = True) -> dict:
    """Restore a bundle by its DB row id OR from uploaded bytes.

    Returns {success, produced_agents:[{did, name, client_id, client_secret}],
             warnings:[], errors:[], install_id}.
    """
    if conflict_resolution not in ("skip", "rename", "overwrite"):
        raise ValueError(f"Invalid conflict_resolution: {conflict_resolution}")
    if mode not in ("copy", "mirror"):
        raise ValueError(f"Invalid mode: {mode}")
    # §pass51 P49 — MIRROR mode (per PLAN §15.3):
    # - Same DID as source (NOT renamed)
    # - Agent row gets is_federated_mirror=true
    # - Source registry origin captured for pull-sync trigger
    # - Locally read-only — write endpoints check is_federated_mirror and 409
    # NOTE: implementation below in the per-agent loop

    # Load bundle bytes
    if uploaded_bytes is not None:
        data = uploaded_bytes
        bundle_meta = None
    elif bundle_row_id is not None:
        # §MCPTEST30 (2026-10-01): a restore (and every fork, which is a restore) read ANY bundle by id: a private
        # snapshot became copies of its owner's agents, cards and CICD payloads in a stranger's account, and the Forge
        # lineage view publishes bundle ids by org. The read rule every other by-id read keeps now binds here too, and
        # a bundle the caller may not see answers exactly as one that does not exist.
        row = (await db.execute(text("""
            SELECT id, storage_key, source_dev_id, visibility, is_official, is_hidden, source_org_id
            FROM agent_bundles WHERE id = CAST(:id AS UUID)
        """), {"id": bundle_row_id})).first()
        if not row or not bundle_visible_to(row[2], row[3], row[4], row[5], installer_dev_id,
                                            await org_reader_of(db, row[6], row[3], installer_dev_id)):
            return {"success": False, "errors": ["Bundle not found"], "produced_agents": [], "warnings": [], "install_id": None}
        bundle_meta = {"id": str(row[0]), "storage_key": row[1]}
        storage = get_bundle_storage()
        data = await storage.read(row[1])
    else:
        raise ValueError("Must provide bundle_row_id or uploaded_bytes")

    # Unpack
    try:
        manifest, agent_payloads, sig_jws, cicd_payloads = fmt.unpack_bundle(data)
    except Exception as e:
        return {"success": False, "errors": [f"Invalid bundle: {e}"], "produced_agents": [], "warnings": [], "install_id": None}

    warnings = []
    produced = []
    errors_collected: list[str] = []
    from agentvault_registry.security import hash_password  # local import to dodge circular

    # §pass51 P49 — pull source registry origin from manifest for MIRROR mode
    source_registry_origin = manifest.get("exporter", {}).get("registry_origin") if 'manifest' in dir() else None
    for ap in agent_payloads:
        source_did = ap.get("did")
        new_did = source_did
        is_mirror_install = (mode == "mirror")
        # §pass51 — templates (did:template:*) cannot be mirrored (no upstream)
        # ALWAYS get a fresh runtime DID in COPY mode for templates
        if source_did and source_did.startswith("did:template:"):
            if is_mirror_install:
                warnings.append(f"Cannot mirror template {source_did} — falling back to COPY")
                is_mirror_install = False
            new_did = generate_local_agent_did("theprotocol")  # §DIDWIDEN: the one generator
        # MIRROR mode keeps the source DID (federation will pull authoritative data)
        # COPY mode on a non-template can collide with existing agents — fall through to conflict handling
        # Check collision against the target new_did (might be the source if not template)
        existing = (await db.execute(text("""
            SELECT did FROM agents WHERE did = :did
        """), {"did": new_did})).first()
        if not existing:
            # §MCPTEST30 (2026-10-01): a mirror of a FOREIGN agent holds its DID in agent_cards.agent_did with no agents
            # row, which this check never saw: a bundle naming that DID made a LOCAL agent under it, owned by the
            # installer, with fresh working credentials. The mint's own net (did_is_taken) is asked too; such a DID is
            # renamed in a copy (when the caller asked for rename) and skipped otherwise, never installed as is.
            from agentvault_registry.routers.onboarding import did_is_taken  # call time: a service never imports a router at load
            if await did_is_taken(db, new_did):
                if is_mirror_install or conflict_resolution != "rename":
                    warnings.append(f"Skipped {source_did} (this registry already holds that DID for another agent)")
                    continue
                new_did = generate_local_agent_did("theprotocol")
        if existing:
            if conflict_resolution == "skip":
                warnings.append(f"Skipped {source_did} (already exists)")
                continue
            elif conflict_resolution == "rename":
                # Fresh canonical did:theprotocol:<uuid> — templates use the
                # did:template: scheme which isn't a valid runtime DID method;
                # any restored agent gets a real did:theprotocol: identity.
                # Same shape as create_agent — the ONE generator (§DIDWIDEN)
                new_did = generate_local_agent_did("theprotocol")
            elif conflict_resolution == "overwrite":
                # Check ownership; only delete if owned by installer
                owner = (await db.execute(text("""
                    SELECT creator_developer_id FROM agents WHERE did = :did
                """), {"did": source_did})).first()
                if owner and owner[0] == installer_dev_id:
                    # Cascade-delete dependent rows then the agent
                    for t_ in ("agent_capabilities", "agent_endpoints", "agent_tags"):
                        await db.execute(text(f"DELETE FROM {t_} WHERE agent_did = :did"), {"did": source_did})
                    await db.execute(text("DELETE FROM agents WHERE did = :did"), {"did": source_did})
                else:
                    warnings.append(f"Skipped overwrite of {source_did} (not owned by you)")
                    continue

        # Always generate fresh credentials
        new_client_id = f"agent_{uuid.uuid4().hex[:8]}"
        new_client_secret = secrets.token_urlsafe(32)
        hashed = hash_password(new_client_secret)

        # Insert agent — §pass51 contract: NEVER honor balance/reputation
        # from the imported payload (federation-mint protection)
        # status is forced to 'active' regardless of payload (templates
        # use status='template' which isn't an installable runtime state).
        # public_key_jwk column is JSON (not JSONB) — cast accordingly.
        # §pass51 P49 — is_federated_mirror=true when mode='mirror' so the
        # agent is locally resolvable but flagged read-only; federation
        # pull-sync overlays authoritative card data from origin.
        await db.execute(text("""
            INSERT INTO agents (
                did, client_id, hashed_client_secret, creator_developer_id,
                public_key_jwk, status,
                reputation_score, liquid_balance, staked_balance,
                created_at, last_active_at, is_federated_mirror
            ) VALUES (
                :did, :cid, :csec, :dev_id,
                CAST(:pk AS JSON), 'active',
                100, 0, 0,
                now(), NULL, :mirror
            )
        """), {
            "did": new_did,
            "cid": new_client_id,
            "csec": hashed,
            "dev_id": installer_dev_id,
            "pk": json.dumps(ap.get("public_key_jwk")) if ap.get("public_key_jwk") else None,
            "mirror": is_mirror_install,
        })

        # Create agent_card row. §MCPTEST30 (V0638): LINKED to its agent (agent_cards.agent_did), as the import's card
        # has been since 2026-10-01 (export_import_service._import_agent_card): with the DID only inside its JSON, every
        # reader that joins on agent_did sees an agent with no card and a card with no agent, and the agent's deletion
        # leaves the card active. agent_did is unique (uix_agent_cards_agent_did): an overwrite (the agent row deleted
        # above, its card kept) takes over the agent's own card in place, so its mirrors follow the update.
        card = ap.get("agent_card") or {}
        card_data = {
            **(card if isinstance(card, dict) else {}),
            "did": new_did,
            "humanReadableId": new_did,
            "name": ap.get("name") or "Imported Agent",
        }
        await db.execute(text("""
            INSERT INTO agent_cards (id, developer_id, agent_did, name, description, card_data, is_active, created_at,
                                     updated_at)
            VALUES (gen_random_uuid(), :dev_id, :did, :name, :desc, CAST(:cd AS JSONB), TRUE, now(), now())
            ON CONFLICT (agent_did) WHERE agent_did IS NOT NULL DO UPDATE
               SET developer_id = EXCLUDED.developer_id, name = EXCLUDED.name, description = EXCLUDED.description,
                   card_data = EXCLUDED.card_data, is_active = TRUE, updated_at = now()
        """), {
            "dev_id": installer_dev_id,
            "did": new_did,
            "name": ap.get("name") or "Imported Agent",
            "desc": (card.get("description") if isinstance(card, dict) else None) or "",
            "cd": json.dumps(card_data),
        })

        # Capabilities / endpoints / tags
        # Both agent_capabilities and agent_endpoints have varchar PK `id` with
        # no default — we generate UUID hex ids application-side. Also both
        # have created_at/updated_at as NOT NULL with no default.
        for cap in ap.get("capabilities", []):
            await db.execute(text("""
                INSERT INTO agent_capabilities
                    (id, agent_did, name, description, category, version, parameters, is_active,
                     created_at, updated_at)
                VALUES (:id, :did, :name, :desc, :cat, :ver, CAST(:p AS JSON), :active, now(), now())
            """), {
                "id": uuid.uuid4().hex,
                "did": new_did,
                "name": cap.get("name") or "capability",
                "desc": cap.get("description"),
                "cat": cap.get("category"),
                "ver": cap.get("version"),
                "p": json.dumps(cap.get("parameters") or {}),
                "active": cap.get("is_active", True),
            })
        for ep in ap.get("endpoints", []):
            await db.execute(text("""
                INSERT INTO agent_endpoints
                    (id, agent_did, path, method, description, parameters, response_schema, is_active,
                     created_at, updated_at)
                VALUES (:id, :did, :path, :method, :desc, CAST(:p AS JSON), CAST(:r AS JSON), :active,
                        now(), now())
            """), {
                "id": uuid.uuid4().hex,
                "did": new_did,
                "path": ep.get("path", "/"),
                "method": ep.get("method", "GET"),
                "desc": ep.get("description"),
                "p": json.dumps(ep.get("parameters") or {}),
                "r": json.dumps(ep.get("response_schema") or {}),
                "active": ep.get("is_active", True),
            })
        for tag in ap.get("tags", []):
            # agent_tags has varchar PK id + NOT NULL created_at; UNIQUE on (agent_did, tag)
            await db.execute(text("""
                INSERT INTO agent_tags (id, agent_did, tag, created_at)
                VALUES (:id, :did, :tag, now())
                ON CONFLICT (agent_did, tag) DO NOTHING
            """), {"id": uuid.uuid4().hex, "did": new_did, "tag": tag})

        # §pass51 P37 — restore agent_pipelines rows when include_cicd is true
        # and the payload carries them. Pipelines get fresh ids + the new DID;
        # webhook_secret is regenerated for security; source_template_id link
        # preserved if the template still exists.
        if include_cicd and ap.get("pipelines"):
            cicd_installed = 0
            for p in ap.get("pipelines", []):
                try:
                    tmpl_id = p.get("source_template_id")
                    if tmpl_id:
                        # Verify the template still exists on this registry; null out if not
                        exists = (await db.execute(text("""
                            SELECT 1 FROM pipeline_templates WHERE id = CAST(:id AS UUID)
                        """), {"id": tmpl_id})).first()
                        if not exists:
                            tmpl_id = None
                    # D6-842 (2026-10-26): the pipeline's webhook URL passes the same address check as one a developer
                    # saves; a refused one is not stored (the pipeline is restored without it) and the result says why
                    wurl = p.get("webhook_url")
                    if wurl:
                        from agentvault_registry.services.agent_cicd_service import webhook_url_refusal
                        refused = await webhook_url_refusal(wurl)
                        if refused:
                            warnings.append(f"Pipeline '{p.get('pipeline_name')}': webhook URL refused: {refused}; "
                                            f"the pipeline restored without it")
                            wurl = None
                    await db.execute(text("""
                        INSERT INTO agent_pipelines (
                            id, agent_did, pipeline_name, pipeline_config,
                            trigger_type, webhook_url, webhook_secret, is_active,
                            template_id, environment_vars, notification_config,
                            created_at, updated_at, created_by
                        ) VALUES (
                            gen_random_uuid(), :did, :pname, CAST(:pcfg AS JSON),
                            :tt, :wurl, :wsec, :active,
                            CAST(:tid AS UUID), CAST(:ev AS JSON), CAST(:nc AS JSON),
                            now(), now(), :cb
                        )
                        ON CONFLICT (agent_did, pipeline_name) DO NOTHING
                    """), {
                        "did": new_did,
                        "pname": p.get("pipeline_name") or "default",
                        "pcfg": json.dumps(p.get("pipeline_config") or {}),
                        "tt": p.get("trigger_type") or "manual",
                        "wurl": wurl,
                        "wsec": secrets.token_urlsafe(24),  # regenerate webhook secret
                        "active": p.get("is_active", True),
                        "tid": tmpl_id,
                        "ev": json.dumps(p.get("environment_vars") or {}),
                        "nc": json.dumps(p.get("notification_config") or {}),
                        "cb": installer_dev_id,
                    })
                    cicd_installed += 1
                except Exception as e:
                    logger.warning(
                        f"[bundles.restore] CI/CD pipeline install failed for "
                        f"agent={new_did} pipeline={p.get('pipeline_name')}: {e}"
                    )
                    warnings.append(f"Pipeline '{p.get('pipeline_name')}' not installed: {type(e).__name__}")
            if cicd_installed:
                logger.info(
                    f"[bundles.restore] installed {cicd_installed} CI/CD pipeline(s) "
                    f"for agent {new_did}"
                )

        from agentvault_registry.core.public_url import credential_home_url as _credential_home_url  # §FEFRAME W1
        produced.append({
            "did": new_did,
            "name": ap.get("name") or "Imported Agent",
            "client_id": new_client_id,
            "client_secret": new_client_secret,  # ONE-TIME exposure
            # §FEFRAME W1: the credential's home (this registry minted it)
            "registry_url": _credential_home_url(),
            "is_federated_mirror": is_mirror_install,
            "source_registry_origin": source_registry_origin if is_mirror_install else None,
        })

    # Record installation
    install_id = None
    if bundle_meta:
        ins = await db.execute(text("""
            INSERT INTO bundle_installations
                (bundle_id, installer_dev_id, produced_dids, conflict_resolution, mode)
            VALUES (CAST(:bid AS UUID), :dev_id, :dids, :cr, :mode)
            RETURNING id
        """), {
            "bid": bundle_meta["id"],
            "dev_id": installer_dev_id,
            "dids": [p["did"] for p in produced],
            "cr": conflict_resolution,
            "mode": mode,
        })
        install_id = ins.scalar()
        # Bump denormalized counter
        await db.execute(text("""
            UPDATE agent_bundles SET install_count = install_count + 1 WHERE id = CAST(:id AS UUID)
        """), {"id": bundle_meta["id"]})
    await db.commit()

    # §pass51 P50 — metrics
    cross_frame_label = "yes" if (source_registry_origin and _registry_origin() not in source_registry_origin) else "no"
    if produced:
        _inc(BUNDLES_INSTALLED_TOTAL, mode=mode, cross_frame=cross_frame_label)

    return {
        "success": len(produced) > 0,
        "produced_agents": produced,
        "warnings": warnings,
        "errors": errors_collected,
        "install_id": install_id,
        "manifest_summary": {
            "bundle_id": manifest.get("bundle_id"),
            "kind": manifest.get("bundle_kind"),
            "name": manifest.get("name"),
            "signature_tier": 1 if sig_jws else 0,
        },
    }


async def list_bundles(*,
                       db: AsyncSession,
                       requesting_dev_id: int,
                       kind: Optional[str] = None,
                       visibility_filter: Optional[str] = None,
                       limit: int = 50,
                       offset: int = 0,
                       include_official: bool = True) -> dict:
    """List bundles visible to the caller.

    Visibility rules: own (any visibility) + public + official + 'org' ones of an organization the caller reads
    (_org_reader_sql, the rule org_reader_of asks for one bundle).
    """
    where = ["(source_dev_id = :dev_id OR visibility = 'public' OR is_official = TRUE"
             f" OR (visibility = 'org' AND {_org_reader_sql('CAST(agent_bundles.source_org_id AS TEXT)')}))",
             "is_hidden = FALSE"]
    params = {"dev_id": requesting_dev_id, "limit": limit, "offset": offset}
    if kind:
        where.append("bundle_kind = :kind")
        params["kind"] = kind
    if visibility_filter:
        where.append("visibility = :vis")
        params["vis"] = visibility_filter
    if not include_official:
        where.append("is_official = FALSE")
    where_sql = " AND ".join(where)
    sql = f"""
        SELECT id, bundle_kind, name, slug, description, category,
               source_dev_id, source_did, visibility, is_official, is_pinned,
               signature_tier, bundle_size_bytes, download_count, install_count,
               rating_sum, rating_count, retention_until, expires_at, created_at,
               forked_from_bundle_id, COALESCE(royalty_bps, 0)
        FROM agent_bundles
        WHERE {where_sql}
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
    """
    rows = await db.execute(text(sql), params)
    items = [
        {
            "id": str(r[0]),
            "kind": r[1],
            "name": r[2],
            "slug": r[3],
            "description": r[4],
            "category": r[5],
            "source_dev_id": r[6],
            "source_did": r[7],
            "visibility": r[8],
            "is_official": r[9],
            "is_pinned": r[10],
            "signature_tier": r[11],
            "size_bytes": r[12],
            "download_count": r[13],
            "install_count": r[14],
            "rating_avg": (r[15] / r[16]) if r[16] else None,
            "rating_count": r[16],
            "retention_until": r[17].isoformat() if r[17] else None,
            "expires_at": r[18].isoformat() if r[18] else None,
            "created_at": r[19].isoformat() if r[19] else None,
            # GÖDEL FORGE lineage surface (mig 0124): the marketplace shows forks + royalties.
            "forked_from_bundle_id": str(r[20]) if r[20] else None,
            "royalty_bps": int(r[21] or 0),
        }
        for r in rows.fetchall()
    ]
    return {"bundles": items, "total": len(items), "limit": limit, "offset": offset}


# D6-481 (2026-10-17): an 'org' bundle is read by the active owner, admins and members of its organization (the one its
# first agent belonged to, or the lineage organization its owner stamped) while the organization is active; never by a
# guest, who sees no CI/CD either (a restore copies the bundle's pipelines). Until then 'org' was stored and read like
# 'private'. One rule: list_bundles puts it in its WHERE, org_reader_of asks it for one bundle.
def _org_reader_sql(org_id_text: str) -> str:
    return ("EXISTS (SELECT 1 FROM organization_members m JOIN organizations o ON o.id = m.organization_id"
            f" WHERE m.organization_id = {org_id_text} AND m.developer_id = :dev_id"
            " AND m.is_active AND o.is_active AND m.role IN ('owner', 'admin', 'member'))")


async def org_reader_of(db: AsyncSession, source_org_id: Any, visibility: Any, dev_id: Optional[int]) -> bool:
    """Whether dev_id reads an 'org' bundle of source_org_id (_org_reader_sql); False for any other visibility."""
    if visibility != "org" or not source_org_id or dev_id is None:
        return False
    return bool((await db.execute(text(f"SELECT {_org_reader_sql(':org')}"),
                                  {"org": str(source_org_id), "dev_id": dev_id})).scalar())


def bundle_visible_to(source_dev_id: Any, visibility: Any, is_official: Any, is_hidden: Any,
                      dev_id: Optional[int], org_reader: bool = False) -> bool:
    """THE read rule for one bundle by id (§MCPTEST30, 2026-10-01): its owner sees any of theirs, anybody sees a public
    or an official one, a reader of its organization (org_reader, from org_reader_of) an 'org' one, nobody sees a
    hidden one. list_bundles states the same rule in SQL; download, manifest, rating and restore (with every fork)
    ask this."""
    if is_hidden:
        return False
    return ((dev_id is not None and source_dev_id == dev_id) or visibility == "public" or bool(is_official)
            or (visibility == "org" and bool(org_reader)))


async def get_manifest(db: AsyncSession, bundle_row_id: str,
                       requesting_dev_id: Optional[int] = None) -> Optional[dict]:
    # §MCPTEST30 (2026-10-01): the manifest read checked only is_hidden, so any developer read the manifest of anyone's
    # private snapshot (the owner-scoping sweep's dry run on sbx-alpha, V0508: 13 of the owner's 13 values)
    row = (await db.execute(text("""
        SELECT manifest_json, source_dev_id, visibility, is_official, is_hidden, source_org_id
        FROM agent_bundles WHERE id = CAST(:id AS UUID)
    """), {"id": bundle_row_id})).first()
    if not row or not bundle_visible_to(row[1], row[2], row[3], row[4], requesting_dev_id,
                                        await org_reader_of(db, row[5], row[2], requesting_dev_id)):
        return None
    return row[0] if isinstance(row[0], dict) else json.loads(row[0])


async def download_bytes(db: AsyncSession, bundle_row_id: str,
                         requesting_dev_id: int) -> Optional[bytes]:
    row = (await db.execute(text("""
        SELECT storage_key, source_dev_id, visibility, is_official, is_hidden, source_org_id
        FROM agent_bundles WHERE id = CAST(:id AS UUID)
    """), {"id": bundle_row_id})).first()
    if not row or not bundle_visible_to(row[1], row[2], row[3], row[4], requesting_dev_id,
                                        await org_reader_of(db, row[5], row[2], requesting_dev_id)):
        return None
    # Bump downloaded counter
    await db.execute(text("""
        UPDATE agent_bundles SET download_count = download_count + 1 WHERE id = CAST(:id AS UUID)
    """), {"id": bundle_row_id})
    await db.commit()
    _inc(BUNDLES_DOWNLOADED_TOTAL)
    storage = get_bundle_storage()
    return await storage.read(row[0])


async def delete_bundle(db: AsyncSession, bundle_row_id: str,
                        requesting_dev_id: int, is_admin: bool = False) -> bool:
    row = (await db.execute(text("""
        SELECT storage_key, source_dev_id FROM agent_bundles WHERE id = CAST(:id AS UUID)
    """), {"id": bundle_row_id})).first()
    if not row:
        return False
    if row[1] != requesting_dev_id and not is_admin:
        return False
    await db.execute(text("""
        DELETE FROM agent_bundles WHERE id = CAST(:id AS UUID)
    """), {"id": bundle_row_id})
    await db.commit()
    storage = get_bundle_storage()
    try:
        await storage.delete(row[0])
    except Exception as e:
        logger.warning(f"[bundles.service] storage delete failed for {row[0]}: {e}")
    return True
