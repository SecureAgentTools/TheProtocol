#!/usr/bin/env python3
"""Alembic graph gate (§CIWIDE 2026-08-05).

Encodes the §NOTIFV2 incident: alembic_version.version_num is VARCHAR(32) —
a 33-char revision id crash-loops the node at upgrade time (the transactional
migration rolls back clean, the boot loop doesn't). Also refuses duplicate
revision ids and split heads: a second head silently forks the migration
chain and only surfaces on the next node boot.
"""
import pathlib
import re
import sys

TREES = {
    "registry": "agentvault_registry/alembic/versions",
    "teg": "agentvault_teg_layer_mvp/alembic/versions",
}

fail = 0
for label, vdir in TREES.items():
    revs, downs, problems = {}, {}, []
    for p in sorted(pathlib.Path(vdir).glob("*.py")):
        t = p.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^revision(?::\s*str)?\s*=\s*['\"]([^'\"]+)['\"]", t, re.M)
        d = re.search(r"^down_revision(?::[^=]*)?\s*=\s*(.+)$", t, re.M)
        if not m:
            problems.append(f"{p.name}: no revision id")
            continue
        rid = m.group(1)
        if len(rid) > 32:
            problems.append(f"{p.name}: id is {len(rid)} chars (>32): {rid}")
        if rid in revs:
            problems.append(f"{p.name}: duplicate id {rid} (also in {revs[rid]})")
        revs[rid] = p.name
        downs[rid] = d.group(1).strip() if d else "None"
    referenced = set()
    for dv in downs.values():
        referenced.update(re.findall(r"['\"]([^'\"]+)['\"]", dv))
    heads = sorted(r for r in revs if r not in referenced)
    print(f"{label}: {len(revs)} revisions, heads={len(heads)}, problems={len(problems)}")
    for pr in problems:
        print(f"  ! {pr}")
    if len(heads) != 1:
        print(f"  ! expected exactly 1 head, got {heads}")
        fail = 1
    if problems:
        fail = 1

sys.exit(fail)
