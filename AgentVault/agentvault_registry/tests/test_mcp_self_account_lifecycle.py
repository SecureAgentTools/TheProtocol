"""§MCPTEST30 (2026-09-30) — the caller's-own-account tools, measured on an account the sweep owns.

Eight tools change the account that CALLS them (2FA on/off, backup codes, refresh, password change, logout, deletion
request/cancel). On the runner each was a hazard, so every night they read NOT MEASURED or ran only a refusal under
expect_status="any", which cannot tell a route that refuses a wrong password from one that accepts it.
`lifecycle_self_account_on_throwaway` runs them on a throwaway developer the fixture phase registers for the run.

Pinned here, offline, against a small in-memory model of the routes (no app import beyond the lifecycle module):
  * the TOTP the tester computes is RFC 6238's (the RFC's own SHA-1 vectors), and the "wrong" code is never valid;
  * a registry that behaves: every success row is healthy, and every guarded rule was probed with a refusal;
  * CONTROLS, one per rule class: a registry that accepts a wrong password, keeps a token alive after a password
    change or logout, or reuses a backup code, gets a BUG-FIND on exactly that tool's row;
  * no subject: the eight tools are NOT MEASURED (named), never run on the runner;
  * no other lifecycle records a row for these tools (a second writer would race this one, last writer wins).
"""
from __future__ import annotations

import ast
import asyncio
import base64
import json
import pathlib
import secrets
import time

import pytest

from agentvault_registry.api_tests.contracts import mcp_lifecycles as L

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"


# ── RFC 6238 ────────────────────────────────────────────────────────────────────────────────────────────────

RFC_KEY_B32 = base64.b32encode(b"12345678901234567890").decode()
# RFC 6238 appendix B, SHA-1, 8 digits; a 6-digit code is the same number mod 10**6.
RFC_VECTORS = [(59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"),
               (1234567890, "89005924"), (2000000000, "69279037"), (20000000000, "65353130")]


@pytest.mark.parametrize("t,expected8", RFC_VECTORS)
def test_totp_matches_rfc6238(t, expected8):
    assert L.totp_code(RFC_KEY_B32, at=t, digits=8) == expected8
    assert L.totp_code(RFC_KEY_B32, at=t) == expected8[-6:]


def test_totp_accepts_the_spaced_display_form():
    spaced = " ".join(RFC_KEY_B32[i:i + 4] for i in range(0, len(RFC_KEY_B32), 4)).lower()
    assert L.totp_code(spaced, at=59) == "287082"


def test_the_wrong_code_is_never_valid_in_the_window():
    for _ in range(50):
        secret = base64.b32encode(secrets.token_bytes(20)).decode()
        t = time.time()
        valid = {L.totp_code(secret, t + d) for d in (-30, 0, 30)}
        w = L.wrong_totp_code(secret, t)
        assert len(w) == 6 and w.isdigit() and w not in valid


def test_credential_refused_reads_the_http_401_and_the_endpoint_refusal():
    assert L.credential_refused(False, {}, "401")
    assert L.credential_refused(False, {"error": {"code": -32001, "message": "auth"}}, "200")
    assert not L.credential_refused(True, {}, "200")
    assert not L.credential_refused(False, {}, "403")


# ── an in-memory registry: the routes' rules, not their code ────────────────────────────────────────────────

class FakeRegistry:
    """Just enough of the auth routes to drive the lifecycle. Flags turn on one defect each (the controls)."""

    def __init__(self, **defects):
        self.d = defects
        self.email, self.pw = "subj@throwaway-pl.example.com", "Tw!0123456789abcdefZ9a"
        self.tv = 0                       # token_version
        self.secret = None
        self.enabled = False
        self.backup = set()
        self.used = set()
        self.deletion = None
        self.calls = []

    # tokens: "t:<tv>:<nonce>" access, "r:<tv>:<nonce>" refresh, "p:<nonce>" partial
    def _tok(self, kind="t"):
        body = {"sub": "4242", "tv": self.tv}
        p = base64.urlsafe_b64encode(json.dumps(body).encode()).decode().rstrip("=")
        return f"{kind}.{p}.{secrets.token_hex(4)}"

    def _valid(self, token):
        try:
            p = token.split(".")[1]
            c = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
        except Exception:
            return False
        if self.d.get("tokens_survive"):
            return True
        return c.get("tv") == self.tv

    async def login(self, email, pw):
        if email != self.email or (pw != self.pw and not self.d.get("old_password_works")):
            return "401", {"detail": "Incorrect email or password"}
        if self.enabled:
            return "200", {"requires_2fa": True, "partial_token": self._tok("p")}
        return "200", {"access_token": self._tok(), "refresh_token": self._tok("r"), "requires_2fa": False}

    def _err(self, code, detail):
        return False, {"result": {"content": [{"type": "text", "text": f"Error: HTTP {code}: {detail}"}]}}, str(code)

    def _okr(self, payload):
        return True, {"result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}, "200"

    async def rpc(self, tool, args, jwt="", timeout=20):
        name = tool.replace("theprotocol_", "")
        self.calls.append((name, dict(args)))
        public = name in ("authValidate2FA", "authRecover2FA")
        if not public and not self._valid(jwt):
            return False, {}, "401"
        code_ok = lambda c: self.secret and c in {L.totp_code(self.secret, time.time() + d) for d in (-30, 0, 30)}
        if name == "getMyDeveloperProfile":
            return self._okr({"email": self.email})
        if name == "authRefresh":
            r = args.get("refresh_token", "")
            if not r.startswith("r."):
                return self._err(401, "Invalid or expired refresh token")
            if not self._valid(r):
                return self._err(401, "Refresh token has been revoked")
            return self._okr({"access_token": self._tok(), "refresh_token": self._tok("r")})
        if name == "setup2FA":
            if args.get("password") != self.pw and not self.d.get("setup_accepts_wrong_password"):
                return self._err(401, "Invalid password")
            self.secret = base64.b32encode(secrets.token_bytes(20)).decode()
            self.backup = {secrets.token_hex(4) for _ in range(8)}
            return self._okr({"secret_raw": self.secret, "backup_codes": sorted(self.backup)})
        if name == "getMy2FAStatus":
            return self._okr({"enabled": self.enabled, "backup_codes_remaining": len(self.backup - self.used)})
        if name == "verify2FA":
            if not code_ok(args.get("code")):
                return self._err(400, "Invalid verification code")
            self.enabled = True
            return self._okr({"status": "enabled"})
        if name == "authValidate2FA":
            if not str(args.get("login_token", "")).startswith("p.") or not code_ok(args.get("code")):
                return self._err(401, "Invalid verification code")
            return self._okr({"access_token": self._tok()})
        if name == "regenerateBackupCodes":
            if args.get("password") != self.pw:
                return self._err(401, "Invalid password")
            if not code_ok(args.get("current_code")):
                return self._err(401, "Invalid verification code")
            self.backup = {secrets.token_hex(4) for _ in range(8)}
            self.used = set()
            return self._okr({"backup_codes": sorted(self.backup)})
        if name == "authRecover2FA":
            c = args.get("backup_code")
            if c not in self.backup or (c in self.used and not self.d.get("backup_code_reusable")):
                return self._err(401, "Invalid backup code")
            self.used.add(c)
            return self._okr({"access_token": self._tok()})
        if name == "disable2FASelf":
            if args.get("password") != self.pw:
                return self._err(401, "Invalid password")
            self.enabled, self.secret = False, None
            return self._okr({"status": "disabled"})
        if name == "requestAccountDeletion":
            if args.get("confirmation") != "DELETE MY ACCOUNT":
                return self._err(400, "Confirmation phrase mismatch")
            self.deletion = "pending_deletion"
            return self._okr({"message": "scheduled"})
        if name == "getMyDeletionStatus":
            return self._okr({"deletion_status": self.deletion})
        if name == "cancelAccountDeletion":
            self.deletion = None
            return self._okr({"message": "cancelled"})
        if name == "changePassword":
            if args.get("current_password") != self.pw:
                return self._err(400, "Current password is incorrect")
            self.old_pw, self.pw = self.pw, args["new_password"]
            self.tv += 1
            return self._okr({"message": "changed"})
        if name == "logoutSession":
            self.tv += 1
            return self._okr({"message": "logged out"})
        raise AssertionError(f"unexpected tool {tool}")


def _parse(body):
    try:
        text = body["result"]["content"][0]["text"]
    except Exception:
        return {}
    try:
        return json.loads(text)
    except Exception:
        return {"_text": text}


class Bag:
    def __init__(self, reg: FakeRegistry, subject=True):
        self.developer_jwt = "runner-token-never-used-here"
        self.dev_login = reg.login
        if subject:
            code, tok = asyncio.run(reg.login(reg.email, reg.pw))
            self.self_subject = {"email": reg.email, "password": reg.pw, "developer_id": "4242",
                                 "access_token": tok["access_token"], "refresh_token": tok["refresh_token"]}
        else:
            self.self_subject = {"why": "POST /auth/register answered HTTP 403"}


def _drive(**defects):
    reg = FakeRegistry(**defects)
    bag = Bag(reg)
    outcomes = {}
    asyncio.run(L.lifecycle_self_account_on_throwaway(reg.rpc, _parse, bag, outcomes))
    return reg, outcomes


def test_a_registry_that_behaves_gives_eleven_healthy_rows():
    reg, out = _drive()
    for t in L.SELF_ACCOUNT_TOOLS:
        assert t in out, f"{t}: no row"
        assert out[t]["healthy"], f"{t}: {out[t].get('fail_reason') or out[t].get('skip_reason')}"
        assert out[t]["probe_expect_status"] == "success"
    names = [c[0] for c in reg.calls]
    # every guarded rule was actually probed with an input it must refuse
    wrong = [(n, a) for n, a in reg.calls if n == "setup2FA" and a.get("password", "").endswith("-wrong")]
    assert wrong, "setup2FA was never probed with a wrong password"
    assert names.count("authRecover2FA") == 2, "the used backup code was not tried a second time"
    assert ("requestAccountDeletion" in names) and names[-1] == "requestAccountDeletion", \
        "the throwaway did not ask for its own deletion last"
    assert reg.deletion == "pending_deletion"


@pytest.mark.parametrize("defect,tool", [
    ("setup_accepts_wrong_password", "theprotocol_setup2FA"),
    ("tokens_survive", "theprotocol_changePassword"),
    ("backup_code_reusable", "theprotocol_authRecover2FA"),
    ("old_password_works", "theprotocol_changePassword"),
])
def test_control_each_broken_rule_is_a_bugfind_on_its_own_row(defect, tool):
    _reg, out = _drive(**{defect: True})
    assert out[tool]["healthy"] is False
    assert "BUG-FIND" in (out[tool].get("fail_reason") or ""), out[tool]


def test_control_tokens_that_survive_logout_are_caught_on_logout():
    _reg, out = _drive(tokens_survive=True)
    assert "BUG-FIND" in (out["theprotocol_logoutSession"].get("fail_reason") or "")


def test_no_subject_means_not_measured_and_nothing_runs():
    reg = FakeRegistry()
    bag = Bag(reg, subject=False)
    out = {}
    asyncio.run(L.lifecycle_self_account_on_throwaway(reg.rpc, _parse, bag, out))
    assert reg.calls == [], "a missing subject must not call anything (never the runner)"
    assert set(out) == set(L._SELF_ACCOUNT_UNMEASURED_WITHOUT_SUBJECT)
    for row in out.values():
        assert row["healthy"] is False and "403" in row["skip_reason"]


def test_a_step_that_raises_leaves_named_not_measured_rows():
    reg = FakeRegistry()
    bag = Bag(reg)

    async def boom(tool, args, jwt="", timeout=20):
        if tool.endswith("changePassword"):
            raise RuntimeError("transport fell over")
        return await reg.rpc(tool, args, jwt=jwt, timeout=timeout)

    out = {}
    asyncio.run(L.lifecycle_self_account_on_throwaway(boom, _parse, bag, out))
    assert "transport fell over" in out["theprotocol_logoutSession"]["skip_reason"]
    assert out["theprotocol_setup2FA"]["healthy"] is True, "rows written before the failure keep their verdict"


# ── static: one writer per tool ─────────────────────────────────────────────────────────────────────────────

def _recording_calls_outside(fn_names: set) -> list:
    """(line, tool) for every _exec_step that RECORDS a row for a self-account tool outside the given functions."""
    tree = ast.parse((SRC / "api_tests" / "contracts" / "mcp_lifecycles.py").read_text())
    bad = []
    for fn in tree.body:
        if not isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)) or fn.name in fn_names:
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_exec_step" and len(node.args) >= 3:
                tool = node.args[2].value if isinstance(node.args[2], ast.Constant) else None
                if tool in L.SELF_ACCOUNT_TOOLS:
                    unrecorded = any(k.arg == "record_as_separate" and isinstance(k.value, ast.Constant)
                                     and k.value.value is False for k in node.keywords)
                    if not unrecorded:
                        bad.append((node.lineno, tool))
    return bad


def test_no_other_lifecycle_records_a_self_account_row():
    bad = _recording_calls_outside({"_self_account_steps", "lifecycle_self_account_on_throwaway"})
    assert not bad, f"a second writer for a self-account tool (last writer wins, nondeterministically): {bad}"


def test_the_lifecycle_is_registered_and_the_runner_account_ones_are_gone():
    names = [lc["name"] for lc in L.LIFECYCLES]
    assert "self_account_on_throwaway" in names
    for gone in ("account_deletion_safe", "2fa_setup_only", "change_password_safe", "auth_refresh_safe"):
        assert gone not in names, f"{gone} acted on the RUNNER's own account; it is replaced, not kept"
