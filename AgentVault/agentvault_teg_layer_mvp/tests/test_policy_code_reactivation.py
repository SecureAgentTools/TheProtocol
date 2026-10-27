"""§BATCH9 (2026-09-06) — eb's finding: deleteTegPolicy soft-deletes and never frees policy_code.

The TEG's create handler treated ANY row with the same code as a conflict, while the registry's list
defaults to active rows — so a deleted code looked free and the re-create answered 409 with nothing
visible. The pure planner decides: no row → create · deactivated row → reactivate in place ·
live row → conflict. Controls both ways. Runner style like its siblings."""
import os
import sys

sys.path.insert(0, "/app")
os.environ.setdefault("AVTP_SYSTEM_API_KEY", "ci-dummy-0123456789abcdef0123456789abcdef")
os.environ.setdefault("TEG_TOKEN_SIGNING_KEY", "ci-dummy-0123456789abcdef0123456789abcdef")
os.environ.setdefault("AUDITED_BALANCE_ENABLED", "false")
os.environ.setdefault("TEG_HOME_FRAME_GUARD_ENABLED", "false")

from src.teg_core_service.api.v1.endpoints_governance import plan_policy_create  # noqa: E402

CASES = [
    ("no row at all → create", None, "create"),
    ("a deactivated row → reactivate in place", False, "reactivate"),
    ("a live row → conflict (the 409 stays for real duplicates)", True, "conflict"),
]

passed = 0
for name, existing_is_active, want in CASES:
    got = plan_policy_create(existing_is_active)
    ok = got == want
    passed += ok
    print(f"{'PASS' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")
print(f"{passed}/{len(CASES)} passed")
sys.exit(0 if passed == len(CASES) else 1)
