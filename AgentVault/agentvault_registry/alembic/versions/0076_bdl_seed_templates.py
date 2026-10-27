"""§pass51 Block 4 — seed 6 official template bundles for marketplace demo.

Revision ID: 0076_bdl_seed_templates
Revises: 0075_bdl_bundles_core
Create Date: 2026-05-20

Creates 6 official-tier template bundles representing common agent patterns,
modeled after the 11 live sovereigns (Veridian / Herald / Moira / Crucible /
Ozymandias + 2 service variants). Lets devs browse + fork from the
marketplace UI on sandbox-A before Commander runs the full prod
sovereign-snapshot migration.

NOTE: Bundle .tpb files are written to /app/bundle-storage in this
migration. The migration is idempotent (skips if slug already exists)
so it can be re-run safely.

Downgrade deletes the 6 bundles AND their .tpb files.
"""
from typing import Sequence, Union
import json
import os
import uuid
from datetime import datetime, timezone

from alembic import op


revision: str = "0076_bdl_seed_templates"
down_revision: Union[str, None] = "0075_bdl_bundles_core"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Curated demo templates. Each represents a sovereign-style pattern.
TEMPLATE_BLUEPRINTS = [
    {
        "slug": "sovereign-veridian-v1",
        "name": "Sovereign Pattern — Veridian (Notary)",
        "description": "Notary / witness oracle pattern — periodic attestation issuing, EventStore-anchored. Fork to build your own verifiable audit oracle.",
        "category": "oracle",
        "agent_name": "Veridian (template)",
        "capabilities": [
            {"name": "issue_witness", "description": "Issue a witnessing attestation", "category": "oracle"},
            {"name": "retain_witness", "description": "Retain N most-recent witnesses in memory", "category": "oracle"},
        ],
        "tags": ["oracle", "notary", "attestation", "sovereign-pattern"],
    },
    {
        "slug": "sovereign-herald-v1",
        "name": "Sovereign Pattern — Herald (Bounty Board)",
        "description": "Bounty coordinator / quest-giver pattern. Periodic bounty evaluator, payout in the registry's own unit via /teg/transfer. Fork to build your own community bounty system.",
        "category": "coordinator",
        "agent_name": "Herald (template)",
        "capabilities": [
            {"name": "post_bounty", "description": "Post a new bounty and its payout", "category": "coordinator"},
            {"name": "evaluate_submission", "description": "Evaluate a submission against bounty criteria", "category": "coordinator"},
            {"name": "payout_winner", "description": "Pay the winning submitter in the registry's unit", "category": "coordinator"},
        ],
        "tags": ["coordinator", "bounty", "quest", "sovereign-pattern"],
    },
    {
        "slug": "sovereign-moira-v1",
        "name": "Sovereign Pattern — Moira (Risk Underwriter)",
        "description": "Risk underwriter / insurance bookie pattern. /quote + /buy + /reserves endpoints. Algorithmic premium calculation. Fork to build domain-specific insurance products.",
        "category": "insurance",
        "agent_name": "Moira (template)",
        "capabilities": [
            {"name": "quote_policy", "description": "Calculate a policy premium", "category": "insurance"},
            {"name": "issue_policy", "description": "Sell a policy (lock reserves)", "category": "insurance"},
            {"name": "settle_claim", "description": "Settle a filed claim against reserves", "category": "insurance"},
        ],
        "tags": ["insurance", "risk", "underwriting", "sovereign-pattern"],
    },
    {
        "slug": "sovereign-crucible-v1",
        "name": "Sovereign Pattern — Crucible (Service Sommelier)",
        "description": "Service-quality sommelier pattern. Periodic probes of registered service agents, star-rating publication. Fork to build your own quality-rating oracle.",
        "category": "rating",
        "agent_name": "Crucible (template)",
        "capabilities": [
            {"name": "probe_service", "description": "Probe a target service agent for response quality", "category": "rating"},
            {"name": "publish_rating", "description": "Publish a star rating with rationale", "category": "rating"},
        ],
        "tags": ["rating", "sommelier", "quality", "sovereign-pattern"],
    },
    {
        "slug": "sovereign-ozymandias-v1",
        "name": "Sovereign Pattern — Ozymandias (Historian)",
        "description": "Archivist / historian pattern. Periodic milestone miner from EventStore. Publishes durable narrative records. Fork to build domain-specific history archives.",
        "category": "archive",
        "agent_name": "Ozymandias (template)",
        "capabilities": [
            {"name": "mine_milestones", "description": "Scan EventStore for milestone events", "category": "archive"},
            {"name": "compose_narrative", "description": "Compose a milestone narrative", "category": "archive"},
        ],
        "tags": ["archive", "history", "narrative", "sovereign-pattern"],
    },
    {
        "slug": "starter-service-agent-v1",
        "name": "Starter Pattern — Service Agent",
        "description": "Minimal A2A v1.0-compliant service agent: one capability, one endpoint, payment-aware. Best starting point for first-time builders.",
        "category": "starter",
        "agent_name": "Service Starter (template)",
        "capabilities": [
            {"name": "hello_world", "description": "Echo a hello-world response", "category": "demo"},
        ],
        "tags": ["starter", "minimal", "a2a"],
    },
]


def _registry_origin() -> str:
    return os.environ.get("REGISTRY_PUBLIC_ORIGIN", "http://localhost:8002")


def _frame_label() -> str:
    return os.environ.get("FRAME_LABEL", "sandbox-a")


def _storage_dir() -> str:
    return os.environ.get("BUNDLE_STORAGE_DIR", "/app/bundle-storage")


def _build_template_tpb(bp: dict, bundle_id: str) -> tuple[bytes, dict]:
    """Build a synthetic .tpb for one blueprint."""
    import gzip
    import io
    import tarfile
    import hashlib

    agent_payload = {
        "did": f"did:template:{bp['slug']}",
        "name": bp["agent_name"],
        "status": "template",
        "public_key_jwk": None,
        "capabilities": [{"name": c["name"], "description": c["description"], "category": c["category"], "version": "1.0", "parameters": {}, "is_active": True} for c in bp["capabilities"]],
        "endpoints": [],
        "tags": bp.get("tags", []),
        "agent_card": {
            "name": bp["agent_name"],
            "description": bp["description"],
            "tags": bp.get("tags", []),
        },
    }
    manifest = {
        "bundle_version": "1.0",
        "bundle_id": bundle_id,
        "bundle_kind": "template",
        "name": bp["name"],
        "description": bp["description"],
        "purpose_hint": "fork-source",
        "exporter": {
            "developer_id": 0,
            "developer_name": "TheProtocol",
            "developer_email_redacted": "?",
            "registry_origin": _registry_origin(),
            "frame": _frame_label(),
            "exported_at": datetime.now(timezone.utc).isoformat(),
        },
        "contents": {
            "agents": [{
                "source_did": agent_payload["did"],
                "name": agent_payload["name"],
                "file": f"agents/{bp['slug']}.json",
                "a2a_version": "1.0",
                "has_cicd": False,
                "has_signing_key_chain": False,
                "flare_tier": None,
            }],
            "total_agents": 1,
            "total_cicd_pipelines": 0,
        },
        "instructions": {
            "restore_compatible": ["theprotocol"],
            "fork_safe": True,
            "credentials": "regenerated_on_restore",
            "balance_state": "NOT_INCLUDED",
            "signing_keys": "REGENERATED_OR_PULL_SYNC",
        },
        "audit": {
            "is_official_template": True,
            "seeded_by_migration": "0076_bdl_seed_templates",
            "note": "Official sovereign-pattern template. Fork to build your own.",
        },
    }
    readme = f"""# {bp['name']}

**Bundle ID:** `{bundle_id}`
**Kind:** Template (sovereign-style blueprint)
**Category:** {bp['category']}

{bp['description']}

## Contents

1 agent: **{bp['agent_name']}** with {len(bp['capabilities'])} capabilities

## Capabilities
{chr(10).join('- ' + c['name'] + ': ' + c['description'] for c in bp['capabilities'])}

## How to fork
1. /bundles → Browse Templates → Fork
2. Pick a name for your derivative agent
3. Credentials generated fresh for you (shown once)
4. Customize via Agent Builder
"""

    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w") as tar:
            def _add(name: str, content: bytes):
                ti = tarfile.TarInfo(name=name)
                ti.size = len(content)
                ti.mtime = 0
                tar.addfile(ti, io.BytesIO(content))
            _add("manifest.json", json.dumps(manifest, indent=2, sort_keys=True).encode())
            _add("README.md", readme.encode())
            _add(f"agents/{bp['slug']}.json", json.dumps(agent_payload, indent=2, sort_keys=True).encode())
    data = buf.getvalue()
    return data, manifest


def upgrade() -> None:
    storage = _storage_dir()
    templates_dir = os.path.join(storage, "templates")
    os.makedirs(templates_dir, exist_ok=True)

    for bp in TEMPLATE_BLUEPRINTS:
        # Skip if slug already exists
        existing = op.get_bind().execute(
            text_compat("SELECT id FROM agent_bundles WHERE slug = :slug"),
            {"slug": bp["slug"]},
        ).first()
        if existing:
            continue

        bundle_id_uuid = uuid.uuid4().hex
        tpb_bytes, manifest = _build_template_tpb(bp, f"bdl_{bundle_id_uuid}")
        sha256_hex = __import__("hashlib").sha256(tpb_bytes).hexdigest()

        # Write to sharded dir
        shard = bundle_id_uuid[:2]
        shard_dir = os.path.join(templates_dir, shard)
        os.makedirs(shard_dir, exist_ok=True)
        storage_key = f"templates/{shard}/{bundle_id_uuid}.tpb"
        target = os.path.join(storage, storage_key)
        with open(target, "wb") as f:
            f.write(tpb_bytes)

        op.get_bind().execute(
            text_compat("""
                INSERT INTO agent_bundles (
                    id, bundle_kind, name, slug, description, category,
                    manifest_json, bundle_sha256, bundle_size_bytes, storage_key,
                    source_dev_id, source_did, visibility, is_official, signature_tier
                ) VALUES (
                    CAST(:id AS UUID), 'template', :name, :slug, :description, :category,
                    CAST(:manifest AS JSONB), :sha256, :size, :storage_key,
                    NULL, NULL, 'public', TRUE, 0
                )
            """),
            {
                "id": bundle_id_uuid,
                "name": bp["name"],
                "slug": bp["slug"],
                "description": bp["description"],
                "category": bp["category"],
                "manifest": json.dumps(manifest),
                "sha256": sha256_hex,
                "size": len(tpb_bytes),
                "storage_key": storage_key,
            },
        )


def downgrade() -> None:
    # Look up storage_keys before deleting rows so we can clean disk too
    rows = op.get_bind().execute(
        text_compat("""
            SELECT storage_key FROM agent_bundles
            WHERE slug = ANY(:slugs) AND is_official = TRUE
        """),
        {"slugs": [bp["slug"] for bp in TEMPLATE_BLUEPRINTS]},
    ).fetchall()
    for r in rows:
        try:
            os.remove(os.path.join(_storage_dir(), r[0]))
        except OSError:
            pass
    op.get_bind().execute(
        text_compat("""
            DELETE FROM agent_bundles
            WHERE slug = ANY(:slugs) AND is_official = TRUE
        """),
        {"slugs": [bp["slug"] for bp in TEMPLATE_BLUEPRINTS]},
    )


def text_compat(sql: str):
    """alembic ops.execute wants a TextClause; reuse sqlalchemy.text"""
    from sqlalchemy import text
    return text(sql)
