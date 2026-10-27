"""GÖDEL FORGE — the self-improving-harness arena API (2026-07-19).

Endpoints (under the FORGE_ENABLED master gate: 403 when the arena is dark, except the status read, which says so):
  GET  /forge/status                 — flags + arena counts (public); {"enabled": false} while the arena is dark
  GET  /forge/lineages/{org_id}      — the Evolution Tree: org roster ∪ spawn kinship ∪ bundle
                                       fork graph ∪ eval scores (one derived view over 4 sources)
  POST /forge/evals/run              — a harness self-triggers an eval run against ITSELF (or a
                                       target it holds forge.evolve_for_org for); EVALS_AGENT_TRIGGER_ENABLED

Δ-irrelevant (reads + an eval trigger; the eval runner's pay is the Δ-neutral carve). No endpoint
here moves money or mints authority.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Body, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..security import get_current_developer, get_current_agent
from .. import models, forge_flags

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/forge", tags=["GÖDEL FORGE"])


DARK_SENTENCE = "GÖDEL FORGE is not enabled on this registry (FORGE_ENABLED)"


def _require_forge():
    if not forge_flags.forge_enabled():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=DARK_SENTENCE)


@router.get("/status", summary="Forge arena status + flags (public)")
async def forge_status(
    db: AsyncSession = Depends(get_db),
):
    if not forge_flags.forge_enabled():
        # §MCPTEST30 V0556 (agentvault2-45's point): the status read SAYS the arena is dark instead of refusing, so the page
        # that asks makes no refused call; the arena's other routes stay behind the gate (403). No database read.
        return {"enabled": False, "detail": DARK_SENTENCE, "lineages": [], "flags": {}, "counts": {}}
    counts = {}
    try:
        counts["lineage_bundles"] = (await db.execute(text(
            "SELECT count(*) FROM agent_bundles WHERE forked_from_bundle_id IS NOT NULL"))).scalar() or 0
        counts["verifiers"] = (await db.execute(text(
            "SELECT count(DISTINCT delegate_agent_did) FROM agent_delegation_grants "
            "WHERE revoked_at IS NULL AND 'forge.verify_for_org' = ANY(permissions)"))).scalar() or 0
        counts["code_patch_results"] = (await db.execute(text(
            "SELECT count(*) FROM eval_results r JOIN eval_tasks t ON t.id = r.task_id "
            "WHERE t.scorer = 'code_patch'"))).scalar() or 0
    except Exception as e:  # noqa: BLE001
        logger.debug("[FORGE] status counts partial: %s", e)
    # Known lineages (for the FE quick-pick): orgs that hold stamped bundles UNION orgs whose
    # members have eval results. organization_id columns are VARCHAR — validate before casting.
    lineages: list = []
    try:
        rows = (await db.execute(text(
            """
            SELECT o.id, o.name, COALESCE(b.n, 0) AS bundles
            FROM organizations o
            LEFT JOIN (SELECT source_org_id::text AS org_txt, count(*) AS n FROM agent_bundles
                       WHERE source_org_id IS NOT NULL GROUP BY source_org_id) b
                   ON b.org_txt = o.id
            WHERE b.n IS NOT NULL
               OR EXISTS (SELECT 1 FROM agents a JOIN eval_results r ON r.agent_did = a.did
                          WHERE a.organization_id = o.id)
            ORDER BY COALESCE(b.n, 0) DESC, o.created_at DESC
            LIMIT 12
            """))).fetchall()
        lineages = [{"org_id": r[0], "name": r[1], "bundles": int(r[2] or 0)} for r in rows]
    except Exception as e:  # noqa: BLE001
        logger.debug("[FORGE] status lineages partial: %s", e)
    return {
        "enabled": True,
        "lineages": lineages,
        "flags": {
            "evals_agent_trigger": forge_flags.evals_agent_trigger_enabled(),
            "royalty": forge_flags.royalty_enabled(),
            "verifier_quorum_m": forge_flags.verifier_quorum_m(),
            "royalty_default_bps": forge_flags.royalty_default_bps(),
            "royalty_max_bps": forge_flags.ROYALTY_MAX_BPS,
            "royalty_max_depth": forge_flags.ROYALTY_MAX_DEPTH,
        },
        # Batch 8 — the concrete admission policy, published so "how do I become a
        # verifier?" has a machine-readable answer the FE and docs both render.
        "verifier_prerequisites": {
            "org_consent_permission": "forge.verify_for_org",
            "min_stake": forge_flags.verifier_min_stake(),
            "min_reputation": forge_flags.verifier_min_reputation(),
            "quorum_m": forge_flags.verifier_quorum_m(),
            "max_seats_per_operator": forge_flags.verifier_max_per_operator(),
            "signed_verdicts_required": forge_flags.verifier_require_sig(),
            "endpoint": "publish your grader's URL as agent_host on your agent card",
        },
        "counts": counts,
    }


@router.get("/lineages/{org_id}", summary="Evolution Tree of a lineage organization (public)")
async def lineage_tree(
    org_id: str,
    db: AsyncSession = Depends(get_db),
):
    # Public read: everything here (DIDs, reputation, bundle names, eval scores) is already
    # public via discovery / marketplace / leaderboard — the tree is just the joined view.
    """Derived Evolution Tree = org roster (Agent.organization_id) ∪ spawn kinship
    (agent_capability_tokens birth edges) ∪ bundle fork graph (forked_from) ∪ eval scores."""
    _require_forge()
    # Roster (agents have no `name` column — the display name lives in agent_cards.card_data).
    agents = (await db.execute(text(
        "SELECT a.did, COALESCE(a.reputation_score, 0), "
        "       (SELECT c.card_data->>'name' FROM agent_cards c WHERE c.agent_did = a.did LIMIT 1) "
        "FROM agents a WHERE a.organization_id = :o"  # agents.organization_id is VARCHAR (not uuid)
    ), {"o": org_id})).fetchall()
    roster = [a[0] for a in agents]
    nodes = [{"type": "agent", "did": a[0], "name": a[2] or a[0], "reputation": int(a[1] or 0)} for a in agents]
    edges = []
    if roster:
        # Spawn kinship (birth tokens): BFS from the roster, ≤3 hops. A single roster-anchored
        # query misses grandchildren — a child→grandchild edge touches no roster DID — so walk
        # the frontier transitively (each hop's new DIDs seed the next) with a dedupe guard.
        known = set(roster)
        frontier = list(roster)
        seen_edges: set[tuple] = set()
        births: list = []
        for _hop in range(3):
            if not frontier:
                break
            rows = (await db.execute(text(
                "SELECT issuer_agent_did, holder_agent_did FROM agent_capability_tokens "
                "WHERE caveats->>'birth' = 'true' AND (issuer_agent_did = ANY(:r) OR holder_agent_did = ANY(:r))"
            ), {"r": frontier})).fetchall()
            fresh = [b for b in rows if (b[0], b[1]) not in seen_edges]
            seen_edges.update((b[0], b[1]) for b in fresh)
            births += fresh
            frontier = sorted({d for b in fresh for d in (b[0], b[1]) if d not in known})
            known.update(frontier)
        edges += [{"kind": "spawn", "from": b[0], "to": b[1]} for b in births]
        # Spawn edges often point at variants that are NOT org members (birth kinship, not
        # roster). Without a node an edge is invisible — add "kin" ghost nodes for them.
        kin = sorted({d for b in births for d in (b[0], b[1]) if d not in set(roster)})
        if kin:
            kin_rows = (await db.execute(text(
                "SELECT a.did, COALESCE(a.reputation_score, 0), "
                "       (SELECT c.card_data->>'name' FROM agent_cards c WHERE c.agent_did = a.did LIMIT 1) "
                "FROM agents a WHERE a.did = ANY(:k)"), {"k": kin})).fetchall()
            nodes += [{"type": "agent", "did": k[0], "name": k[2] or k[0],
                       "reputation": int(k[1] or 0), "kin": True} for k in kin_rows]
        # Recent eval mean score per tree agent (roster + kin)
        tree_dids = roster + kin
        scores = (await db.execute(text(
            "SELECT agent_did, round(avg(score)::numeric, 3) FROM eval_results "
            "WHERE agent_did = ANY(:r) GROUP BY agent_did"
        ), {"r": tree_dids})).fetchall()
        smap = {s[0]: float(s[1]) for s in scores}
        for n in nodes:
            if n.get("type") == "agent":
                n["eval_score"] = smap.get(n["did"])
    # Bundle fork graph for this org
    bundles = (await db.execute(text(
        "SELECT id, name, forked_from_bundle_id, COALESCE(royalty_bps,0) "
        "FROM agent_bundles WHERE source_org_id = CAST(:o AS UUID)"
    ), {"o": org_id})).fetchall()
    for b in bundles:
        nodes.append({"type": "bundle", "id": str(b[0]), "name": b[1], "royalty_bps": int(b[3] or 0)})
        if b[2]:
            edges.append({"kind": "fork", "from": str(b[2]), "to": str(b[0])})
    return {"org_id": org_id, "nodes": nodes, "edges": edges,
            "agent_count": len(roster), "bundle_count": len(bundles)}


class EvalRunRequest(BaseModel):
    suite_id: int
    target_did: Optional[str] = None  # default = the caller (self-eval)


_EVAL_TARGET_REFUSED = ("Evaluating another agent requires owning it (the same developer account) or a live "
                        "forge.evolve_for_org grant from the organization that agent and you belong to")


async def _eval_target_refusal(db: AsyncSession, agent: models.Agent, target_did: str) -> Optional[str]:
    """None when ``agent`` may run an eval suite against ``target_did`` (another agent), else the refusal.

    D6-686 (2026-10-16), the design of agent_authz.py and services/org_authz.py: ``forge.evolve_for_org`` is an
    org-consent permission, honored ONLY through an ``org:`` delegation grant (a role, legacy-full included, never
    suffices), and it speaks for the org's own lineage. The route asked ``resolve_agent_permissions`` instead (the
    agent's roles, where legacy-full carries every permission) and never related the permission to the target, so
    any legacy-full agent could run suites against any agent on the registry. Allowed now:
      - the target belongs to the caller's own developer account (a variant it spawned, or a sibling agent), or
      - the target and the caller belong to the same organization, and that organization has granted the caller
        ``forge.evolve_for_org`` (a live grant: not revoked, not expired).
    """
    row = (await db.execute(text(
        "SELECT creator_developer_id, organization_id FROM agents WHERE did = :d"), {"d": target_did})).first()
    if row is None:
        return _EVAL_TARGET_REFUSED
    target_dev, target_org = row[0], row[1]
    if target_dev is not None and target_dev == getattr(agent, "creator_developer_id", None):
        return None
    if not target_org or target_org != getattr(agent, "organization_id", None):
        return _EVAL_TARGET_REFUSED
    slug = (await db.execute(text("SELECT slug FROM organizations WHERE id = :o"), {"o": target_org})).scalar()
    refs = [f"org:{target_org}"] + ([f"org:{slug}"] if slug else [])
    grant = (await db.execute(text(
        "SELECT 1 FROM agent_delegation_grants WHERE delegate_agent_did = :d AND principal_type = 'org' "
        "AND principal_ref = ANY(:refs) AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now()) "
        "AND 'forge.evolve_for_org' = ANY(permissions) LIMIT 1"
    ), {"d": agent.did, "refs": refs})).first()
    return None if grant is not None else _EVAL_TARGET_REFUSED


@router.post("/evals/run", summary="Harness self-triggers an eval run")
async def trigger_eval(
    body: EvalRunRequest = Body(...),
    agent: models.Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """A self-improving harness runs an eval suite against ITSELF (or a target it is delegated
    ``forge.evolve_for_org`` for). Gated EVALS_AGENT_TRIGGER_ENABLED; scores settle via the runner
    (code_patch → verifier quorum). No self-reported scores."""
    _require_forge()
    # Jurisdiction Profiles (SPEC 2026-07-31): operator-declared feature restriction.
    # Deny-only, pre-escrow, before any money moves. Byte-inert while JURISDICTION_MODE=off.
    from agentvault_registry.services import jurisdiction as _juris
    await _juris.check_jurisdiction(db, "forge", actor=agent.did)
    if not forge_flags.evals_agent_trigger_enabled():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Agent-triggered eval runs are disabled (EVALS_AGENT_TRIGGER_ENABLED)")
    target = body.target_did or agent.did
    if target != agent.did:
        # Another agent: owned by the caller's developer, or an org grant for that target (D6-686).
        refusal = await _eval_target_refusal(db, agent, target)
        if refusal:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=refusal)
    from ..background_tasks.eval_runner import run_suite_once_for, EVALS_ENABLED
    if not EVALS_ENABLED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="EVALS_ENABLED is false here")
    run_id = await run_suite_once_for(body.suite_id, target)
    if run_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suite not found")
    return {"suite_id": body.suite_id, "target_did": target, "run_id": run_id, "status": "completed"}
