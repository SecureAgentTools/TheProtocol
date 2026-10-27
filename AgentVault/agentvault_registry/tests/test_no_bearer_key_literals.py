"""§RELEASE-P3 (2026-09-05) — no source or script may carry a bearer-key LITERAL as a fallback.
Measured: scripts/eigentrust_simulation.py held frame-a's live TEG admin key in `admin_key = env or "<64 hex>"`,
in a tracked file, for months; the frame-a TEG still accepted it (ADMIN_API_KEY by shape). The release cut
is a fresh-history export, so the tree itself must be clean, not just the image (which excludes scripts/)."""
import os
import pathlib
import re

import pytest

ROOT = pathlib.Path(os.environ.get("KEYLIT_ROOT", str(pathlib.Path(__file__).resolve().parent.parent)))
SCAN_DIRS = ("src", "scripts")
# a 64-hex or 40+ char token used as an `or "<literal>"` fallback, or assigned to a *key/secret/token name
FALLBACK = re.compile(r'\bor\s+["\'][0-9a-fA-F]{40,}["\']')
ASSIGN = re.compile(r'(?i)\b[a-z_]*(api_key|admin_key|secret|token)[a-z_]*\s*=\s*["\'][0-9a-fA-F]{40,}["\']')


def _py_files():
    for d in SCAN_DIRS:
        base = ROOT / d
        if base.is_dir():
            yield from base.rglob("*.py")


def test_no_hex_bearer_literal_fallback_in_tree():
    hits = []
    for f in _py_files():
        if "/tests/" in str(f) or f.name.startswith("test_"):
            continue
        for i, ln in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if FALLBACK.search(ln) or ASSIGN.search(ln):
                hits.append(f"{f.relative_to(ROOT)}:{i}")
    assert not hits, f"bearer-key literal(s) in the tree: {hits}"


def _scripts_file(name):
    """Locate a repo `scripts/` file, or None where it is not present.

    §EVTYPES8 2026-09-06: `scripts/` is NOT shipped in the registry image (measured:
    /app/scripts is absent from both the tier's image and a fresh build), so a test
    that reads it unguarded can only ever pass against a repo checkout. This one and
    its twin in test_enforcement_propagation.py were the ONLY two of 2331 that failed
    in-image, and they failed identically on the pre-existing image — noise that makes
    an in-image run unusable as a gate, because a reader cannot tell two permanent reds
    from a real regression. Every other scripts/-reading test in this suite already
    skips loudly; these two now do too. NOT a product defect, and never was.
    """
    for cand in (ROOT / "scripts" / name, pathlib.Path("/w/scripts") / name):
        if cand.is_file():
            return cand
    return None


def test_the_sim_script_reads_the_key_from_env_only():
    f = _scripts_file("eigentrust_simulation.py")
    if f is None:
        pytest.skip("scripts/ not shipped in the image — NOT MEASURED")
    s = f.read_text(encoding="utf-8")
    assert 'os.environ.get("TEG_ADMIN_API_KEY_A", "")' in s
    assert "auto-mint leg disabled" in s, "an unset key must skip loudly, not fall back"
