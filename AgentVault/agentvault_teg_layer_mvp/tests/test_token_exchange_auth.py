"""CB-049 (2026-10-16): POST /auth/token must verify the registry's exchange JWT whether or not the TEG's settings name
the registry key. Before this fix the check was skipped when REGISTRY_JWT_SECRET was unset (every frame and operator
TEG), the purpose claim was optional, and the agent was matched by substring, so a caller that reached the route got a
TEG token for any agent.

Through FastAPI (TestClient on the real router), no database: get_db is overridden and get_or_create is recorded.
Runner style (python tests/test_token_exchange_auth.py) so the CI job's "<passed>/<total> passed" gate reads it.
"""
import os
import sys
import time

sys.path.insert(0, "/app")

# secure_config requires these at import; dummies only, never a production value.
os.environ.setdefault("AVTP_SYSTEM_API_KEY", "ci-dummy-0123456789abcdef0123456789abcdef")
os.environ.setdefault("TEG_TOKEN_SIGNING_KEY", "ci-dummy-0123456789abcdef0123456789abcdef")
os.environ.setdefault("AUDITED_BALANCE_ENABLED", "false")
os.environ.setdefault("TEG_HOME_FRAME_GUARD_ENABLED", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://teg:none@127.0.0.1:1/none")   # never connected: get_db is overridden
for _k in ("REGISTRY_JWT_SECRET", "TEG_REGISTRY_JWT_SECRET", "REGISTRY_SERVICE_TOKEN"):
    os.environ.pop(_k, None)

import jwt as pyjwt                                                  # noqa: E402
from fastapi import FastAPI                                          # noqa: E402
from fastapi.testclient import TestClient                            # noqa: E402
from pydantic import SecretStr                                       # noqa: E402

from src.teg_core_service.api.v1 import endpoints_auth as ea          # noqa: E402
from src.teg_core_service.core import secure_config as sc             # noqa: E402

KEY = "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"   # a SHAPE (64 hex), not a secret
AGENT = "did:theprotocol:eu.theprotocol.cloud:7f3e2c1a-0000-4000-8000-000000000001"
CREATED = []

app = FastAPI()
app.include_router(ea.router, prefix="/api/v1/auth")
app.dependency_overrides[ea.get_db] = lambda: None
ea.AgentCRUD.get_or_create = staticmethod(lambda db, agent_id: CREATED.append(agent_id))
client = TestClient(app)


def _secret(value):
    ea.settings.registry_jwt_secret = None if value is None else SecretStr(value)


def _jwt(key=KEY, agent=AGENT, purpose="teg_token_exchange", exp_in=300, extra=None):
    claims = {"sub": "registry", "iss": "agentvault-registry", "exp": int(time.time()) + exp_in}
    if agent is not None:
        claims["agent_id"] = agent
    if purpose is not None:
        claims["purpose"] = purpose
    claims.update(extra or {})
    return pyjwt.encode(claims, key, algorithm="HS256")


def _post(token, agent=AGENT):
    CREATED.clear()
    return client.post("/api/v1/auth/token", json={"agent_id": agent, "registry_jwt": token})


def _refused(r, status, words):
    assert r.status_code == status, (r.status_code, r.text[:200])
    assert words in r.text, r.text[:200]
    assert "access_token" not in r.text and CREATED == [], "a refused exchange must issue nothing and create nothing"


def test_valid_exchange_issues_a_token():
    _secret(KEY)
    r = _post(_jwt())
    assert r.status_code == 200, r.text[:200]
    assert r.json()["access_token"] and CREATED == [AGENT]


def test_unset_secret_refuses_every_exchange():
    _secret(None)
    _refused(_post(_jwt()), 503, "not configured")
    _refused(_post("not-even-a-jwt"), 503, "not configured")


def test_blank_secret_refuses_every_exchange():
    _secret("   ")
    _refused(_post(_jwt()), 503, "not configured")


def test_forged_signature_is_refused():
    _secret(KEY)
    _refused(_post(_jwt(key="not-the-registry-key-0123456789abcdef0123456789")), 401, "signature is invalid")


def test_expired_jwt_is_refused():
    _secret(KEY)
    _refused(_post(_jwt(exp_in=-60)), 401, "expired")


def test_jwt_without_purpose_is_refused():
    _secret(KEY)
    _refused(_post(_jwt(purpose=None)), 401, "not a token exchange token")


def test_jwt_with_other_purpose_is_refused():
    _secret(KEY)
    _refused(_post(_jwt(purpose="session")), 401, "not a token exchange token")


def test_jwt_without_agent_is_refused():
    _secret(KEY)
    _refused(_post(_jwt(agent=None)), 401, "missing agent identity")


def test_agent_must_match_exactly():
    _secret(KEY)
    _refused(_post(_jwt(agent=AGENT[:-1]), agent=AGENT), 401, "does not match")     # JWT names a prefix of the asked agent
    _refused(_post(_jwt(agent=AGENT + "2"), agent=AGENT), 401, "does not match")    # JWT names a longer one
    _refused(_post(_jwt(agent="registry"), agent=AGENT), 401, "does not match")


def test_settings_read_the_names_the_composes_pass():
    def settings_with(env):
        saved = {k: os.environ.pop(k, None) for k in ("REGISTRY_JWT_SECRET", "TEG_REGISTRY_JWT_SECRET", "REGISTRY_SERVICE_TOKEN")}
        try:
            os.environ.update(env)
            return sc.Settings(_env_file=None).registry_jwt_secret
        finally:
            for k in env:
                os.environ.pop(k, None)
            os.environ.update({k: v for k, v in saved.items() if v is not None})
    for name in ("REGISTRY_JWT_SECRET", "TEG_REGISTRY_JWT_SECRET", "REGISTRY_SERVICE_TOKEN"):
        got = settings_with({name: KEY})
        assert got is not None and got.get_secret_value() == KEY, name
    assert settings_with({}) is None
    assert settings_with({"REGISTRY_SERVICE_TOKEN": ""}) is None, "an empty interpolated value must read as unset"


TESTS = [
    test_valid_exchange_issues_a_token,
    test_unset_secret_refuses_every_exchange,
    test_blank_secret_refuses_every_exchange,
    test_forged_signature_is_refused,
    test_expired_jwt_is_refused,
    test_jwt_without_purpose_is_refused,
    test_jwt_with_other_purpose_is_refused,
    test_jwt_without_agent_is_refused,
    test_agent_must_match_exactly,
    test_settings_read_the_names_the_composes_pass,
]

if __name__ == "__main__":
    failed = 0
    for t in TESTS:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            print(f"FAIL  {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)
