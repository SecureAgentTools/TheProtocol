"""§MCPTEST30 (V0546) — a paying achievement is a money path any developer can open: the run says so the day one appears.

POST /achievements/record (and /claim-pending) pays an enabled achievement's `payout_avt` from the reward waterfall
(/admin/reward-fund on the TEG) to ANY agent DID the caller names, once per (developer, type), with no proof the
achievement was earned (sessionlogs2026/FINDINGS_2026-10-02_TEG_ADMIN_SCOPE.md, section 6). It is latent while no enabled
achievement pays: achievement_rewards held 0 rows on every node on 2026-10-02. With open registration, one paying row
is a faucet whose size is the number of accounts anyone can make.

This row reads the public catalog (enabled achievements only, with their payout) once per run. A paying entry turns it
red and names the types; a catalog with nothing that pays is a pass that says so. It reads only, and keeps types and
counts, never an amount.
"""
from __future__ import annotations

import time
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, Optional, Tuple

PREFIX = "achievements: "
ROW = PREFIX + "an unearned claim pays nothing"
FINDINGS = "FINDINGS_2026-10-02_TEG_ADMIN_SCOPE.md, section 6"


def _pays(value: Any) -> bool:
    try:
        return Decimal(str(value)) > 0
    except (InvalidOperation, TypeError, ValueError):
        return False


def verdict(catalog: Any) -> Tuple[bool, Optional[str], Optional[str], Dict[str, Any]]:
    """(healthy, fail, skip, evidence) for the catalog's answer."""
    rows = catalog.get("achievements") if isinstance(catalog, dict) else None
    if not isinstance(rows, list):
        return False, None, "NOT MEASURED: the achievement catalog did not answer a list", {}
    paying = [a for a in rows if isinstance(a, dict) and _pays(a.get("payout_avt"))]
    ev: Dict[str, Any] = {"enabled": len(rows), "paying": len(paying),
                          "paying_types": [str(a.get("type"))[:60] for a in paying][:10]}
    if paying:
        return False, (f"BUG-FIND: achievements: {len(paying)} enabled achievement(s) pay ({', '.join(ev['paying_types'])}): "
                       "any developer can claim each for any agent DID with no proof it was earned, paid from the funding "
                       f"waterfall ({FINDINGS})"), None, ev
    return True, None, None, ev


async def run_achievement_claims(rpc: Callable, parse: Callable, bag: Any, outcomes: Dict[str, dict],
                                 make_outcome: Callable, answered: Callable, said: Callable) -> None:
    t0 = time.time()
    ok, body, code = await rpc("theprotocol_getAchievementCatalog", {}, jwt=getattr(bag, "developer_jwt", "") or "",
                               timeout=20)
    inner = parse(body)
    ms = int((time.time() - t0) * 1000)
    if not answered(ok, inner, code):
        outcomes[ROW] = make_outcome(ROW, "achievements", False, str(code), ms, None, {}, expect_status="success",
                                     skip_reason=f"NOT MEASURED: the achievement catalog did not answer ({said(inner)[:100]})")
        return
    healthy, fail, skip, ev = verdict(inner)
    outcomes[ROW] = make_outcome(ROW, "achievements", healthy, str(code), ms, fail, {}, expect_status="success",
                                 skip_reason=skip)
    outcomes[ROW]["result_excerpt"] = ev
