"""V0664 "Migrate a system" (session-lead, room seq 3873): check_migration_pins.py pins the registry's copies of the SDK's
migration constants equal. Offline, on small trees written here (the real SDK and AgentVault trees are not in this
checkout): each side written in its own style, so the check is about the VALUES; a control per pin that must fail.
"""
import importlib.util
import pathlib
import subprocess

HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("check_migration_pins", HERE.parent / "check_migration_pins.py")
cmp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cmp)

SCHEMA_PY = '''"""M3's kit schema (a fixture)."""
from __future__ import annotations
import json
import re
from typing import Any, Dict
from .elsewhere import something   # never imported: the check reads the file

SCHEMA_ID = "theprotocol.migration/v1"
PATH_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$"
KIT_CAPS = {"max_files": 64, "max_file_bytes": 256 * 1024, "max_total_bytes": 2 * 1024 * 1024,
            "path_pattern": PATH_PATTERN, "encoding": "utf-8"}
KINDS = ["sql", "file", "rest"]
_SIDE = {"type": "object", "required": ["kind"], "properties": {"kind": {"enum": KINDS}}}
MANIFEST_SCHEMA: Dict[str, Any] = {
    "$id": SCHEMA_ID, "type": "object", "required": ["schema", "rollback"],
    "properties": {"schema": {"const": SCHEMA_ID}, "from": _SIDE, "to": _SIDE, "rollback": {"enum": ["auto", "manual"]}},
}


def canonical(doc: Any) -> bytes:
    """The SDK's words about it."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
'''

SPEC_PY = '''import re
from .plugins import load
REF = re.compile(r"^(env|file):(.+)$")
SECRET_KEY = re.compile(r"(?:^|[_-])(?:secret|password|token)s?$",
                        re.I)
'''

REGISTRY_PY = '''"""The registry's copy (a fixture), written differently on purpose."""
import json
import re

MAX_FILES, MAX_BYTES = 64, 256 * 1024
KIT_CAPS = {"max_files": MAX_FILES, "max_file_bytes": MAX_BYTES, "max_total_bytes": 2097152,
            "path_pattern": r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$", "encoding": "utf-8"}
PATH_PATTERN = KIT_CAPS["path_pattern"]
SECRET_KEY = re.compile(r"(?:^|[_-])(?:secret|password|token)s?$", re.IGNORECASE)
REF = re.compile(r"^(env|file):(.+)$")
_KIND = {"enum": ["sql", "file", "rest"]}
_BASE = {"type": "object", "required": ["kind"]}
MANIFEST_SCHEMA = {
    "$id": "theprotocol.migration/v1", "type": "object", "required": ["schema", "rollback"],
    "properties": {"schema": {"const": "theprotocol.migration/v1"},
                   "from": {**_BASE, "properties": {"kind": _KIND}}, "to": {**_BASE, "properties": {"kind": _KIND}},
                   "rollback": {"enum": ["auto", "manual"]}},
}


def canonical(doc):
    """The registry's own words: a docstring is prose, not the rule."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
'''


def tree(tmp_path, *, schema=SCHEMA_PY, spec=SPEC_PY, registry=REGISTRY_PY):
    stack, av = tmp_path / "stack", tmp_path / "AgentVault"
    for root, rel, text in ((stack, cmp.SDK_SCHEMA, schema), (stack, cmp.SDK_SPEC, spec), (av, cmp.REGISTRY, registry)):
        if text is not None:
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
    return stack, av


def run(stack, av, *extra):
    lines = []
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmp.main(["--stack-dir", str(stack), "--agentvault-dir", str(av), *extra])
    lines = buf.getvalue().splitlines()
    return rc, lines


def _row(lines, pin):
    return next(l for l in lines if l.split()[2:3] == [pin] or l.split()[2:3] == [pin + ":"])


def test_equal_values_written_two_ways_pass(tmp_path):
    rc, lines = run(*tree(tmp_path))
    assert rc == 0, lines
    assert lines[-1] == "MIGRATION PINS: 6 of 6 equal, verdict equal"


def test_a_nested_schema_difference_is_named_by_its_path(tmp_path):
    rc, lines = run(*tree(tmp_path, registry=REGISTRY_PY.replace('"rollback": {"enum": ["auto", "manual"]}',
                                                                  '"rollback": {"enum": ["auto"]}')))
    assert rc == 1
    row = _row(lines, "MANIFEST_SCHEMA")
    assert "DIFFERS" in row and "properties.rollback.enum(length)" in row, row


def test_a_required_key_the_registry_lacks_is_a_difference(tmp_path):
    rc, lines = run(*tree(tmp_path, registry=REGISTRY_PY.replace('"required": ["schema", "rollback"]',
                                                                  '"required": ["schema", "reconcile"]')))
    assert rc == 1 and "required[1]" in _row(lines, "MANIFEST_SCHEMA")


def test_a_cap_and_a_regex_flag_are_pinned(tmp_path):
    rc, lines = run(*tree(tmp_path, registry=REGISTRY_PY.replace("2097152", "2097153")
                          .replace(", re.IGNORECASE)", ")")))
    assert rc == 1
    assert "max_total_bytes" in _row(lines, "KIT_CAPS") and "flags" in _row(lines, "SECRET_KEY")
    assert "EQUAL" in _row(lines, "REF")


def test_the_canonical_json_is_pinned_but_not_its_docstring(tmp_path):
    rc, lines = run(*tree(tmp_path, registry=REGISTRY_PY.replace("ensure_ascii=False", "ensure_ascii=True")))
    assert rc == 1 and "DIFFERS" in _row(lines, "canonical")
    assert "EQUAL" in _row(run(*tree(tmp_path / "b"))[1], "canonical")


def test_a_missing_name_or_file_is_never_a_pass(tmp_path):
    no_caps = REGISTRY_PY.replace("PATH_PATTERN = KIT_CAPS[\"path_pattern\"]", "PATH_PATTERN = '" +
                                  r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$" + "'")
    no_caps = no_caps[:no_caps.index("KIT_CAPS = ")] + no_caps[no_caps.index("PATH_PATTERN = "):]
    rc, lines = run(*tree(tmp_path / "a", registry=no_caps))
    assert rc == 2 and "MISSING" in _row(lines, "KIT_CAPS") and "EQUAL" in _row(lines, "PATH_PATTERN")
    rc, lines = run(*tree(tmp_path / "b", schema=None))
    assert rc == 2 and "no file" in _row(lines, "MANIFEST_SCHEMA") and "EQUAL" in _row(lines, "REF")
    rc, lines = run(*tree(tmp_path / "c", registry=None))
    assert rc == 2 and "the registry file" in lines[0]


def test_a_value_the_evaluator_cannot_read_is_missing_not_equal(tmp_path):
    rc, lines = run(*tree(tmp_path, registry=REGISTRY_PY.replace('PATH_PATTERN = KIT_CAPS["path_pattern"]',
                                                                  "PATH_PATTERN = make_pattern()")))
    assert rc == 2 and "not a value this check can read" in _row(lines, "PATH_PATTERN")


def test_a_git_ref_is_read_from_the_repository_not_the_tree(tmp_path):
    stack, av = tree(tmp_path)
    git = ["git", "-c", "user.email=t@example.org", "-c", "user.name=t", "-c", "commit.gpgsign=false"]
    for root in (stack, av):
        subprocess.run(git + ["init", "-q", str(root)], check=True)
        subprocess.run(git + ["-C", str(root), "add", "-A"], check=True)
        subprocess.run(git + ["-C", str(root), "commit", "-q", "-m", "fixture"], check=True)
    (av / cmp.REGISTRY).write_text(REGISTRY_PY.replace("2097152", "1"))     # the working tree differs, the ref does not
    assert run(stack, av)[0] == 1
    rc, lines = run(stack, av, "--sdk-ref", "HEAD", "--agentvault-ref", "HEAD")
    assert rc == 0, lines
    rc, lines = run(stack, av, "--agentvault-ref", "no-such-ref")
    assert rc == 2 and "no-such-ref" in lines[0]


def test_json_output_carries_every_pin(tmp_path):
    import contextlib
    import io
    import json
    stack, av = tree(tmp_path)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmp.main(["--stack-dir", str(stack), "--agentvault-dir", str(av), "--json"])
    out = json.loads(buf.getvalue())
    assert rc == 0 and out["verdict"] == "equal" and [r["pin"] for r in out["rows"]] == [p[0] for p in cmp.PINS]
