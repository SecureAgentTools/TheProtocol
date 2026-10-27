"""§MCPTEST30 (V0546) — the achievements tripwire (api_tests/contracts/achievement_claims.py).

Any developer can claim any enabled achievement for any agent DID with no proof it was earned; latent while nothing
pays (the strict run of 2026-10-02 04:02Z read the catalog as {"achievements": [], "total": 0}). The row stays green
while nothing pays and turns red, naming the types, the run a paying achievement appears.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from agentvault_registry.api_tests.contracts import achievement_claims as AC


def _outcome(name, tier, ok, code, ms, fail, inner, expect_status="success", skip_reason=None):
    return {"tool": name, "healthy": ok and not skip_reason, "status": code, "error": fail, "skip_reason": skip_reason}


def _answered(ok, inner, code):
    return bool(ok) and str(code).startswith("2")


def _said(inner):
    return (inner or {}).get("_text", "") if isinstance(inner, dict) else str(inner)


class _Bag:
    developer_jwt = "dev"


def _run(answer, code="200", ok=True):
    calls = []

    async def rpc(tool, args, jwt="", timeout=30):
        calls.append((tool, jwt))
        return ok, answer, code
    out = {}
    asyncio.run(AC.run_achievement_claims(rpc, lambda b: b, _Bag(), out, _outcome, _answered, _said))
    return out[AC.ROW], calls


def test_the_measured_catalog_is_a_pass_that_says_nothing_pays():
    row, calls = _run({"achievements": [], "total": 0})
    assert row["healthy"] is True and row["result_excerpt"] == {"enabled": 0, "paying": 0, "paying_types": []}
    assert calls == [("theprotocol_getAchievementCatalog", "dev")], "one read, with a bearer (the MCP endpoint wants one)"


def test_enabled_achievements_that_pay_nothing_are_a_pass():
    row, _ = _run({"achievements": [{"type": "tutorial_x", "payout_avt": 0}, {"type": "y", "payout_avt": "0.0"}], "total": 2})
    assert row["healthy"] is True and row["result_excerpt"]["enabled"] == 2 and row["result_excerpt"]["paying"] == 0


def test_a_paying_achievement_is_the_finding_and_names_its_type_never_its_amount():
    row, _ = _run({"achievements": [{"type": "tutorial_agent_lifecycle", "payout_avt": 25.0},
                                    {"type": "free", "payout_avt": 0}], "total": 2})
    assert row["healthy"] is False and row["error"].startswith("BUG-FIND: achievements: 1 enabled achievement(s) pay")
    assert "tutorial_agent_lifecycle" in row["error"] and AC.FINDINGS in row["error"]
    assert "25" not in json.dumps(row["result_excerpt"]) and "25" not in row["error"]


@pytest.mark.parametrize("answer", [{"detail": "x"}, {"achievements": None}, [], None, "text"])
def test_an_answer_that_is_not_a_list_is_not_measured(answer):
    row, _ = _run(answer)
    assert row["healthy"] is False and row["error"] is None
    assert row["skip_reason"] == "NOT MEASURED: the achievement catalog did not answer a list"


def test_a_refused_read_is_not_measured_and_says_what_came_back():
    row, _ = _run({"_text": "Error: HTTP 503: down"}, code="503", ok=False)
    assert row["skip_reason"].startswith("NOT MEASURED: the achievement catalog did not answer (Error: HTTP 503")


def test_the_lifecycle_is_registered_and_its_row_is_synthetic():
    from agentvault_registry.api_tests.contracts import mcp_lifecycles as L
    from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
    assert any(e["name"] == "achievement_claims" and e["runner"] is L.lifecycle_achievement_claims for e in L.LIFECYCLES)
    assert AC.PREFIX in F._SYNTHETIC_ROW_PREFIXES and AC.ROW.startswith(AC.PREFIX)


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
