"""§EXTREACH design A (agentvault2-5b, 2026-10-14): frame-reach.py turns the network's dial-back into one fix per lane.

Offline: the probe's answers are faked; what is measured is the exit code and the sentence a self-hoster reads.
"""
import importlib.util
import pathlib
import types

HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("frame_reach", HERE.parent / "frame-reach.py")
fr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fr)

PORTS = {"console": 443, "federation": 8443, "bundle": 8444, "ledger": 8445}


def _answer(**verdicts):
    rows = [{"role": r, "port": p, "verdict": verdicts.get(r, "ok"), "detail": f"{r} detail"} for r, p in PORTS.items()]
    return {"public_name": "frame.example.org", "address": "203.0.113.5", "addresses": ["203.0.113.5"],
            "caller_address": "203.0.113.5", "name_points_at_caller": True, "results": rows,
            "all_ok": all(r["verdict"] == "ok" for r in rows)}


def _run(status, answer):
    lines = []
    rc, _ = fr.check_and_report("frame.example.org", PORTS, "https://probe.example/x", out=lines.append,
                                send=lambda url, payload: (status, answer))
    return rc, "\n".join(lines)


def test_every_lane_answers():
    rc, text = _run(200, _answer())
    assert rc == 0 and "a peer can federate" in text and "FAIL" not in text


def test_a_lane_the_router_does_not_forward_names_the_port():
    rc, text = _run(200, _answer(bundle="timeout"))
    assert rc == 1
    assert "FAIL SPIRE bundle endpoint" in text and "forward TCP 8444 to this machine" in text
    assert "frame-reach.py --public-name frame.example.org again" in text


def test_every_verdict_has_a_fix():
    for v in ("timeout", "refused", "not_tls", "certificate_invalid", "wrong_name", "not_a_bundle", "unreachable"):
        s = fr.fix_for({"role": "ledger", "port": 8445, "verdict": v, "detail": "x"}, "frame.example.org", "203.0.113.5")
        assert s and len(s) > 30, v


def test_no_a_record_names_the_address_to_use():
    rc, text = _run(200, {"refusal": "no_address", "caller_address": "198.51.100.7", "addresses": []})
    assert rc == 1 and "create one pointing at 198.51.100.7" in text


def test_a_private_address_is_named():
    rc, text = _run(200, {"refusal": "private_address", "caller_address": "198.51.100.7", "addresses": ["192.168.1.20"]})
    assert rc == 1 and "192.168.1.20" in text and "198.51.100.7" in text


def test_a_probe_not_offered_is_not_judged():
    rc, text = _run(503, {"detail": "this registry does not offer the reachability probe (REACH_PROBE_ENABLED)"})
    assert rc == 2 and "could not be judged" in text and "REACH_PROBE_ENABLED" in text
    rc, text = _run(404, {"detail": "Not Found"})
    assert rc == 2 and "arrives with a later release" in text
    rc, text = _run(None, {"error": "ConnectionRefusedError: refused"})
    assert rc == 2 and "ConnectionRefusedError" in text


def test_nat_with_another_egress_is_noted():
    a = _answer()
    a.update(caller_address="198.51.100.7", name_points_at_caller=False)
    rc, text = _run(200, a)
    assert rc == 0 and "called from 198.51.100.7" in text


def test_frame_up_asks_after_its_summary_and_skips_test_frames():
    spec = importlib.util.spec_from_file_location("frame_up", HERE.parent / "frame-up.py")
    fu = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fu)
    src = (HERE.parent / "frame-up.py").read_text()
    assert '"--skip-reach"' in src and "reach_check(a)" in src
    a = types.SimpleNamespace(edge_tls="internal")
    assert fu.reach_check(a) is None, "an internal-TLS test frame has no public name to dial"


def test_custom_ports_from_another_address_say_where_to_run_it():
    rc, text = _run(200, {"refusal": "custom_ports_need_own_address", "caller_address": "198.51.100.7",
                          "addresses": ["203.0.113.5"]})
    assert rc == 2 and "run this on the frame's own host" in text and "198.51.100.7" in text
