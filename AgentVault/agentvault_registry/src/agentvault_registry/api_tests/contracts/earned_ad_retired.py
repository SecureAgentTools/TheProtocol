"""§MCPTEST30 (V0651, order (p) gwo_b109ec1d4454d0db66ef6d32, agentvault2-d3, 2026-10-31): the retired token bridge,
measured where it is retired. His word, typed in agentvault2-d3's session ~11:43Z: "retire." Session-release's
v0651/retire-token-bridge (e2fb85a8f) answers each of the bridge's six routes 410 Gone (application/problem+json, title
"Gone", the retirement sentence in "detail") on every registry, whatever TOKEN_BRIDGE_ENABLED says, reading no body and
running no dependency (room seq 238). Its five MCP tools left the catalogs; getBridgeAggregate stays, an admin read of the
history.

One row reads all six through the admin bridge (adminRequest with the run's admin token: the routes take no caller's
identity, so the token decides nothing). Nothing moves: a retired route runs no handler.
  retired: the token bridge's six routes   each answers 410, title "Gone", the sentence word for word
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

from agentvault_registry.api_tests.contracts.earned_fixtures import lc, unmeasured

ROW = "retired: the token bridge's six routes"
TIER = "admin"
SENTENCE = ("The token bridge is retired (V0651, the maintainer's decision of 2026-10-31): wrapped transfers between frames "
            "are gone on every registry. Move units between frames with POST /api/v1/teg/cross-registry-transfer, or "
            "across currencies through the FX route. The bridge's history (bridge_transactions) is kept and stays "
            "readable by an admin.")
ROUTES: Tuple[Tuple[str, str], ...] = (
    ("POST", "/api/v1/bridge/transfer"), ("POST", "/api/v1/bridge/mint-wrapped"), ("POST", "/api/v1/bridge/redeem"),
    ("POST", "/api/v1/bridge/unlock"), ("POST", "/api/v1/bridge/confirm-lock"),
    ("GET", "/api/v1/bridge/status/00000000-0000-4000-8000-000000000000"))


async def _read(bag: Any, parse: Any, method: str, path: str) -> Tuple[int, Dict[str, Any]]:
    """(status, body) of one REST call through the admin bridge; (0, {}) when it could not be made."""
    args: Dict[str, Any] = {"method": method, "endpoint": path}
    if method == "POST":
        args["body"] = {}
    try:
        _ok, raw, code = await bag.rpc_admin("theprotocol_adminRequest", args, jwt=bag.developer_jwt, timeout=30)
    except Exception:                                                  # noqa: BLE001
        return 0, {}
    got = parse(raw) if isinstance(raw, dict) else {}
    got = got if isinstance(got, dict) else {}
    try:
        st = int(got.get("status_code"))
    except (TypeError, ValueError):
        st = int(code) if str(code).isdigit() else 0
    body = got.get("response") if "response" in got else got
    return st, body if isinstance(body, dict) else {}


async def lifecycle_bridge_retired(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    """The six routes, each read once (the module docstring)."""
    if getattr(bag, "rpc_admin", None) is None:
        return unmeasured(outcomes, ROW, TIER, "this flow carries no admin bridge (bag.rpc_admin)")
    t0 = time.time()
    wrong: List[str] = []
    gone = 0
    for method, path in ROUTES:
        st, body = await _read(bag, parse, method, path)
        if st == 410 and body.get("title") == "Gone" and body.get("detail") == SENTENCE:
            gone += 1
            continue
        said = str(body.get("detail") if body.get("detail") is not None else body)[:120]
        wrong.append(f"{method} {path}: HTTP {st or 'none'}, title {body.get('title')!r}, detail {said!r}")
    fail = None if not wrong else ("not retired as (p) says (410, title Gone, the retirement sentence): "
                                   + "; ".join(wrong))
    row = lc()._make_outcome(ROW, TIER, not wrong, "410" if not wrong else "0", int((time.time() - t0) * 1000), fail,
                             {"routes": len(ROUTES), "answered_410_with_the_sentence": gone},
                             expect_status="error_4xx")
    outcomes[ROW] = row


LIFECYCLES: List[Dict[str, Any]] = [
    {"name": "earn_bridge_retired", "runner": lifecycle_bridge_retired},
]
