"""§REVIEWLANE (2026-09-26): frame-review.py answers, check by check, whether a contribution archive's claim holds.

Every check has a control: an archive frame-contribute.py wrote passes it, and a planted defect makes it RED or HELD
for the reason the sentence names. A gate that cannot fail measures nothing.
"""
import hashlib
import importlib.util
import io
import json
import os
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))


def _mod(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, "..", rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fr = _mod("frame_review", "frame-review.py")
fc = _mod("frame_contribute", "frame-contribute.py")
kp = _mod("kit_provenance", "kit_provenance.py")

SUITE_FILE = "AgentVault/agentvault_registry/src/agentvault_registry/api_tests/contracts/x.py"   # the suite tree
CONTRACTS_FILE = "AgentVault/agentvault_registry/src/agentvault_registry/routers/contracts_v2.py"
KIT_FILES = {"src/a.py": "x = 1\n", "README.md": "# kit\n", "alembic/versions/0001_x.py": "rev = '0001'\n",
             "teg/teg_integration.py": "fee = 1\n", ".env.example": "A=1\n", SUITE_FILE: "EXPECT = 1\n",
             CONTRACTS_FILE: "def accept():\n    return 1\n", "scripts/distribution/frame-test.py": "# the instrument\n"}
FLOW = "flow_mcp_lifecycle_complete"
FED = "flow_federation_suite_complete"
SIGNOFF = "Ada Lovelace <ada@example.org>"
BASE = {"t1": "pass", "t2": "fail", "t3": "pass"}
AFTER = {"t1": "pass", "t2": "pass", "t3": "pass"}
# a suite change: the new test t_new fails on the release (the control) and passes on the change
THREE = {FLOW: {"base": {"t1": "pass", "t2": "pass"}, "control": {"t1": "pass", "t2": "pass", "t_new": "fail"},
                "after": {"t1": "pass", "t2": "pass", "t_new": "pass"}}}
SUITE_CHANGE = {SUITE_FILE: "EXPECT = 2\n", "src/a.py": "x = 2\n"}


def _kit(tmp_path, files=None, tarball_files=None):
    """An unpacked kit (with its manifest) and the release tarball it came from (manifest included, as a real kit)."""
    root = tmp_path / "kit"
    for rel, text in (files or KIT_FILES).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    kp.write_manifest(str(root))
    pristine = tmp_path / "kit.tar.gz"
    with tarfile.open(pristine, "w:gz") as tar:
        for rel in sorted(list((files or KIT_FILES).keys()) + [kp.MANIFEST]):
            data = (root / rel).read_bytes() if tarball_files is None or rel not in tarball_files else tarball_files[rel].encode()
            info = tarfile.TarInfo(f"theprotocol-kit/{rel}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return root, pristine


def _report(tmp_path, name, tree, modified, verdicts, suite="s" * 64, flow=FLOW):
    p = tmp_path / name
    p.write_text(json.dumps({"flow": flow, "suite_hash": suite, "verdicts": verdicts, "reasons": {}, "report_format": 2,
                             "summary_line": f"{len(verdicts)} tools", "build": {"tree_digest": tree, "modified": modified,
                                                                                  "kit_version": "1.0.0"}}))
    return str(p)


def _build(tmp_path, changes=None, flows=None, signoff=SIGNOFF, tarball_files=None):
    """A real archive, written by frame-contribute.py, for a change to the fixture kit. flows: {flow: {"base", "after"
    [, "control"] verdicts}}; a flow with a control runs the NEW suite on the release plus exactly the suite change."""
    root, pristine = _kit(tmp_path, tarball_files=tarball_files)
    for rel, text in (changes or {"src/a.py": "x = 2\n"}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    now, release = kp.digests(str(root)), kp.read_manifest(str(root))
    tree = kp.tree_digest(now)
    changed, _release = kp.changed(str(root))
    control_tree = fc.control_tree(release, now, [p for p in changed if fc.is_suite_path(p)])
    args = []
    for i, (flow, spec) in enumerate((flows or {FLOW: {"base": BASE, "after": AFTER}}).items()):
        suite = "n" * 64 if "control" in spec else "s" * 64
        args += ["--baseline", _report(tmp_path, f"b{i}.json", kp.tree_digest(release), False, spec["base"], flow=flow),
                 "--after", _report(tmp_path, f"a{i}.json", tree, True, spec["after"], suite=suite, flow=flow)]
        if "control" in spec:
            args += ["--control", _report(tmp_path, f"c{i}.json", control_tree, True, spec["control"], suite=suite, flow=flow)]
    rc = fc.main(["--pristine", str(pristine), *args, "--signoff", signoff, "--root", str(root)])
    assert rc == 0
    out = [f for f in os.listdir(root / "dist") if f.startswith("contribution-")]
    return root / "dist" / out[0], pristine, root, tree


def _archive(tmp_path, changes=None, verdicts_after=None, signoff=SIGNOFF, tarball_files=None):
    """One lifecycle flow, two runs: the shape most tests start from."""
    archive, pristine, root, tree = _build(tmp_path, changes, {FLOW: {"base": BASE, "after": verdicts_after or AFTER}},
                                           signoff, tarball_files)
    return archive, pristine, root, None, tree


def _rewrite(archive, edits, refresh_manifest=True):
    """Rewrite members of an archive: name -> bytes, a callable over the old bytes, or None to drop it."""
    with tarfile.open(archive) as tar:
        top = tar.getnames()[0].split("/", 1)[0]
        files = {m.name.split("/", 1)[1]: tar.extractfile(m).read() for m in tar if m.isfile()}
    for name, edit in edits.items():
        if edit is None:
            files.pop(name, None)
        elif callable(edit):
            files[name] = edit(files[name])
        else:
            files[name] = edit
    if refresh_manifest:
        files["MANIFEST.txt"] = "".join(f"{hashlib.sha256(v).hexdigest()}  {k}\n" for k, v in sorted(files.items())
                                        if k != "MANIFEST.txt").encode()
    with tarfile.open(archive, "w:gz") as tar:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo(f"{top}/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def _run(archive, *flags):
    rc = fr.main([str(archive), *flags])
    stem = os.path.basename(str(archive))[:-len(".tar.gz")]
    js = json.load(open(os.path.join(os.path.dirname(str(archive)), f"review-{stem}.json")))
    return rc, js


def _v(js, cid):
    return next(c["verdict"] for c in js["checks"] if c["id"] == cid)


def _s(js, cid):
    return next(c["sentence"] for c in js["checks"] if c["id"] == cid)


def _cla(tmp_path, mail="ada@example.org"):
    p = tmp_path / "cla.txt"
    p.write_text("# record\nI have read and accept the TheProtocol Contributor License Agreement v1.1. "
                 f"Ada Lovelace <{mail}>   2026-09-27  PR #1\n")
    return str(p)


def test_a_clean_archive_with_the_acceptance_on_file_is_mergeable(tmp_path):
    archive, pristine, root, _b, _t = _archive(tmp_path)
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path))
    assert rc == 0 and js["decision"] == "MERGEABLE"
    for cid in ("R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R10"):
        assert _v(js, cid) == "GREEN", (cid, _s(js, cid))
    assert _v(js, "R9") == "NOT MEASURED"
    page = open(os.path.join(os.path.dirname(str(archive)), f"review-{os.path.basename(str(archive))[:-7]}.md")).read()
    assert "**MERGEABLE**" in page and "src/a.py" in page and "Ada Lovelace" in page


def test_without_the_acceptance_the_review_is_held_not_refused(tmp_path):
    archive, pristine, _r, _b, _t = _archive(tmp_path)
    rc, js = _run(archive, "--pristine", str(pristine))
    assert rc == 1 and js["decision"] == "HELD" and _v(js, "R8") == "HELD"
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path, mail="someone-else@example.org"))
    assert rc == 1 and _v(js, "R8") == "HELD" and "ada@example.org" in _s(js, "R8")


def test_a_tampered_after_report_is_refused(tmp_path):
    archive, pristine, _r, _b, _t = _archive(tmp_path)

    def new_red(data):
        d = json.loads(data)
        d["verdicts"]["t3"] = "fail"
        return json.dumps(d).encode()
    _rewrite(archive, {f"after-{FLOW}.json": new_red})
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path))
    assert rc == 2 and js["decision"] == "REFUSED" and _v(js, "R4") == "RED" and "new red" in _s(js, "R4")


def test_a_manifest_that_does_not_match_is_refused(tmp_path):
    archive, pristine, _r, _b, _t = _archive(tmp_path)
    _rewrite(archive, {"contribution.patch": lambda b: b + b"\n"}, refresh_manifest=False)
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path))
    assert rc == 2 and _v(js, "R2") == "RED" and "contribution.patch" in _s(js, "R2")


def test_a_missing_signoff_is_refused_and_a_one_word_name_is_held(tmp_path):
    archive, pristine, _r, _b, _t = _archive(tmp_path)
    _rewrite(archive, {"contribution.patch": lambda b: b.replace(b"Signed-off-by: " + SIGNOFF.encode() + b"\n", b"")})
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path))
    assert rc == 2 and _v(js, "R3") == "RED" and "Signed-off-by" in _s(js, "R3")
    archive2, pristine2, _r2, _b2, _t2 = _archive(tmp_path / "two", signoff="ada <ada@example.org>")
    rc, js = _run(archive2, "--pristine", str(pristine2), "--cla-file", _cla(tmp_path))
    assert rc == 1 and _v(js, "R3") == "HELD" and "real name" in _s(js, "R3")


def test_a_secret_shape_in_an_added_line_is_refused_without_printing_it(tmp_path):
    key = "avreg_" + "k" * 30
    archive, pristine, _r, _b, _t = _archive(tmp_path, changes={"src/a.py": f"x = 2\nKEY = '{key}'\n"})
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path))
    assert rc == 2 and _v(js, "R6") == "RED" and "avreg_api_key in src/a.py" in _s(js, "R6")
    assert key not in json.dumps(js)


def test_evidence_about_another_release_is_refused(tmp_path):
    archive, _p, _r, _b, _t = _archive(tmp_path)
    other_files = dict(KIT_FILES, **{"README.md": "# another release\n"})
    _root, other = _kit(tmp_path / "other", files=other_files)
    rc, js = _run(archive, "--pristine", str(other), "--cla-file", _cla(tmp_path))
    assert rc == 2 and _v(js, "R7") == "RED" and "another" in _s(js, "R7") or "release" in _s(js, "R7")


def test_a_patch_that_does_not_apply_to_the_release_is_refused(tmp_path):
    # the archive was made against the real release; the reviewer is handed a tarball with the SAME manifest whose
    # src/a.py is not what that manifest says: the digest check passes, the apply check must not
    archive, _p, _r, _b, _t = _archive(tmp_path)
    _root, pristine = _kit(tmp_path / "other", tarball_files={"src/a.py": "y = 9\n"})
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path))
    assert rc == 2 and _v(js, "R7") == "RED" and "does not apply" in _s(js, "R7")


def test_the_maintainers_own_run_reproduces_disagrees_or_finds_a_red(tmp_path):
    archive, pristine, _r, _b, tree = _archive(tmp_path)
    same = _report(tmp_path, "own.json", tree, True, {"t1": "pass", "t2": "pass", "t3": "pass"})
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path), "--own-after", same)
    assert rc == 0 and _v(js, "R9") == "GREEN" and "reproduced" in _s(js, "R9")
    differs = _report(tmp_path, "own2.json", tree, True, {"t1": "pass", "t2": "pass", "t3": "skip"})
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path), "--own-after", differs)
    assert rc == 1 and _v(js, "R9") == "HELD" and "t3" in _s(js, "R9")
    red = _report(tmp_path, "own3.json", tree, True, {"t1": "fail", "t2": "pass", "t3": "pass"})
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path), "--own-after", red)
    assert rc == 2 and _v(js, "R9") == "RED" and "t1" in _s(js, "R9")
    other_tree = _report(tmp_path, "own4.json", "f" * 64, True, {"t1": "pass", "t2": "pass", "t3": "pass"})
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path), "--own-after", other_tree)
    assert rc == 2 and _v(js, "R9") == "RED" and "measured tree" in _s(js, "R9")


def test_the_areas_a_change_touches_are_named_for_the_reader(tmp_path):
    # a money change with what R12 asks of one: the federation suite in the archive, the invariant tool passing
    fed = {"base": {"f1": "pass", "supply_invariant_audit": "pass"}, "after": {"f1": "pass", "supply_invariant_audit": "pass"}}
    archive, pristine, _r, _t = _build(tmp_path, {"alembic/versions/0001_x.py": "rev = '0002'\n", "teg/teg_integration.py": "fee = 2\n"},
                                       {FLOW: {"base": BASE, "after": AFTER}, FED: fed})
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path))
    assert rc == 0, js["checks"]
    areas = {a["area"] for a in js["facts"]["diff"]["areas"]}
    assert {"money", "migration"} <= areas
    assert js["facts"]["diff"]["files"][0]["path"] in ("alembic/versions/0001_x.py", "teg/teg_integration.py")
    assert _v(js, "R12") == "GREEN" and "1 invariant tool(s), every one pass" in _s(js, "R12")
    assert js["facts"]["diff"]["caps"]["cap_files"] == 12                  # the cap where money is touched


def test_a_change_to_the_instruments_is_held(tmp_path):
    archive, pristine, _r, _b, _t = _archive(tmp_path, changes={"scripts/distribution/frame-test.py": "# changed\n"})
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path))
    assert rc == 1 and _v(js, "R5") == "HELD" and "instruments" in _s(js, "R5") and "frame-test.py" in _s(js, "R5")


def test_a_forbidden_path_is_refused_and_a_shipped_template_is_not(tmp_path):
    archive, pristine, _r, _b, _t = _archive(tmp_path, changes={".env.operator": "SECRET_NAME=value\n"})
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path))
    assert rc == 2 and _v(js, "R5") == "RED" and ".env.operator" in _s(js, "R5")
    archive2, pristine2, _r2, _b2, _t2 = _archive(tmp_path / "two", changes={".env.example": "A=2\n"})
    rc, js = _run(archive2, "--pristine", str(pristine2), "--cla-file", _cla(tmp_path))
    assert rc == 0 and _v(js, "R5") == "GREEN"


def test_a_tests_line_that_does_not_match_its_reports_is_refused(tmp_path):
    archive, pristine, _r, _b, _t = _archive(tmp_path)
    _rewrite(archive, {"contribution.patch": lambda b: b.replace(b"3 tools -> 3 tools, no new red", b"3 tools -> 9 tools, no new red")})
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path))
    assert rc == 2 and _v(js, "R10") == "RED"


def test_an_archive_that_is_not_a_contribution_is_refused(tmp_path):
    bogus = tmp_path / "contribution-x.tar.gz"
    with tarfile.open(bogus, "w:gz") as tar:
        data = b"hello"
        info = tarfile.TarInfo("contribution-x/notes.txt")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    rc, js = _run(bogus)
    assert rc == 2 and _v(js, "R1") == "RED"
    escaping = tmp_path / "contribution-y.tar.gz"
    with tarfile.open(escaping, "w:gz") as tar:
        info = tarfile.TarInfo("contribution-y/../evil.txt")
        info.size = 0
        tar.addfile(info, io.BytesIO(b""))
    rc, js = _run(escaping)
    assert rc == 2 and _v(js, "R1") == "RED" and "leaves" in _s(js, "R1")


# §REVIEWLANE-2 (his "approved" 2026-09-26): red then green, the caps, the coverage rules. Every rule with its planted
# defect; the clean archives are the controls that must stay GREEN.

def _members(archive):
    with tarfile.open(archive) as tar:
        return {m.name.split("/", 1)[1] for m in tar}


def test_the_suite_rule_is_frame_contributes(tmp_path):
    for p in (SUITE_FILE, "api_tests/x.py", "a/api_tests/b/c.py", "src/a.py", "api_testsx/y.py", "mcp_tester/suite.py"):
        assert fr.is_suite_path(p) == fc.is_suite_path(p), p


def test_a_clean_three_run_archive_is_mergeable_red_then_green(tmp_path):
    archive, pristine, _r, _t = _build(tmp_path, SUITE_CHANGE, THREE)
    assert f"control-{FLOW}.json" in _members(archive)
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path))
    assert rc == 0 and js["decision"] == "MERGEABLE", js["checks"]
    for cid in ("R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R10", "R11", "R12"):
        assert _v(js, cid) == "GREEN", (cid, _s(js, cid))
    assert "red then green: 1" in _s(js, "R11") and "red then green: 1" in _s(js, "R5")
    assert "every control run measured the release plus exactly the suite hunks" in _s(js, "R7")
    areas = {a["area"] for a in js["facts"]["diff"]["areas"]}
    assert "suite" in areas and "contracts" not in areas            # a test under api_tests/contracts is not the contracts area
    # without the release kit the control's tree is not verified, and the page says so
    rc, js = _run(archive, "--cla-file", _cla(tmp_path))
    assert _v(js, "R7") == "NOT MEASURED" and "control runs" in _s(js, "R7")
    # planted: a control that measured another tree; R7 recomputes it from the suite hunks and refuses
    def other_tree(data):
        d = json.loads(data)
        d["build"]["tree_digest"] = "c" * 64
        return json.dumps(d).encode()
    _rewrite(archive, {f"control-{FLOW}.json": other_tree})
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path))
    assert rc == 2 and _v(js, "R7") == "RED" and "did not measure the release plus exactly the suite hunks" in _s(js, "R7")


def test_a_three_run_after_that_leaves_an_expected_red_red_is_refused(tmp_path):
    archive, pristine, _r, _t = _build(tmp_path, SUITE_CHANGE, THREE)

    def still_red(data):
        d = json.loads(data)
        d["verdicts"]["t_new"] = "fail"
        return json.dumps(d).encode()
    _rewrite(archive, {f"after-{FLOW}.json": still_red})
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path))
    assert rc == 2 and _v(js, "R4") == "RED" and "still fail on the change" in _s(js, "R4")
    assert _v(js, "R11") == "RED" and "t_new" in _s(js, "R11")


def test_a_control_that_turns_an_existing_tool_red_is_refused(tmp_path):
    archive, pristine, _r, _t = _build(tmp_path, SUITE_CHANGE, THREE)

    def existing_red(data):
        d = json.loads(data)
        d["verdicts"]["t1"] = "fail"
        return json.dumps(d).encode()
    _rewrite(archive, {f"control-{FLOW}.json": existing_red})
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path))
    assert rc == 2 and _v(js, "R4") == "RED" and "existing tool(s) red on the release" in _s(js, "R4")
    assert _v(js, "R11") == "RED"


def test_an_existing_tool_gone_from_the_suite_is_held_for_a_human(tmp_path):
    gone = {FLOW: {"base": {"t1": "pass", "t2": "pass"}, "control": {"t1": "pass", "t_new": "fail"},
                   "after": {"t1": "pass", "t_new": "pass"}}}
    archive, pristine, _r, _t = _build(tmp_path, SUITE_CHANGE, gone)
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path))
    assert rc == 1 and _v(js, "R4") == "HELD" and _v(js, "R11") == "HELD" and "t2" in _s(js, "R11")


def test_a_suite_change_without_its_control_is_refused(tmp_path, monkeypatch):
    # frame-contribute refuses to pack it, so the archive is made the way a hand-made one would be: the packer is told
    # the suite path is not the suite
    monkeypatch.setattr(fc, "is_suite_path", lambda rel: False)
    archive, pristine, _r, _t = _build(tmp_path, SUITE_CHANGE)
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path))
    assert rc == 2 and _v(js, "R5") == "RED" and "no control run" in _s(js, "R5")


def test_a_control_for_some_flows_only_is_refused(tmp_path):
    fed = {"base": {"f1": "pass"}, "control": {"f1": "pass", "f_new": "fail"}, "after": {"f1": "pass", "f_new": "pass"}}
    archive, pristine, _r, _t = _build(tmp_path, SUITE_CHANGE, dict(THREE, **{FED: fed}))
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path))
    assert rc == 0 and "red then green: 1" in _s(js, "R11") and _s(js, "R11").count("red then green") == 2
    _rewrite(archive, {f"control-{FED}.json": None})
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path))
    assert rc == 2 and _v(js, "R1") == "RED" and "some flows" in _s(js, "R1")


def test_the_caps_hold_a_large_change_and_a_design_issue_releases_it(tmp_path):
    many = {f"src/m{i:02d}.py": f"v = {i}\n" for i in range(25)}
    archive, pristine, _r, _b, _t = _archive(tmp_path, changes=many)
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path))
    assert rc == 1 and _v(js, "R5") == "HELD" and "25 code file(s)" in _s(js, "R5") and "split it" in _s(js, "R5")
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path), "--design-issue", "#7")
    assert rc == 0 and _v(js, "R5") == "GREEN" and "read in slices under design issue #7" in _s(js, "R5")
    # at the cap is not over it; docs do not count
    at_cap = dict({f"src/m{i:02d}.py": f"v = {i}\n" for i in range(20)}, **{f"docs/d{i}.md": "x\n" for i in range(9)})
    archive2, pristine2, _r2, _b2, _t2 = _archive(tmp_path / "two", changes=at_cap)
    rc, js = _run(archive2, "--pristine", str(pristine2), "--cla-file", _cla(tmp_path))
    assert rc == 0 and _v(js, "R5") == "GREEN"


def test_a_money_change_without_the_federation_suite_is_refused(tmp_path):
    archive, pristine, _r, _b, _t = _archive(tmp_path, changes={"teg/teg_integration.py": "fee = 2\n"})
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path))
    assert rc == 2 and _v(js, "R12") == "RED" and "require the federation suite too" in _s(js, "R12")


def test_an_invariant_tool_that_is_not_pass_is_refused(tmp_path):
    # red on the release and red on the change: no NEW red (R4 stays GREEN), and still not acceptable for money (R12)
    fed = {"base": {"f1": "pass", "supply_delta_check": "fail"}, "after": {"f1": "pass", "supply_delta_check": "fail"}}
    archive, pristine, _r, _t = _build(tmp_path, {"teg/teg_integration.py": "fee = 2\n"}, {FLOW: {"base": BASE, "after": AFTER}, FED: fed})
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path))
    assert rc == 2 and _v(js, "R4") == "GREEN" and _v(js, "R12") == "RED" and "supply_delta_check" in _s(js, "R12")
    # none in the report: not measured, said as such
    fed = {"base": {"f1": "pass"}, "after": {"f1": "pass"}}
    archive, pristine, _r, _t = _build(tmp_path / "two", {"teg/teg_integration.py": "fee = 2\n"}, {FLOW: {"base": BASE, "after": AFTER}, FED: fed})
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path))
    assert rc == 0 and _v(js, "R12") == "NOT MEASURED" and "no invariant tool" in _s(js, "R12")


def test_the_contracts_area_is_named_and_takes_the_tight_cap(tmp_path):
    archive, pristine, _r, _b, _t = _archive(tmp_path, changes={CONTRACTS_FILE: "def accept():\n    return 2\n"})
    rc, js = _run(archive, "--pristine", str(pristine), "--cla-file", _cla(tmp_path))
    areas = {a["area"] for a in js["facts"]["diff"]["areas"]}
    assert "contracts" in areas and js["facts"]["diff"]["caps"]["cap_files"] == 12
    assert rc == 2 and _v(js, "R12") == "RED" and "contracts" in _s(js, "R12")
