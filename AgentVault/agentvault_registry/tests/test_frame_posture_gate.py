"""§TESTBED P1 (2026-09-19): a frame that DECLARES production never executes the test suite, whatever the execution flag
says; a sandbox may; a frame that declares nothing keeps the older gate alone (the network's own sandbox pair)."""
import asyncio
import types

import pytest
from fastapi import HTTPException

from agentvault_registry.core import frame_posture as fp
from agentvault_registry.routers import admin_api_test as aat


def test_declared_posture_reads_one_variable():
    assert fp.declared_posture({"FRAME_POSTURE": "Sandbox "}) == "sandbox"
    assert fp.declared_posture({"FRAME_POSTURE": "production"}) == "production"
    assert fp.declared_posture({"FRAME_POSTURE": "staging"}) == "unknown"
    assert fp.declared_posture({}) == ""


def test_the_refusal_follows_the_declaration():
    assert "never runs on a production frame" in fp.test_execution_refusal({"FRAME_POSTURE": "production"})
    assert fp.test_execution_refusal({"FRAME_POSTURE": "staging"})
    assert fp.test_execution_refusal({"FRAME_POSTURE": "sandbox"}) is None
    assert fp.test_execution_refusal({}) is None


def test_a_console_that_targets_itself():
    assert fp.targets_itself("http://registry-test:8000") and fp.targets_itself("http://localhost:8000")
    assert not fp.targets_itself("http://sbx-alpha-registry:8000")


def _req():
    return types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="10.0.0.9"), method="POST",
                                 url=types.SimpleNamespace(path="/api/v1/admin/api-test/test-flow"))


@pytest.mark.parametrize("posture,allowed", [("production", False), ("sandbox", True), ("", True), ("staging", False)])
def test_the_target_gate_is_the_second_lock(monkeypatch, posture, allowed):
    monkeypatch.setenv("API_TEST_EXECUTION_ENABLED", "true")
    if posture:
        monkeypatch.setenv("FRAME_POSTURE", posture)
    else:
        monkeypatch.delenv("FRAME_POSTURE", raising=False)
    if allowed:
        asyncio.run(aat.require_api_test_execution(_req()))
    else:
        with pytest.raises(HTTPException) as e:
            asyncio.run(aat.require_api_test_execution(_req()))
        assert e.value.status_code == 503 and "FRAME_POSTURE" in e.value.detail


def test_the_execution_flag_still_refuses_first(monkeypatch):
    monkeypatch.setenv("API_TEST_EXECUTION_ENABLED", "false")
    monkeypatch.setenv("FRAME_POSTURE", "sandbox")
    with pytest.raises(HTTPException) as e:
        asyncio.run(aat.require_api_test_execution(_req()))
    assert "API_TEST_EXECUTION_ENABLED=false" in e.value.detail
