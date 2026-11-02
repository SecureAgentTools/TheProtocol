"""V0653 (an), item 2 (session-lead's choice, the sessions' room seq 769): every key the provisioner claims a child inherits
from its parent frame is a key the parent REGISTRY reads, because that is where the provisioner reads it.

services/cloud_provisioner._inherit_parent_posture writes each PARENT_POSTURE_KEYS key from the registry process's own
environment (the parent frame's registry). A key only another service reads (the TEG's) is never in that environment,
so listing it claimed an inheritance that never happened: TEG_ONBOARDING_MINT_ENABLED and TEG_STAKING_REWARD_CYCLE_ENABLED
sat in the list from §BATCH5 until V0653 and passed on nothing (both are retired money surfaces, both default off in the
TEG; a child's TEG takes that default). This names every claim and the file of the registry that reads it, and fails
if a key the registry does not read is ever listed again.

"The registry reads it" = the key's exact name is a string constant in the registry's own code (a getenv, a knob, a
surface switch, a catalog row) or a field of its Settings, outside the provisioner itself, the tests and the tester
(api_tests names flags it measures, which is not reading them). BASE: on a5ef48ddd (V0652) the two TEG keys are listed.
"""
from __future__ import annotations

import ast
import pathlib

from agentvault_registry.services import cloud_provisioner as cp

REG = pathlib.Path(cp.__file__).resolve().parents[1]           # src/agentvault_registry
TEG_ONLY = ("TEG_ONBOARDING_MINT_ENABLED", "TEG_STAKING_REWARD_CYCLE_ENABLED")


def registry_reads() -> dict:
    """Every env-shaped name the registry's own code names exactly, with the first file that names it."""
    out: dict = {}
    for f in sorted(REG.rglob("*.py")):
        rel = f.relative_to(REG).as_posix()
        if rel == "services/cloud_provisioner.py" or rel.startswith(("api_tests/", "tests/")):
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.isupper() and "_" in n.value:
                out.setdefault(n.value, rel)
            elif isinstance(n, ast.ClassDef) and any("BaseSettings" in ast.unparse(b) for b in n.bases):
                for st in n.body:
                    if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                        out.setdefault(st.target.id.upper(), rel)
    return out


def test_every_inherited_key_is_read_where_the_provisioner_reads_it():
    reads = registry_reads()
    sides = {k: reads.get(k) for k in cp.PARENT_POSTURE_KEYS}
    unread = sorted(k for k, where in sides.items() if where is None)
    assert unread == [], (f"listed as inherited, but the parent registry never reads (so never holds) them: {unread}. "
                          "A key another service reads is that service's posture: drop it here, or read it there.")
    assert len(sides) == len(set(cp.PARENT_POSTURE_KEYS)) >= 39


def test_the_teg_keys_are_not_claimed_any_more():
    assert not set(TEG_ONLY) & set(cp.PARENT_POSTURE_KEYS)


def test_control_the_reader_tells_the_two_sides_apart():
    reads = registry_reads()
    assert reads.get("REPUTATION_BOND_MODE") and reads.get("COMMONS_MAX_BUDGET") and reads.get("ARENA_BETTING_ENABLED")
    for k in TEG_ONLY:                      # a TEG key, named in a registry comment or docstring only, is not read here
        assert k not in reads, k


def test_control_a_teg_key_put_back_would_fail(monkeypatch):
    monkeypatch.setattr(cp, "PARENT_POSTURE_KEYS", tuple(cp.PARENT_POSTURE_KEYS) + ("TEG_ONBOARDING_MINT_ENABLED",))
    reads = registry_reads()
    assert [k for k in cp.PARENT_POSTURE_KEYS if k not in reads] == ["TEG_ONBOARDING_MINT_ENABLED"]
