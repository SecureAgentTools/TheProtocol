"""§TESTBED P5 (2026-09-19): frame-test.py's comparison. The runs themselves are proven on a sandbox."""
import importlib.util
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("frame_test", os.path.join(HERE, "..", "frame-test.py"))
ft = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ft)


def _report(verdicts, suite="s" * 64, flow="flow_mcp_lifecycle_complete"):
    return {"flow": flow, "suite_hash": suite, "verdicts": verdicts, "reasons": {t: "why" for t, v in verdicts.items() if v != "pass"},
            "summary_line": "x", "build": {"tree_digest": "t" * 64, "modified": False}}


def test_verdict_of_a_result():
    assert ft.verdict({"skipped": True, "healthy": False}) == "skip"
    assert ft.verdict({"healthy": True}) == "pass" and ft.verdict({"healthy": False}) == "fail"


def test_compare_names_new_reds_greens_and_the_rest():
    old = _report({"a": "pass", "b": "fail", "c": "pass", "d": "skip", "gone": "pass"})
    new = _report({"a": "fail", "b": "pass", "c": "pass", "d": "fail", "added": "pass"})
    cmp = ft.compare(new, old)
    assert cmp["new_reds"] == ["a", "d"] and cmp["new_greens"] == ["b"]
    assert cmp["gone"] == ["gone"] and cmp["added"] == ["added"] and cmp["still_red"] == []


def _cli(tmp_path, new, old):
    n, o = tmp_path / "new.json", tmp_path / "old.json"
    n.write_text(json.dumps(new)); o.write_text(json.dumps(old))
    try:
        return ft.main(["--compare", "--report", str(n), "--against", str(o)])
    except SystemExit as e:
        return e.code


def test_exit_codes(tmp_path):
    base = _report({"a": "pass", "b": "fail"})
    assert _cli(tmp_path, _report({"a": "pass", "b": "pass"}), base) == 0     # a new green is fine
    assert _cli(tmp_path, _report({"a": "fail", "b": "fail"}), base) == 1     # a new red is not
    assert _cli(tmp_path, _report({"a": "pass", "b": "fail"}, suite="z" * 64), base) == 4   # a changed suite: not comparable
    assert _cli(tmp_path, _report({"a": "pass"}, flow="flow_federation_suite_complete"), base) == 4


def _sandbox(tmp_path, monkeypatch, build):
    """A sandbox on disk and a registry that answers /health with `build`; returns the list of calls made."""
    sd = tmp_path / "sbx-1"; sd.mkdir()
    (sd / "frame-up.json").write_text(json.dumps({"sandbox_of": "myframe", "ports": {"registry": 1}, "secrets_dir": str(tmp_path)}))
    (tmp_path / ".sbx_frame_admin.secret.json").write_text(json.dumps({"admin_email": "a@b.c", "admin_password": "p"}))
    monkeypatch.setattr(ft.frame_names, "stack_dirs", lambda root, name, need_file=None: ["sbx-1"])
    calls = []

    def http(method, url, body=None, headers=None, form=False, timeout=120):
        calls.append(url)
        if url.endswith("/auth/login"):
            return 200, {"access_token": "t"}
        if url.endswith("/health"):
            return 200, {"status": "ok", "build": build}
        raise AssertionError(f"no call past /health expected: {url}")
    monkeypatch.setattr(ft, "http", http)
    monkeypatch.setattr(ft.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no docker call expected")))
    return calls


def test_a_baseline_on_a_changed_build_is_refused_before_the_run(tmp_path, monkeypatch):
    calls = _sandbox(tmp_path, monkeypatch, {"modified": True, "changed_files": 2})
    try:
        ft.run_suite(str(tmp_path), "sbx", "flow_mcp_lifecycle_complete", 1, baseline=True)
        raise AssertionError("run_suite went on")
    except SystemExit as e:
        assert e.code == 2
    assert not any("mcp-tester/run" in u for u in calls)


def test_a_compare_without_its_baseline_is_refused_before_the_run(tmp_path, monkeypatch):
    calls = _sandbox(tmp_path, monkeypatch, {"modified": True})
    monkeypatch.setattr(ft, "run_suite", lambda *a, **k: (_ for _ in ()).throw(AssertionError("the suite ran")))
    try:
        rc = ft.main(["--name", "sbx", "--compare", "--flow", "flow_federation_suite_complete", "--stack-root", str(tmp_path)])
    except SystemExit as e:
        rc = e.code
    assert rc == 2 and calls == []



def test_a_changed_build_against_another_releases_baseline_is_not_comparable(tmp_path):
    base = _report({"a": "pass"}); base["build"] = {"tree_digest": "r" * 64, "modified": False}
    mine = _report({"a": "pass"}); mine["build"] = {"tree_digest": "m" * 64, "modified": True, "release_digest": "o" * 64}
    assert _cli(tmp_path, mine, base) == 4
    mine["build"]["release_digest"] = "r" * 64                                      # the release this change is made against
    assert _cli(tmp_path, mine, base) == 0


def test_a_tool_on_two_surfaces_keeps_both_verdicts():
    """Measured in every sweep: the six gateway meta-tools run on the public surface (tier none) AND the admin one;
    keyed by name, the admin result overwrote the public one, so a public-only regression read as a pass."""
    res = [{"tool": "theprotocol_listToolsets", "tier": "none", "healthy": False, "error": "public broke"},
           {"tool": "theprotocol_listToolsets", "tier": "admin", "healthy": True},
           {"tool": "theprotocol_getApyRates", "tier": "public", "healthy": True},
           {"tool": "theprotocol_x", "tier": "admin", "healthy": True}, {"tool": "theprotocol_x", "tier": "admin", "healthy": False}]
    v, why = ft.keyed_verdicts(res)
    assert v == {"theprotocol_listToolsets@none": "fail", "theprotocol_listToolsets@admin": "pass",
                 "theprotocol_getApyRates": "pass", "theprotocol_x@admin": "fail"}
    assert why["theprotocol_listToolsets@none"] == "public broke"


def test_reports_of_different_formats_are_not_compared(tmp_path):
    old, new = _report({"a": "pass"}), _report({"a": "pass"})
    old["report_format"], new["report_format"] = 1, 2
    assert _cli(tmp_path, new, old) == 4
