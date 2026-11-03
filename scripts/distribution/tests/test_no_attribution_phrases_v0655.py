"""V0655 (aw), order gwo_22ba4784e0615b4537aefa21: no comment or docstring in the stack paths the OSS export carries says
that a choice was the maintainer's own, and the stack keeps no string that does (the AgentVault repository keeps a few,
listed in its agentvault_registry/tests/attribution_kept.json).

oss_export.py's G15 reads the whole export, AgentVault included, against that list. This test reads the stack's half on
every push with the export's own predicates: what the copy ships (STACK_SHIP less NEVER and the screenshots, as
copy_tree decides) and what G15 counts (G15_PHRASE). CI does not run --selftest, so G15 is also driven through gate() on
a planted tree here. The phrases are built from parts, so this file holds none of them.
"""
import importlib.util
import json
import os
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(HERE, "..")
ROOT = Path(os.path.abspath(os.path.join(DIST, "..", "..")))
HIS = "h" + "is"


def _load():
    spec = importlib.util.spec_from_file_location("oss_export_attribution", os.path.join(DIST, "oss_export.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


X = _load()


def _shipped():
    """(path, its name in the export) for every stack file the export's copy takes"""
    for item in X.STACK_SHIP:
        src = ROOT / item
        if src.is_file():
            yield src, item
            continue
        for dirpath, dirnames, filenames in os.walk(src):
            rel_dir = str(Path(dirpath).relative_to(ROOT))
            dirnames[:] = [d for d in dirnames if d not in X.SCREENSHOT_DIRS
                           and (not X.matches(f"{rel_dir}/{d}", X.NEVER) or X.matches(f"{rel_dir}/{d}", X.ALLOW_EVEN_IF_NEVER))]
            for fn in filenames:
                rel = f"{rel_dir}/{fn}"
                if (X.matches(rel, X.NEVER) and not X.matches(rel, X.ALLOW_EVEN_IF_NEVER)) or X.is_screenshot(rel):
                    continue
                yield Path(dirpath) / fn, rel


def test_the_stack_half_of_the_export_holds_no_phrase():
    read, hits = 0, []
    for p, rel in _shipped():
        try:
            if p.stat().st_size > X.TEXT_MAX:
                continue
            data = p.read_bytes()
        except OSError:
            continue
        read += 1
        lines = [data.count(b"\n", 0, m.start()) + 1 for m in X.G15_PHRASE.finditer(data)]
        if lines:
            hits.append(f"{rel}:{lines}")
    # V0654's export carried 709 stack files
    assert read >= 600, f"read {read} files of the stack's export set, expected at least 600: the check measured too little"
    assert not hits, ("a comment or docstring says whose choice it was; say what the code does and why (the stack keeps no "
                      "such string):\n  " + "\n  ".join(hits))


def test_g15_through_the_gate():
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        g15 = lambda: X.gate(t, lambda s: None, live=[])["G15_attribution"]
        kept = t / X.G15_KEPT
        kept.parent.mkdir(parents=True)
        kept.write_text(json.dumps({"kept": {"agentvault_registry/x/reasons.py": 1}}))
        reasons = t / "AgentVault/agentvault_registry/x/reasons.py"
        reasons.parent.mkdir(parents=True)
        reasons.write_text(f"REASON = 'skipped: {HIS} decision, pinned by a test'\n")
        assert g15() == [], "a kept string within its count must pass"
        reasons.write_text(f"REASON = 'skipped: {HIS} decision, pinned by a test'   # {HIS} call\n")
        assert g15() == ["AgentVault/agentvault_registry/x/reasons.py (2, the list allows 1)"]
        tool = t / "scripts/distribution/tool.py"
        tool.parent.mkdir(parents=True)
        tool.write_text(f'"""Runs the kit (on {HIS} word)."""\n')
        assert "scripts/distribution/tool.py (1, the list allows 0)" in g15()
        kept.unlink()
        assert len(g15()) == 2, "an export without the list allows none"


def test_the_phrases_and_their_neighbours():
    count = lambda text: len(X.G15_PHRASE.findall(text.encode()))
    assert count(f"# ({HIS} word 2026-10-27)") == 1
    assert count(f"# on {HIS} word") == 1
    assert count(f"{HIS.upper()} WORDS, {HIS} decision, {HIS} call and {HIS} order") == 4
    assert count(f"# t{HIS} word, {HIS} wording, {HIS} orders, the maintainer decided") == 0
