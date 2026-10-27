"""§MCPSWEEP 2026-09-28: an exec whose exit code is not known yet is not a success, and an exec that captured no
HTTP answer says so.

Every federation-suite probe and every lifecycle MCP call reaches the target through
api_tests.multiframe_helpers.exec_in_container (docker-py). docker-py 7.2.0's exec_run reads ExitCode from
exec_inspect right after the output stream ends, which can be None while the process is still being reaped, and the
old `int(rc or 0)` turned that into 0. Since the V0478 roll about one probe per run came back as rc 0 with no output
while the server's audit row shows it answered: the rig printed "HTTP : " and the auth matrix "status=0". These tests
drive the helper through a fake Docker API (and the rig's MCP call through a patched exec) and hold both halves.
"""
from __future__ import annotations

import asyncio

import pytest

from agentvault_registry.api_tests import multiframe_helpers as mh
from agentvault_registry.api_tests.federation_suite import rig as rig_mod


class _Api:
    def __init__(self, inspects, output=b"body\n--HTTP_CODE=200--"):
        self.inspects, self.output, self.created = list(inspects), output, []

    def exec_create(self, cid, args, **kw):
        self.created.append((cid, args, kw))
        return {"Id": "exec-1"}

    def exec_start(self, exec_id, demux=False):
        return self.output

    def exec_inspect(self, exec_id):
        return self.inspects.pop(0) if len(self.inspects) > 1 else self.inspects[0]


class _Container:
    def __init__(self, api):
        self.id, self.client = "cid-1", type("C", (), {"api": api})()
        self._api = api

    def exec_run(self, args, demux=False):     # the OLD path, for the red-first control
        first = self._api.exec_inspect("exec-1")
        return first.get("ExitCode"), self._api.output


@pytest.fixture
def fake(monkeypatch):
    def install(inspects, output=b"body\n--HTTP_CODE=200--"):
        api = _Api(inspects, output)
        monkeypatch.setattr(mh, "_get_container", lambda name: _Container(api))
        monkeypatch.setattr(mh, "_EXEC_EXIT_WAIT_S", 0.3, raising=False)   # raising=False: the red run on the old module
        return api
    return install


RUNNING = {"Running": True, "ExitCode": None}


def test_a_late_exit_code_is_waited_for_and_the_output_kept(fake):
    fake([RUNNING, RUNNING, {"Running": False, "ExitCode": 0}])
    assert mh._exec_once("sbx-alpha-registry", ["true"]) == (0, "body\n--HTTP_CODE=200--")


def test_an_exit_code_that_never_arrives_is_a_named_failure_not_success(fake):
    fake([RUNNING], output=b"")
    rc, out = mh._exec_once("sbx-alpha-registry", ["true"])
    assert rc == -1 and "no exit code" in out


def test_a_nonzero_exit_is_returned_as_is(fake):
    fake([{"Running": False, "ExitCode": 7}], output=b"boom")
    assert mh._exec_once("sbx-alpha-registry", ["false"]) == (7, "boom")


def test_the_exec_is_created_with_both_streams_on_the_containers_id(fake):
    api = fake([{"Running": False, "ExitCode": 0}])
    mh._exec_once("sbx-alpha-registry", ["echo", "x"])
    (cid, args, kw), = api.created
    assert cid == "cid-1" and args == ["echo", "x"] and kw == {"stdout": True, "stderr": True}


def test_control_the_old_rule_read_an_unknown_exit_code_as_success(fake):
    fake([RUNNING], output=b"")
    c = mh._get_container("sbx-alpha-registry")
    rc, out = c.exec_run(["true"], demux=False)
    assert int(rc or 0) == 0 and not out          # what `int(rc or 0)` made of it: a success with no answer


def test_the_rig_names_an_exec_that_captured_no_http_answer(monkeypatch):
    client = rig_mod.MCPClient(rig_mod.SANDBOX_REGISTRIES["sandbox-A-admin"])

    async def _jwt():
        return "test-jwt"
    monkeypatch.setattr(client, "_ensure_jwt", _jwt)
    monkeypatch.setattr(rig_mod, "exec_in_container", lambda name, args, timeout=30: (0, ""))
    with pytest.raises(rig_mod.MCPError) as ei:
        asyncio.run(client.call("getNetworkStats", {}))
    assert ei.value.http_status == "none"
    assert "no HTTP status captured" in str(ei.value)


def test_control_a_real_status_still_reaches_the_old_branches(monkeypatch):
    client = rig_mod.MCPClient(rig_mod.SANDBOX_REGISTRIES["sandbox-A-admin"])

    async def _jwt():
        return "test-jwt"
    monkeypatch.setattr(client, "_ensure_jwt", _jwt)
    monkeypatch.setattr(rig_mod, "exec_in_container",
                        lambda name, args, timeout=30: (0, "oops\n--HTTP_CODE=500--"))
    with pytest.raises(rig_mod.MCPError) as ei:
        asyncio.run(client.call("getNetworkStats", {}))
    assert ei.value.http_status == "500" and "no HTTP status captured" not in str(ei.value)


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    # asyncio.run() leaves the thread with no current loop; put one back for the next file
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
