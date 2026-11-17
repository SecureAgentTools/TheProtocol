"""V0664 (session-tester, session-lead seq 4292): the tester's two new account writes run only where the target ITSELF
states "sandbox".

The tester ships in every registry image, production's included. 080e3579d added two writes: the federation suite's
second developer (federation_suite/own_developer.register: a registration through the frame admin) and the MCP
tester's Guild counterparty (phase-3 14c: a minted developer, a funded and bonded agent). Beside the guards a run meets
first (require_api_test_execution: API_TEST_EXECUTION_ENABLED and the frame's FRAME_POSTURE; the MCP tester's
sandbox-only target), each write now asks the target's own registry-config: `environment` exactly "sandbox"
(earned_agent_public.sandbox_stated, the rule the earned Guild lifecycle already keeps). Anything else (production,
no field, a config not read) writes nothing and says why. Red on 080e3579d.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple

import pytest

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
from agentvault_registry.api_tests.federation_suite import own_developer as O
from agentvault_registry.api_tests.federation_suite import rig as R


class _Client:
    def __init__(self, label, rig):
        self.label, self.rig = label, rig

    async def call(self, tool, args, timeout=60):
        self.rig.calls.append((self.label, tool, dict(args or {})))
        if tool == "adminRequest" and args.get("endpoint") == "/api/v1/public/registry-config":
            return {"status_code": self.rig.cfg_code, "response": self.rig.cfg}
        if tool == "adminRequest":
            return {"status_code": 201, "response": {"message": "registered"}}
        return {"id": 1}


class _Rig(R.FederationTestRig):
    def __init__(self, cfg, code=200):
        super().__init__()
        self.calls: List[Tuple[str, str, Dict[str, Any]]] = []
        self.cfg, self.cfg_code = cfg, code

    def mcp(self, label):
        return _Client(label, self)


def _registers(rig):
    return [a for _l, t, a in rig.calls if t == "adminRequest" and a.get("endpoint") == "/api/v1/auth/register"]


@pytest.mark.parametrize("cfg,code", [({"environment": "production"}, 200), ({}, 200), ({"environment": "Sandbox"}, 200),
                                      (None, 503)])
def test_the_second_developer_is_never_registered_where_the_target_is_no_sandbox(cfg, code):
    rig = _Rig(cfg, code)
    with pytest.raises(R.PreconditionUnmet) as e:
        asyncio.run(O.register(rig, "sandbox-A", "sandbox-A-admin", "t", []))
    assert "sandbox" in str(e.value) and _registers(rig) == []


def test_a_stated_sandbox_registers_the_second_developer():
    rig = _Rig({"environment": "sandbox"})
    owners = []
    label = asyncio.run(O.register(rig, "sandbox-A", "sandbox-A-admin", "t", owners))
    assert label.startswith("sandbox-A~") and len(_registers(rig)) == 1 and len(owners) == 1


@pytest.mark.parametrize("code,text,ok", [("200", '{"environment": "sandbox"}', True),
                                         ("200", '{"environment": "production"}', False),
                                         ("200", '{}', False), ("503", "down", False)])
def test_the_guild_counterparty_is_minted_only_on_a_stated_sandbox(monkeypatch, code, text, ok):
    async def http(container, method, path, *a, **k):
        assert path == "/api/v1/public/registry-config"
        return code, text
    monkeypatch.setattr(F, "_http_in_target", http)
    allowed, why = asyncio.run(F._guild_worker_allowed("c"))
    assert allowed is ok and (ok or "sandbox" in why)
