"""Sandbox fixture credentials — env-backed, never baked into the image.

§SBROTATE 2026-08-08 (Commander: "rotate all sandbox admin creds … i dont want a
leak thru a admin login on sandbox").

Before this module, the passwords of `admin@test.sandbox` and
`tutorial-admin@theprotocol.cloud` were written as literals in
**18 source files**, which meant every one of the 18 registry images carried a
working sandbox admin login. Those accounts do not exist on the three prod
mainframes (verified: HTTP 401 on registry-a, frame-b and frame-c), so the blast
radius was the sandbox tier only — but a credential in an image that ships to
third parties is a credential you have already published.

There is deliberately **no secret default**. An unset variable yields an empty
password and the login fails loudly, which is the correct failure: a harness that
silently falls back to a known-bad password is how the literal survived this long.

Set on the sandbox registries only (compose `environment:`), never on prod.
"""

import os

SANDBOX_ADMIN_EMAIL = os.getenv("SANDBOX_ADMIN_EMAIL", "admin@test.sandbox")
SANDBOX_ADMIN_PASSWORD = os.getenv("SANDBOX_ADMIN_PASSWORD", "")

SANDBOX_TUTORIAL_EMAIL = os.getenv(
    "SANDBOX_TUTORIAL_EMAIL", "tutorial-admin@theprotocol.cloud")
SANDBOX_TUTORIAL_PASSWORD = os.getenv("SANDBOX_TUTORIAL_PASSWORD", "")


def have_sandbox_admin() -> bool:
    """True when a rotated password has actually been supplied."""
    return bool(SANDBOX_ADMIN_PASSWORD)
