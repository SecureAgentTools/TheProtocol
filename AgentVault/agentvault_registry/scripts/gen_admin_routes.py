#!/usr/bin/env python3
"""V0662: write (or check) the console's copy of the registry's admin route rule.

Run where the registry imports (a release image, or the test container), from agentvault_registry/:
    python scripts/gen_admin_routes.py --write     # writes src/.../services/api/adminRoutes.generated.json
    python scripts/gen_admin_routes.py --check     # exit 1 when the committed copy differs from the app
The app is imported, nothing is served, no database is touched. The rule: services/admin_route_rule.py.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", action="store_true")
    ap.add_argument("--out", type=Path, default=None, help="write here instead of the console's tree")
    a = ap.parse_args()
    from agentvault_registry.main import app
    from agentvault_registry.services import admin_route_rule as R
    rule = R.admin_route_rule(app)
    text = R.render(rule)
    target = a.out or R.FE_RULE_PATH
    if a.write:
        target.write_text(text, encoding="utf-8")
        admin = sum(1 for r in rule["routes"] if r[2])
        print(f"wrote {target}: {len(rule['routes'])} routes, {admin} need an admin flag")
        return 0
    same = R.load_committed(target) == rule
    print("the console's copy is the app's rule" if same else f"DIFFERS: run {Path(__file__).name} --write")
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
