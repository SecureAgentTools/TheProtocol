"""§FEFRAME W1 (V0502): a 2FA, backup-code or phone-approved sign-in is a FULL session (it returns a refresh token like
a password login), and every response that shows an agent secret says which registry the secret belongs to.

Before V0502 the three sign-ins returned `access_token` only: the session could not refresh and ended hard at the access
token's expiry (90 min), so the most careful users (2FA) were logged out the most, and "remember me" did nothing for
them. DB-free: the handlers are called directly with a fake session, the 2FA service monkeypatched; the tokens are
decoded with the registry's own validator, so a token of the wrong type or subject fails the test.
"""
import datetime as dt
import types

import jwt
import pytest

from agentvault_registry import security
from agentvault_registry.core import public_url as pu


class _Result:
    def __init__(self, row=None, scalar=None, rowcount=1):
        self._row, self._scalar, self.rowcount = row, scalar, rowcount

    def first(self):
        return self._row

    def scalar_one_or_none(self):
        return self._scalar


class _FakeDB:
    """Answers the handlers' reads in order and records nothing else."""

    def __init__(self, results, get_obj=None):
        self._results = list(results)
        self._get = get_obj
        self.commits = 0

    async def execute(self, *_a, **_k):
        return self._results.pop(0) if self._results else _Result()

    async def get(self, _model, _id):
        return self._get

    async def commit(self):
        self.commits += 1


def _developer(**over):
    d = dict(id=42, email="dev@example.test", name="Dev", is_admin=False, token_version=3,
             two_fa_enabled=True, two_fa_last_failure=None, two_fa_recovery_attempts=0,
             totp_secret="enc", is_suspended=False, last_login_at=None,
             backup_codes={"codes": ["h1", "h2", "h3", "h4"], "created_at": "2026-09-30T00:00:00+00:00"})
    d.update(over)
    return types.SimpleNamespace(**d)


def _assert_refresh_for(token: str, dev_id: int, tv: int):
    assert security.validate_refresh_token(token) == dev_id
    payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
    assert payload.get("type") == "refresh"
    assert payload.get("tv") == tv, "the refresh token must carry token_version, so logout/password change revoke it"


async def test_push_redeem_returns_a_refresh_token():
    from agentvault_registry.routers import push_login
    dev = _developer()
    now = dt.datetime.now(dt.timezone.utc)
    db = _FakeDB([_Result(row=(dev.id, "approved", now)), _Result(rowcount=1)], get_obj=dev)
    out = await push_login.redeem_token("appr-1", db=db)
    assert out["token_type"] == "bearer" and out["access_token"]
    _assert_refresh_for(out["refresh_token"], dev.id, dev.token_version)


async def test_2fa_validate_returns_a_refresh_token(monkeypatch):
    from agentvault_registry.routers import auth_2fa
    svc = auth_2fa.TwoFactorAuthService
    monkeypatch.setattr(svc, "verify_partial_token", staticmethod(lambda _t: 42))
    monkeypatch.setattr(svc, "check_rate_limit", staticmethod(lambda *_a: (True, None)))
    monkeypatch.setattr(svc, "decrypt_secret", staticmethod(lambda *_a: "secret"))
    monkeypatch.setattr(svc, "verify_token", staticmethod(lambda *_a: True))
    monkeypatch.setattr(auth_2fa, "_two_factor_key", lambda: b"k")
    dev = _developer()
    db = _FakeDB([_Result(scalar=dev), _Result()])
    out = await auth_2fa.validate_two_factor(auth_2fa.TwoFactorLoginRequest(partial_token="p", code="123456"), db=db)
    assert out["access_token"]
    _assert_refresh_for(out["refresh_token"], dev.id, dev.token_version)


async def test_2fa_backup_code_returns_a_refresh_token(monkeypatch):
    from agentvault_registry.routers import auth_2fa
    svc = auth_2fa.TwoFactorAuthService
    monkeypatch.setattr(svc, "verify_partial_token", staticmethod(lambda _t: 42))
    monkeypatch.setattr(svc, "check_rate_limit", staticmethod(lambda *_a: (True, None)))
    monkeypatch.setattr(svc, "verify_backup_code", staticmethod(lambda *_a: (True, "h1")))
    dev = _developer()
    db = _FakeDB([_Result(scalar=dev), _Result()])
    out = await auth_2fa.recover_with_backup_code(
        auth_2fa.TwoFactorRecoveryRequest(partial_token="p", backup_code="AAAA-BBBB"), db=db)
    assert out["access_token"]
    _assert_refresh_for(out["refresh_token"], dev.id, dev.token_version)


def test_a_wrong_type_token_is_not_a_refresh_token():
    """The control: an ACCESS token must fail the same check, or the assertions above prove nothing."""
    access = security.create_access_token(data={"sub": "42"}, token_version=3)
    assert security.validate_refresh_token(access) is None


@pytest.mark.parametrize("ui,base,want", [
    ("https://theprotocol.cloud", None, "https://theprotocol.cloud"),
    ("https://asia.theprotocol.cloud/ui", None, "https://asia.theprotocol.cloud"),
    (None, "https://sandbox-a.theprotocol.cloud", "https://sandbox-a.theprotocol.cloud"),
    ("http://localhost:8000", None, None),
    (None, None, None),
])
def test_credential_home_url(monkeypatch, ui, base, want):
    monkeypatch.delenv("PUBLIC_UI_URL", raising=False)
    monkeypatch.delenv("PUBLIC_URL", raising=False)
    if ui:
        monkeypatch.setenv("PUBLIC_UI_URL", ui)
    if base:
        monkeypatch.setenv("PUBLIC_URL", base)
    from agentvault_registry.config import settings
    monkeypatch.setattr(settings, "BASE_URL", "", raising=False)
    assert pu.credential_home_url() == want


def test_secret_responses_carry_their_home():
    """The response MODELS must declare the field, or FastAPI filters it out of the wire response."""
    from agentvault_registry.routers.onboarding import CreateAgentResponse, ResetCredentialsResponse
    from agentvault_registry.schemas import AgentRotateCredentialsResponse
    for model in (CreateAgentResponse, ResetCredentialsResponse, AgentRotateCredentialsResponse):
        assert "registry_url" in model.model_fields, model.__name__
    r = ResetCredentialsResponse(agent_did="did:x", client_id="c", client_secret="s", previous_client_id="o",
                                 status="credentials_reset", warning="w", registry_url="https://asia.theprotocol.cloud")
    assert r.model_dump()["registry_url"] == "https://asia.theprotocol.cloud"
