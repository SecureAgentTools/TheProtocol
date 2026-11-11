"""D6-850: how a device credential joins and leaves an account.

DB-free. The routes run against a recording fake session; each assertion reads what a route WROTE (or refused to
write), so one file shows the base's behaviour (red) and the fix's (green). Run in the registry image:

    docker run --rm -v <worktree>/agentvault_registry:/w:ro -w /w -e DATABASE_URL=postgresql+asyncpg://u:p@localhost/db \
      -e API_KEY_SECRET=dummy --entrypoint python agentvault2-registry-a:v0656 -m pytest -q -p no:cacheprovider \
      -o addopts= -o asyncio_mode=auto tests/test_device_enrolment_d6850.py
"""
import asyncio
import base64
import datetime as dt
import hashlib
import json
import types

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException

from agentvault_registry import models, security
from agentvault_registry.routers import device_push as DP
from agentvault_registry.routers import liability as L
from agentvault_registry.services import stepup

ENROL_WRITES = ("INSERT INTO device_push_registrations", "UPDATE device_push_registrations SET webauthn_credential_id")
DEV = types.SimpleNamespace(id=42, email="d6850@example.test", name="D", two_fa_enabled=False, totp_secret=None,
                            is_admin=False)
REQ = types.SimpleNamespace(url=types.SimpleNamespace(hostname="localhost"))


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def now():
    return dt.datetime.now(dt.timezone.utc)


class Result:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def first(self):
        return self.rows[0] if self.rows else None

    def scalar(self):
        r = self.first()
        return None if r is None else (r[0] if isinstance(r, (tuple, list)) else r)

    def scalars(self):
        return types.SimpleNamespace(first=self.first, all=lambda: list(self.rows))

    def mappings(self):
        return types.SimpleNamespace(first=self.first, all=lambda: list(self.rows))

    def fetchall(self):
        return list(self.rows)


class FakeDB:
    """Records every statement; `on(fragment, fn)` answers the first statement containing the fragment."""

    def __init__(self):
        self.sql, self.added, self.objects, self.rules = [], [], {}, []
        self.on("INSERT INTO device_push_registrations", lambda s, p: [(7,)])
        self.on("SET status = 'consumed'", self._spend_registration)
        self.on("SET status='spent'", self._spend_stepup)
        self.on("FROM liability_challenges WHERE developer_id = :d AND action_type = :a AND challenge_hash",
                self._find_issued)
        self.on("SELECT count(*) FROM liability_challenges WHERE developer_id = :d AND action_type = :a AND created_at",
                lambda s, p: [(len(self.challenges(p.get("a"))),)])
        self.on("UPDATE liability_challenges SET status = 'expired', resolved_at = now() WHERE id = :c",
                self._retire)

    def on(self, fragment, fn):
        self.rules.insert(0, (fragment, fn))
        return self

    async def execute(self, stmt, params=None):
        s = " ".join(str(stmt).split())
        p = dict(params or {})
        self.sql.append((s, p))
        for frag, fn in self.rules:
            if frag in s:
                return Result(fn(s, p))
        return Result([])

    async def get(self, model, key):
        for o in self.added:
            if isinstance(o, model) and getattr(o, "id", None) == key:
                return o
        return self.objects.get((model.__name__, key))

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None

    async def commit(self):
        return None

    async def rollback(self):
        return None

    async def refresh(self, obj):
        return None

    def wrote(self, *fragments):
        return [s for s, _ in self.sql if any(f in s for f in fragments)]

    def challenges(self, action_type):
        return [o for o in self.added if isinstance(o, models.LiabilityChallenge) and o.action_type == action_type]

    def _find_issued(self, s, p):
        return [o for o in self.added if isinstance(o, models.LiabilityChallenge) and o.status == "issued"
                and o.developer_id == p.get("d") and o.challenge_hash == p.get("h")]

    def _spend_registration(self, s, p):
        hit = [o for o in self.added if isinstance(o, models.LiabilityChallenge) and o.id == p.get("c")
               and o.status == "issued"]
        for o in hit:
            o.status = "consumed"
        return [(o.id,) for o in hit]

    def _retire(self, s, p):
        hit = [o for o in self.added if isinstance(o, models.LiabilityChallenge) and o.id == p.get("c")
               and o.status == "issued"]
        for o in hit:
            o.status = "expired"
        return [(o.id,) for o in hit]

    def _spend_stepup(self, s, p):
        hit = [o for o in self.added if isinstance(o, models.LiabilityChallenge) and o.id == p.get("c")
               and o.status == "approved"]
        for o in hit:
            o.status = "spent"
        return [(o.id,) for o in hit]


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    """No audit DB, no phone, and an account without a factor unless a test says otherwise."""
    async def _log(*a, **k):
        return None

    async def _factors(db, dev):
        return {"totp": False, "device": False, "any": False}

    async def _announce(*a, **k):
        return None

    monkeypatch.setattr(L, "log_liability_action", _log)
    monkeypatch.setattr(stepup, "available_factors", _factors)
    import agentvault_registry.services.governance_presence as gp
    monkeypatch.setattr(gp, "announce_challenge", _announce)
    try:   # the account's notice is a background task: no push from a unit test
        from agentvault_registry.services import device_enrollment as _de
        monkeypatch.setattr(_de, "tell_the_account", lambda *a, **k: None, raising=False)
    except ImportError:
        pass
    yield


def with_device(monkeypatch, device=True, totp=False):
    async def _factors(db, dev):
        return {"totp": totp, "device": device, "any": device or totp}
    monkeypatch.setattr(stepup, "available_factors", _factors)


def credential(challenge_b64u, *, rp="localhost", origin="http://localhost", flags=0x45, kind="webauthn.create",
               cred=b"d6850-credential-01"):
    """A registration response a platform authenticator would send (attestation "none")."""
    pub = ec.generate_private_key(ec.SECP256R1()).public_key().public_numbers()
    cose = (bytes([0xA5, 0x01, 0x02, 0x03, 0x26, 0x20, 0x01, 0x21, 0x58, 0x20]) + pub.x.to_bytes(32, "big")
            + bytes([0x22, 0x58, 0x20]) + pub.y.to_bytes(32, "big"))
    auth = (hashlib.sha256(rp.encode()).digest() + bytes([flags]) + (0).to_bytes(4, "big") + bytes(16)
            + len(cred).to_bytes(2, "big") + cred + cose)
    att = (b"\xa3" + b"\x63fmt" + b"\x64none" + b"\x67attStmt" + b"\xa0" + b"\x68authData" + b"\x59"
           + len(auth).to_bytes(2, "big") + auth)
    cdj = json.dumps({"type": kind, "challenge": challenge_b64u, "origin": origin, "crossOrigin": False}).encode()
    return {"attestation_object": b64u(att), "client_data_json": b64u(cdj)}


def run(coro):
    return asyncio.run(coro)


def options(db, dev=DEV):
    try:
        return run(L.webauthn_options_self(REQ, dev=dev, db=db))
    except TypeError:   # the base's route takes no session: its challenge is stored nowhere
        return run(L.webauthn_options_self(REQ, dev=dev))


def register(db, body, confirm=None, dev=DEV, totp=None):
    extra = {**({"confirm_challenge_id": confirm} if confirm else {}), **({"totp_code": totp} if totp else {})}
    return run(L.webauthn_register_self(L.WebAuthnRegisterIn(**body, **extra), REQ, dev=dev, db=db))


def status_of(answer):
    return getattr(answer, "status_code", 200)


def body_of(answer):
    return json.loads(answer.body) if hasattr(answer, "body") else answer


@pytest.fixture
def api_key():
    t1 = security._PRESENTED_KEY_ID.set(77)
    t2 = security._PRESENTED_KEY_SCOPES.set(["*"])
    yield
    security._PRESENTED_KEY_ID.reset(t1)
    security._PRESENTED_KEY_SCOPES.reset(t2)


# ── registration ────────────────────────────────────────────────────────────────────────────────

def test_options_issue_a_stored_single_use_challenge():
    db = FakeDB()
    opts = options(db)
    issued = db.challenges("device_register")
    assert len(issued) == 1 and issued[0].status == "issued" and issued[0].developer_id == DEV.id
    assert opts["challenge"] == L.liab.b64u_from_hex(issued[0].challenge_hash)


def test_options_refuse_an_api_key(api_key):
    with pytest.raises(HTTPException) as e:
        options(FakeDB())
    assert e.value.status_code == 403


def test_register_refuses_an_api_key(api_key):
    db = FakeDB()
    with pytest.raises(HTTPException) as e:
        register(db, credential(b64u(b"never-issued-challenge-0123456789")))
    assert e.value.status_code == 403
    assert not db.wrote(*ENROL_WRITES)


def test_register_refuses_a_challenge_this_server_never_issued():
    db = FakeDB()
    with pytest.raises(HTTPException) as e:
        register(db, credential(b64u(b"never-issued-challenge-0123456789")))
    assert e.value.status_code == 422
    assert not db.wrote(*ENROL_WRITES)


def test_register_refuses_a_credential_without_user_verification():
    db = FakeDB()
    ch = options(db)["challenge"]
    with pytest.raises(HTTPException) as e:
        register(db, credential(ch, flags=0x41))   # present, attested, NOT verified
    assert e.value.status_code == 422 and "user_verification_missing" in str(e.value.detail)
    assert not db.wrote(*ENROL_WRITES)


def test_register_refuses_an_assertion_dressed_as_a_registration():
    db = FakeDB()
    ch = options(db)["challenge"]
    with pytest.raises(HTTPException) as e:
        register(db, credential(ch, kind="webauthn.get"))
    assert e.value.status_code == 422 and "wrong_ceremony_type" in str(e.value.detail)
    assert not db.wrote(*ENROL_WRITES)


def test_register_refuses_a_page_that_is_not_ours():
    db = FakeDB()
    ch = options(db)["challenge"]
    with pytest.raises(HTTPException) as e:
        register(db, credential(ch, origin="https://elsewhere.example"))
    assert e.value.status_code == 422 and "origin_mismatch" in str(e.value.detail)
    assert not db.wrote(*ENROL_WRITES)


def test_first_device_enrols_and_spends_its_challenge():
    db = FakeDB()
    ch = options(db)["challenge"]
    answer = register(db, credential(ch))
    assert status_of(answer) == 200 and body_of(answer)["ok"] is True
    assert db.wrote(*ENROL_WRITES)
    assert [o.status for o in db.challenges("device_register")] == ["consumed"]


def test_a_used_challenge_cannot_enrol_twice():
    db = FakeDB()
    ch = options(db)["challenge"]
    register(db, credential(ch))
    with pytest.raises(HTTPException) as e:
        register(db, credential(ch, cred=b"d6850-credential-02"))
    assert e.value.status_code == 422


def test_a_new_device_waits_for_an_enrolled_device(monkeypatch):
    with_device(monkeypatch)
    db = FakeDB()
    ch = options(db)["challenge"]
    answer = register(db, credential(ch))
    assert status_of(answer) == 428 and body_of(answer)["error"] == "step_up_required"
    assert not db.wrote(*ENROL_WRITES)
    asked = db.challenges("device_add")
    assert len(asked) == 1 and asked[0].status == "pending"
    assert body_of(answer)["step_up"]["challenge_id"] == asked[0].id
    assert [o.status for o in db.challenges("device_register")] == ["issued"]   # kept for the resend


def test_an_enrolled_device_approval_enrols_the_new_one(monkeypatch):
    with_device(monkeypatch)
    db = FakeDB()
    body = credential(options(db)["challenge"])
    asked = body_of(register(db, body))["step_up"]["challenge_id"]
    ch = next(o for o in db.challenges("device_add") if o.id == asked)
    ch.status, ch.method = "approved", "webauthn_uv"            # the phone approved it with a fingerprint
    answer = register(db, body, confirm=asked)
    assert status_of(answer) == 200 and body_of(answer)["approval"] == "enrolled_device"
    assert db.wrote(*ENROL_WRITES)
    assert ch.status == "spent" and [o.status for o in db.challenges("device_register")] == ["consumed"]


def test_a_code_does_not_approve_a_new_device(monkeypatch):
    with_device(monkeypatch, totp=True)
    db = FakeDB()
    body = credential(options(db)["challenge"])
    asked = body_of(register(db, body))["step_up"]["challenge_id"]
    ch = next(o for o in db.challenges("device_add") if o.id == asked)
    ch.status, ch.method = "approved", "totp"
    answer = register(db, body, confirm=asked)
    assert status_of(answer) == 428 and "not a code" in body_of(answer)["step_up"]["reason"]
    assert not db.wrote(*ENROL_WRITES)


def test_a_waiting_approval_is_answered_again_without_a_new_challenge(monkeypatch):
    with_device(monkeypatch)
    db = FakeDB()
    body = credential(options(db)["challenge"])
    asked = body_of(register(db, body))["step_up"]["challenge_id"]
    again = register(db, body, confirm=asked)
    assert status_of(again) == 428 and body_of(again)["step_up"]["challenge_id"] == asked
    assert len(db.challenges("device_add")) == 1


def test_an_approval_for_another_device_does_not_carry_over(monkeypatch):
    with_device(monkeypatch)
    db = FakeDB()
    first = credential(options(db)["challenge"])
    asked = body_of(register(db, first))["step_up"]["challenge_id"]
    ch = next(o for o in db.challenges("device_add") if o.id == asked)
    ch.status, ch.method = "approved", "webauthn_uv"
    other = credential(options(db)["challenge"], cred=b"d6850-credential-99")
    answer = register(db, other, confirm=asked)
    assert status_of(answer) == 428 and "different device" in body_of(answer)["step_up"]["reason"]


def test_a_declined_device_ends_its_registration_without_asking_again(monkeypatch):
    with_device(monkeypatch)
    db = FakeDB()
    body = credential(options(db)["challenge"])
    asked = body_of(register(db, body))["step_up"]["challenge_id"]
    ch = next(o for o in db.challenges("device_add") if o.id == asked)
    ch.status = "denied"                                        # the owner said no on the phone
    with pytest.raises(HTTPException) as e:
        register(db, body, confirm=asked)
    assert e.value.status_code == 403
    assert len(db.challenges("device_add")) == 1                # nobody was asked again
    assert [o.status for o in db.challenges("device_register")] == ["expired"]
    assert not db.wrote(*ENROL_WRITES)


def test_new_device_prompts_stop_at_three_an_hour(monkeypatch):
    with_device(monkeypatch)
    db = FakeDB()
    for n in range(3):
        answer = register(db, credential(options(db)["challenge"], cred=f"d6850-cap-{n}".encode()))
        assert status_of(answer) == 428
    with pytest.raises(HTTPException) as e:
        register(db, credential(options(db)["challenge"], cred=b"d6850-cap-3"))
    assert e.value.status_code == 429
    assert len(db.challenges("device_add")) == 3


def test_both_screens_show_the_same_code(monkeypatch):
    with_device(monkeypatch)
    db = FakeDB()
    answer = body_of(register(db, credential(options(db)["challenge"], cred=b"d6850-code")))
    from agentvault_registry.services import device_enrollment as de
    code = de.match_code(b64u(b"d6850-code"))
    assert answer["step_up"]["facts"]["code"] == code and code in answer["message"]
    assert len(code) == 7 and code[3] == "-"


DEV_2FA = types.SimpleNamespace(id=43, email="d6850-2fa@example.test", name="E", two_fa_enabled=True,
                                totp_secret="JBSWY3DPEHPK3PXP", is_admin=False)


def test_a_first_device_on_a_2fa_account_takes_a_code(monkeypatch):
    async def _verify(dev, code):
        return code == "123456"
    monkeypatch.setattr(stepup, "verify_totp", _verify)
    db = FakeDB()
    body = credential(options(db, dev=DEV_2FA)["challenge"])
    asked = register(db, body, dev=DEV_2FA)
    assert status_of(asked) == 428 and body_of(asked)["step_up"]["methods"] == ["totp"]
    assert not db.wrote(*ENROL_WRITES)
    wrong = register(db, body, dev=DEV_2FA, totp="000000")
    assert status_of(wrong) == 428 and "not current" in body_of(wrong)["step_up"]["reason"]
    done = register(db, body, dev=DEV_2FA, totp="123456")
    assert status_of(done) == 200 and body_of(done)["approval"] == "first_device_code"


def test_a_first_device_code_leaves_no_card_in_approvals(monkeypatch):
    """V0657 recut (the console proof, fes-20261107T085224Z-70e6): the code-less first try minted a device_add challenge
    that nothing resolved, so Pocket's Approvals (it lists PENDING challenges) showed a stale "Add a new device" card once
    the code had enrolled the device. The first device's code step leaves no pending challenge, and its 428 still names
    a challenge id (the console's step-up parser reads one). Red on v0657/cut."""
    async def _verify(dev, code):
        return code == "123456"
    monkeypatch.setattr(stepup, "verify_totp", _verify)
    db = FakeDB()
    body = credential(options(db, dev=DEV_2FA)["challenge"])
    asked = register(db, body, dev=DEV_2FA)
    assert status_of(asked) == 428 and body_of(asked)["step_up"]["challenge_id"]
    assert register(db, body, dev=DEV_2FA, totp="000000") is not None
    done = register(db, body, dev=DEV_2FA, totp="123456")
    assert status_of(done) == 200
    adds = db.challenges("device_add")
    assert len(adds) == 2 and all(o.status != "pending" for o in adds), [o.status for o in adds]


def test_first_device_codes_stop_at_three_an_hour(monkeypatch):
    """A control, green before and after: the hourly cap counts the code step's challenges, so the codes an account can
    be asked with stay bounded (three a hour, then 429), whatever their state."""
    async def _verify(dev, code):
        return False
    monkeypatch.setattr(stepup, "verify_totp", _verify)
    db = FakeDB()
    body = credential(options(db, dev=DEV_2FA)["challenge"])
    for code in (None, "000001", "000002"):
        assert status_of(register(db, body, dev=DEV_2FA, totp=code)) == 428
    with pytest.raises(HTTPException) as e:
        register(db, body, dev=DEV_2FA, totp="000003")
    assert e.value.status_code == 429


def test_a_first_device_without_2fa_needs_no_code():
    db = FakeDB()
    done = register(db, credential(options(db)["challenge"]))
    assert status_of(done) == 200 and body_of(done)["approval"] == "first_device"


# ── the per-device enrolment trio ───────────────────────────────────────────────────────────────

def test_the_per_device_enrolment_routes_are_retired():
    db = FakeDB()
    with pytest.raises(HTTPException) as e1:
        run(L.webauthn_options(3, REQ, dev=DEV, db=db))
    with pytest.raises(HTTPException) as e2:
        run(L.webauthn_register(3, L.WebAuthnRegisterIn(**credential(b64u(b"x" * 32))), REQ, dev=DEV, db=db))
    with pytest.raises(HTTPException) as e3:
        run(L.enroll_device_key(3, L.KeyEnrollIn(pubkey_jwk={"kty": "EC", "crv": "P-256", "x": "a", "y": "b"}),
                                dev=DEV, db=db))
    assert [e.value.status_code for e in (e1, e2, e3)] == [410, 410, 410]
    assert not db.wrote("UPDATE device_push_registrations")


# ── removal ─────────────────────────────────────────────────────────────────────────────────────

def phone(revoked=False):
    return types.SimpleNamespace(id=3, developer_id=DEV.id, webauthn_public_key="cose", pubkey_jwk=None,
                                 key_revoked_at=now() if revoked else None, label="phone", prefs=None)


def test_revoking_a_live_key_takes_the_second_factor(monkeypatch):
    with_device(monkeypatch)
    db = FakeDB()
    db.objects[("DevicePushRegistration", 3)] = phone()
    answer = run(L.revoke_device_key(device_id=3, dev=DEV, db=db))
    assert status_of(answer) == 428 and body_of(answer)["error"] == "step_up_required"
    assert not db.wrote("SET key_revoked_at = now()")


def test_revoking_refuses_an_api_key(monkeypatch, api_key):
    db = FakeDB()
    db.objects[("DevicePushRegistration", 3)] = phone()
    with pytest.raises(HTTPException) as e:
        run(L.revoke_device_key(device_id=3, dev=DEV, db=db))
    assert e.value.status_code == 403
    assert not db.wrote("SET key_revoked_at = now()")


def test_removing_a_device_that_holds_a_key_takes_the_second_factor(monkeypatch):
    with_device(monkeypatch)
    db = FakeDB()
    db.on("SELECT id, developer_id, label, webauthn_public_key", lambda s, p: [phone()])
    answer = run(DP.unregister_device(device_id=3, current=DEV, db=db))
    assert status_of(answer) == 428
    # the only DELETE that ran spares a row whose credential is live
    assert all("key_revoked_at IS NULL" in s for s in db.wrote("DELETE FROM device_push_registrations"))


def test_unsubscribing_push_keeps_the_signing_credential():
    db = FakeDB()
    db.on("SELECT id FROM device_push_registrations WHERE developer_id=:d AND rail='webpush'", lambda s, p: [(3,)])
    db.on("SET rail = 'local'", lambda s, p: [(3,)])
    run(DP.webpush_unsubscribe(DP.WebPushSubscribeIn(endpoint="https://push.example/e", keys={}), dev=DEV, db=db))
    assert db.wrote("SET rail = 'local'")
    unconditional = [s for s in db.wrote("DELETE FROM device_push_registrations") if "key_revoked_at" not in s]
    assert not unconditional


def test_a_dead_push_subscription_keeps_the_signing_credential():
    from agentvault_registry.background_tasks import push_notify
    db = FakeDB()
    db.on("SET rail = 'local'", lambda s, p: [(3,)])
    kept = run(push_notify.prune_dead_subscription(db, 3))
    assert kept is True and not db.wrote("DELETE FROM device_push_registrations")


def test_the_maintainers_recovery_route_revokes_every_key():
    db = FakeDB()
    db.on("SET key_revoked_at = now() WHERE developer_id = :d", lambda s, p: [(3,), (5,)])
    admin = types.SimpleNamespace(id=1, is_admin=True)
    answer = run(L.admin_revoke_device_keys(42, L.DeviceKeysRecoveryIn(reason="verified by phone call, ticket 99"),
                                            admin=admin, db=db))
    assert answer["revoked_devices"] == [3, 5]
