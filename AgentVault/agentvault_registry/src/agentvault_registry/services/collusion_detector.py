"""
CollusionDetector — Economic Engine Sprint 10 §5.4

Detects strongly-connected agent clusters (potential collusion rings) using
Tarjan's SCC algorithm on the cross-registry trust graph.

Requires: networkx (pip install networkx)
  → Add to Dockerfile: RUN pip install networkx
  → If networkx is unavailable the detector degrades gracefully to a no-op.

Strategy:
  1. Build a directed graph: edge A→B if A has transferred to B >= MIN_EDGE_WEIGHT AVT
     (aggregated from LocalTrustScore.satisfactory * volume proxy).
  2. Find all SCCs with size >= MIN_SCC_SIZE.
  3. Score each SCC by internal_transfer_ratio = intra_ring_volume / total_ring_volume.
  4. Flag rings where score >= COLLUSION_SCORE_THRESHOLD as suspicious.
  5. Write AuditorFlagLog rows for newly-detected rings.

Calling convention:
    detector = get_collusion_detector()
    rings = await detector.run(db)
    # rings: list of {nodes: [did, ...], score: float, flag_id: str}

Called daily by background_tasks/collusion_worker.py.
"""
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_

logger = logging.getLogger(__name__)

# Tuning constants
MIN_EDGE_WEIGHT = 10        # minimum total transfers between a pair to form an edge
MIN_SCC_SIZE = 3            # minimum agents in a suspicious ring
COLLUSION_SCORE_THRESHOLD = 0.75  # internal transfer ratio above which ring is flagged


def _try_import_networkx():
    """Graceful import: return nx module or None."""
    try:
        import networkx as nx
        return nx
    except ImportError:
        logger.warning(
            "[CollusionDetector] networkx not installed. "
            "SCC analysis disabled. Add 'RUN pip install networkx' to Dockerfile."
        )
        return None


class CollusionDetector:
    """
    Directed-graph SCC collusion detector.

    Uses networkx if available; degrades to no-op with a warning if missing.
    """

    async def run(self, db: AsyncSession) -> List[Dict[str, Any]]:
        """
        Execute one detection pass.

        Returns list of flagged ring dicts:
            {nodes: [did,...], score: float, scc_size: int, flag_id: str|None}

        flag_id is the AuditorFlagLog.id if a new log row was written, else None
        (existing logs are not duplicated).
        """
        nx = _try_import_networkx()
        if nx is None:
            return []

        # Step 1: Build graph from LocalTrustScore bilateral trust data
        G = await self._build_graph(db, nx)
        if G.number_of_nodes() == 0:
            logger.info("[CollusionDetector] Empty graph; nothing to analyse")
            return []

        # Step 2: Find SCCs
        sccs = [scc for scc in nx.strongly_connected_components(G) if len(scc) >= MIN_SCC_SIZE]
        if not sccs:
            logger.info(f"[CollusionDetector] No SCCs >= {MIN_SCC_SIZE} nodes found")
            return []

        # Step 3+4: Score and filter
        flagged = []
        for scc_nodes in sccs:
            score = self._score_scc(G, scc_nodes)
            if score >= COLLUSION_SCORE_THRESHOLD:
                flag_id = await self._write_flag(db, list(scc_nodes), score)
                flagged.append({
                    "nodes": sorted(scc_nodes),
                    "score": round(score, 4),
                    "scc_size": len(scc_nodes),
                    "flag_id": flag_id,
                })

        if flagged:
            logger.warning(
                f"[CollusionDetector] {len(flagged)} suspicious ring(s) detected: "
                + ", ".join(f"size={r['scc_size']} score={r['score']}" for r in flagged)
            )
        else:
            logger.info(
                f"[CollusionDetector] {len(sccs)} SCC(s) analysed; "
                f"none exceeded threshold {COLLUSION_SCORE_THRESHOLD}"
            )

        return flagged

    async def _build_graph(self, db: AsyncSession, nx) -> Any:
        """
        Build directed graph from LocalTrustScore: edge A→B if satisfactory >= MIN_EDGE_WEIGHT.
        """
        from ..models import LocalTrustScore

        result = await db.execute(
            select(
                LocalTrustScore.from_did,
                LocalTrustScore.to_did,
                LocalTrustScore.satisfactory,
            ).where(LocalTrustScore.satisfactory >= MIN_EDGE_WEIGHT)
        )
        rows = result.all()

        G = nx.DiGraph()
        for from_did, to_did, weight in rows:
            G.add_edge(from_did, to_did, weight=int(weight))

        logger.info(
            f"[CollusionDetector] Graph: {G.number_of_nodes()} nodes, "
            f"{G.number_of_edges()} edges (threshold={MIN_EDGE_WEIGHT})"
        )
        return G

    def _score_scc(self, G: Any, scc_nodes: set) -> float:
        """
        Compute internal transfer ratio for the SCC.

        score = intra_ring_edge_weight_sum / total_incident_edge_weight_sum
        """
        scc_set = set(scc_nodes)
        intra = sum(
            d.get("weight", 1)
            for u, v, d in G.edges(data=True)
            if u in scc_set and v in scc_set
        )
        total = sum(
            d.get("weight", 1)
            for u, v, d in G.edges(data=True)
            if u in scc_set or v in scc_set
        )
        return intra / total if total > 0 else 0.0

    async def _write_flag(
        self, db: AsyncSession, nodes: List[str], score: float
    ) -> Optional[str]:
        """
        Write an AuditorFlagLog row for the detected ring.
        Skips if an identical ring (same anchor node) was already flagged today.
        """
        from ..models import AuditorFlagLog

        nodes_key = ",".join(sorted(nodes))
        now_utc = datetime.now(timezone.utc)
        today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

        # De-dup: check if same ring anchor already flagged today
        existing = await db.execute(
            select(AuditorFlagLog.id).where(
                AuditorFlagLog.flag_type == "CollusionRingDetected",
                AuditorFlagLog.created_at >= today_start,
                AuditorFlagLog.flagged_agent_did == nodes[0],
            )
        )
        if existing.scalar_one_or_none():
            return None  # already flagged today

        flag_id = str(uuid.uuid4())
        flag = AuditorFlagLog(
            flagged_agent_did=nodes[0],  # lead node as anchor
            flag_type="CollusionRingDetected",
            severity="HIGH",
            details={
                "ring_members": nodes,
                "ring_size": len(nodes),
                "collusion_score": round(score, 4),
                "threshold": COLLUSION_SCORE_THRESHOLD,
                "detection_method": "Tarjan_SCC",
                "nodes_key": nodes_key,
            },
        )
        db.add(flag)
        await db.commit()
        logger.warning(
            f"[CollusionDetector] Flagged ring: {len(nodes)} agents, score={score:.4f} "
            f"(flag_id={flag_id[:8]})"
        )
        return flag_id


# Singleton
_detector: Optional[CollusionDetector] = None


def get_collusion_detector() -> CollusionDetector:
    global _detector
    if _detector is None:
        _detector = CollusionDetector()
    return _detector
