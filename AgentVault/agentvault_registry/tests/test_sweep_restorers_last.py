"""§SWEEPORDER (2026-09-24): the MCP tester's sweeps run their tools concurrently, so a toggle pair raced. The nightly
called adminCanaryFleetPause and adminCanaryFleetResume in the same second and whichever landed second won: sbx-alpha's
canary fleet was left paused on 3 of 5 nights. A tool named with a restore verb now runs only after every other item of
the same sweep has finished. Fails on V0445 (the helper and the ordering do not exist there)."""
import asyncio

import pytest

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as flow


@pytest.mark.parametrize("name", [
    "theprotocol_adminCanaryFleetResume", "theprotocol_resumeAgentPayouts", "theprotocol_reinstateAgentEnforcement",
    "theprotocol_liftQuarantine", "theprotocol_unblockFederationAgent", "theprotocol_unhideBundle",
    "theprotocol_reactivatePeerRegistry", "theprotocol_restoreBundle", "theprotocol_enableToolset",
])
def test_restore_verbs_are_restorers(name):
    assert flow._is_restorer_item({"name": name}) is True


@pytest.mark.parametrize("item", [
    {"name": "theprotocol_adminCanaryFleetPause"}, {"name": "theprotocol_disableToolset"},
    {"name": "theprotocol_suspendAgent"}, {"name": "theprotocol_adminCanaryFleetStatus"},
    {"no": "name"}, ("a", "tuple"), None,
])
def test_everything_else_is_not(item):
    assert flow._is_restorer_item(item) is False


@pytest.mark.asyncio
async def test_a_restorer_starts_only_after_every_other_item_has_finished():
    events = []

    async def worker(item):
        name = item["name"]
        events.append(("start", name))
        # the restorer is FIRST in the input and the quickest, so a plain concurrent sweep would start it first and
        # finish it before the slow pause
        await asyncio.sleep(0.05 if name.endswith("Pause") else 0.001)
        events.append(("end", name))
        return name

    items = [{"name": "theprotocol_adminCanaryFleetResume"}, {"name": "theprotocol_adminCanaryFleetPause"},
             {"name": "theprotocol_adminCanaryFleetStatus"}]
    out = await flow._bounded_sweep(items, worker, concurrency=8)
    assert out == [i["name"] for i in items]  # results still come back in input order
    resume_start = events.index(("start", "theprotocol_adminCanaryFleetResume"))
    for other in ("theprotocol_adminCanaryFleetPause", "theprotocol_adminCanaryFleetStatus"):
        assert events.index(("end", other)) < resume_start


@pytest.mark.asyncio
async def test_a_sweep_of_non_tools_is_unchanged():
    out = await flow._bounded_sweep([3, 1, 2], lambda x: asyncio.sleep(0, result=x * 10), concurrency=2)
    assert out == [30, 10, 20]
