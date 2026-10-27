"""§MCPTEST30 (V0524, 2026-10-01) — a unique name asked for twice: one object and one refusal, never a server error.

`teams` carry UNIQUE(organization_id, name), and a team is soft-deleted (is_active = false, the name stays in the index).
A route that checks nothing before its insert hands the database's IntegrityError to the caller as a 500, for a
duplicate asked in a row as much as for two asked at once, and for the name of a team deleted long ago. Three cases on
the run's own organization, each with a fresh name, and every team the probe made deleted again:
  concurrent    two createOrganizationTeam at once: one success and one 4xx. A 5xx, or two successes, is the finding.
  sequential    the same name twice in a row: a success, then a 4xx naming the conflict. A 5xx is the finding.
  after_delete  a deleted team's name asked again: a success (V0524: a deleted team gives its name up). A refusal is
                the finding (no listed team carries the name), and so is a 5xx.
Rows `race: createOrganizationTeam <case>`; they keep kinds and statuses, never a name or an id.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

PREFIX = "race: "
TOOL = "theprotocol_createOrganizationTeam"
_STATUS = re.compile(r"\b(?:HTTP|returned)\s+(\d{3})\b")


def kind_of(ok: bool, inner: Any, code: Any, answered: Callable) -> Tuple[str, Optional[int]]:
    """`created`, `refused` (a 4xx the tool passed on), `server_error` (a 5xx, or the words of one), `no_answer`."""
    if answered(ok, inner, code):
        return "created", None
    if inner in (None, {}, []) and not str(code or "").startswith("2"):
        return "no_answer", None
    t = inner.get("_text") if isinstance(inner, dict) else None
    text = t if isinstance(t, str) else json.dumps(inner, default=str)
    m = _STATUS.search(text or "")
    wrapped = str(code or "")
    st = int(m.group(1)) if m else (int(wrapped) if wrapped.isdigit() and not wrapped.startswith("2") else None)
    if (st is not None and st >= 500) or "Internal Server Error" in (text or ""):
        return "server_error", st
    return "refused", st


def verdict(case: str, kinds: List[Tuple[str, Optional[int]]]) -> Tuple[Optional[bool], Optional[str], Dict[str, Any]]:
    """(healthy | None for NOT MEASURED, the failure or skip sentence, evidence) for one case."""
    ev = {"answers": [f"{k} HTTP {s}" if s else k for k, s in kinds]}
    names = [k for k, _s in kinds]
    if "no_answer" in names:
        return None, "NOT MEASURED: a create did not come back over MCP", ev
    if "server_error" in names:
        return False, (f"BUG-FIND: race: {case}: a duplicate team name answered a server error ({', '.join(ev['answers'])}): "
                       "the unique index refused the insert and nobody turned that into a refusal"), ev
    if case == "concurrent":
        if names.count("created") != 1:
            return False, (f"BUG-FIND: race: concurrent: two creates of one name gave {names.count('created')} teams "
                           f"({', '.join(ev['answers'])}): the name is unique, exactly one may be made"), ev
        return True, None, ev
    if case == "sequential":
        if names != ["created", "refused"]:
            return False, (f"BUG-FIND: race: sequential: the same name twice in a row answered {', '.join(ev['answers'])}, "
                           "not a team then a refusal"), ev
        return True, None, ev
    # after_delete: the deleted team's name is free again (V0524: a deleted team gives its name up)
    if names != ["created"]:
        return False, (f"BUG-FIND: race: after_delete: the name of a deleted team stayed taken ({', '.join(ev['answers'])}) "
                       "while no listed team carries it"), ev
    return True, None, ev


async def run_race(rpc: Callable, parse: Callable, bag: Any, outcomes: Dict[str, dict], make_outcome: Callable,
                   answered: Callable) -> None:
    """The three cases on the run's organization (flow_values.organization_id), developer JWT; rows `race: ...`."""
    org_id = (getattr(bag, "flow_values", None) or {}).get("organization_id")
    jwt = getattr(bag, "developer_jwt", "") or ""
    cases = ("concurrent", "sequential", "after_delete")
    if not org_id or not jwt:
        for case in cases:
            name = f"{PREFIX}createOrganizationTeam {case}"
            outcomes[name] = make_outcome(name, "race", False, "0", 0, None, {}, expect_status="any",
                                          skip_reason="NOT MEASURED: the run has no organization of its own to create teams in")
        return

    async def create(team_name: str) -> Tuple[str, Optional[int]]:
        ok, body, code = await rpc(TOOL, {"org_id": str(org_id), "name": team_name,
                                          "description": "MCP tester unique-name probe"}, jwt=jwt, timeout=30)
        return kind_of(ok, parse(body), code, answered)

    async def teams_named(team_name: str) -> List[str]:
        ok, body, _c = await rpc("theprotocol_listOrganizationTeams", {"org_id": str(org_id)}, jwt=jwt, timeout=30)
        inner = parse(body)
        rows = inner.get("teams", inner.get("items")) if isinstance(inner, dict) else inner
        return [str(t.get("id")) for t in (rows or []) if isinstance(t, dict) and t.get("name") == team_name and t.get("id")]

    async def drop(team_name: str) -> int:
        n = 0
        for tid in await teams_named(team_name):
            ok, _b, _c = await rpc("theprotocol_deleteOrganizationTeam", {"org_id": str(org_id), "team_id": tid},
                                   jwt=jwt, timeout=30)
            n += 1 if ok else 0
        return n

    async def record(case: str, kinds: List[Tuple[str, Optional[int]]], t0: float, extra: Dict[str, Any]) -> None:
        healthy, sentence, ev = verdict(case, kinds)
        ev.update(extra)
        name = f"{PREFIX}createOrganizationTeam {case}"
        outcomes[name] = make_outcome(name, "race", bool(healthy), "200", int((time.time() - t0) * 1000),
                                      sentence if healthy is False else None, {}, expect_status="any",
                                      skip_reason=sentence if healthy is None else None)
        outcomes[name]["result_excerpt"] = ev

    tag = uuid.uuid4().hex[:8]
    t0 = time.time()
    n1 = f"mcp-race-{tag}"
    kinds = list(await asyncio.gather(create(n1), create(n1)))
    made = len(await teams_named(n1))
    await record("concurrent", kinds, t0, {"teams_made": made, "deleted": await drop(n1)})

    t0 = time.time()
    n2 = f"mcp-seq-{tag}"
    kinds = [await create(n2), await create(n2)]
    deleted = await drop(n2)
    await record("sequential", kinds, t0, {"deleted": deleted})

    t0 = time.time()
    kinds = [await create(n2)]   # the name of the team deleted just above
    await record("after_delete", kinds, t0, {"deleted": await drop(n2)})
