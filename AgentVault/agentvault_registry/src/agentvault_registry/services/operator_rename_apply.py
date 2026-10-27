"""Local apply of an operator IDENTITY rename — the per-frame command handler.

§2026-06-14 — the event-sourced rename's convergence unit. Called on EACH frame
(the home frame directly by the rename trigger, and every peer frame by the
`/federation/admin/operators/rename` endpoint that `reactor_operator_renamed`
fans out to). It mutates ONLY this frame's OWN derived rows — it never reaches
across to another frame's DB. Cross-frame propagation is the event + reactor +
HTTP fanout, NOT direct cross-frame SQL (see
`memory/feedback_no_cross_frame_db_mutation_use_events`).

What it updates locally, keyed on the OLD slug (stable at rename time):
  • `peer_registries` row for the op → name/base_url/operator_did in place
    (the routing key — `_resolve_receiver_registry`, canary, GCC relay all read
    `peer_registries.name`). UPDATE-in-place, so no stale duplicate row is left
    behind (the hazard if we let federation_sync re-discover the new name).
  • §2026-06-16 (a) — DEACTIVATE any *other* row still carrying the OLD slug
    (esp. `peer_type='discovered'` ghosts re-seeded by the registry-card fan-out).
    These shadow the canonical row in `_resolve_receiver_registry` Step-3 (raw
    `status='ACTIVE'` scan) and cause cross-TEG dials to the old-slug hostname
    against a new-slug SVID cert → TLS hostname-mismatch (the london→singapore
    FX-corridor refund). Set status=INACTIVE so the resolver skips them.
  • every native/shadow `agent_cards` card referencing the OLD slug in
    `card_data.federation_metadata`:
      - `origin_registry_name` (the BFS PASS value) → new slug.
      - §2026-06-16 (b) — `source_registry` / `first_synced_from` /
        `last_synced_from` SPIFFE strings → reslug the OLD-slug token to NEW.
        `source_registry` is the FIRST key `_resolve_receiver_registry` Step-3
        matches on; it is sticky/write-once at ingestion so a re-sync never fixes
        it. Both wire encodings are handled (`/operator/<slug>/…` canonical and
        the legacy `…/sa/registry-<slug>` synthesized SVID).
  • §2026-06-16 (c) — `canary_remote_paths.home_registry` old→new (master-only
    table; a harmless no-op off the master scheduler).
  • §2026-06-19 (d) — `exchange_participants.home_registry` old→new (audit/display
    hygiene; same "rename leaves stale derived rows" class as (c)). This is the home
    LABEL on a dev_card holder — surfaced in admin/participants and stamped onto repat
    gateway-credits. It is NOT a routing key: AGORA dividend repatriation
    (`_foreign_home` → `dividend_repat_park` → `/teg/send`) routes by the holder's DID
    (+ auto-FX), so a stale label never strands a payout — this only keeps the label
    truthful after a rename. Matches the prod `op-<slug>` value; non-unique →
    blind UPDATE (no collision guard). Local table on every venue registry.

Idempotent: re-running with the same args is a no-op (rows already at new_slug
won't match). `dry_run=True` computes the would-change counts then ROLLS BACK
(used by the mainframe admin reconcile endpoint to preview). Returns counts for
the audit log.
"""
import logging
from typing import Any, Dict, Optional

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from agentvault_registry import models

logger = logging.getLogger(__name__)


def _reslug_value(val: Optional[str], old: str, new: str) -> Optional[str]:
    """Rewrite the OLD operator slug to NEW inside a SPIFFE/identity string.

    Handles the two encodings seen in the wild and a bare-slug value, matching
    only TOKEN-bounded occurrences so it can never touch a substring of an
    unrelated slug. Idempotent (returns the input unchanged once already NEW):
      • canonical SVID : spiffe://<td>/operator/<old>/...  → /operator/<new>/...
      • legacy synth   : spiffe://.../sa/registry-<old>     → .../sa/registry-<new>
    """
    if not isinstance(val, str) or not val or old not in val:
        return val
    if val == old:
        return new
    out = val.replace(f"/operator/{old}/", f"/operator/{new}/")
    if out.endswith(f"/operator/{old}"):
        out = out[: -len(old)] + new
    out = out.replace(f"registry-{old}", f"registry-{new}")
    return out


async def apply_operator_rename_local(
    db: AsyncSession,
    *,
    old_slug: str,
    new_slug: str,
    new_base_url: Optional[str] = None,
    new_operator_did: Optional[str] = None,
    dry_run: bool = False,
    actor: str = "operator_rename",
) -> Dict[str, Any]:
    """Apply a rename to THIS frame's local rows. Local DB only; idempotent.

    dry_run=True → compute counts then ROLL BACK (no mutation), for preview.
    """
    out: Dict[str, Any] = {
        "old_slug": old_slug, "new_slug": new_slug, "dry_run": bool(dry_run),
        "peer_rows": 0, "deactivated_stale": 0, "card_rows": 0,
        "canary_remote_paths": 0, "exchange_participants": 0, "actor": actor,
    }
    if not old_slug or not new_slug or old_slug == new_slug:
        out["error"] = "old_slug/new_slug invalid or identical"
        return out

    # 1) peer_registries — rename the routing row IN PLACE (keyed on the old slug
    #    name; exact-match, the value the trigger captured before the flip).
    old_row = (await db.execute(
        select(models.PeerRegistry).where(models.PeerRegistry.name == old_slug)
    )).scalar_one_or_none()
    new_row = (await db.execute(
        select(models.PeerRegistry).where(models.PeerRegistry.name == new_slug)
    )).scalar_one_or_none()
    if old_row is not None and new_row is not None and old_row.id != new_row.id:
        # Dedup: federation_sync (or a prior partial run) already inserted a `new`
        # row alongside the `old` one. Collapse to one — keep `new`, drop the stale
        # `old` duplicate (the hazard the in-place rename exists to avoid).
        if new_base_url:
            new_row.base_url = new_base_url
        if new_operator_did and hasattr(new_row, "operator_did"):
            new_row.operator_did = new_operator_did
        await db.delete(old_row)
        out["peer_rows"] = 1
        out["deduped"] = True
    elif old_row is not None:
        old_row.name = new_slug
        if new_base_url:
            old_row.base_url = new_base_url
        if new_operator_did and hasattr(old_row, "operator_did"):
            old_row.operator_did = new_operator_did
        out["peer_rows"] = 1
    elif new_row is not None:
        # Already converged to `new` (idempotent replay) — just refresh base_url.
        if new_base_url:
            new_row.base_url = new_base_url

    # 1b) §2026-06-16 (a) — DEACTIVATE any OTHER row still named with the old slug
    #     (the canonical row is now `new_slug` after the block above). These are
    #     `discovered` ghosts re-seeded via the registry-card fan-out; left ACTIVE
    #     they shadow-match the resolver Step-3 and mis-route cross-TEG to the
    #     old-slug hostname. Flush first so the in-place rename/delete is visible
    #     to this WHERE (autoflush would do it anyway; explicit for clarity).
    await db.flush()
    deact = await db.execute(
        update(models.PeerRegistry)
        .where(models.PeerRegistry.name == old_slug,
               models.PeerRegistry.status != "INACTIVE")
        .values(status="INACTIVE")
    )
    out["deactivated_stale"] = int(deact.rowcount or 0)

    # 2) agent_cards — re-stamp origin_registry_name AND reslug the SPIFFE identity
    #    fields (source_registry/first_synced_from/last_synced_from). Broadened
    #    scan so it catches BOTH a fresh rename (origin still == old) AND a
    #    reconcile of an already-origin-migrated card (origin already new, but the
    #    sticky source_registry SPIFFE still embeds the old slug).
    rows = (await db.execute(
        select(models.AgentCard).where(
            text(
                "card_data->'federation_metadata'->>'origin_registry_name' = :old "
                "OR card_data->'federation_metadata'->>'source_registry' LIKE :oldlike "
                "OR card_data->'federation_metadata'->>'first_synced_from' LIKE :oldlike "
                "OR card_data->'federation_metadata'->>'last_synced_from' LIKE :oldlike"
            )
        ).params(old=old_slug, oldlike=f"%{old_slug}%")
    )).scalars().all()
    for c in rows:
        cd = dict(c.card_data or {})
        fm = dict(cd.get("federation_metadata") or {})
        changed = False
        if fm.get("origin_registry_name") == old_slug:
            fm["origin_registry_name"] = new_slug
            changed = True
        for key in ("source_registry", "first_synced_from", "last_synced_from"):
            nv = _reslug_value(fm.get(key), old_slug, new_slug)
            if nv != fm.get(key):
                fm[key] = nv
                changed = True
        if changed:
            cd["federation_metadata"] = fm
            c.card_data = cd
            out["card_rows"] += 1

    # 3) §2026-06-16 (c) — canary_remote_paths master schedule (registry-a only;
    #    empty no-op on non-master frames). Collision-safe: a prior partial rename
    #    (or the canary ② repoint) may already hold (new_slug, remote_path_id) rows
    #    alongside the old — UNIQUE(home_registry, remote_path_id) would reject a
    #    blind rename, so DELETE the colliding OLD rows first, then rename the rest.
    _crp = models.CanaryRemotePath
    _crp_new = aliased(_crp)
    _collide = (
        select(_crp_new.id)
        .where(func.lower(_crp_new.home_registry) == new_slug.lower(),
               _crp_new.remote_path_id == _crp.remote_path_id)
        .exists()
    )
    crp_del = await db.execute(
        delete(_crp).where(func.lower(_crp.home_registry) == old_slug.lower(), _collide)
    )
    crp_upd = await db.execute(
        update(_crp).where(func.lower(_crp.home_registry) == old_slug.lower())
        .values(home_registry=new_slug)
    )
    out["canary_remote_paths"] = int((crp_del.rowcount or 0) + (crp_upd.rowcount or 0))

    # 4) §2026-06-19 (d) — exchange_participants.home_registry old→new (audit/display
    #    hygiene; same rename-leaves-stale-derived-rows class as block 3). It is the
    #    home LABEL on a dev_card holder + the attribution stamped on repat gateway-
    #    credits — NOT a routing key: dividend repatriation /teg/send routes by the
    #    holder's DID (+ auto-FX), so a stale label never strands a payout; this only
    #    keeps the label truthful after a rename. Matches the prod `op-<slug>` value
    #    (sim-created `cloud-op-op-<slug>` artifacts are ephemeral / recreated each run
    #    and need no fixup). home_registry is non-unique (PK=id; only agent_did is
    #    UNIQUE) → blind UPDATE, no collision guard. Local table; no-op where none here.
    ep_upd = await db.execute(
        update(models.ExchangeParticipant)
        .where(func.lower(models.ExchangeParticipant.home_registry) == old_slug.lower())
        .values(home_registry=new_slug)
    )
    out["exchange_participants"] = int(ep_upd.rowcount or 0)

    if dry_run:
        await db.rollback()
    else:
        await db.commit()
    logger.info(
        "[OperatorRenameApply]%s %s → %s : peer_rows=%s deactivated_stale=%s "
        "card_rows=%s canary_remote_paths=%s exchange_participants=%s (actor=%s)",
        " DRY-RUN" if dry_run else "", old_slug, new_slug, out["peer_rows"],
        out["deactivated_stale"], out["card_rows"], out["canary_remote_paths"],
        out["exchange_participants"], actor,
    )
    return out
