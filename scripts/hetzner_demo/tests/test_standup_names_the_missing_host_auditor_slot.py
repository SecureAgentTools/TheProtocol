"""§MTLSHOPS T3 and (a) (2026-09-15, agentvault2-b5, agentvault2-85's input): the standup's summary names what the host
auditor watches of a frame whose databases take TLS clients with a frame certificate only.

It reads the frame's rendered compose and the host auditor's own frame list, as sidecars.host_auditor_frame answers it
((reachable, entry)): a public-only slot reads "public supply audit only", no slot reads "no slot for this frame yet", and an
auditor that did not answer reads "not asked", never "no slot". A frame whose databases take other clients, or an unwired
host, prints nothing. Red on master's driver: its helper takes no frame list, and its summary asks none.
"""
import ast
import importlib.util
import pathlib

import pytest

HERE = pathlib.Path(__file__).resolve().parents[1]
T3_COMPOSE = "services:\n  f-db:\n    command: postgres -c ssl=on -c hba_file=/opt/data-tls/pg_hba.conf\n"
T2_COMPOSE = "services:\n  f-db:\n    command: postgres\n"


@pytest.fixture(scope="module")
def drv():
    spec = importlib.util.spec_from_file_location("standup_driver_host_auditor_summary", HERE / "standup_driver.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stack(tmp_path, compose):
    (tmp_path / "docker-compose.frame-test.yml").write_text(compose)
    return str(tmp_path)


def test_a_t3_frame_with_a_public_only_slot_says_the_host_reads_its_public_audit_only(drv, tmp_path):
    line = drv.host_auditor_summary(True, _stack(tmp_path, T3_COMPOSE), (True, {"id": "f", "public_only": True}))
    assert line.startswith("  Host auditor:  this frame's public supply audit only")
    assert "holds its attestation" in line


def test_a_t3_frame_with_no_slot_names_the_missing_slot(drv, tmp_path):
    line = drv.host_auditor_summary(True, _stack(tmp_path, T3_COMPOSE), (True, None))
    assert line.startswith("  Host auditor:  no slot for this frame yet")
    assert "the frame's own auditor does the exact check" in line


def test_an_auditor_that_did_not_answer_reads_not_asked_never_no_slot(drv, tmp_path):
    for slot in ((False, None), None):
        line = drv.host_auditor_summary(True, _stack(tmp_path, T3_COMPOSE), slot)
        assert line.startswith("  Host auditor:  not asked") and "no slot" not in line


def test_a_frame_whose_databases_take_other_clients_prints_nothing(drv, tmp_path):
    assert drv.host_auditor_summary(True, _stack(tmp_path, T2_COMPOSE), (True, None)) == ""


def test_an_unwired_host_or_no_compose_prints_nothing(drv, tmp_path):
    assert drv.host_auditor_summary(False, _stack(tmp_path, T3_COMPOSE), (True, None)) == ""
    assert drv.host_auditor_summary(True, "", (True, None)) == ""
    assert drv.host_auditor_summary(True, str(tmp_path / "missing"), (True, None)) == ""


def test_the_live_summary_asks_the_host_auditor_after_the_ledger_line():
    src = (HERE / "standup_driver.py").read_text()
    live = [f for f in ast.walk(ast.parse(src))
            if isinstance(f, ast.FunctionDef) and 'IS LIVE")' in (ast.get_source_segment(src, f) or "")]
    assert len(live) == 1, [f.name for f in live]
    seg = ast.get_source_segment(src, live[0])
    # §NIGHTPROV: asked when the frame is wired into the host auditor (--wire-prod, or --wire-only naming auditor)
    ask = '_ha_slot = sidecars.host_auditor_frame(sidecars.load(), args.name) if wires(args, "auditor") else None'
    call = '_host_auditor = host_auditor_summary(wires(args, "auditor"), ctx.stack_dir_host, _ha_slot)'
    assert ask in seg and call in seg and "print(_host_auditor)" in seg
    assert seg.index('IS LIVE")') < seg.index("  Ledger audit:  ") < seg.index(ask) < seg.index(call) < seg.index("print(_host_auditor)")
