"""§TESTBED P1 (2026-09-19): what a frame DECLARES it is, for the gates that must never run tests on a production frame.

The standup driver writes FRAME_POSTURE (`production` or `sandbox`) into every frame it builds, and this module is the one
reader. The MCP and API testers execute inside whichever registry receives test-flow and write into it (measured), so a
production frame refuses test execution by its DECLARATION, even where API_TEST_EXECUTION_ENABLED was switched on by
mistake: two locks, and the posture one is written at birth. A frame that declares nothing (built before this line, or
by hand, like the network's own sandbox pair) keeps the older gate alone: this module adds a refusal and removes none.
"""
from __future__ import annotations

import os
from typing import Mapping, Optional
from urllib.parse import urlparse

POSTURES = ("production", "sandbox")


def declared_posture(env: Optional[Mapping[str, str]] = None) -> str:
    """`production`, `sandbox`, `unknown` (declared but not a posture), or "" (nothing declared)."""
    value = ((os.environ if env is None else env).get("FRAME_POSTURE") or "").strip().lower()
    if not value:
        return ""
    return value if value in POSTURES else "unknown"


def test_execution_refusal(env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """None when this frame's declaration allows executing the test suite, else the refusal's sentence."""
    posture = declared_posture(env)
    if posture == "production":
        return ("this frame declares FRAME_POSTURE=production: the test suite never runs on a production frame "
                "(its tests write into the frame they run in); run it in this frame's sandbox")
    if posture == "unknown":
        return "this frame declares a FRAME_POSTURE that is not production or sandbox: test execution is refused until it says sandbox"
    return None


def targets_itself(target_url: str) -> bool:
    """True when a console's tester target is its own registry (the kit default: its `registry-test` alias)."""
    host = (urlparse(target_url or "").hostname or "").lower()
    return host in ("registry-test", "localhost", "127.0.0.1", "::1")
