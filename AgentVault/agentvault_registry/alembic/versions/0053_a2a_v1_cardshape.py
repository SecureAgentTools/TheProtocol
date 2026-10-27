"""Backfill agent_cards.card_data with A2A v1.0 fields (Q-C W1).

Revision ID: 0053_a2a_v1_cardshape
Revises: 0052_fiat_emit_pol
Create Date: 2026-05-12

Q-C scope (BL-3 + BL-14 bundled) — A2A v0.3.0 -> v1.0 migration.

JSONB CONTENT migration (NO DDL). For each agent_cards row, canonicalize
card_data via services/a2a_v1/compat.canonicalize_card_data():
  - Derives securitySchemes{} + security[] from v0.3 authSchemes[]
  - Derives supportedInterfaces[] from v0.3 top-level url + preferredTransport
  - Backfills capabilities.extendedAgentCard
  - Bumps protocolVersion to "1.0", preserves original in schemaVersion

Does NOT strip v0.3 fields — both shapes coexist for 6-month transition
(Commander Q5 signoff 2026-05-12). 0054_drop_v03_fields.py lands ~6mo later.

IDEMPOTENT — canonicalize_card_data is a no-op on already-v1.0 cards.
The WHERE clause filters out already-migrated rows. Safe to replay
(matters for cloud-op migration_bridge which resets to 0001).

Revision-id length: 22 chars.
"""
from __future__ import annotations

import json
import logging
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "0053_a2a_v1_cardshape"
down_revision: Union[str, None] = "0052_fiat_emit_pol"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


logger = logging.getLogger(__name__)


def upgrade() -> None:
    """Backfill all agent_cards rows to v1.0 dual-shape."""
    from agentvault_registry.services.a2a_v1.compat import (
        canonicalize_card_data,
        is_v1_card,
    )

    bind = op.get_bind()

    rows = bind.execute(
        text("SELECT id, card_data FROM agent_cards WHERE card_data IS NOT NULL")
    ).fetchall()

    upgraded = 0
    skipped = 0
    for row in rows:
        card_data = row.card_data
        if not isinstance(card_data, dict):
            try:
                card_data = json.loads(card_data) if isinstance(card_data, (str, bytes)) else card_data
            except (TypeError, ValueError):
                logger.warning("[0053] skipping row %s: card_data not parseable", row.id)
                skipped += 1
                continue

        if is_v1_card(card_data):
            skipped += 1
            continue

        new_card_data = canonicalize_card_data(card_data)
        if new_card_data == card_data:
            skipped += 1
            continue

        bind.execute(
            text("UPDATE agent_cards SET card_data = CAST(:cd AS JSON), updated_at = NOW() WHERE id = :id"),
            {"cd": json.dumps(new_card_data), "id": str(row.id)},
        )
        upgraded += 1

    logger.info(
        "[0053_a2a_v1_cardshape] upgrade complete: %d rows upgraded, %d skipped",
        upgraded, skipped,
    )


def downgrade() -> None:
    """Reverse: strip v1.0-derived fields, restore v0.3 shape (lossy)."""
    from agentvault_registry.services.a2a_v1.compat import render_for_v03_peer

    bind = op.get_bind()
    rows = bind.execute(
        text("SELECT id, card_data FROM agent_cards WHERE card_data IS NOT NULL")
    ).fetchall()

    for row in rows:
        card_data = row.card_data
        if not isinstance(card_data, dict):
            try:
                card_data = json.loads(card_data) if isinstance(card_data, (str, bytes)) else card_data
            except (TypeError, ValueError):
                continue

        if "supportedInterfaces" not in card_data and "securitySchemes" not in card_data:
            continue

        downgraded = render_for_v03_peer(card_data)
        bind.execute(
            text("UPDATE agent_cards SET card_data = CAST(:cd AS JSON), updated_at = NOW() WHERE id = :id"),
            {"cd": json.dumps(downgraded), "id": str(row.id)},
        )
