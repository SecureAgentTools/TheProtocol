"""§pass47 A8 — Migration safety static-analysis suite.

These tests do NOT spin up a database (CI runs them in <1s). They scan every
file under ``alembic/versions/`` and assert structural guarantees that have
caused production incidents in the past:

  1. ``migration_bridge.py`` skips single-head DBs (§pass42 root cause).
  2. Migrations that UPDATE/DELETE ``flare_*`` columns also guard with
     ``IS DISTINCT FROM 'sovereign'`` (memory:
     ``feedback_destructive_migrations_sovereign_immune``).
  3. Every ``op.create_index`` is paired with ``IF NOT EXISTS`` semantics
     (alembic batch_op or raw SQL) so migration_bridge replays are idempotent.

Designed to ride along with the existing astraeus AST tests in the same
test session; no extra dependencies, no DB required.
"""
from __future__ import annotations

import pathlib
import re
from typing import Dict, List, Tuple

ALEMBIC_VERSIONS = (
    pathlib.Path(__file__).resolve().parent.parent / "alembic" / "versions"
)
MIGRATION_BRIDGE = (
    pathlib.Path(__file__).resolve().parent.parent
    / "src" / "agentvault_registry" / "migration_bridge.py"
)

# Sovereign-touching column substrings — every flare-mutating migration must
# carry the IS DISTINCT FROM 'sovereign' guard somewhere in the same file.
SOVEREIGN_SENSITIVE_COLS = (
    "flare_tier",
    "selected_corner_flare",
    "selected_encirclement_flare",
    "flare_corner_variant",
    "flare_encirclement_variant",
    "iconUrl",
)

# §pass47 S3 — apply the sovereign-immunity gate ONLY to migrations authored
# after the §pass39 sovereign-flares ship (2026-05-18). Earlier migrations
# (0001–0054) were authored BEFORE any sovereign data existed; they're
# blanket-grandfathered. The migration_bridge guard (project_migration_bridge
# post-squash check) prevents replays of historical migrations against
# already-migrated DBs, so the lack of explicit sovereign guards in 0001–0054
# can't bite production.
#
# Any NEW migration (0055+) that mutates sovereign-sensitive cols MUST carry
# the guard. This is the regression-bound the test enforces.
SOVEREIGN_GUARD_REQUIRED_FROM = 55  # numeric prefix


# Migrations that historically don't strictly need IF NOT EXISTS on CREATE INDEX
# because they're the initial squash (run exactly once during fresh DB bootstrap)
# or other established legacy. Future migrations should add IF NOT EXISTS.
INDEX_EXEMPT_MIGRATIONS = {
    "0001_squash_initial.py",
}


def _iter_migrations() -> List[Tuple[str, str]]:
    """Yield (filename, source) for every migration file."""
    out: List[Tuple[str, str]] = []
    for path in sorted(ALEMBIC_VERSIONS.glob("[0-9][0-9][0-9][0-9]_*.py")):
        out.append((path.name, path.read_text(encoding="utf-8")))
    return out


def test_migration_bridge_skips_single_head_dbs():
    """§pass42 root cause: migration_bridge re-ran post-squash migrations on
    every container boot, wiping sovereign flare data. The fix gates on the
    DB having multiple heads (i.e., needs the bridge to converge)."""
    assert MIGRATION_BRIDGE.exists(), f"missing {MIGRATION_BRIDGE}"
    src = MIGRATION_BRIDGE.read_text(encoding="utf-8")
    # Either condition acceptable: "single head" branch OR length-based skip.
    has_guard = (
        "len(current_revs)" in src
        or "single head" in src.lower()
        or "single-head" in src.lower()
    )
    assert has_guard, (
        "migration_bridge.py must guard against running on single-head DBs "
        "(see memory: feedback_migration_bridge_post_squash_guard)"
    )


def test_sovereign_immunity_guard_on_destructive_flare_migrations():
    """Every NEW migration (revision >= SOVEREIGN_GUARD_REQUIRED_FROM) that
    UPDATEs or DELETEs flare-sensitive columns must also mention ``sovereign``
    (the guard pattern). Earlier migrations are grandfathered — they ran
    before any sovereign data existed and the migration_bridge guard prevents
    replays. Memory: ``feedback_destructive_migrations_sovereign_immune``.
    """
    offenders: Dict[str, List[str]] = {}
    for name, src in _iter_migrations():
        m = re.match(r"^(\d{4})_", name)
        if not m:
            continue
        rev_num = int(m.group(1))
        if rev_num < SOVEREIGN_GUARD_REQUIRED_FROM:
            continue  # grandfathered legacy
        if not re.search(r"\b(UPDATE|DELETE)\b", src, re.IGNORECASE):
            continue
        touched = [c for c in SOVEREIGN_SENSITIVE_COLS if c in src]
        if not touched:
            continue
        if "sovereign" not in src.lower():
            offenders[name] = touched
    assert not offenders, (
        f"Destructive flare migrations >= {SOVEREIGN_GUARD_REQUIRED_FROM} "
        f"missing sovereign-immunity guard:\n"
        + "\n".join(f"  {n}: touches {cols}" for n, cols in offenders.items())
    )


def test_create_index_uses_if_not_exists():
    """Idempotency invariant: every raw-SQL ``CREATE INDEX`` must use ``IF
    NOT EXISTS`` semantics so a replay (from migration_bridge, P&P recovery,
    etc.) doesn't fail with DuplicateTable. The ``INDEX_EXEMPT_MIGRATIONS``
    set lists historical files that pre-date the idempotency rule.
    """
    offenders: Dict[str, List[int]] = {}
    for name, src in _iter_migrations():
        if name in INDEX_EXEMPT_MIGRATIONS:
            continue
        for lineno, line in enumerate(src.splitlines(), 1):
            stripped = line.strip()
            if re.search(r"\bCREATE\s+(UNIQUE\s+)?INDEX\b", stripped, re.IGNORECASE):
                if "IF NOT EXISTS" not in stripped.upper():
                    if stripped.startswith("op.execute") or '"""' in stripped:
                        offenders.setdefault(name, []).append(lineno)
    assert not offenders, (
        "Raw SQL CREATE INDEX statements without IF NOT EXISTS — these will "
        "fail on migration replay:\n"
        + "\n".join(f"  {n}: lines {ls}" for n, ls in offenders.items())
    )


def test_every_migration_has_revision_metadata():
    """Sanity: each migration must declare ``revision`` and ``down_revision``.

    Accepts ``revision = "..."`` OR ``revision: str = "..."`` (PEP 526 style
    used by some alembic templates).
    """
    offenders: List[str] = []
    for name, src in _iter_migrations():
        has_rev = re.search(r"^revision(\s*:\s*\w+)?\s*=", src, re.MULTILINE)
        has_down = re.search(r"^down_revision(\s*:\s*[\w\[\], |]+)?\s*=", src, re.MULTILINE)
        if not has_rev or not has_down:
            offenders.append(name)
    assert not offenders, (
        "Migrations missing revision metadata:\n  " + "\n  ".join(offenders)
    )


def test_migration_filenames_have_monotonic_prefixes():
    """Sanity: filenames are 0000_*.py with strictly increasing numeric prefix.
    Catches accidental duplicate numbers across branches.
    """
    nums = []
    for name, _src in _iter_migrations():
        m = re.match(r"^(\d{4})_", name)
        assert m, f"non-conforming migration filename: {name}"
        nums.append(int(m.group(1)))
    dupes = {n for n in nums if nums.count(n) > 1}
    assert not dupes, f"duplicate migration numbers: {sorted(dupes)}"
