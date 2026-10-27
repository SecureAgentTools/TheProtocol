"""§MCPTEST30 (V0556, agentvault2-45's point): where the arena is dark, GET /forge/status SAYS so (200, enabled false)
instead of refusing, so the /forge page makes no refused call; the arena's other routes stay behind the gate (403).

Before, the status read raised the same 403 as every forge route, the page turned the refusal into "The arena is dark on
this registry", and a console suite that counts refused calls had to list /forge as an expected refusal on every
forge-dark frame (sbx-beta, production). Awaited, never asyncio.run.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from agentvault_registry import forge_flags
from agentvault_registry.routers import forge


class _NoDb:
    """A database the dark answer must never touch."""

    async def execute(self, *a, **k):
        raise AssertionError("the dark status read touched the database")


class _FailingDb:
    """The enabled path's counts and lineages are best-effort: a failing read leaves them empty, never a 500."""

    async def execute(self, *a, **k):
        raise RuntimeError("no database in this test")


async def test_a_dark_arena_answers_enabled_false_without_a_database_read(monkeypatch):
    monkeypatch.setattr(forge_flags, "forge_enabled", lambda: False)
    out = await forge.forge_status(db=_NoDb())
    assert out["enabled"] is False
    assert out["detail"] == forge.DARK_SENTENCE and "FORGE_ENABLED" in out["detail"]
    # the keys the MCP tester's contract reads (getForgeStatus: enabled, counts, flags) are all there
    assert {"enabled", "counts", "flags"} <= set(out) and out["lineages"] == []


async def test_the_other_forge_routes_still_refuse_while_dark(monkeypatch):
    monkeypatch.setattr(forge_flags, "forge_enabled", lambda: False)
    with pytest.raises(HTTPException) as e:
        forge._require_forge()
    assert e.value.status_code == 403 and e.value.detail == forge.DARK_SENTENCE


async def test_a_lit_arena_answers_as_before(monkeypatch):
    monkeypatch.setattr(forge_flags, "forge_enabled", lambda: True)
    out = await forge.forge_status(db=_FailingDb())
    assert out["enabled"] is True and "detail" not in out
    assert {"evals_agent_trigger", "royalty", "verifier_quorum_m"} <= set(out["flags"])
    assert out["counts"] == {} and out["lineages"] == [] and "verifier_prerequisites" in out
    forge._require_forge()   # no refusal while the arena is lit
