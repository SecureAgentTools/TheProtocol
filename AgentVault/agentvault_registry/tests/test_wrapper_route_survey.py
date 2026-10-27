"""§MCPTEST30 (V0547) — the sweep's wrapper↔route check is the request survey, run sealed on the target.

Phase F.3's static check fetched /openapi.json (308 since §pass52) and never ran; round 14's strict run said so in its
own summary (wrapper_drift_measured=False) while the tile read 0. The sweep now runs tests/mcp_request_survey.py in a
child process with none of the node's environment, every connect refused and no process started, and reads it by the
build gate's own rule (api_tests/contracts/wrapper_route_survey.py).
"""
from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from agentvault_registry.api_tests.contracts import wrapper_route_survey as W
from agentvault_registry.routers import mcp_tester as mt

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src" / "agentvault_registry"
FLOW = SRC / "api_tests" / "categories" / "flow_mcp_lifecycle" / "test_flow_mcp_lifecycle.py"

PROBE = textwrap.dedent('''
    import asyncio, json, os, socket, subprocess, sys
    out = {}
    def note(name, fn):
        try:
            fn()
            out[name] = "ran"
        except Exception as e:
            out[name] = f"{type(e).__name__}: {e}"
    note("tcp", lambda: socket.create_connection(("127.0.0.1", 9), timeout=2))
    note("sock", lambda: socket.socket().connect(("127.0.0.1", 9)))
    note("unix", lambda: socket.socket(socket.AF_UNIX).connect("/nonexistent-phase6.sock"))
    note("asyncio", lambda: asyncio.run(asyncio.open_connection("127.0.0.1", 9)))
    note("process", lambda: subprocess.run(["true"], check=True))
    async def _spawn():
        p = await asyncio.create_subprocess_exec("true")
        await p.wait()
    note("asyncio_process", lambda: asyncio.run(_spawn()))
    note("system", lambda: (_ for _ in ()).throw(OSError("rc")) if os.system("true") else None)
    json.dump(out, open(sys.argv[1], "w"))
''')


def _probe(tmp_path, sealed: bool) -> dict:
    script, out = tmp_path / "probe.py", tmp_path / "probe.json"
    script.write_text(PROBE)
    argv = [sys.executable, "-c", W.SEAL, str(script), str(out)] if sealed else [sys.executable, str(script), str(out)]
    r = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(out.read_text())


def test_the_seal_refuses_every_connection_and_every_process(tmp_path):
    got = _probe(tmp_path, sealed=True)
    assert set(got) == {"tcp", "sock", "unix", "asyncio", "process", "asyncio_process", "system"}
    assert all("sealed:" in v for v in got.values()), got


def test_the_control_without_the_seal_connects_and_starts_processes(tmp_path):
    """The seal's words come from the seal: unsealed, a refused port is the kernel's refusal and a process runs."""
    got = _probe(tmp_path, sealed=False)
    assert not [v for v in got.values() if "sealed:" in v], got
    assert got["process"] == "ran" and got["asyncio_process"] == "ran" and got["system"] == "ran", got
    assert got["tcp"].startswith(("ConnectionRefusedError", "OSError")), got


def _gate_module():
    spec = importlib.util.spec_from_file_location("_gate", HERE / W.GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_rule_is_the_gates_own():
    gated, known = W.read_rule(HERE / W.GATE)
    gate = _gate_module()
    assert gated == tuple(gate.GATED) and known == dict(gate.KNOWN)


def test_a_gate_file_without_the_rule_is_refused(tmp_path):
    f = tmp_path / W.GATE
    f.write_text("GATED = ('NO_ROUTE',)\n")
    with pytest.raises(ValueError):
        W.read_rule(f)


GOOD_CONTROLS = {"no_route": [["NO_ROUTE", "GET /phase6"]], "good": [["ADMIN_ROUTE", "an admin route"]]}


def _survey(admin_classes=None, public_classes=None, controls=None):
    return {"controls": GOOD_CONTROLS if controls is None else controls, "surfaces": {
        "admin": {"tools": 2, "requests": 2, "classes": admin_classes or {}, "surveyed": ["theprotocol_a", "theprotocol_adminRequest"]},
        "public": {"tools": 2, "requests": 2, "classes": public_classes or {}, "surveyed": ["theprotocol_b", "theprotocol_c"]},
    }}


GATED = ("NO_ROUTE", "MISSING_ALWAYS", "TIER")
KNOWN = {"theprotocol_adminRequest": "a generic proxy"}


def test_a_gated_class_is_drift_a_reported_class_is_not_and_a_named_exception_is_listed_apart():
    v = W.verdict(_survey(admin_classes={"MISSING_ALWAYS": {"theprotocol_adminRequest": ["body -> x"]},
                                         "TYPE": {"theprotocol_a": ["query -> limit"]}},
                          public_classes={"NO_ROUTE": {"theprotocol_b": ["GET /api/v1/nope"]},
                                          "TIER": {"theprotocol_b": ["agent token at a developer route"]}}),
                  GATED, KNOWN)
    assert v["measured"] is True and v["drift"] == 1
    assert v["details"] == [{"tool": "theprotocol_b", "surface": "public", "classes": ["NO_ROUTE", "TIER"],
                             "detail": "NO_ROUTE: GET /api/v1/nope"}]
    assert v["known"] == [{"tool": "theprotocol_adminRequest", "reason": "a generic proxy"}]
    assert v["tools"] == 4 and v["requests"] == 4 and len(v["surveyed"]) == 4


def test_a_clean_survey_is_a_measured_zero():
    v = W.verdict(_survey(), GATED, KNOWN)
    assert (v["measured"], v["drift"], v["details"], v["known"]) == (True, 0, [], [])


@pytest.mark.parametrize("controls", [{}, {"no_route": [], "good": []},
                                      {"no_route": [["NO_ROUTE", "x"]], "good": [["MISSING", "body -> tier"]]}])
def test_a_survey_whose_controls_did_not_come_out_as_built_measures_nothing(controls):
    v = W.verdict(_survey(controls=controls), GATED, KNOWN)
    assert v == {"measured": False, "reason": "the survey's own controls did not come out as built"}


def test_a_surface_with_no_tool_or_no_request_measures_nothing():
    s = _survey()
    s["surfaces"]["public"]["requests"] = 0
    assert W.verdict(s, GATED, KNOWN)["measured"] is False
    assert W.verdict({"controls": GOOD_CONTROLS, "surfaces": {}}, GATED, KNOWN)["measured"] is False


def _fake_root(tmp_path, body: str) -> Path:
    root = tmp_path / "tests"
    root.mkdir()
    (root / W.GATE).write_text(f"GATED = {GATED!r}\nKNOWN = {KNOWN!r}\n")
    (root / W.SURVEY).write_text(textwrap.dedent(body))
    return root


def test_the_child_runs_sealed_with_none_of_the_nodes_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("PHASE6_NODE_SECRET", "must-not-reach-the-child")
    root = _fake_root(tmp_path, '''
        import json, os, socket, sys
        try:
            socket.create_connection(("127.0.0.1", 9), timeout=2)
            seen = "connected"
        except Exception as e:
            seen = str(e)
        out = {"controls": {"no_route": [["NO_ROUTE", "x"]], "good": []}, "surfaces": {
            "admin": {"tools": 1, "requests": 1, "classes": {}, "surveyed": sorted(os.environ)},
            "public": {"tools": 1, "requests": 1, "classes": {}, "surveyed": ["connect: " + seen]}}}
        json.dump(out, open(sys.argv[sys.argv.index("--json") + 1], "w"))
    ''')
    v = asyncio.run(W.run_survey(root=root, timeout=60))
    assert v["measured"] is True, v
    env = [x for x in v["surveyed"] if not x.startswith("connect: ")]
    assert set(env) == set(W.sealed_env(Path("/x"), "/h")), env
    assert "connect: sealed: the request survey makes no connection" in v["surveyed"], v["surveyed"]


def test_an_image_without_the_survey_says_so(tmp_path):
    v = asyncio.run(W.run_survey(root=tmp_path, timeout=10))
    assert v["measured"] is False and v["reason"].startswith("this image carries no request survey"), v


def test_a_survey_that_fails_or_hangs_is_not_measured_and_says_which(tmp_path):
    v = asyncio.run(W.run_survey(root=_fake_root(tmp_path, "import sys\nsys.exit(3)\n"), timeout=60))
    assert v["measured"] is False and v["reason"].startswith("the survey exited 3"), v
    hang = tmp_path / "hang"
    hang.mkdir()
    v = asyncio.run(W.run_survey(root=_fake_root(hang, "import time\ntime.sleep(60)\n"), timeout=2))
    assert v == {"measured": False, "reason": "the survey did not finish in 2 s"}


def test_flow_values_never_turn_an_unmeasured_run_into_a_zero():
    fv = W.flow_values({"measured": False, "reason": "the survey did not finish in 300 s"})
    assert fv["wrapper_drift_measured"] is False and fv["wrapper_drift_reason"] == "the survey did not finish in 300 s"
    assert fv["wrapper_drift_details"] == [] and fv["wrapper_drift_surveyed_tools"] == []
    assert mt._detectors_measured(fv)["wrapper_route"] is False
    good = W.flow_values(W.verdict(_survey(), GATED, KNOWN))
    assert good["wrapper_drift_measured"] is True and good["wrapper_drift_reason"] is None
    assert mt._detectors_measured(good)["wrapper_route"] is True


def _axis(tool, fv, wrapper=()):
    return mt._detector_axes(tool, fv, mt._detectors_measured(fv), set(), set(), set(wrapper))["wrapper_route_drift"]


def test_a_row_is_graded_by_the_survey_where_the_survey_called_it():
    v = W.verdict(_survey(admin_classes={"MISSING_ALWAYS": {"theprotocol_adminRequest": ["body -> x"]}},
                          public_classes={"NO_ROUTE": {"theprotocol_b": ["GET /api/v1/nope"]}}), GATED, KNOWN)
    fv = W.flow_values(v)
    assert _axis("theprotocol_c", fv) == {"state": "pass",
                                          "detail": "its request passes its route's own validation (the request survey)"}
    fail = _axis("theprotocol_b", fv, wrapper=["theprotocol_b"])
    assert fail["state"] == "fail" and "NO_ROUTE: GET /api/v1/nope" in fail["detail"]
    named = _axis("theprotocol_adminRequest", fv)
    assert named["state"] == "na" and named["detail"].startswith("a named exception of the build gate: a generic proxy")
    assert _axis("theprotocol_never_surveyed", fv) == {"state": "na",
                                                       "detail": "not among the tools the request survey called"}


def test_a_tool_at_a_peer_only_route_is_listed_apart_never_counted_and_its_row_is_not_graded():
    v = W.verdict(_survey(public_classes={"PEER_ROUTE": {"theprotocol_c": [
        "GET /api/v1/federation/agent-cards authenticates only a federation peer (x: get_federation_identity)"]}}),
        GATED, KNOWN)
    assert v["measured"] is True and v["drift"] == 0 and v["details"] == []
    assert v["peer_route"] == [{"tool": "theprotocol_c", "surface": "public", "class": "PEER_ROUTE", "detail":
                                "GET /api/v1/federation/agent-cards authenticates only a federation peer "
                                "(x: get_federation_identity)"}]
    fv = W.flow_values(v)
    assert fv["wrapper_peer_route"] == v["peer_route"]
    row = _axis("theprotocol_c", fv)
    assert row["state"] == "na" and "only a federation peer" in row["detail"]


def test_the_strict_sweep_runs_the_survey_once_and_carries_its_values():
    tree = ast.parse(FLOW.read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "run_survey"]
    assert len(calls) == 1
    spreads = [v for n in ast.walk(tree) if isinstance(n, ast.Dict) for k, v in zip(n.keys, n.values)
               if k is None and isinstance(v, ast.Name) and v.id == "wrapper_drift_summary"]
    assert len(spreads) == 1
    assert "wrapper_drift_measured" in W.flow_values({"measured": False})


def test_the_retired_static_check_is_gone():
    """Read on the AST: the new module's docstring names what it replaced, and prose is not an import."""
    assert not (SRC / "api_tests" / "contracts" / "check_wrapper_route_drift.py").exists()
    importers = []
    for p in SRC.rglob("*.py"):
        if "node_modules" in p.parts:
            continue
        for n in ast.walk(ast.parse(p.read_text(errors="replace"))):
            names = [n.module or ""] if isinstance(n, ast.ImportFrom) else \
                [a.name for a in n.names] if isinstance(n, ast.Import) else []
            if isinstance(n, ast.ImportFrom):
                names += [a.name for a in n.names]
            if any("check_wrapper_route_drift" in x for x in names):
                importers.append(str(p))
    assert importers == []


@pytest.mark.skipif(not (HERE / W.SURVEY).is_file(), reason="the survey ships beside this test")
def test_the_real_survey_runs_sealed_and_agrees_with_the_build_gate():
    """End to end on this image's own code: the sealed run measures every tool and reads what the gate reads."""
    v = asyncio.run(W.run_survey(root=HERE, timeout=600))
    assert v["measured"] is True, v
    assert v["drift"] == 0, v["details"]
    _, known = W.read_rule(HERE / W.GATE)
    assert {k["tool"] for k in v["known"]} == set(known), v["known"]
    assert v["tools"] >= 700 and len(v["surveyed"]) == v["tools"], (v["tools"], len(v["surveyed"]))
    gate = _gate_module()
    assert {k["tool"] for k in v["peer_route"]} == set(gate.PEER_ROUTE_BASELINE), v["peer_route"]
