"""D8 — the TEG's own onboarding faucet, a retired money surface, mounts only on an explicit TEG_ONBOARDING_MINT_ENABLED.

V0653 (an), the V0653 plan's item 1 (session-lead, sessionlogs2026/PLAN_2026-11-01_V0653_CANDIDATES.md): the default
was ON, so a compose that never named the key ran the faucet (the four production operators until V0652's roll, Frame
A's TEG until 2026-11-01 22:02Z). The default is OFF now: only true (1, yes, on) mounts it. Read by behavior: the TEG's
API is imported in a fresh process for each value and its routes are read from the app's OpenAPI (a module imports its
flags once). BASE (V0652's TEG source): unset and an unknown word mount the three routes.
"""
import json
import os
import pathlib
import subprocess
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
FAUCET = ["/api/v1/onboarding/admin/bootstrap/cleanup-expired", "/api/v1/onboarding/bootstrap/request-token",
          "/api/v1/onboarding/onboard/register"]
PROBE = ("import json\n"
         "from fastapi import FastAPI\n"
         "import teg_core_service.api.v1.api as a\n"
         "app = FastAPI(); app.include_router(a.api_router, prefix='/api/v1')\n"
         "print(json.dumps(sorted(p for p in app.openapi()['paths'] if p.startswith('/api/v1/onboarding/'))))\n")


def _mounted(value):
    env = {k: v for k, v in os.environ.items() if k != "TEG_ONBOARDING_MINT_ENABLED"}
    env.update({"PYTHONPATH": str(SRC), "PYTHONDONTWRITEBYTECODE": "1",
                "AVTP_SYSTEM_API_KEY": env.get("AVTP_SYSTEM_API_KEY") or "ci-dummy-avtp-key-0000000000000000000000",
                "TEG_TOKEN_SIGNING_KEY": env.get("TEG_TOKEN_SIGNING_KEY") or "ci-dummy-signing-key-000000000000000000000",
                "DATABASE_URL": env.get("DATABASE_URL") or "postgresql+asyncpg://ci:ci@127.0.0.1:1/ci"})
    if value is not None:
        env["TEG_ONBOARDING_MINT_ENABLED"] = value
    r = subprocess.run([sys.executable, "-c", PROBE], env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("value", [None, "", "false", "0", "off", "no", "maybe"])
def test_the_faucet_stays_off_unless_named_on(value):
    assert _mounted(value) == []


@pytest.mark.parametrize("value", ["true", "1", "yes", "on", " TRUE "])
def test_an_explicit_on_mounts_its_three_routes(value):
    assert _mounted(value) == FAUCET


def test_one_mount_inside_the_guard():
    s = (SRC / "teg_core_service" / "api" / "v1" / "api.py").read_text(encoding="utf-8")
    assert s.count("endpoints_onboarding.router") == 1, "one mount, inside the guard"
