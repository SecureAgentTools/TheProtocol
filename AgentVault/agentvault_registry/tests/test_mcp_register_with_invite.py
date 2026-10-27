"""§MCPTEST30 (V0639): the sweep's own registration takes an invite where the target registers only with one.

lifecycle_auth_register_and_logout registered its throwaway developer with no invite, so on a cloud operator
(beta_invite_required) authRegister answered 403 "Beta access requires an invite code" and the row was red (the
operator sweeps' wide list, 2026-10-24 13:39-13:46Z, both operators). Pinned: with bag.registration_invite the run asks
its admin for one and registers with it; without one to be had the row is NOT MEASURED with the reason and nothing is
registered; a target that needs no invite is asked exactly as before.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from agentvault_registry.api_tests.contracts import mcp_lifecycles as M


def _run(invite=None):
    seen = []

    async def rpc(tool, args, jwt="", timeout=20):
        seen.append((tool, dict(args)))
        return True, {"result": {"message": "registered", "recovery_keys": []}}, "200"

    def parse(body):
        r = body.get("result") if isinstance(body, dict) else None
        return r if isinstance(r, dict) else {}

    bag = SimpleNamespace(developer_jwt="dev-jwt", dev_login=None)
    if invite is not None:
        async def _invite():
            return invite
        bag.registration_invite = _invite
    outcomes = {}
    asyncio.run(M.lifecycle_auth_register_and_logout(rpc, parse, bag, outcomes))
    regs = [a for t, a in seen if t == "theprotocol_authRegister"]
    return regs, outcomes


def test_an_operator_registration_carries_the_invite_the_run_asked_for():
    regs, outcomes = _run(("INV-7", ""))
    assert len(regs) == 1 and regs[0]["invite_code"] == "INV-7"
    assert outcomes["theprotocol_authRegister"]["healthy"] is True


def test_no_invite_to_be_had_is_not_measured_and_registers_nothing():
    regs, outcomes = _run(("", "generateInviteCodes answered HTTP 403"))
    assert regs == []
    row = outcomes["theprotocol_authRegister"]
    assert row["healthy"] is False and row["skip_reason"].startswith("NOT MEASURED")
    assert "generateInviteCodes answered HTTP 403" in row["skip_reason"]


def test_a_target_that_needs_no_invite_is_asked_as_before():
    regs, outcomes = _run(None)
    assert len(regs) == 1 and "invite_code" not in regs[0]
    assert set(regs[0]) == {"name", "email", "password"}
