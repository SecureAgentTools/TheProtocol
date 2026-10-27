"""
Sandbox canary bootstrap — idempotent re-onboard + re-fund + path seed.

Mirrors prod's canary topology on sandbox infra:
  - 10 canary agents (2 per registry × 5 registries)
  - 13 canary paths (intra + async + 2pc)
  - 1-minute cadence (interval_sec=60 — live alarm/continuous test data, Commander
    directive 2026-06-01; was 3600/hourly which left the live ledger idle 59 min/hr)
  - One canary state DB shared across frames (sb-a's Redis DB 2)

Runs as a startup step on `registry-test` (sandbox A mainframe). Every boot:
  1. Loads existing canary_agents rows from `agentvault_registry_test`.
  2. For each spec, verifies the agent's DID still resolves on its home registry.
     If 404 (sandbox was reset since last bootstrap), re-onboards via standard
     bootstrap-token + create_agent flow.
  3. Re-funds each agent up to its prefund target on its home TEG (idempotent
     mint-then-fund).
  4. UPSERTs canary_agents and canary_paths rows in the local registry DB.

Idempotent. Non-fatal on any individual failure (logs + continues). Safe to run
every boot. Designed for Commander's "sandbox is reset often" reality.

Invocation:
  PYTHONPATH=/app/src python -m agentvault_registry.sandbox_canary_bootstrap

See: PRODUCTION_DOCS/06_OPERATIONS/Canary_System.md (prod canary doc)
     sessionlogs2026/PLAN_2026-05-06_SANDBOX_CANARY_REACTOR.md (this work)
"""
from __future__ import annotations

import asyncio
import logging
import os
import json
import secrets
import sys
import time
from typing import Optional

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from agentvault_registry.config import settings
from .core.sandbox_creds import SANDBOX_ADMIN_EMAIL, SANDBOX_ADMIN_PASSWORD  # §SBROTATE

logger = logging.getLogger("sandbox_canary_bootstrap")
logging.basicConfig(
    level=logging.INFO,
    format="[sandbox_canary_bootstrap] %(levelname)s: %(message)s",
)


# ---------------------------------------------------------------------------
# Topology specs — hardcoded, this script only runs in sandbox
# ---------------------------------------------------------------------------

# admin login credentials per home registry. Cloud-op admin passwords were reset
# 2026-05-06 to a known sandbox value via direct SQL UPDATE; if a cloud-op DB is
# wiped, the bootstrap will skip its agents until the password is re-set.
ADMIN_CREDS = {
    "registry-test":                  (SANDBOX_ADMIN_EMAIL, SANDBOX_ADMIN_PASSWORD),
    "registry-test-b":                (SANDBOX_ADMIN_EMAIL, SANDBOX_ADMIN_PASSWORD),
    # §pass73.3 (2026-05-27) — topology compaction. Beta + Gamma torn down per
    # Commander direction (2 sandbox cloud-ops total: 1 sb-a + 1 sb-b). Delta
    # added as the sandbox-B-parented cloud-op.
    "cloud-op-sandboxalpha-registry": ("admin@cloud-op-sandboxalpha.dev", "SandboxOpAdmin2026!"),
    "cloud-op-sandboxdelta-registry": ("admin@cloud-op-sandboxdelta.dev", "SandboxOpAdmin2026!"),
    # §2026-06-02 — Frame C (BVT) sandbox mainframe + its first cloud-op
    # (sandboxcharlie). Covers the Frame-C internal network paths (intra-mainframe,
    # intra-cloud-op, and cloud-op↔mainframe cross-TEG — the path whose svid-writer
    # SAN gap + disabled balance-outbox left genesis funding stuck inflight). All
    # BVT same-currency (cross-frame A↔C is FX, validated separately).
    "registry-test-c":                (SANDBOX_ADMIN_EMAIL, SANDBOX_ADMIN_PASSWORD),
    "cloud-op-sandboxcharlie-registry": ("admin@cloud-op-sandboxcharlie.dev", "SandboxOpAdmin2026!"),
}

# Per-agent: (name, registry_id, registry_url, admin_url, frame, prefund_amount)
#   - registry_url: where canary_runner FIRES transfers FROM. Internal Docker DNS
#     when the runner can resolve it (registry-test only); host port otherwise.
#   - admin_url:    where this bootstrap SUBMITS onboarding/funding requests.
#     Always uses the host-loopback path so bootstrap doesn't depend on cross-
#     network Docker DNS that may not be available from registry-test.
#
# §pass73.3 topology: sandboxalpha = sandbox-A's cloud-op (frame-a, port 30000),
# sandboxdelta = sandbox-B's cloud-op (frame-b, port 30100). The frame label
# determines which TEG the agent uses + which side of cross-frame paths it
# belongs to. Cross-frame paths exercise async/2pc transfers via SF-4
# replicator + the cross-frame 2pc coordination saga.
# §BATCH3 item 1 (2026-09-05): the two spec tables used to be literals naming the RETIRED sandbox
# tier and the box IP. They are DATA about one deployment, so they now come from a JSON file named
# by SANDBOX_CANARY_SPECS_FILE: {"agents": [[name, registry_slug, base_url, teg_url, frame, prefund], ...],
#                                "paths":  [[path_id, sender, receiver, backend, amount, interval_sec], ...]}
# The last literal tables are recorded verbatim in the operations record
# (sessionlogs2026/BATCH3_sandbox_canary_specs_retired-2026.json). No file => nothing to seed, said loudly.
SANDBOX_CANARY_SPECS_FILE = os.getenv("SANDBOX_CANARY_SPECS_FILE", "").strip()


def _load_specs():
    if not SANDBOX_CANARY_SPECS_FILE:
        return [], []
    with open(SANDBOX_CANARY_SPECS_FILE) as fh:
        data = json.load(fh)
    agents = [tuple(row) for row in data.get("agents", [])]
    paths = [tuple(row) for row in data.get("paths", [])]
    for row in agents:
        if len(row) != 6:
            raise SystemExit(f"SANDBOX_CANARY_SPECS_FILE: agent row needs 6 fields, got {len(row)}: {row!r}")
    for row in paths:
        if len(row) != 6:
            raise SystemExit(f"SANDBOX_CANARY_SPECS_FILE: path row needs 6 fields, got {len(row)}: {row!r}")
    return agents, paths


CANARY_AGENT_SPECS, CANARY_PATH_SPECS = _load_specs()


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

async def _login(client: httpx.AsyncClient, admin_url: str, email: str, password: str) -> Optional[str]:
    try:
        r = await client.post(
            f"{admin_url}/api/v1/auth/login",
            data={"username": email, "password": password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15.0,
        )
        if r.status_code == 200:
            return r.json().get("access_token")
        logger.warning(f"login failed {admin_url} ({email}): {r.status_code} {r.text[:120]}")
        return None
    except Exception as e:
        logger.warning(f"login error {admin_url}: {e}")
        return None


async def _verify_agent_alive(client: httpx.AsyncClient, admin_url: str, agent_did: str) -> bool:
    """Check if an agent is LOCALLY owned (not just federated) on this registry.

    §pass73.3.6 — `/agents/by-did/{did}` returns 200 for ANY agent visible to
    the registry, including federated agent_cards pulled in via federation_sync
    from a peer. That's the wrong predicate for canary bootstrap idempotency:
    a phantom federated card was making the bootstrap skip the create step for
    agents that don't actually exist locally, breaking sb-alpha:local with
    HTTP 400 "use cross-registry-transfer instead".

    The response payload has `client_id` populated only for LOCALLY-owned
    agents (federated cards have client_id=null). That's the cleanest signal
    in the existing response shape without needing a new API parameter.
    """
    try:
        r = await client.get(f"{admin_url}/api/v1/agents/by-did/{agent_did}", timeout=10.0)
        if r.status_code != 200:
            return False
        body = r.json() if r.text else {}
        # Local agents have client_id; federated cards have client_id=null.
        return bool(body.get("client_id"))
    except Exception:
        return False


async def _onboard_agent(client: httpx.AsyncClient, admin_url: str, dev_token: str, name: str) -> tuple:
    """Run bootstrap-token + create_agent flow. Returns (agent_did, client_id, client_secret)."""
    r = await client.post(
        f"{admin_url}/api/v1/onboard/bootstrap/request-token",
        json={"agent_type_hint": "canary_agent", "requested_by": f"sandbox_canary_bootstrap_{name}"},
        headers={"Authorization": f"Bearer {dev_token}", "Content-Type": "application/json"},
        timeout=15.0,
    )
    if r.status_code != 200:
        raise RuntimeError(f"bootstrap-token {r.status_code}: {r.text[:160]}")
    bootstrap_token = r.json().get("bootstrap_token")
    if not bootstrap_token:
        raise RuntimeError("bootstrap-token missing in response")

    ts = int(time.time() * 1000)
    agent_card = {
        "humanReadableId": f"sandbox-canary-{name}-{ts}-{secrets.token_hex(2)}",
        "name": f"Sandbox Canary {name}",
        "description": f"Synthetic transaction monitor — sandbox canary agent {name} (auto-onboarded by sandbox_canary_bootstrap)",
        "agentVersion": "1.0",
        "schemaVersion": "1.0",
        "url": f"https://canary.sandbox.test/{name}",
        "provider": {"name": "TheProtocol Sandbox Canary System", "url": "https://sandbox.theprotocol.cloud"},
        "capabilities": {"a2aVersion": "1.0", "supportedMessageParts": ["text"], "supportsPushNotifications": False},
        "authSchemes": [{"scheme": "oauth2", "tokenUrl": f"{admin_url}/api/v1/auth/agent/token"}],
    }
    r = await client.post(
        f"{admin_url}/api/v1/onboard/create_agent",
        json={"agent_did_method": "theprotocol", "agent_card": agent_card},
        headers={"Bootstrap-Token": bootstrap_token, "Content-Type": "application/json"},
        timeout=20.0,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"create_agent {r.status_code}: {r.text[:160]}")
    data = r.json()
    return data["agent_did"], data["client_id"], data["client_secret"]


async def _fund_agent(client: httpx.AsyncClient, admin_url: str, dev_token: str, agent_did: str, amount: int, name: str) -> bool:
    """Mint into treasury (best-effort) + fund agent (required)."""
    ts = int(time.time() * 1000)
    # Mint enough to cover this fund call + headroom (idempotent — extra mints fine in sandbox)
    try:
        await client.post(
            f"{admin_url}/api/v1/teg/treasury/mint",
            json={"amount": "200000", "reason": f"canary bootstrap issuance {name}",
                  "reference_id": f"canary-bootstrap-mint-{name}-{ts}"},
            headers={"Authorization": f"Bearer {dev_token}", "Content-Type": "application/json"},
            timeout=15.0,
        )
    except Exception as e:
        logger.info(f"  mint best-effort failed for {name} (probably ok if treasury already has funds): {e}")

    try:
        r = await client.post(
            f"{admin_url}/api/v1/teg/treasury/fund-agent",
            json={"target_agent_did": agent_did, "amount": str(amount),
                  "reason": f"canary prefund {name}",
                  "reference_id": f"canary-prefund-{name}-{ts}-{secrets.token_hex(2)}"},
            headers={"Authorization": f"Bearer {dev_token}", "Content-Type": "application/json"},
            timeout=20.0,
        )
        if r.status_code in (200, 201):
            logger.info(f"  funded {name} {amount} AVT")
            return True
        logger.warning(f"  fund {name} {r.status_code}: {r.text[:160]}")
        return False
    except Exception as e:
        logger.warning(f"  fund error {name}: {e}")
        return False


# ---------------------------------------------------------------------------
# Per-spec orchestrator
# ---------------------------------------------------------------------------

async def ensure_agent(spec: tuple, existing_by_name: dict) -> Optional[dict]:
    """Idempotently ensure one canary agent. Returns dict with credentials or None on fatal."""
    name, registry_id, registry_url, admin_url, frame, prefund = spec
    creds = ADMIN_CREDS.get(registry_id)
    if not creds:
        logger.error(f"no ADMIN_CREDS for {registry_id} — cannot bootstrap {name}")
        return None
    email, password = creds

    async with httpx.AsyncClient() as client:
        dev_token = await _login(client, admin_url, email, password)
        if not dev_token:
            logger.error(f"admin login failed for {registry_id} — skipping {name}")
            return None

        existing = existing_by_name.get(name)
        if existing and existing.get("agent_did"):
            alive = await _verify_agent_alive(client, admin_url, existing["agent_did"])
            if alive:
                logger.info(f"{name} alive (DID={existing['agent_did'][:35]}...) — re-fund only")
                await _fund_agent(client, admin_url, dev_token, existing["agent_did"], prefund, name)
                return {
                    "name": name, "agent_did": existing["agent_did"],
                    "client_id": existing.get("client_id") or "",
                    "client_secret": existing.get("client_secret") or "",
                    "registry_id": registry_id, "registry_url": registry_url,
                    "frame": frame, "prefund": prefund,
                    "_keep_existing": True,
                }
            logger.info(f"{name} stale (DID gone) — re-onboarding fresh")

        # Fresh onboard
        try:
            agent_did, client_id, client_secret = await _onboard_agent(client, admin_url, dev_token, name)
            logger.info(f"{name} onboarded → DID={agent_did[:35]}...")
        except Exception as e:
            logger.error(f"{name} onboard failed: {e}")
            return None

        await _fund_agent(client, admin_url, dev_token, agent_did, prefund, name)
        return {
            "name": name, "agent_did": agent_did,
            "client_id": client_id, "client_secret": client_secret,
            "registry_id": registry_id, "registry_url": registry_url,
            "frame": frame, "prefund": prefund,
            "_keep_existing": False,
        }


# ---------------------------------------------------------------------------
# DB upserts (against local registry-test DB)
# ---------------------------------------------------------------------------

async def upsert_canary_agent(session: AsyncSession, r: dict) -> int:
    """UPSERT one canary_agents row. Returns the row id."""
    # If we kept existing creds (agent was alive), don't overwrite client_id/secret —
    # they're already in DB and would be re-stored as empty strings if we wrote.
    if r.get("_keep_existing"):
        result = await session.execute(text("""
            UPDATE canary_agents SET
                registry_id = :rid, registry_url = :rurl,
                frame = :frame, is_active = true,
                prefund_amount = :pf, notes = :notes
            WHERE agent_did = :did
            RETURNING id
        """), {"did": r["agent_did"], "rid": r["registry_id"], "rurl": r["registry_url"],
               "frame": r["frame"], "pf": r["prefund"], "notes": r["name"]})
        row = result.first()
        if row:
            return row.id
        # fall through to INSERT if UPDATE matched nothing

    result = await session.execute(text("""
        INSERT INTO canary_agents
            (agent_did, client_id, client_secret, registry_id, registry_url,
             frame, is_active, prefund_amount, notes, created_at)
        VALUES
            (:did, :cid, :csec, :rid, :rurl, :frame, true, :pf, :notes, NOW())
        ON CONFLICT (agent_did) DO UPDATE SET
            client_id = EXCLUDED.client_id,
            client_secret = EXCLUDED.client_secret,
            registry_id = EXCLUDED.registry_id,
            registry_url = EXCLUDED.registry_url,
            frame = EXCLUDED.frame,
            is_active = true,
            prefund_amount = EXCLUDED.prefund_amount,
            notes = EXCLUDED.notes
        RETURNING id
    """), {"did": r["agent_did"], "cid": r["client_id"], "csec": r["client_secret"],
           "rid": r["registry_id"], "rurl": r["registry_url"], "frame": r["frame"],
           "pf": r["prefund"], "notes": r["name"]})
    return result.scalar_one()


async def upsert_canary_path(session: AsyncSession, path_id: str, sender_id: int,
                             receiver_id: int, backend: str, amount: float, interval_sec: int):
    await session.execute(text("""
        INSERT INTO canary_paths
            (path_id, sender_agent_id, receiver_agent_id, backend, amount,
             interval_sec, slo_http_ms, slo_settled_sec, is_active, created_at)
        VALUES
            (:pid, :sid, :rid, :backend, :amount, :interval, 5000, 60, true, NOW())
        ON CONFLICT (path_id) DO UPDATE SET
            sender_agent_id = EXCLUDED.sender_agent_id,
            receiver_agent_id = EXCLUDED.receiver_agent_id,
            backend = EXCLUDED.backend,
            amount = EXCLUDED.amount,
            interval_sec = EXCLUDED.interval_sec,
            is_active = true
    """), {"pid": path_id, "sid": sender_id, "rid": receiver_id,
           "backend": backend, "amount": amount, "interval": interval_sec})


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

async def run_bootstrap() -> int:
    if not CANARY_AGENT_SPECS and not CANARY_PATH_SPECS:
        logger.error("nothing to seed: SANDBOX_CANARY_SPECS_FILE is unset or empty (see the module docstring)")
        return 2
    registry_name = os.environ.get("REGISTRY_NAME", "")
    if registry_name != "Registry-Test":
        logger.info(f"REGISTRY_NAME='{registry_name}' is not Registry-Test — skipping canary bootstrap")
        return 0

    logger.info("Starting sandbox canary bootstrap (10 agents, 13 paths, hourly cadence)")

    # Phase 0: Load existing canary_agents from local DB
    engine = create_async_engine(settings.DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    existing_by_name: dict = {}
    try:
        async with SessionLocal() as session:
            rows = await session.execute(text("""
                SELECT id, agent_did, client_id, client_secret, registry_id, notes
                FROM canary_agents
                WHERE notes LIKE 'canary-sb-%'
            """))
            for row in rows:
                existing_by_name[row.notes] = {
                    "id": row.id,
                    "agent_did": row.agent_did,
                    "client_id": row.client_id,
                    "client_secret": row.client_secret,
                    "registry_id": row.registry_id,
                }
        logger.info(f"loaded {len(existing_by_name)} existing canary agents from local DB")
    except Exception as e:
        logger.warning(f"loading existing agents failed (treating as fresh): {e}")

    # Phase 1: Ensure each agent (network-bound, run sequentially to avoid login storms)
    results = []
    for spec in CANARY_AGENT_SPECS:
        r = await ensure_agent(spec, existing_by_name)
        results.append(r)

    successful = [r for r in results if r is not None]
    logger.info(f"agent phase: {len(successful)}/{len(CANARY_AGENT_SPECS)} ready")

    # Phase 2: UPSERT agent rows + collect IDs by name
    agent_id_by_name: dict = {}
    try:
        async with SessionLocal() as session:
            async with session.begin():
                for r in successful:
                    aid = await upsert_canary_agent(session, r)
                    agent_id_by_name[r["name"]] = aid
        logger.info(f"upserted {len(agent_id_by_name)} canary_agents rows")
    except Exception as e:
        logger.error(f"agent upsert failed: {e}")
        await engine.dispose()
        return 1

    # Phase 3: UPSERT canary_paths (need both sender and receiver IDs)
    path_count = 0
    try:
        async with SessionLocal() as session:
            async with session.begin():
                for path_id, sender_name, receiver_name, backend, amount, interval_sec in CANARY_PATH_SPECS:
                    sid = agent_id_by_name.get(sender_name)
                    rid = agent_id_by_name.get(receiver_name)
                    if not (sid and rid):
                        logger.warning(f"path {path_id} skipped — sender={sid} receiver={rid}")
                        continue
                    await upsert_canary_path(session, path_id, sid, rid, backend, amount, interval_sec)
                    path_count += 1
        logger.info(f"upserted {path_count}/{len(CANARY_PATH_SPECS)} canary_paths rows")
    except Exception as e:
        logger.error(f"path upsert failed: {e}")
        await engine.dispose()
        return 1

    await engine.dispose()
    logger.info("Sandbox canary bootstrap complete.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run_bootstrap()))
