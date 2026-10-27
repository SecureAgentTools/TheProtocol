"""§TESTBED P5 (2026-09-19): kit_provenance names the tree a build came from and whether it differs from the release."""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("kit_provenance", os.path.join(HERE, "..", "kit_provenance.py"))
kp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kp)


def _tree(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "build.sh").write_text("echo build\n")
    (tmp_path / "README.md").write_text("# kit\n")
    (tmp_path / "VERSION").write_text("1.0.0-beta.6\n")
    return tmp_path


def test_an_unchanged_release_is_not_modified(tmp_path):
    root = _tree(tmp_path)
    assert kp.write_manifest(str(root)) == 3
    info = kp.build_info(str(root), "1.0.0-beta.6")
    assert info["modified"] is False and info["changed_files"] == 0
    assert info["tree_digest"] == info["release_digest"]


def test_an_edit_and_an_added_file_are_counted_and_move_the_digest(tmp_path):
    root = _tree(tmp_path)
    kp.write_manifest(str(root))
    before = kp.build_info(str(root), "v")["tree_digest"]
    (root / "README.md").write_text("# kit, changed\n")
    (root / "scripts" / "new.py").write_text("x = 1\n")
    info = kp.build_info(str(root), "v")
    assert info["modified"] is True and info["changed_files"] == 2
    assert info["tree_digest"] != before and set(info["changed_sample"]) == {"README.md", "scripts/new.py"}


def test_build_leftovers_are_not_the_kits_content(tmp_path):
    root = _tree(tmp_path)
    kp.write_manifest(str(root))
    for d in ("node_modules", "dist", "__pycache__", ".git"):
        (root / d).mkdir()
        (root / d / "x").write_text("y")
    (root / "scripts" / "m.pyc").write_bytes(b"\x00")
    (root / "BUILD_INFO.json").write_text("{}")
    assert kp.build_info(str(root), "v")["modified"] is False


def test_a_tree_without_a_manifest_says_it_cannot_tell(tmp_path):
    info = kp.build_info(str(_tree(tmp_path)), "v")
    assert info["modified"] is None and info["release_digest"] is None and "KIT_FILES.sha256" in info["note"]
    assert len(info["tree_digest"]) == 64


def test_what_setup_writes_into_the_kit_is_not_a_change(tmp_path):
    """CB-016: operator-setup.sh and the generators write .env.operator (and the bundle generator pgbouncer.ini,
    userlist.txt, redis-users.acl) beside themselves in scripts/distribution. Counted as a change, a build after setup
    took the version tag only and the standalone compose kept running the previous :stable."""
    root = _tree(tmp_path)
    dist = root / "scripts" / "distribution"
    (dist / "nginx-templates").mkdir(parents=True)
    (dist / "nginx-templates" / "pgbouncer.ini").write_text("[databases]\n")
    kp.write_manifest(str(root))
    for name in (".env.operator", "pgbouncer.ini", "userlist.txt", "redis-users.acl"):
        (dist / name).write_text("SECRET=not-kit-content\n")
    assert kp.build_info(str(root), "v")["modified"] is False
    # the controls: the bundle's template of the same name IS kit content, and a secret file anywhere else stays a
    # change (frame-contribute packs it and frame-review refuses it)
    (dist / "nginx-templates" / "pgbouncer.ini").write_text("[databases]\nchanged\n")
    (root / ".env.operator").write_text("SECRET=x\n")
    info = kp.build_info(str(root), "v")
    assert info["modified"] is True
    assert info["changed_sample"] == [".env.operator", "scripts/distribution/nginx-templates/pgbouncer.ini"]
