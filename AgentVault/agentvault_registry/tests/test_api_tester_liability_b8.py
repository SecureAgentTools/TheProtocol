"""§SUITES1018 batch 8 (part 3, 2026-10-19): the liability chain runs on the sweep's own mandate.

In the V0625 sweep (2026-10-19) 13 liability rows read EF: the mandate row sent the presence code "000000" ("presence
gate"), every row naming a mandate or a challenge named one of nothing ("needs a live liability mandate"), and the
intent row found no underwriter. Now the sweep's admin (who made the sweep's agents) issues a mandate for the sweep's
agent with a code of its own presence secret: setup hands the secret back and the sweep never verifies it, so the
admin's sign-in stays one factor. {mid} is that mandate (issued anew once the revoke row revoked it), {chid} a challenge
of its own per row (approve's acked and its read floor waited out), the mandate revoke is the sweep's own revocation, a
posture that refuses a TOTP answer is an accepted refusal by its own sentence, and PUT ceiling sends a removal (POST
asks to raise). Also: the catalog's dict literal carried enroll-key twice, and the later fixed key replaced batch 6's
fresh one.

RED on 9669b622 (batch 8 part 1): every test_red_* fails there; the test_control_* ones pass on both.
"""
from __future__ import annotations

import ast
import asyncio
import itertools
import json
import pathlib
import time

import httpx
import pyotp

ADMIN = "admin-token"
ADMIN_PW = "Aa1!sandbox-admin-test-password"
AGENT = "did:theprotocol:sweep-agent"


class _SharedValues(dict):
    async def refresh_from_redis(self):
        return None


class _LiabilityFrame:
    """The sweep's admin's presence re-key (POST /auth/2fa/setup), mandates, challenges, the posture's read floor and
    approve, as routers/auth_2fa.py and routers/liability.py answer them. Records every request."""

    def __init__(self, monkeypatch, *, floor_ms=120, refuse_rekey=False):
        self.seen, self.mandates, self.challenges = [], {}, {}
        self.secret, self.floor_ms, self.refuse_rekey = None, floor_ms, refuse_rekey
        self.ids = itertools.count(1)
        real = httpx.AsyncClient

        def _client(*a, **k):
            k["transport"] = httpx.MockTransport(self._handle)
            return real(*a, **k)
        monkeypatch.setattr(httpx, "AsyncClient", _client)

    def _ok_code(self, code):
        return bool(self.secret) and pyotp.TOTP(self.secret).verify(code or "", valid_window=1)

    def _handle(self, req):
        self.seen.append(req)
        p, m = req.url.path, req.method
        body = json.loads(req.content) if req.content else {}
        if req.headers.get("authorization") != f"Bearer {ADMIN}" and not p.endswith("/verify"):
            return httpx.Response(401, json={"detail": "Could not validate credentials"})
        if p == "/api/v1/auth/2fa/setup":
            if self.refuse_rekey or body.get("password") != ADMIN_PW:
                return httpx.Response(401, json={"detail": "Invalid password"})
            self.secret = pyotp.random_base32()
            return httpx.Response(200, json={"secret_raw": self.secret, "backup_codes": ["AAAA-0000"]})
        if p == "/api/v1/liability/mandates" and m == "POST":
            if not self._ok_code(body.get("totp_code")):
                return httpx.Response(401, json={"detail": "Presence check failed (invalid TOTP)"})
            mid = f"lm_{next(self.ids)}"
            self.mandates[mid] = {"id": mid, "status": "signed", "agent_did": body["agent_did"], "body": body}
            return httpx.Response(201, json={"id": mid, "status": "signed"})
        if p.startswith("/api/v1/liability/mandates/"):
            mid = p.split("/")[5]
            mnd = self.mandates.get(mid)
            if not mnd:
                return httpx.Response(404, json={"detail": "Mandate not found"})
            if p.endswith("/revoke"):
                mnd["status"] = "revoked"
                return httpx.Response(200, json={"ok": True, "id": mid, "status": "revoked"})
            if p.endswith("/ceiling") and m == "PUT":
                if str(body.get("max_per_tx")) not in ("0", "0.0"):
                    return httpx.Response(409, json={"detail": {"error": "no_ceiling_to_tighten"}})
                return httpx.Response(200, json={"mandate_id": mid, "ceiling": None, "removed": True})
            return httpx.Response(200, json={"id": mid, "status": mnd["status"]})
        if p == "/api/v1/liability/posture":
            return httpx.Response(200, json={"posture": "swift", "dials": {"read_floor_ms": self.floor_ms}})
        if p == "/api/v1/liability/challenges":
            mnd = self.mandates.get(body.get("mandate_id"))
            if not mnd:
                return httpx.Response(404, json={"detail": "Mandate not found"})
            if mnd["status"] != "signed":
                return httpx.Response(409, json={"detail": f"Mandate is {mnd['status']}"})
            chid = f"lch_{next(self.ids)}"
            self.challenges[chid] = {"status": "pending", "clock": time.monotonic()}
            return httpx.Response(201, json={"id": chid, "mandate_id": mnd["id"]})
        if p.startswith("/api/v1/liability/challenges/"):
            chid = p.split("/")[5]
            ch = self.challenges.get(chid)
            if not ch:
                return httpx.Response(404, json={"detail": "Challenge not found"})
            if p.endswith("/ack"):
                ch["clock"] = time.monotonic()
                return httpx.Response(200, json={"ok": True, "challenge_id": chid})
            if p.endswith("/approve"):
                if (time.monotonic() - ch["clock"]) * 1000 < self.floor_ms:
                    return httpx.Response(425, json={"detail": {"error": "read_floor_not_met"}})
                if not self._ok_code(body.get("totp_code")):
                    return httpx.Response(401, json={"detail": "Presence check failed"})
                ch["status"] = "approved"
                return httpx.Response(200, json={"ok": True, "id": chid, "status": "approved", "method": "totp"})
            if p.endswith("/deny"):
                ch["status"] = "denied"
                return httpx.Response(200, json={"ok": True, "id": chid, "status": "denied"})
        return httpx.Response(200, json={"items": []})

    def paths(self):
        return [(r.method, r.url.path) for r in self.seen]


def _router(monkeypatch, **values):
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", _SharedValues(agent_did=AGENT, **values))
    monkeypatch.setattr(R, "API_TEST_TARGET_URL", "http://registry-test:8000")
    monkeypatch.setattr(R, "SANDBOX_ADMIN_PASSWORD", ADMIN_PW)
    monkeypatch.setattr(R, "_delegation_target", lambda: None)
    return R


def test_red_the_sweep_issues_its_own_mandate_with_a_code_of_the_admins_rekeyed_secret(monkeypatch):
    R = _router(monkeypatch)
    f = _LiabilityFrame(monkeypatch)
    mid = asyncio.run(R._sweep_mandate(ADMIN))
    assert mid and f.mandates[mid]["agent_did"] == AGENT and R.DYNAMIC_VALUES["liability_mandate_id"] == mid
    sent = f.mandates[mid]["body"]
    assert sent["scope"] == ["a2a.pay"] and sent["expires_in_days"] == 1 and sent["tier"] == "T1"
    # the admin's second factor is never turned on: no verify, ever
    assert not [p for _, p in f.paths() if p.startswith("/api/v1/auth/2fa/") and p != "/api/v1/auth/2fa/setup"]
    # a signed mandate is reused; a revoked one is replaced
    assert asyncio.run(R._sweep_mandate(ADMIN)) == mid and len(f.mandates) == 1
    f.mandates[mid]["status"] = "revoked"
    again = asyncio.run(R._sweep_mandate(ADMIN))
    assert again and again != mid and R.DYNAMIC_VALUES["liability_mandate_id"] == again


def test_control_with_no_presence_code_no_mandate_is_issued(monkeypatch):
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", _SharedValues(agent_did=AGENT))
    monkeypatch.setattr(R, "API_TEST_TARGET_URL", "http://registry-test:8000")
    monkeypatch.setattr(R, "_delegation_target", lambda: None)
    f = _LiabilityFrame(monkeypatch, refuse_rekey=True)
    if hasattr(R, "_sweep_mandate"):
        assert asyncio.run(R._sweep_mandate(ADMIN)) is None
    assert not [p for m, p in f.paths() if m == "POST" and p == "/api/v1/liability/mandates"]


def test_red_the_mandate_and_challenge_placeholders_name_the_sweeps_own(monkeypatch):
    R = _router(monkeypatch)
    f = _LiabilityFrame(monkeypatch, floor_ms=0)
    out = asyncio.run(R.replace_path_placeholders("/liability/mandates/{mid}/receipts", ADMIN, "agent", method="GET"))
    (mid,) = f.mandates
    assert out == f"/liability/mandates/{mid}/receipts"
    a = asyncio.run(R.replace_path_placeholders("/liability/challenges/{chid}/ack", ADMIN, "agent", method="POST"))
    b = asyncio.run(R.replace_path_placeholders("/liability/challenges/{chid}/deny", ADMIN, "agent", method="POST"))
    assert a.split("/")[3] in f.challenges and b.split("/")[3] in f.challenges and a.split("/")[3] != b.split("/")[3]


def test_red_approve_is_presented_waits_its_read_floor_and_answers_with_a_fresh_code(monkeypatch):
    R = _router(monkeypatch)
    f = _LiabilityFrame(monkeypatch, floor_ms=150)
    path = asyncio.run(R.replace_path_placeholders("/liability/challenges/{chid}/approve", ADMIN, "agent",
                                                   method="POST"))
    chid = path.split("/")[3]
    assert ("POST", f"/api/v1/liability/challenges/{chid}/ack") in f.paths()
    body = asyncio.run(R._resolve_body_markers(R.request_bodies.get_body("/liability/challenges/{chid}/approve"),
                                               ADMIN))
    r = f._handle(httpx.Request("POST", f"http://t/api/v1{path}", json=body, headers={"authorization": f"Bearer {ADMIN}"}))
    assert r.status_code == 200, r.json()


def test_red_the_markers_name_the_sweeps_mandate_and_a_live_code(monkeypatch):
    R = _router(monkeypatch)
    f = _LiabilityFrame(monkeypatch)
    for path in ("/liability/challenges", "/liability/previews"):
        body = asyncio.run(R._resolve_body_markers(R.request_bodies.get_body(path), ADMIN))
        assert body["mandate_id"] in f.mandates, (path, body)
    prev = R.request_bodies.get_body("/liability/previews")["facts"]
    assert prev.get("currency") and "counterparty_did" in prev     # I11: an amount names its unit and counterparty
    body = asyncio.run(R._resolve_body_markers(R.request_bodies.get_body("/liability/mandates"), ADMIN))
    assert f._ok_code(body["totp_code"]), body


def test_red_put_ceiling_sends_a_removal_and_post_asks_to_raise(monkeypatch):
    R = _router(monkeypatch)
    assert R._METHOD_BODIES[("PUT", "/liability/mandates/{mid}/ceiling")]["max_per_tx"] == "0"
    assert ("POST", "/liability/mandates/{mid}/ceiling") not in R._METHOD_BODIES
    assert R.request_bodies.get_body("/liability/mandates/{mid}/ceiling")["max_per_tx"] == "1.0"


def test_red_the_mandate_revoke_is_the_sweeps_own_and_a_posture_refusal_is_accepted():
    from agentvault_registry.api_tests import base as B
    assert B._classify_destructive("POST", "/liability/mandates/lm_abc/revoke") == ""
    said = B._classify_sentence_refusal("POST", "/liability/challenges/lch_1/approve", 403,
                                        {"detail": {"error": "method_below_floor", "posture": "hardened"}})
    assert "stronger presence" in said, said


def test_control_other_revocations_stay_withheld():
    from agentvault_registry.api_tests import base as B
    assert B._classify_destructive("POST", "/liability/devices/{device_id}/revoke-key") == ""
    assert B._classify_destructive("POST", "/agents/{did}/delegations/{grant_id}/revoke")
    assert B._classify_destructive("POST", "/admin/federation/licence/{cert_hash}/revoke")


def test_red_the_catalogs_dict_literals_hold_each_key_once():
    import agentvault_registry.api_tests.request_bodies as RB
    tree = ast.parse(pathlib.Path(RB.__file__).read_text())
    dups = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
            dups += sorted({k for k in keys if keys.count(k) > 1})
    assert dups == [], dups
    assert RB.RequestBodies().get_body("/liability/devices/{device_id}/enroll-key") == {"pubkey_jwk": "__P256_JWK__"}
