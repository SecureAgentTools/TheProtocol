"""§TESTBED P5 (2026-09-19): frame-contribute.py packages a change only with evidence about that change."""
import importlib.util
import io
import json
import os
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("frame_contribute", os.path.join(HERE, "..", "frame-contribute.py"))
fc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fc)
kp_spec = importlib.util.spec_from_file_location("kit_provenance", os.path.join(HERE, "..", "kit_provenance.py"))
kp = importlib.util.module_from_spec(kp_spec)
kp_spec.loader.exec_module(kp)


SUITE = "AgentVault/agentvault_registry/src/agentvault_registry/api_tests/contracts/x.py"   # frame-test's suite tree
FLOW = "flow_mcp_lifecycle_complete"


def _kit(tmp_path):
    root = tmp_path / "kit"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("x = 1\n")
    (root / "README.md").write_text("# kit\n")
    (root / SUITE).parent.mkdir(parents=True)
    (root / SUITE).write_text("EXPECT = 1\n")
    kp.write_manifest(str(root))
    pristine = tmp_path / "kit.tar.gz"
    with tarfile.open(pristine, "w:gz") as tar:
        for rel in ("src/a.py", "README.md", SUITE):
            data = (root / rel).read_bytes()
            info = tarfile.TarInfo(f"theprotocol-kit/{rel}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return root, pristine


def _report(tmp_path, name, tree, modified, verdicts, suite="s" * 64, flow="flow_mcp_lifecycle_complete"):
    p = tmp_path / name
    p.write_text(json.dumps({"flow": flow, "suite_hash": suite, "verdicts": verdicts,
                             "reasons": {}, "summary_line": "x", "build": {"tree_digest": tree, "modified": modified,
                                                                           "kit_version": "1.0.0"}}))
    return str(p)


def _run(root, pristine, base, after):
    """base/after: one report path each, or lists of them (one pair per flow)."""
    pairs = []
    for b, af in zip(base if isinstance(base, list) else [base], after if isinstance(after, list) else [after]):
        pairs += ["--baseline", b, "--after", af]
    try:
        return fc.main(["--pristine", str(pristine), *pairs, "--signoff", "A Person <a@example.org>", "--root", str(root)])
    except SystemExit as e:
        return e.code


def test_a_change_with_its_evidence_is_packaged(tmp_path):
    root, pristine = _kit(tmp_path)
    (root / "src" / "a.py").write_text("x = 2\n")
    tree = kp.tree_digest(kp.digests(str(root)))
    base = _report(tmp_path, "b.json", kp.tree_digest(kp.read_manifest(str(root))), False, {"t1": "pass", "t2": "fail"})
    after = _report(tmp_path, "a.json", tree, True, {"t1": "pass", "t2": "pass"})
    assert _run(root, pristine, base, after) == 0
    out = [f for f in os.listdir(root / "dist") if f.startswith("contribution-")]
    with tarfile.open(root / "dist" / out[0]) as tar:
        names = {m.name.split("/", 1)[1]: m for m in tar}
        patch = tar.extractfile(names["contribution.patch"]).read().decode()
    f = "flow_mcp_lifecycle_complete"
    assert set(names) == {"contribution.patch", f"baseline-{f}.json", f"after-{f}.json", f"comparison-{f}.txt", "MANIFEST.txt"}
    assert "-x = 1" in patch and "+x = 2" in patch and "Signed-off-by: A Person <a@example.org>" in patch
    assert kp.build_info(str(root), "v")["changed_files"] == 1          # the archive under dist/ is not part of the change


def test_evidence_about_another_tree_is_refused(tmp_path):
    root, pristine = _kit(tmp_path)
    (root / "src" / "a.py").write_text("x = 2\n")
    base = _report(tmp_path, "b.json", kp.tree_digest(kp.read_manifest(str(root))), False, {"t1": "pass"})
    assert _run(root, pristine, base, _report(tmp_path, "a.json", "o" * 64, True, {"t1": "pass"})) == 2


def test_a_new_red_or_a_modified_baseline_is_refused(tmp_path):
    root, pristine = _kit(tmp_path)
    (root / "src" / "a.py").write_text("x = 2\n")
    tree = kp.tree_digest(kp.digests(str(root)))
    good_base = _report(tmp_path, "b.json", kp.tree_digest(kp.read_manifest(str(root))), False, {"t1": "pass"})
    assert _run(root, pristine, good_base, _report(tmp_path, "a.json", tree, True, {"t1": "fail"})) == 1
    bad_base = _report(tmp_path, "b2.json", kp.tree_digest(kp.read_manifest(str(root))), True, {"t1": "pass"})
    assert _run(root, pristine, bad_base, _report(tmp_path, "a2.json", tree, True, {"t1": "pass"})) == 2


def test_an_unchanged_tree_has_nothing_to_contribute(tmp_path):
    root, pristine = _kit(tmp_path)
    tree = kp.tree_digest(kp.digests(str(root)))
    base = _report(tmp_path, "b.json", tree, False, {"t1": "pass"})
    assert _run(root, pristine, base, _report(tmp_path, "a.json", tree, False, {"t1": "pass"})) == 2


def test_a_federation_change_carries_one_pair_per_flow(tmp_path):
    root, pristine = _kit(tmp_path)
    (root / "src" / "a.py").write_text("x = 2\n")
    tree = kp.tree_digest(kp.digests(str(root)))
    fed = "flow_federation_suite_complete"
    bases = [_report(tmp_path, "b1.json", kp.tree_digest(kp.read_manifest(str(root))), False, {"t1": "pass"}),
             _report(tmp_path, "b2.json", kp.tree_digest(kp.read_manifest(str(root))), False, {"f1": "pass"}, suite="f" * 64, flow=fed)]
    afters = [_report(tmp_path, "a1.json", tree, True, {"t1": "pass"}),
              _report(tmp_path, "a2.json", tree, True, {"f1": "pass"}, suite="f" * 64, flow=fed)]
    assert _run(root, pristine, bases, afters) == 0
    out = [f for f in os.listdir(root / "dist") if f.startswith("contribution-")]
    with tarfile.open(root / "dist" / out[0]) as tar:
        names = {m.name.split("/", 1)[1] for m in tar}
    assert {f"comparison-{fed}.txt", "comparison-flow_mcp_lifecycle_complete.txt"} <= names
    # a red in the SECOND flow refuses the whole archive; so do an unpaired argument and a flow given twice
    afters[1] = _report(tmp_path, "a3.json", tree, True, {"f1": "fail"}, suite="f" * 64, flow=fed)
    assert _run(root, pristine, bases, afters) == 1
    assert _run(root, pristine, bases, afters[:1] + afters[:1]) == 2           # the lifecycle flow twice
    try:
        rc = fc.main(["--pristine", str(pristine), "--baseline", bases[0], "--baseline", bases[1], "--after", afters[0],
                      "--signoff", "A Person <a@example.org>", "--root", str(root)])
    except SystemExit as e:
        rc = e.code
    assert rc == 2



def test_a_baseline_of_another_release_is_refused(tmp_path):
    root, pristine = _kit(tmp_path)
    (root / "src" / "a.py").write_text("x = 2\n")
    tree = kp.tree_digest(kp.digests(str(root)))
    other = _report(tmp_path, "b.json", "e" * 64, False, {"t1": "pass"})           # unmodified, but another release
    assert _run(root, pristine, other, _report(tmp_path, "a.json", tree, True, {"t1": "pass"})) == 2


# §REVIEWLANE-2 (2026-09-26): a change to the suite (api_tests/) carries a third report per flow, the control: the NEW
# suite on the unmodified release. Red then green: the control turns no existing tool red, the tools it adds may be red,
# the after report holds no new red against the control and turns every one of those green.

def _three(tmp_path, root, pristine, control_verdicts, after_verdicts, control_tree=None, suite_change=True):
    if suite_change:
        (root / SUITE).write_text("EXPECT = 2\n")
    (root / "src" / "a.py").write_text("x = 2\n")
    release, now = kp.read_manifest(str(root)), kp.digests(str(root))
    ctree = control_tree or fc.control_tree(release, now, [SUITE] if suite_change else [])
    base = _report(tmp_path, "b.json", kp.tree_digest(release), False, {"t1": "pass", "t2": "pass"})
    control = _report(tmp_path, "c.json", ctree, True, control_verdicts, suite="n" * 64)
    after = _report(tmp_path, "a.json", kp.tree_digest(now), True, after_verdicts, suite="n" * 64)
    try:
        return fc.main(["--pristine", str(pristine), "--baseline", base, "--control", control, "--after", after,
                        "--signoff", "A Person <a@example.org>", "--root", str(root)])
    except SystemExit as e:
        return e.code


RED_ON_RELEASE = {"t1": "pass", "t2": "pass", "t_new": "fail"}
GREEN_ON_CHANGE = {"t1": "pass", "t2": "pass", "t_new": "pass"}


def test_a_suite_change_without_its_control_is_refused(tmp_path, capsys):
    root, pristine = _kit(tmp_path)
    (root / SUITE).write_text("EXPECT = 2\n")
    tree = kp.tree_digest(kp.digests(str(root)))
    base = _report(tmp_path, "b.json", kp.tree_digest(kp.read_manifest(str(root))), False, {"t1": "pass"})
    assert _run(root, pristine, base, _report(tmp_path, "a.json", tree, True, {"t1": "pass"})) == 2
    assert "give a --control per flow" in capsys.readouterr().out


def test_a_control_that_ran_another_tree_is_refused(tmp_path, capsys):
    root, pristine = _kit(tmp_path)
    assert _three(tmp_path, root, pristine, RED_ON_RELEASE, GREEN_ON_CHANGE, control_tree="o" * 64) == 2
    assert "the control measured tree" in capsys.readouterr().out
    # the control of the WHOLE change (code and suite together) is not the release plus the suite change alone
    root2, pristine2 = _kit(tmp_path / "two")
    (root2 / SUITE).write_text("EXPECT = 2\n")
    (root2 / "src" / "a.py").write_text("x = 2\n")
    whole = kp.tree_digest(kp.digests(str(root2)))
    assert _three(tmp_path / "two", root2, pristine2, RED_ON_RELEASE, GREEN_ON_CHANGE, control_tree=whole) == 2
    assert "the control measured tree" in capsys.readouterr().out


def test_a_control_that_turns_an_existing_tool_red_is_refused(tmp_path, capsys):
    root, pristine = _kit(tmp_path)
    assert _three(tmp_path, root, pristine, {"t1": "fail", "t2": "pass", "t_new": "fail"}, GREEN_ON_CHANGE) == 1
    assert "existing tool(s) red on the release (t1)" in capsys.readouterr().out


def test_an_after_that_leaves_an_expected_red_red_is_refused(tmp_path, capsys):
    root, pristine = _kit(tmp_path)
    assert _three(tmp_path, root, pristine, RED_ON_RELEASE, RED_ON_RELEASE) == 1
    assert "still fail on your change (t_new)" in capsys.readouterr().out


def test_a_control_without_a_suite_change_is_refused(tmp_path, capsys):
    root, pristine = _kit(tmp_path)
    assert _three(tmp_path, root, pristine, RED_ON_RELEASE, GREEN_ON_CHANGE, suite_change=False) == 2
    assert "does not touch the test suite" in capsys.readouterr().out


def test_a_clean_three_run_change_is_packaged_red_then_green(tmp_path):
    root, pristine = _kit(tmp_path)
    assert _three(tmp_path, root, pristine, RED_ON_RELEASE, GREEN_ON_CHANGE) == 0
    out = [f for f in os.listdir(root / "dist") if f.startswith("contribution-")]
    with tarfile.open(root / "dist" / out[0]) as tar:
        names = {m.name.split("/", 1)[1]: m for m in tar}
        patch = tar.extractfile(names["contribution.patch"]).read().decode()
        comparison = tar.extractfile(names[f"comparison-{FLOW}.txt"]).read().decode()
    assert set(names) == {"contribution.patch", f"baseline-{FLOW}.json", f"control-{FLOW}.json", f"after-{FLOW}.json",
                          f"comparison-{FLOW}.txt", "MANIFEST.txt"}
    assert f"tests: {FLOW} x -> x -> x, red then green: 1" in patch.split("\n")
    assert "expected_reds (1): t_new" in comparison.split("\n") and "turned_green (1): t_new" in comparison.split("\n")
    assert "control_new_reds (0): " in comparison.split("\n")
