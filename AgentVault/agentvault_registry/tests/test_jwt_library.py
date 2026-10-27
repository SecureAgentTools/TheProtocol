"""§DEPS (2026-09-28): the registry's JWTs are PyJWT's; python-jose is gone.

python-jose pulled in ecdsa, whose P-256 timing flaw (CVE-2024-23342, PYSEC-2026-1325) will never be fixed upstream, and
it was the last user of rsa and six. PyJWT was already installed (spiffe needs it, < 2.14). Every token the registry
mints is HS256 over the 64-byte API_KEY_SECRET, and a token minted before the swap must still be accepted after it (and
the reverse after a rollback): the fixture below was made by python-jose 3.5.0 in the V0476 image with a test key.
"""
from __future__ import annotations

import ast
import pathlib

import jwt
import pytest

from agentvault_registry import security

TEST_KEY = "test-only-key-for-the-jose-to-pyjwt-crossing-00000000"
# made by python-jose 3.5.0 (V0476): jwt.encode(CLAIMS, TEST_KEY, algorithm="HS256"); exp 2100-01-01
JOSE_TOKEN = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
              "eyJzdWIiOiI0MiIsInR5cGUiOiJyZWZyZXNoIiwiZXhwIjo0MTAyNDQ0ODAwLCJqdGkiOiIwYzdhNGI0ZS02ZjJlLTRkMWEtOWM1NS0yZjhm"
              "NWExYjNjOWQiLCJ0diI6MywiYWN0Ijp7InN1YiI6InNlcnZpY2U6YTJhLXNldHRsZSIsInJlYXNvbiI6ImFuY2hvcmVkLWhhbmQifX0."
              "rQAopaa6HVk3F0yTuDM2xOfpQiJQcsUvecDHvQlomnE")
CLAIMS = {"sub": "42", "type": "refresh", "exp": 4102444800, "jti": "0c7a4b4e-6f2e-4d1a-9c55-2f8f5a1b3c9d", "tv": 3,
          "act": {"sub": "service:a2a-settle", "reason": "anchored-hand"}}


def test_a_token_python_jose_made_decodes_with_the_same_claims():
    assert jwt.get_unverified_header(JOSE_TOKEN) == {"alg": "HS256", "typ": "JWT"}
    assert jwt.decode(JOSE_TOKEN, TEST_KEY, algorithms=["HS256"]) == CLAIMS
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(JOSE_TOKEN, TEST_KEY + "x", algorithms=["HS256"])


def test_the_security_helpers_round_trip_and_refuse():
    tok = security.create_refresh_token(42, token_version=3)
    assert security.validate_refresh_token(tok) == 42
    claims = jwt.decode(tok, security.SECRET_KEY, algorithms=[security.ALGORITHM])
    assert claims["type"] == "refresh" and claims["tv"] == 3 and isinstance(claims["jti"], str)
    assert security.validate_refresh_token(tok[:-2] + ("AA" if tok[-2:] != "AA" else "BB")) is None
    assert security.validate_refresh_token("not-a-jwt") is None
    access = security.create_access_token({"sub": "did:theprotocol:probe", "type": "agent", "agent_id": "3"})
    got = jwt.decode(access, security.SECRET_KEY, algorithms=[security.ALGORITHM])
    assert got["sub"] == "did:theprotocol:probe" and got["type"] == "agent" and "exp" in got and "jti" in got


def test_an_expired_token_is_a_jwterror_where_the_code_catches_it():
    import datetime as dt
    old = jwt.encode({"sub": "1", "exp": dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)}, security.SECRET_KEY,
                     algorithm=security.ALGORITHM)
    with pytest.raises(security.JWTError):
        jwt.decode(old, security.SECRET_KEY, algorithms=[security.ALGORITHM])


def test_pyjwt_is_the_line_spiffe_accepts():
    major, minor = (int(x) for x in jwt.__version__.split(".")[:2])
    assert (major, minor) >= (2, 13) and (major, minor) < (2, 14), jwt.__version__


SRC = pathlib.Path(security.__file__).resolve().parent


def test_nothing_imports_python_jose():
    offenders, seen = [], 0
    for path in sorted(SRC.rglob("*.py")):
        seen += 1
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else [])
            offenders += [f"{path.relative_to(SRC)}:{node.lineno} {n}" for n in names if n.split(".")[0] == "jose"]
    assert seen > 300 and offenders == []
