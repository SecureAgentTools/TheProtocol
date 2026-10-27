"""§MCPTEST30 (V0559): the MCP tester's admin sweep takes back the broadcast it composes.

Every run's destructive-safe sweep composed one "phase6 sweep" broadcast and left it active, so the newest scrolled
across every console's header on the target for good. The sweep now retracts it, through the tool, with the id the
compose answered, and the cleanup adds no row (retractBroadcast's own row stays the probe of an id that names nothing).
"""
import ast
import pathlib

from agentvault_registry.api_tests.contracts import mcp_admin_lifecycles as m

SRC = pathlib.Path(m.__file__).read_text()


def _fn(name):
    return next(n for n in ast.walk(ast.parse(SRC)) if isinstance(n, ast.AsyncFunctionDef) and n.name == name)


def _calls_to_exec_step(fn):
    return [c for c in ast.walk(fn) if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_exec_step"]


def test_the_sweep_that_composes_a_broadcast_retracts_it_with_the_answered_id():
    fn = _fn("lifecycle_admin_destructive_safe")
    consts = {n.value for n in ast.walk(fn) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "theprotocol_composeBroadcast" in consts
    cleanups = []
    for c in _calls_to_exec_step(fn):
        if len(c.args) > 2 and isinstance(c.args[2], ast.Constant) and c.args[2].value == "theprotocol_retractBroadcast":
            cleanups.append(c)
    assert len(cleanups) == 1, "one retraction of the composed broadcast"
    call = cleanups[0]
    payload = call.args[4]
    assert isinstance(payload, ast.Dict) and isinstance(payload.values[0], ast.Name) and payload.values[0].id == "composed"
    kw = {k.arg: k.value for k in call.keywords}
    assert isinstance(kw.get("record_as_separate"), ast.Constant) and kw["record_as_separate"].value is False


def test_the_composed_id_is_read_from_the_compose_answer():
    fn = _fn("lifecycle_admin_destructive_safe")
    reads = [c for c in ast.walk(fn) if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "composed_id"]
    assert len(reads) == 1


def test_the_probe_row_of_retract_stays_an_id_that_names_nothing():
    assert '("theprotocol_retractBroadcast", {"broadcast_id": 999999})' in SRC
