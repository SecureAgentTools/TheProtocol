"""§MCPTEST30 (V0525, 2026-10-01) — does a write's route check the text it stores before its database does?

Measured by hand on sbx-alpha (V0521): a NUL in a team name and in an API key name answered 500 "A database error
occurred" (Postgres refuses a NUL in text and in jsonb); V0524 answers that class 422 NUL_IN_TEXT in errors.py. This
probe holds the line on three writes whose objects the run can remove again, each asked with a NUL inside, LIKE's two
wildcards ending in its escape character, and 4,000 characters:
  createOrganizationTeam   a team in the run's own organization (name)
  createApiKey             an API key of the runner (its name)
  createWebhook            a webhook of the runner pointed at an `.invalid` host (its description), so nothing it
                           would deliver can leave the sandbox
Every object a value made is removed again (teams deleted, keys revoked, webhooks deleted), by its own unique tag. A
server error is the finding; a refusal or a created-and-removed object is the route doing its job. An object the probe
made and could not remove is reported as litter on the row. Rows `write_hygiene: <tool>`, kinds only, never a value.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

PREFIX = "write_hygiene: "
_STATUS = re.compile(r"\b(?:HTTP|returned)\s+(\d{3})\b")


def hostile(tag: str) -> Tuple[Tuple[str, str], ...]:
    """(label, value) per call; each value carries the run's tag, so the cleanup finds exactly what this run made."""
    return (("nul", f"mcp-hyg-{tag}\x00n"), ("escape", f"mcp-hyg-{tag}%_\\"), ("long", f"mcp-hyg-{tag}" + "p" * 4000))


def kind_of(ok: bool, inner: Any, code: Any, answered: Callable) -> Tuple[str, Optional[int]]:
    """`stored`, `refused` (below 500), `server_error` (a 5xx or its words), `no_answer`."""
    if answered(ok, inner, code):
        return "stored", None
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


def verdict(kinds: Dict[str, Tuple[str, Optional[int]]], litter: int) -> Tuple[Optional[bool], Optional[str], Dict[str, Any]]:
    ev: Dict[str, Any] = {label: (f"{k} HTTP {st}" if st else k) for label, (k, st) in kinds.items()}
    if litter:
        ev["litter"] = litter
    errs = [label for label, (k, _st) in kinds.items() if k == "server_error"]
    if errs:
        return False, (f"BUG-FIND: write_hygiene: a text value the write does not check answered a server error "
                       f"({', '.join(errs)}): it reached the database unchecked"), ev
    if all(k == "no_answer" for k, _st in kinds.values()):
        return None, "NOT MEASURED: no write came back over MCP", ev
    return True, None, ev


def _rows(inner: Any, *keys: str) -> List[dict]:
    if isinstance(inner, list):
        return [r for r in inner if isinstance(r, dict)]
    if isinstance(inner, dict):
        for k in keys:
            v = inner.get(k)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
    return []


async def run_write_hygiene(rpc: Callable, parse: Callable, bag: Any, outcomes: Dict[str, dict], make_outcome: Callable,
                            answered: Callable) -> None:
    jwt = getattr(bag, "developer_jwt", "") or ""
    org_id = (getattr(bag, "flow_values", None) or {}).get("organization_id")
    tag = uuid.uuid4().hex[:8]
    mark = f"mcp-hyg-{tag}"

    async def call(tool: str, args: Dict[str, Any]) -> Tuple[bool, Any, Any]:
        ok, body, code = await rpc(tool, args, jwt=jwt, timeout=30)
        return ok, parse(body), code

    async def clean_teams() -> int:
        left = 0
        ok, inner, _c = await call("theprotocol_listOrganizationTeams", {"org_id": str(org_id)})
        for t in _rows(inner, "teams", "items"):
            if str(t.get("name") or "").startswith(mark):
                ok_d, _i, _c2 = await call("theprotocol_deleteOrganizationTeam", {"org_id": str(org_id), "team_id": str(t.get("id"))})
                left += 0 if ok_d else 1
        return left

    async def clean_keys() -> int:
        left = 0
        ok, inner, _c = await call("theprotocol_getMyApiKeys", {})
        for k in _rows(inner, "api_keys", "items"):
            if str(k.get("description") or k.get("name") or k.get("key_name") or "").startswith(mark) and k.get("is_active", True):
                try:
                    kid = int(k.get("id"))
                except (TypeError, ValueError):
                    left += 1
                    continue
                ok_r, _i, _c2 = await call("theprotocol_revokeApiKey", {"key_id": kid})
                left += 0 if ok_r else 1
        return left

    async def clean_hooks() -> int:
        left = 0
        ok, inner, _c = await call("theprotocol_getMyWebhooks", {})
        for h in _rows(inner, "webhooks", "items"):
            if mark in str(h.get("url") or ""):
                ok_d, _i, _c2 = await call("theprotocol_deleteWebhook", {"webhook_id": str(h.get("id"))})
                left += 0 if ok_d else 1
        return left

    cases: List[Tuple[str, Callable[[str], Dict[str, Any]], Callable, Optional[str]]] = [
        ("theprotocol_createOrganizationTeam",
         lambda v: {"org_id": str(org_id), "name": v, "description": "MCP tester write hygiene"}, clean_teams,
         None if org_id else "NOT MEASURED: the run has no organization of its own to create a team in"),
        ("theprotocol_createApiKey", lambda v: {"key_name": v}, clean_keys, None),
        ("theprotocol_createWebhook",
         lambda v: {"url": f"https://{mark}.invalid/hook", "events": ["agent.created"], "description": v}, clean_hooks, None),
    ]
    for tool, args_for, clean, unmet in cases:
        t0 = time.time()
        name = PREFIX + tool.replace("theprotocol_", "")
        if not jwt or unmet:
            outcomes[name] = make_outcome(name, "write_hygiene", False, "0", 0, None, {}, expect_status="any",
                                          skip_reason=unmet or "NOT MEASURED: no developer token")
            continue
        kinds: Dict[str, Tuple[str, Optional[int]]] = {}
        last: Any = 0
        for label, value in hostile(tag):
            ok, inner, code = await call(tool, args_for(value))
            kinds[label], last = kind_of(ok, inner, code, answered), code
        litter = await clean()
        healthy, sentence, ev = verdict(kinds, litter)
        outcomes[name] = make_outcome(name, "write_hygiene", bool(healthy), str(last or "0"), int((time.time() - t0) * 1000),
                                      sentence if healthy is False else None, {}, expect_status="any",
                                      skip_reason=sentence if healthy is None else None)
        outcomes[name]["result_excerpt"] = ev
