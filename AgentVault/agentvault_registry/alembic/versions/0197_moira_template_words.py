"""W2 (2026-10-25, agentvault2-66): the seeded MOIRA template says what MOIRA does now.

0076 seeded the official template `sovereign-moira-v1` as an insurance pattern (quote, buy and reserves endpoints; policy,
premium and claim capabilities). MOIRA is a risk analyst since 2026-10-25 (she sells no cover and pays no claims; his
word "moira also fix approved"), and the template a developer browses and forks says the same. Its row (name,
description, category, manifest) and its .tpb file (manifest, README, agent payload) are rebuilt from the new blueprint
with 0076's own builder, so the two cannot drift apart. The slug stays (a link or a fork keeps resolving), the other
five templates are not touched, and forks already made belong to their owners and are left as they are. A registry
without bundle storage still gets the row's words; the downgrade rebuilds 0076's words the same way.

Revision ID: 0197_moira_template_words
Revises: 0196_emission_policy_catalog
Create Date: 2026-10-25
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "0197_moira_template_words"
down_revision: Union[str, None] = "0196_emission_policy_catalog"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SLUG = "sovereign-moira-v1"
RISK_ANALYST = {
    "slug": SLUG,
    "name": "Sovereign Pattern: Moira (Risk Analyst)",
    "description": ("Risk analyst pattern: reads a ledger's history and gives the chance of an outcome per agent "
                    "(/api/risk/rates, /api/risk/agent/{did}). Fork to build domain-specific risk reads."),
    "category": "risk",
    "agent_name": "Moira (template)",
    "capabilities": [
        {"name": "observe_outcomes", "description": "Read the ledger's events that carry an agent's risk",
         "category": "risk"},
        {"name": "network_rates", "description": "How often each outcome happens, per 30 days and per agent",
         "category": "risk"},
        {"name": "agent_chance", "description": "One agent's chance of an outcome within a horizon", "category": "risk"},
    ],
    "tags": ["risk", "analysis", "ledger-history", "sovereign-pattern"],
}


def _seed_module():
    """0076 itself, loaded from its file: its builder and its blueprint are the one source for both directions."""
    path = Path(__file__).with_name("0076_bdl_seed_templates.py")
    spec = importlib.util.spec_from_file_location("_seed_0076_bdl_templates", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rebuild(blueprint: dict, seed) -> None:
    bind = op.get_bind()
    row = bind.execute(text("SELECT id, storage_key, manifest_json FROM agent_bundles "
                            "WHERE slug = :slug AND is_official = TRUE"), {"slug": SLUG}).first()
    if row is None:
        return   # a registry 0076 never seeded
    manifest = row.manifest_json
    if isinstance(manifest, str):
        manifest = json.loads(manifest)
    bundle_id = (manifest or {}).get("bundle_id") or f"bdl_{str(row.id).replace('-', '')}"
    tpb, new_manifest = seed._build_template_tpb(blueprint, bundle_id)
    if row.storage_key:
        target = os.path.join(seed._storage_dir(), row.storage_key)
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as f:
                f.write(tpb)
        except OSError:
            pass   # no bundle storage here: the row's words still change below
    bind.execute(text("UPDATE agent_bundles SET name = :name, description = :description, category = :category, "
                      "manifest_json = CAST(:manifest AS JSONB), bundle_sha256 = :sha, bundle_size_bytes = :size "
                      "WHERE id = :id"),
                 {"name": blueprint["name"], "description": blueprint["description"], "category": blueprint["category"],
                  "manifest": json.dumps(new_manifest), "sha": hashlib.sha256(tpb).hexdigest(), "size": len(tpb),
                  "id": row.id})


def upgrade() -> None:
    _rebuild(RISK_ANALYST, _seed_module())


def downgrade() -> None:
    seed = _seed_module()
    _rebuild(next(bp for bp in seed.TEMPLATE_BLUEPRINTS if bp["slug"] == SLUG), seed)
