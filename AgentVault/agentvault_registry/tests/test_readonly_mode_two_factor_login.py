"""§DOCSFIX D6-232 (2026-10-16): during a READONLY_MODE freeze an account with two-factor sign-in can still sign in.

The freeze keeps "login and token minting" open so an operator can authenticate to look at the system they froze. For
an account with 2FA, the password step answers a partial token and the session comes from the second step, POST
/api/v1/auth/2fa/validate (a TOTP code) or /recover (a backup code). Neither was exempt, so an admin with 2FA could not
finish signing in while frozen. The exempt list also named /api/v1/auth/token, which no route serves. The middleware is
driven through FastAPI's TestClient with the freeze engaged.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.middleware import readonly_mode as RO

SIGN_IN = ["/api/v1/auth/login", "/api/v1/auth/agent/token", "/api/v1/auth/refresh",
           "/api/v1/auth/2fa/validate", "/api/v1/auth/2fa/recover"]


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(RO, "_ENABLED", True)
    app = FastAPI()
    for path in SIGN_IN + ["/api/v1/auth/2fa/disable", "/api/v1/teg/transfer"]:
        app.add_api_route(path, lambda: {"reached": True}, methods=["POST"])
    app.add_middleware(RO.ReadOnlyModeMiddleware)
    return TestClient(app)


@pytest.mark.parametrize("path", SIGN_IN)
def test_every_sign_in_step_stays_open(frozen, path):
    r = frozen.post(path)
    assert r.status_code == 200 and r.json() == {"reached": True}, (path, r.status_code)


@pytest.mark.parametrize("path", ["/api/v1/auth/2fa/disable", "/api/v1/teg/transfer"])
def test_other_writes_are_still_refused(frozen, path):
    assert frozen.post(path).status_code == 503


def test_the_list_names_no_route_that_does_not_exist():
    assert "/api/v1/auth/token" not in RO._EXEMPT_WRITE_PATHS
