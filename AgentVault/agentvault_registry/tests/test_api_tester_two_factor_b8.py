"""§SUITES1018 batch 8 (part 2, 2026-10-19): the 2FA rows are measured, on a fixture account of the sweep's own.

In the V0625 sweep (2026-10-19) POST /auth/2fa/setup ran its contract as the sweep's admin and wrote a TOTP secret and
backup codes to the tester's own sandbox admin (developer 2 on sbx-alpha; read 2026-10-19: a secret set, 2FA never
verified); verify, validate and recover read EF "the harness can't generate wall-clock-aligned codes"; backup-codes and
disable NOT MEASURED "manually verified working". Setup hands the secret back, so the harness can compute every code.
Now each row acts on a throwaway account of the sweep's own (reused across rows and sweeps: its password is derived,
never stored), reset to off through the admin's emergency route when an earlier row left 2FA on, set up and verified
when the row needs it on, signed in again for the partial token validate and recover complete. The sweep's admin token
and password reach no 2FA route, and a result names the response's fields only (secrets, codes and sessions stay out
of the archive).

RED on 9669b622 (batch 8 part 1): every test_red_* fails there; the test_control_* one passes on both.
"""
from __future__ import annotations

import asyncio
import itertools
import json
from urllib.parse import parse_qs

import httpx
import pyotp
import pytest

ADMIN = "admin-token"
ROWS = ("/auth/2fa/setup", "/auth/2fa/verify", "/auth/2fa/validate", "/auth/2fa/recover", "/auth/2fa/backup-codes",
        "/auth/2fa/disable")


class _SharedValues(dict):
    async def refresh_from_redis(self):
        return None


class _TwoFactorFrame:
    """Registration, sign-in, the admin list and its emergency 2FA route, and the six 2FA routes, as the registry
    answers them (routers/auth_secure.py, routers/auth_2fa.py, routers/admin_developers.py). Records every request."""

    def __init__(self, monkeypatch, *, refuse_verify=False, refuse_register=False):
        self.seen, self.accounts, self.sessions, self.partials = [], {}, {}, {}
        self.ids = itertools.count(9100)
        self.refuse_verify, self.refuse_register = refuse_verify, refuse_register
        real = httpx.AsyncClient

        def _client(*a, **k):
            k["transport"] = httpx.MockTransport(self._handle)
            return real(*a, **k)
        monkeypatch.setattr(httpx, "AsyncClient", _client)

    def seed(self, email, password, *, enabled):
        acct = {"id": next(self.ids), "email": email, "password": password, "enabled": enabled,
                "secret": pyotp.random_base32() if enabled else None, "codes": ["AAAA-1111"] if enabled else []}
        self.accounts[email] = acct
        return acct

    def _who(self, req):
        tok = req.headers.get("authorization", "")[len("Bearer "):]
        return self.accounts.get(self.sessions.get(tok, ""))

    def _handle(self, req):
        self.seen.append(req)
        p, m = req.url.path, req.method
        body = json.loads(req.content) if req.content and req.headers.get("content-type", "").startswith(
            "application/json") else {}
        if p == "/api/v1/admin/developers" and m == "GET":
            assert req.headers.get("authorization") == f"Bearer {ADMIN}"
            q = req.url.params.get("search", "")
            rows = [{"id": a["id"], "email": a["email"], "two_fa_enabled": a["enabled"], "is_suspended": False,
                     "deleted_at": None, "is_admin": False}
                    for a in sorted(self.accounts.values(), key=lambda a: -a["id"]) if q in a["email"]]
            return httpx.Response(200, json={"developers": rows, "total": len(rows), "limit": 20, "offset": 0})
        if p == "/api/v1/auth/register":
            if self.refuse_register:
                return httpx.Response(400, json={"detail": "Registration is closed on this frame"})
            self.seed(body["email"], body["password"], enabled=False)
            return httpx.Response(201, json={"message": "ok", "recovery_keys": ["x"]})
        if p == "/api/v1/auth/login":
            form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
            a = self.accounts.get(form.get("username"))
            if not a or a["password"] != form.get("password"):
                return httpx.Response(401, json={"detail": "Incorrect email or password"})
            if a["enabled"]:
                tok = f"partial-{a['id']}-{len(self.partials)}"
                self.partials[tok] = a["email"]
                return httpx.Response(200, json={"access_token": "", "requires_2fa": True, "partial_token": tok})
            tok = f"session-{a['id']}-{len(self.sessions)}"
            self.sessions[tok] = a["email"]
            return httpx.Response(200, json={"access_token": tok, "requires_2fa": False, "partial_token": None})
        if p.startswith("/api/v1/admin/developers/") and p.endswith("/disable-2fa"):
            assert req.headers.get("authorization") == f"Bearer {ADMIN}"
            a = next(a for a in self.accounts.values() if str(a["id"]) == p.split("/")[-2])
            if not a["enabled"]:
                return httpx.Response(400, json={"detail": "Developer does not have 2FA enabled"})
            a.update(enabled=False, secret=None, codes=[])
            return httpx.Response(200, json={"status": "2fa_disabled"})
        if p in ("/api/v1/auth/2fa/validate", "/api/v1/auth/2fa/recover"):
            a = self.accounts.get(self.partials.get(body.get("partial_token"), ""))
            if not a:
                return httpx.Response(401, json={"detail": "Invalid or expired partial token"})
            if p.endswith("/validate"):
                if not pyotp.TOTP(a["secret"]).verify(body.get("code", ""), valid_window=1):
                    return httpx.Response(401, json={"detail": "Invalid verification code"})
            elif body.get("backup_code") not in a["codes"]:
                return httpx.Response(401, json={"detail": "Invalid backup code"})
            else:
                a["codes"].remove(body["backup_code"])
            tok = f"session-{a['id']}-{len(self.sessions)}"
            self.sessions[tok] = a["email"]
            return httpx.Response(200, json={"access_token": tok, "refresh_token": "r", "token_type": "bearer"})
        if p.startswith("/api/v1/auth/2fa/"):
            a = self._who(req)
            if not a:
                return httpx.Response(401, json={"detail": "Could not validate credentials"})
            if p.endswith("/setup"):
                if a["enabled"]:
                    return httpx.Response(400, json={"detail": "Two-factor authentication is already enabled"})
                if body.get("password") != a["password"]:
                    return httpx.Response(401, json={"detail": "Invalid password"})
                a["secret"], a["codes"] = pyotp.random_base32(), ["ABCD-1234", "EF01-5678"]
                return httpx.Response(200, json={"status": "setup_required", "secret_raw": a["secret"],
                                                 "secret": a["secret"], "backup_codes": list(a["codes"]),
                                                 "qr_code": "data:", "otpauth_uri": "otpauth://"})
            if p.endswith("/verify"):
                if self.refuse_verify:
                    return httpx.Response(400, json={"detail": "Invalid verification code"})
                if a["enabled"] or not a["secret"]:
                    return httpx.Response(400, json={"detail": "Please initiate 2FA setup first"})
                if not pyotp.TOTP(a["secret"]).verify(body.get("code", ""), valid_window=1):
                    return httpx.Response(400, json={"detail": "Invalid verification code"})
                a["enabled"] = True
                return httpx.Response(200, json={"status": "enabled"})
            if not a["enabled"]:
                return httpx.Response(400, json={"detail": "Two-factor authentication is not enabled"})
            if body.get("password") != a["password"]:
                return httpx.Response(401, json={"detail": "Invalid password"})
            code = body.get("current_code") if p.endswith("/backup-codes") else body.get("code")
            if not pyotp.TOTP(a["secret"]).verify(code or "", valid_window=1):
                return httpx.Response(401, json={"detail": "Invalid verification code"})
            if p.endswith("/backup-codes"):
                a["codes"] = ["9999-0000"]
                return httpx.Response(200, json={"backup_codes": list(a["codes"]), "message": "New backup codes"})
            a.update(enabled=False, secret=None, codes=[])
            return httpx.Response(200, json={"status": "disabled"})
        return httpx.Response(404, json={"detail": "Not Found"})

    def calls(self, path):
        return [r for r in self.seen if r.url.path == "/api/v1" + path]


def _router(monkeypatch):
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", _SharedValues(agent_did="did:theprotocol:sweep"))
    monkeypatch.setattr(R, "API_TEST_TARGET_URL", "http://registry-test:8000")
    monkeypatch.setattr(R, "_delegation_target", lambda: None)

    async def _tokens():
        return ADMIN, "agent-token"
    monkeypatch.setattr(R, "get_sandbox_tokens", _tokens)

    async def _no_redis():
        return None
    monkeypatch.setattr(R, "_get_leader_redis", _no_redis)
    return R


def _row(R, path):
    return asyncio.run(R.test_endpoint(request=None, endpoint_test={"method": "POST", "path": path,
                                                                    "auth": "developer"}, current_developer=None))


@pytest.mark.parametrize("path", ROWS)
def test_red_each_2fa_row_is_measured_on_the_sweeps_own_account(monkeypatch, path):
    R = _router(monkeypatch)
    f = _TwoFactorFrame(monkeypatch)
    out = _row(R, path)
    assert out["healthy"] is True and out["statusCode"] == 200, out
    assert out.get("dispatched_via") == "two_factor_fixture" and not out.get("not_measured"), out
    (acct,) = f.accounts.values()
    assert acct["email"].startswith("apitest-2fa-") and acct["email"].endswith("@test.sandbox")
    own = f.calls(path)[-1]                                   # the row's own call
    if path in ("/auth/2fa/validate", "/auth/2fa/recover"):
        assert "authorization" not in own.headers
    else:
        assert f.accounts.get(f.sessions.get(own.headers["authorization"][len("Bearer "):])) is acct
    # the sweep's admin token reaches no 2FA route
    assert not [r for r in f.seen if r.url.path.startswith("/api/v1/auth/2fa/")
                and r.headers.get("authorization") == f"Bearer {ADMIN}"]


def test_red_the_sweeps_admin_password_reaches_no_2fa_route(monkeypatch):
    from agentvault_registry.core.sandbox_creds import SANDBOX_ADMIN_PASSWORD
    R = _router(monkeypatch)
    f = _TwoFactorFrame(monkeypatch)
    for path in ROWS:
        assert _row(R, path)["healthy"] is True
    if SANDBOX_ADMIN_PASSWORD:
        assert not [r for r in f.seen if r.url.path.startswith("/api/v1/auth/2fa/")
                    and SANDBOX_ADMIN_PASSWORD in r.content.decode()]
    assert len([r for r in f.seen if r.url.path == "/api/v1/auth/register"]) == 1     # one account for all six rows


def test_red_an_account_left_on_is_reset_through_the_admin_route_first(monkeypatch):
    R = _router(monkeypatch)
    f = _TwoFactorFrame(monkeypatch)
    email = "apitest-2fa-1@test.sandbox"
    acct = f.seed(email, R._two_factor_password(email), enabled=True)     # an earlier row's verify left it on
    out = _row(R, "/auth/2fa/setup")
    assert out["healthy"] is True, out
    assert [r.url.path for r in f.seen if r.url.path.endswith("/disable-2fa")] == [
        f"/api/v1/admin/developers/{acct['id']}/disable-2fa"]
    assert not [r for r in f.seen if r.url.path == "/api/v1/auth/register"]          # reused, not a second account


def test_red_a_reused_account_whose_password_no_longer_signs_in_is_replaced(monkeypatch):
    R = _router(monkeypatch)
    f = _TwoFactorFrame(monkeypatch)
    f.seed("apitest-2fa-1@test.sandbox", "Aa1!an-older-secret-made-this", enabled=False)
    out = _row(R, "/auth/2fa/verify")
    assert out["healthy"] is True, out
    assert len(f.accounts) == 2 and len([r for r in f.seen if r.url.path == "/api/v1/auth/register"]) == 1


def test_red_the_result_names_fields_never_secrets_codes_or_sessions(monkeypatch):
    R = _router(monkeypatch)
    f = _TwoFactorFrame(monkeypatch)
    out = _row(R, "/auth/2fa/setup")
    (acct,) = f.accounts.values()
    text = json.dumps(out)
    assert out["responseData"] == {"fields": ["backup_codes", "otpauth_uri", "qr_code", "secret", "secret_raw",
                                              "status"]}, out
    for value in [acct["secret"], acct["password"], *acct["codes"], *f.sessions]:
        assert value not in text


def test_red_an_account_that_cannot_be_made_is_not_measured_with_its_sentence(monkeypatch):
    R = _router(monkeypatch)
    _TwoFactorFrame(monkeypatch, refuse_register=True)
    out = _row(R, "/auth/2fa/validate")
    assert out["not_measured"] is True and out["failure_bucket"] == "not_measured_fixture", out
    assert "Registration is closed on this frame" in out["not_measured_reason"], out


def test_red_a_refused_own_call_is_a_failure_carrying_the_routes_sentence(monkeypatch):
    R = _router(monkeypatch)
    _TwoFactorFrame(monkeypatch, refuse_verify=True)
    out = _row(R, "/auth/2fa/verify")                     # verify is this row's own call, not an arrangement step
    assert out["healthy"] is False and out["statusCode"] == 400 and not out.get("not_measured"), out
    assert out["error"] == "HTTP 400: Invalid verification code", out


def test_control_the_status_read_keeps_its_contract(monkeypatch):
    from agentvault_registry.api_tests.contracts import load_all
    R = _router(monkeypatch)
    load_all()
    assert "/auth/2fa/status" not in getattr(R, "_TWO_FACTOR_ROWS", {})
    assert R._contract_for("GET", "/auth/2fa/status") is not None


def test_red_the_password_is_derived_and_meets_the_strength_rule(monkeypatch):
    from agentvault_registry.input_validators import validate_password_strength
    R = _router(monkeypatch)
    a, b = R._two_factor_password("apitest-2fa-1@test.sandbox"), R._two_factor_password("apitest-2fa-2@test.sandbox")
    assert a == R._two_factor_password("apitest-2fa-1@test.sandbox") and a != b and len(a) == 28
    validate_password_strength(a)
