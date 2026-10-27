"""§MONEY-M2 — the knob table must describe the code, not a wish.

A config file whose names nothing reads is worse than no config file: it looks
like the money knobs live in one place while the real amounts sit somewhere
else. Two gates hold that line:

  1. PARITY  — every name in scripts/network_profile_knobs.py is read somewhere
               in the source trees.
  2. LITERALS — the amounts M2 moved out of the code have not crept back.

Both scan the tree as TEXT deliberately: the point is that no path, however
built, still carries the literal.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re

import pytest

def _find_repo() -> pathlib.Path | None:
    """Walk up looking for the stack root.

    Never index parents[] blind: CI mounts this suite at /w/tests, which has
    fewer parents than the repo layout, and an IndexError at import time takes
    the whole file out of collection — a suite that vanishes reads as green.
    """
    here = pathlib.Path(__file__).resolve()
    for cand in here.parents:
        if (cand / "scripts" / "network_profile_knobs.py").is_file():
            return cand
    return None


def _find_stack_root():
    """The directory that holds AgentVault/ and agentvault-event-store/."""
    for cand in pathlib.Path(__file__).resolve().parents:
        if (cand / "AgentVault" / "agentvault_registry" / "src").is_dir():
            return cand
    return None


REPO = _find_repo()
KNOB_TABLE = (REPO / "scripts" / "network_profile_knobs.py") if REPO else pathlib.Path("/nonexistent")

# Source LAYOUTS, most specific first. Exactly ONE is scanned: unioning them
# would mix the source under test with whatever an image happens to carry, and
# the absence gates would then report the image's old literals as a regression
# in code that no longer has them (measured 2026-09-04 — this is not theory).
_STACK = _find_stack_root()
_LAYOUTS = []
if _STACK:
    _LAYOUTS.append([
        _STACK / "AgentVault" / "agentvault_registry" / "src",
        _STACK / "AgentVault" / "agentvault_teg_layer_mvp" / "src",
        _STACK / "agentvault-event-store" / "src",
    ])
# CI mounts the three component trees under /w with these names (ci.yml).
_LAYOUTS.append([pathlib.Path("/w/src"), pathlib.Path("/w/teg_src"), pathlib.Path("/w/es_src")])
_LAYOUTS.append([pathlib.Path("/app/src")])  # running inside the image itself

_CANDIDATE_TREES = [t for layout in _LAYOUTS for t in layout]
TREES = next((([t for t in layout if t.is_dir()]) for layout in _LAYOUTS
              if any(t.is_dir() for t in layout)), [])

# A knob is read by exactly one component, and a run may not have that
# component's tree mounted. Asserting over the union would report a TEG knob as
# unread whenever only the registry is present — a red that says nothing about
# the code. So parity is checked PER SCOPE, and scopes with no tree are reported
# as NOT MEASURED rather than passed or failed.
# Each scope, and the path fragments that identify its tree in either layout
# (repo checkout, or the CI mounts named in ci.yml).
_SCOPE_MARKERS = {
    "registry": ("agentvault_registry", "/w/src", "/app/src"),
    "provisioner": ("agentvault_registry", "/w/src", "/app/src"),
    "ops": ("agentvault_registry", "/w/src", "/app/src"),
    "teg": ("agentvault_teg_layer_mvp", "/w/teg_src"),
    "es": ("agentvault-event-store", "/w/es_src"),
}


def _tree_for_scope(scope: str):
    for marker in _SCOPE_MARKERS.get(scope, ("agentvault_registry",)):
        for t in TREES:
            if marker in str(t):
                return t
    return None


def _load_knobs():
    spec = importlib.util.spec_from_file_location("network_profile_knobs", KNOB_TABLE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.KNOBS


MIN_FILES = 200  # the registry package alone is far above this


def _source_text() -> tuple[str, int]:
    parts, n = [], 0
    for tree in TREES:
        for p in tree.rglob("*.py"):
            # node_modules: a checkout with the FE's dependencies installed carries
            # third-party python there, which is neither a reader nor a literal of ours
            if ".bak" in p.name or "node_modules" in p.parts:
                continue
            try:
                parts.append(p.read_text(encoding="utf-8", errors="ignore"))
                n += 1
            except OSError:
                pass
    return "\n".join(parts), n


@pytest.fixture(scope="module")
def source() -> str:
    """The concatenated source, or a loud skip.

    An empty scan would make every absence-gate below pass vacuously — the
    all()-over-empty trap in a config costume. So the population is asserted
    before any gate reads it.
    """
    text, n = _source_text()
    if n == 0:
        pytest.skip(f"no source tree found to scan (looked in {_CANDIDATE_TREES}) — NOT MEASURED")
    assert n >= MIN_FILES, (
        f"only {n} python files were scanned from {TREES}; the absence gates below "
        f"would pass by not looking. Fix the mount before trusting this suite."
    )
    return text


def _scope_text(tree: pathlib.Path) -> str:
    parts = []
    for p in tree.rglob("*.py"):
        if ".bak" in p.name or "node_modules" in p.parts:
            continue
        try:
            parts.append(p.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            pass
    return "\n".join(parts)


@pytest.mark.skipif(not KNOB_TABLE.is_file(), reason="knob table not in this checkout")
def test_every_knob_is_read_somewhere(source):
    """A knob nobody reads is a lie in a config file."""
    cache, missing, unmeasured = {}, [], []
    for k in _load_knobs():
        tree = _tree_for_scope(k["scope"])
        if tree is None:
            unmeasured.append(f"{k['name']}({k['scope']})")
            continue
        if tree not in cache:
            cache[tree] = _scope_text(tree)
        if k["name"] not in cache[tree]:
            missing.append(f"{k['name']} (scope {k['scope']}, expected in {tree})")
    if unmeasured:
        # loud, not silent: say what this run could not see
        print(f"\nNOT MEASURED (that scope's tree is not mounted here): {unmeasured}")
    assert not missing, (
        "these profile knobs are read nowhere in their component's tree — either "
        f"wire them or drop them from the table: {missing}"
    )


@pytest.mark.skipif(not KNOB_TABLE.is_file(), reason="knob table not in this checkout")
def test_the_table_is_well_formed():
    for k in _load_knobs():
        assert k["name"] and k["name"].isupper(), k
        assert k["scope"] in {"registry", "teg", "es", "provisioner", "ops"}, k
        assert k["reader"], f"{k['name']} has no reader file:line — it cannot be audited"
        assert k["note"], f"{k['name']} has no note — a number with no reason is a magic number"


# ── the literals M2 moved out must not come back ────────────────────────────

RETIRED_LITERALS = [
    # (a regex, where it used to live, the knob that owns it now)
    (r"MIN_STAKE_AMOUNT\s*=\s*Decimal\(", "routers/staking_enhanced.py", "STAKING_MIN_STAKE_AMOUNT"),
    (r"if val > Decimal\('10000000'\)", "routers/teg_integration.py", "TEG_TRANSFER_MAX_AVT"),
    (r"if val > Decimal\('100000000'\)", "routers/teg_integration.py", "TEG_MINT_MAX_AVT"),
    (r"if amount > Decimal\(\"100000\"\)", "routers/funding_requests.py", "FUNDING_REQUEST_MAX_AVT"),
    (r'GENESIS_GRANT_AMOUNT=5000\.0', "services/cloud_provisioner.py", "GENESIS_GRANT_AMOUNT"),
]


@pytest.mark.parametrize("pattern,where,knob", RETIRED_LITERALS)
def test_a_retired_literal_has_not_come_back(source, pattern, where, knob):
    hits = re.findall(pattern, source)
    assert not hits, (
        f"{where} carries the literal M2 moved into the profile knob {knob} "
        f"({len(hits)} occurrence(s)). Read it through money_knob() instead."
    )
