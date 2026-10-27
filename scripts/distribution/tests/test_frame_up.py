"""frame-up's pure pieces (§HELLOFRAME Phase 2b): the runner installer's last line is the only carrier of the socket gid."""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("frame_up", os.path.join(HERE, "..", "frame-up.py"))
fu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fu)


def test_gid_is_read_from_the_last_line_that_names_it():
    out = "installing the service\nwaiting for the socket\nFRAME_RUNNER_SOCKET_GID=1234 SOCKET=/run/theprotocol/operator/frame-runner.sock EDGE=caddy\n"
    assert fu.runner_gid_from_output(out) == "1234"


def test_no_gid_line_is_none_not_a_guess():
    assert fu.runner_gid_from_output("done\n") is None
    assert fu.runner_gid_from_output("") is None
    assert fu.runner_gid_from_output("FRAME_RUNNER_SOCKET_GID=deploy SOCKET=x\n") is None


def test_a_later_line_wins_over_an_earlier_one():
    out = "FRAME_RUNNER_SOCKET_GID=1 SOCKET=a\nretrying\nFRAME_RUNNER_SOCKET_GID=2 SOCKET=b EDGE=caddy\n"
    assert fu.runner_gid_from_output(out) == "2"


def test_interrupted_stack_is_the_newest_failed_one(tmp_path):
    import json as _json
    root = tmp_path
    for ts, events in (("100", [("compose", "end", "ok"), ("spire", "fail", "refused")]),
                       ("200", [("compose", "end", "ok"), ("jurisdiction", "fail", "refused")])):
        d = root / f"hello-{ts}"; d.mkdir()
        (d / "hetzner-demo-run.json").write_text("{}")
        (d / "standup-progress.jsonl").write_text("\n".join(_json.dumps({"step": s, "event": e, "verdict": v}) for s, e, v in events) + "\n")
    assert fu.interrupted_stack(str(root), "hello") == (str(root / "hello-200"), "jurisdiction")
    assert fu.interrupted_stack(str(root), "other") is None


def test_a_finished_or_recorded_stack_is_not_interrupted(tmp_path):
    import json as _json
    d = tmp_path / "hello-300"; d.mkdir(); (d / "hetzner-demo-run.json").write_text("{}")
    (d / "standup-progress.jsonl").write_text(_json.dumps({"step": "mtls", "event": "end", "verdict": "ok"}) + "\n")
    assert fu.interrupted_stack(str(tmp_path), "hello") is None
    (d / "standup-progress.jsonl").write_text(_json.dumps({"step": "mtls", "event": "fail", "verdict": "refused"}) + "\n")
    (d / "frame-up.json").write_text("{}")   # frame-up finished this one earlier; a later failed line is not a resume
    assert fu.interrupted_stack(str(tmp_path), "hello") is None


def test_doctor_held_ports_parse_docker_ps_and_count_the_edge():
    spec = importlib.util.spec_from_file_location("frame_doctor", os.path.join(HERE, "..", "frame-doctor.py"))
    fd = importlib.util.module_from_spec(spec); spec.loader.exec_module(fd)
    text = ("hello-nginx-federation\t0.0.0.0:28443->8443/tcp, [::]:28443->8443/tcp\n"
            "hello-edge\t\n"
            "other-registry\t0.0.0.0:8000->8000/tcp\n"
            "hello-registry\t127.0.0.1:8600->8000/tcp\n")
    assert fd.held_ports_from_docker_ps(text, "hello", (28446, 28447)) == {28443, 28446, 28447, 8600}
    assert fd.held_ports_from_docker_ps(text, "other") == {8000}
    assert fd.held_ports_from_docker_ps("", "hello", (1, 2)) == set()


def test_installer_facts_and_adopt_argv():
    line = "FRAME_RUNNER_SOCKET_GID=1234 SOCKET=/run/theprotocol/hello/frame-runner.sock OPERATOR_SOCKET_DIR=/run/theprotocol/hello/operator EDGE=caddy\n"
    assert fu.runner_fact_from_output(line, "SOCKET") == "/run/theprotocol/hello/frame-runner.sock"
    assert fu.runner_fact_from_output(line, "OPERATOR_SOCKET_DIR") == "/run/theprotocol/hello/operator"
    assert fu.runner_fact_from_output(line, "NOPE") is None
    argv = fu.adopt_argv("/x", "hello", "/opt/theprotocol/stack/hello-1", "/run/s.sock")
    assert argv[1:] == ["-u", "/x/tools/frame-runner/frame_runner.py", "adopt", "--name", "hello", "--stack-dir", "/opt/theprotocol/stack/hello-1", "--socket", "/run/s.sock"]
    assert "--socket" not in fu.adopt_argv("/x", "hello", "/s")


def test_doctor_held_ports_follow_the_project_label_not_the_prefix():
    """§TESTBED P0 a: with the label column, `hello` does not count the ports of a frame named `hello-b`."""
    spec = importlib.util.spec_from_file_location("frame_doctor", os.path.join(HERE, "..", "frame-doctor.py"))
    fd = importlib.util.module_from_spec(spec); spec.loader.exec_module(fd)
    text = ("hello-registry\t127.0.0.1:8600->8000/tcp\thello-1789\n"
            "hello-b-registry\t127.0.0.1:8700->8000/tcp\thello-b-1790\n"
            "hello-edge\t\thello-edge\n")
    assert fd.held_ports_from_docker_ps(text, "hello", (443, 80)) == {8600, 443, 80}
    assert fd.held_ports_from_docker_ps(text, "hello-b") == {8700}


def test_frame_up_finds_its_stack_exactly(tmp_path):
    """The stack frame-up reports is <name>-<ts> with a run record, never a longer-named frame's."""
    for d in ("hello-1789", "hello-b-1790"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "hetzner-demo-run.json").write_text("{}")
    assert fu.frame_names.stack_dirs(str(tmp_path), "hello", need_file="hetzner-demo-run.json") == ["hello-1789"]


def test_edge_admin_port_skips_listeners_and_recorded_ports(tmp_path):
    """§TESTBED P0 g: each kit edge gets its own Caddy admin port; a stopped frame's recorded port stays its own."""
    import json as _json
    (tmp_path / "other-1").mkdir()
    (tmp_path / "other-1" / "frame-up.json").write_text(_json.dumps({"edge": {"admin_port": 2020}}))
    assert fu.edge_admin_port(str(tmp_path), listeners={2019}) == 2021
    assert fu.edge_admin_port(str(tmp_path / "none"), listeners=set()) == 2019
    import pytest
    with pytest.raises(RuntimeError):
        fu.edge_admin_port(str(tmp_path), start=2019, stop=2021, listeners={2019})


def test_the_edge_template_names_its_admin_port_and_the_sandboxes_import():
    text = open(os.path.join(HERE, "..", "frame-edge.Caddyfile.tmpl")).read()
    assert "admin 127.0.0.1:{{ADMIN_PORT}}" in text and "import sandboxes/*.caddy" in text
