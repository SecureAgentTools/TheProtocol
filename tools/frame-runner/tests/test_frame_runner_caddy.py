"""§HELLOFRAME lane 6 (2026-09-18): the runner's CADDY edge posture.

A frame stood up by frame-up on a stranger's host has no host nginx: its public door is its own `<name>-edge` Caddy
container reading <stack>/edge/Caddyfile, whose template imports operators/*.caddy. Under policy `"edge": "caddy"` the
runner writes ONE site file per operator into that directory and asks the edge to validate and reload; under the
default ("nginx", or the key absent) every line of the nginx path runs byte for byte as before — the first test here
is the control for that. No docker, no nginx and no /etc are touched: `docker exec` is a fake that records its argv.
"""
import glob
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import threading

import pytest

HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("frame_runner", HERE.parent / "frame_runner.py")
fr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fr)

VALIDATE = ["caddy", "validate", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
RELOAD = ["caddy", "reload", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]


def _conf(**over):
    base = {"images": {"registry": ["agentvault2-registry-a:v0359"], "teg": ["agentvault2-teg-layer:v0351"]},
            "allowed_uids": [os.getuid()], "min_free_gb": 0, "max_load": 10 ** 6, "min_mem_gib": 0}
    base.update(over)
    return base


def _runner(tmp_path, monkeypatch, **conf):
    """A Runner with every path under tmp_path and NO server: the edge methods are called directly, as the job
    flow calls them. The nginx paths are pointed at empty tmp dirs so a caddy run that touched them would show."""
    cfg = fr.Config(conf=_conf(**conf), socket=str(tmp_path / "run" / "fr.sock"),
                    operator_socket=str(tmp_path / "run" / "operator" / "fr.sock"),
                    state=str(tmp_path / "state"), driver=str(tmp_path / "standup_driver.py"),
                    teardown=str(tmp_path / "teardown.sh"), python=sys.executable,
                    stack_root=str(tmp_path / "stack"), protected_list=str(tmp_path / "protected.list"),
                    template=str(tmp_path / "template.yml.tmpl"))
    (tmp_path / "stack").mkdir(exist_ok=True)
    sites = tmp_path / "sites-enabled"
    sites.mkdir(exist_ok=True)
    (tmp_path / "vhost-backups").mkdir(exist_ok=True)
    monkeypatch.setattr(fr.Runner, "NGINX_SITES", str(sites))
    monkeypatch.setattr(fr.Runner, "NGINX_BACKUPS", str(tmp_path / "vhost-backups"))
    monkeypatch.setattr(fr.Runner, "NGINX_SNI_MAP", str(tmp_path / "federation-mtls.conf"))
    return fr.Runner(cfg), sites


def _frame(runner, tmp_path, name="harbor", *, frame_up=True, tls="internal", extra_edge=None, caddyfile=None):
    """A frame record the runner reads (state/frames/<name>.json) and the stack frame-up leaves behind."""
    stack = tmp_path / "stack" / f"{name}-1"
    (stack / "edge").mkdir(parents=True, exist_ok=True)
    frames = pathlib.Path(runner.cfg.state) / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    (frames / f"{name}.json").write_text(json.dumps({"name": name, "stack_dir": str(stack)}))
    if frame_up:
        edge = {"tls": tls, "http_port": 80, "https_port": 443, "container": f"{name}-edge",
                "operators_dir": str(stack / "edge" / "operators")}
        edge.update(extra_edge or {})
        (stack / "frame-up.json").write_text(json.dumps({"name": name, "public_name": f"{name}.example",
                                                         "stack_dir": str(stack), "edge": edge}))
    if caddyfile is not None:
        (stack / "edge" / "Caddyfile").write_text(caddyfile)
    return stack


def _job(runner, job_id="caddyjob00000001", **edge):
    jd = pathlib.Path(runner.job_dir(job_id))
    jd.mkdir(mode=0o700, parents=True, exist_ok=True)
    spec_edge = {"domain": "harborop.harbor.example", "reg_port": 31600, "fed_port": 31643,
                 "bind_address": "172.17.0.1", "mode": "caddy"}
    spec_edge.update(edge)
    (jd / "spec.json").write_text(json.dumps({"edge": spec_edge}))
    return {"id": job_id, "op": "operator_provision", "operator": "harborop", "name": "harbor",
            "state": "succeeded", "result": {}}


def _fake_docker(monkeypatch, *, validate_rc=0, reload_rc=0, stderr="", missing=False):
    """`docker exec <edge> caddy validate|reload ...` recorded; everything else (nothing, in these tests) refused."""
    calls = []

    def fake_run(argv, **kw):
        if argv[:2] == ["docker", "exec"]:
            calls.append(argv)
            verb = argv[3:]
            if missing:
                return subprocess.CompletedProcess(argv, 1, "", "Error response from daemon: No such container: "
                                                                 + argv[2])
            rc = validate_rc if verb == VALIDATE else reload_rc if verb == RELOAD else 99
            return subprocess.CompletedProcess(argv, rc, "", stderr if rc else "")
        raise AssertionError(f"unexpected command under the caddy posture: {argv}")

    monkeypatch.setattr(fr.subprocess, "run", fake_run)
    return calls


# ---- the control: the posture key is inert unless it says caddy ------------------------------------------------

def test_the_policy_edge_defaults_to_nginx_and_refuses_anything_else():
    assert fr.Config(conf=_conf()).edge == "nginx"
    assert fr.Config(conf=_conf(edge="nginx")).edge == "nginx"
    assert fr.Config(conf=_conf(edge="caddy")).edge == "caddy"
    with pytest.raises(SystemExit):
        fr.Config(conf=_conf(edge="traefik"))


def test_under_nginx_the_edge_step_is_the_old_one_untouched(tmp_path, monkeypatch):
    runner, sites = _runner(tmp_path, monkeypatch)                # no edge key at all
    calls = _fake_docker(monkeypatch)
    rec = {"id": "caddyjob00000001", "op": "operator_provision", "operator": "harborop", "name": "harbor",
           "state": "succeeded", "result": {}}
    runner._apply_operator_edge(rec)
    assert rec["notes"] == ["edge: the result carried no host_vhost, so nothing was written"]
    assert not calls and not list(sites.iterdir())


def test_both_pings_carry_the_edge(tmp_path, monkeypatch):
    runner, _ = _runner(tmp_path, monkeypatch, edge="caddy")
    cfg = runner.cfg
    (tmp_path / "run").mkdir(exist_ok=True)
    srv = fr.make_server(cfg, runner)
    opsrv = fr.make_server(cfg, runner, cfg.operator_socket, fr.OPERATOR_OPS)
    for s in (srv, opsrv):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        assert fr.call(cfg.socket, {"op": "ping"}, timeout=30)["result"]["edge"] == "caddy"
        r = fr.call(cfg.operator_socket, {"op": "operator_ping"}, timeout=30)["result"]
        assert r["edge"] == "caddy" and r["socket"] == "operator"
    finally:
        for s in (srv, opsrv):
            s.shutdown()
            s.server_close()


# ---- the pure helpers --------------------------------------------------------------------------------------------

def test_the_tls_line_follows_the_frames_choice():
    assert fr.caddy_tls_line("internal") == "tls internal"
    assert fr.caddy_tls_line("INTERNAL", "someone@example") == "tls internal"
    assert fr.caddy_tls_line("acme", "ops@harbor.example") == "tls ops@harbor.example"
    assert fr.caddy_tls_line("acme", "") == ""                       # the Caddyfile's global email applies
    assert fr.caddy_tls_line("acme", "no-at-sign") == ""
    assert fr.caddy_tls_line("acme", "a@b {\n evil") == ""          # never a second directive smuggled in


def test_the_operator_block_is_one_site_with_the_frames_headers_and_no_ledger_handle():
    text = fr.caddy_operator_block(domain="harborop.harbor.example", bind_address="172.17.0.1", reg_port=31600,
                                   tls_line="tls internal")
    lines = text.splitlines()
    assert lines[0].startswith("# operator harborop.harbor.example: written by the frame runner")
    assert lines[1] == "harborop.harbor.example {"
    assert lines[2] == "\ttls internal"
    assert "\treverse_proxy 172.17.0.1:31600 {" in lines
    assert "\t\theader_up X-Forwarded-Proto https" in lines and "\t\theader_up X-Real-IP {remote_host}" in lines
    assert '\t\tStrict-Transport-Security "max-age=31536000; includeSubDomains"' in lines
    assert "ws/events" not in text, "an operator has no store: no ledger handle"
    assert text.endswith("}\n") and text.count("{") == text.count("}")
    without = fr.caddy_operator_block(domain="a.b.example", bind_address="", reg_port=1)
    assert "\ttls" not in without and "reverse_proxy 127.0.0.1:1 {" in without


@pytest.mark.parametrize("bad", [
    dict(domain="harbor op.example", bind_address="172.17.0.1", reg_port=31600),
    dict(domain="a..b", bind_address="172.17.0.1", reg_port=31600),
    dict(domain="a.b {\n}", bind_address="172.17.0.1", reg_port=31600),
    dict(domain="a.b", bind_address="evil.host", reg_port=31600),
    dict(domain="a.b", bind_address="172.17.0.1", reg_port=0),
    dict(domain="a.b", bind_address="172.17.0.1", reg_port=70000),
    dict(domain="a.b", bind_address="172.17.0.1", reg_port="x"),
])
def test_RED_the_block_refuses_what_could_escape_the_site(bad):
    with pytest.raises(ValueError):
        fr.caddy_operator_block(**bad)


def test_the_site_path_is_the_slug_under_operators_and_nothing_else():
    assert fr.caddy_site_path("/s/edge/operators", "harborop") == "/s/edge/operators/harborop.caddy"
    for bad in ("Harbor", "../x", "a b", "", "x" * 41):
        with pytest.raises(ValueError):
            fr.caddy_site_path("/s/edge/operators", bad)


def test_frame_up_facts_read_the_file_and_fill_what_an_older_frame_up_left_out(tmp_path):
    missing = fr.frame_up_facts(str(tmp_path), "harbor")
    assert missing["ok"] is False and "frame-up.json is missing" in missing["why"]
    (tmp_path / "edge").mkdir()
    (tmp_path / "frame-up.json").write_text(json.dumps({"public_name": "harbor.example", "edge": {"tls": "acme"}}))
    (tmp_path / "edge" / "Caddyfile").write_text("{\n\thttp_port 80\n\thttps_port 443\n\temail ops@harbor.example\n}\n")
    f = fr.frame_up_facts(str(tmp_path), "harbor")
    assert f["ok"] and f["container"] == "harbor-edge" and f["tls"] == "acme"
    assert f["operators_dir"] == str(tmp_path / "edge" / "operators")
    assert f["acme_email"] == "ops@harbor.example", "the ACME address comes from the Caddyfile's global block"
    (tmp_path / "frame-up.json").write_text(json.dumps({"public_name": "harbor.example", "edge": {
        "tls": "internal", "container": "custom-edge", "operators_dir": "/elsewhere/ops", "acme_email": "x@y.example"}}))
    f = fr.frame_up_facts(str(tmp_path), "harbor")
    assert f["container"] == "custom-edge" and f["operators_dir"] == "/elsewhere/ops" and f["acme_email"] == "x@y.example"
    (tmp_path / "frame-up.json").write_text("{ not json")
    assert fr.frame_up_facts(str(tmp_path), "harbor")["ok"] is False


def test_read_caddy_global_email():
    assert fr.read_caddy_global_email("{\n\temail a@b.example\n}\n") == "a@b.example"
    assert fr.read_caddy_global_email("{\n\t# internal CA: no ACME account\n}\n") == ""
    assert fr.read_caddy_global_email("") == ""


# ---- the apply --------------------------------------------------------------------------------------------------

def test_under_caddy_the_apply_writes_the_site_validates_then_reloads_and_touches_no_nginx(tmp_path, monkeypatch):
    runner, sites = _runner(tmp_path, monkeypatch, edge="caddy")
    stack = _frame(runner, tmp_path)
    calls = _fake_docker(monkeypatch)
    rec = _job(runner)
    runner._apply_operator_edge(rec)
    site = stack / "edge" / "operators" / "harborop.caddy"
    assert site.exists(), rec.get("notes")
    body = site.read_text()
    assert "harborop.harbor.example {" in body and "\ttls internal" in body
    assert "reverse_proxy 172.17.0.1:31600 {" in body
    assert oct(site.stat().st_mode & 0o777) == "0o644"
    assert [c[2:] for c in calls] == [["harbor-edge"] + VALIDATE, ["harbor-edge"] + RELOAD], calls
    assert rec["state"] == "succeeded"
    assert rec["edge"] == {"mode": "caddy", "site": "harborop.harbor.example", "file": str(site), "reloaded": True}
    assert any("validated and reloaded harbor-edge" in n for n in rec["notes"]), rec["notes"]
    assert not list(sites.iterdir()), "no host nginx vhost under the caddy posture"
    assert not os.path.exists(runner.NGINX_SNI_MAP), "no SNI line under the caddy posture"


def test_the_acme_frame_gets_the_global_email_as_its_tls_line(tmp_path, monkeypatch):
    runner, _ = _runner(tmp_path, monkeypatch, edge="caddy")
    stack = _frame(runner, tmp_path, tls="acme",
                   caddyfile="{\n\thttp_port 80\n\thttps_port 443\n\temail ops@harbor.example\n}\n")
    _fake_docker(monkeypatch)
    runner._apply_operator_edge(_job(runner))
    assert "\ttls ops@harbor.example" in (stack / "edge" / "operators" / "harborop.caddy").read_text()


def test_a_second_apply_replaces_the_site_and_keeps_a_copy_the_edge_never_imports(tmp_path, monkeypatch):
    runner, _ = _runner(tmp_path, monkeypatch, edge="caddy")
    stack = _frame(runner, tmp_path)
    _fake_docker(monkeypatch)
    runner._apply_operator_edge(_job(runner))
    runner._apply_operator_edge(_job(runner, reg_port=31700))
    ops = stack / "edge" / "operators"
    assert [os.path.basename(p) for p in glob.glob(str(ops / "*.caddy"))] == ["harborop.caddy"]
    assert "reverse_proxy 172.17.0.1:31700 {" in (ops / "harborop.caddy").read_text()
    baks = glob.glob(str(ops / "harborop.caddy.*.bak"))
    assert len(baks) == 1 and "31600" in open(baks[0]).read()


def test_RED_a_site_caddy_refuses_is_reverted_and_never_reloaded_and_the_job_stays_succeeded(tmp_path, monkeypatch):
    """The operator is UP when the edge runs; a door that could not be opened is a note, never a failed job."""
    runner, _ = _runner(tmp_path, monkeypatch, edge="caddy")
    stack = _frame(runner, tmp_path)
    ops = stack / "edge" / "operators"
    ops.mkdir(parents=True)
    (ops / "harborop.caddy").write_text("# a prior site\n")
    calls = _fake_docker(monkeypatch, validate_rc=1, stderr="Error: adapting config using caddyfile: unrecognized")
    rec = _job(runner)
    runner._apply_operator_edge(rec)
    assert (ops / "harborop.caddy").read_text() == "# a prior site\n", "the prior site must be restored"
    assert [c[3:] for c in calls] == [VALIDATE], "validate ran, reload never did"
    assert rec["state"] == "succeeded" and "edge" not in rec
    assert any("REFUSED by caddy validate and reverted" in n for n in rec["notes"]), rec["notes"]


def test_RED_a_refused_first_site_is_removed_again(tmp_path, monkeypatch):
    runner, _ = _runner(tmp_path, monkeypatch, edge="caddy")
    stack = _frame(runner, tmp_path)
    _fake_docker(monkeypatch, validate_rc=1, stderr="bad")
    runner._apply_operator_edge(_job(runner))
    assert not glob.glob(str(stack / "edge" / "operators" / "*.caddy"))


def test_a_stopped_edge_is_a_logged_skip_and_the_site_stays_for_its_next_start(tmp_path, monkeypatch):
    runner, _ = _runner(tmp_path, monkeypatch, edge="caddy")
    stack = _frame(runner, tmp_path)
    calls = _fake_docker(monkeypatch, missing=True)
    rec = _job(runner)
    runner._apply_operator_edge(rec)
    assert (stack / "edge" / "operators" / "harborop.caddy").exists()
    assert len(calls) == 1, "one validate that found no container; no reload attempted"
    assert rec["state"] == "succeeded" and rec["edge"]["reloaded"] is False
    assert any("harbor-edge is not running" in n for n in rec["notes"]), rec["notes"]


def test_a_failed_reload_after_a_clean_validate_keeps_the_site_and_says_so(tmp_path, monkeypatch):
    runner, _ = _runner(tmp_path, monkeypatch, edge="caddy")
    stack = _frame(runner, tmp_path)
    _fake_docker(monkeypatch, reload_rc=1, stderr="reload: connection refused")
    rec = _job(runner)
    runner._apply_operator_edge(rec)
    assert (stack / "edge" / "operators" / "harborop.caddy").exists()
    assert rec["state"] == "succeeded" and rec["edge"]["reloaded"] is False
    assert any("reload of harbor-edge failed" in n for n in rec["notes"]), rec["notes"]


def test_a_frame_without_frame_up_json_is_skipped_not_failed(tmp_path, monkeypatch):
    runner, _ = _runner(tmp_path, monkeypatch, edge="caddy")
    stack = _frame(runner, tmp_path, frame_up=False)
    calls = _fake_docker(monkeypatch)
    rec = _job(runner)
    runner._apply_operator_edge(rec)
    assert not calls and not (stack / "edge" / "operators").exists()
    assert rec["state"] == "succeeded"
    assert any("SKIPPED" in n and "frame-up.json is missing" in n for n in rec["notes"]), rec["notes"]


def test_a_spec_without_the_edge_facts_writes_nothing_and_says_so(tmp_path, monkeypatch):
    runner, _ = _runner(tmp_path, monkeypatch, edge="caddy")
    _frame(runner, tmp_path)
    calls = _fake_docker(monkeypatch)
    rec = _job(runner)
    pathlib.Path(runner.job_dir(rec["id"]), "spec.json").write_text(json.dumps({"edge": {"domain": ""}}))
    runner._apply_operator_edge(rec)
    assert not calls and any("no edge.domain" in n for n in rec["notes"]), rec["notes"]


def test_RED_a_spec_whose_domain_could_escape_the_site_is_refused(tmp_path, monkeypatch):
    runner, _ = _runner(tmp_path, monkeypatch, edge="caddy")
    stack = _frame(runner, tmp_path)
    calls = _fake_docker(monkeypatch)
    rec = _job(runner, domain="harborop.harbor.example {\n}\nevil.example")
    runner._apply_operator_edge(rec)
    assert not calls and not (stack / "edge" / "operators").exists()
    assert any("REFUSED" in n and "not a host name" in n for n in rec["notes"]), rec["notes"]


# ---- the removal ------------------------------------------------------------------------------------------------

def test_the_removal_deletes_the_site_reloads_and_never_fails_the_teardown(tmp_path, monkeypatch):
    runner, _ = _runner(tmp_path, monkeypatch, edge="caddy")
    stack = _frame(runner, tmp_path)
    calls = _fake_docker(monkeypatch)
    runner._apply_operator_edge(_job(runner))
    del calls[:]
    out = runner._remove_operator_edge("harborop", None, frame_name="harbor")
    ops = stack / "edge" / "operators"
    assert not glob.glob(str(ops / "*.caddy")), "the live site is gone"
    assert len(glob.glob(str(ops / "harborop.caddy.*.torn-down"))) == 1, "a copy stays, under a name never imported"
    assert [c[3:] for c in calls] == [RELOAD]
    assert out["caddy_removed"] is True and out["nginx_removed"] is False and "failed" not in out
    assert "removed" in out["note"] and "reloaded harbor-edge" in out["note"]
    again = runner._remove_operator_edge("harborop", None, frame_name="harbor")
    assert again["caddy_removed"] is False and "nothing to remove" in again["note"] and "failed" not in again


def test_the_removal_finds_the_site_without_a_frame_name_and_skips_a_stopped_edge(tmp_path, monkeypatch):
    runner, _ = _runner(tmp_path, monkeypatch, edge="caddy")
    stack = _frame(runner, tmp_path)
    _fake_docker(monkeypatch)
    runner._apply_operator_edge(_job(runner))
    calls = _fake_docker(monkeypatch, missing=True)
    out = runner._remove_operator_edge("harborop", None)         # an older teardown record: no frame name
    assert not glob.glob(str(stack / "edge" / "operators" / "*.caddy"))
    assert out["caddy_removed"] is True and "failed" not in out and "not running" in out["note"]
    assert len(calls) == 1


def test_the_teardown_record_hands_the_frame_name_to_the_removal():
    """The call site: a teardown job is launched under the frame's name, and the removal reads it from the record."""
    src = (HERE.parent / "frame_runner.py").read_text()
    assert 'self._remove_operator_edge(slug, rec.get("sni_name"), frame_name=rec.get("name"))' in src
