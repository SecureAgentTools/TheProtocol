"""§DEPS (2026-09-27, his words "the no jwt fallback path trap needs deletion. shouldnt be possible").

Measured before: core/jwt_svid/validator.py imported `pyspiffe`, every TEG image ships `spiffe` (never `pyspiffe`), so
with USE_JWT_SVID_AUTH=true every token went to a fallback that checked HS256 against an environment secret whose
default was empty, and PyJWT accepts an empty HMAC key: anyone could sign a JWT-SVID for any agent. The flag was unset
on all 13 TEGs, so it never ran; the path is gone so it cannot.

RED control: run with PYTHONPATH naming the tree before the fix (AgentVault f53c2f97): the forged tokens below are
accepted as agent `agent_victim` and the structure checks find the fallback. (PyJWT >= 2.14 refuses an empty HMAC
key by itself, so the tokens are signed here by hand, as an attacker would: the refusal must not rest on the library.)
"""
from __future__ import annotations

import ast
import base64
import hashlib
import hmac
import json
import pathlib
import time

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from teg_core_service.core.jwt_svid import validator as v

TREE = ast.parse(pathlib.Path(v.__file__).read_text())


def _b64(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def _forged(key: str) -> str:
    now = int(time.time())
    claims = {"iss": f"spiffe://{v.TRUST_DOMAIN}", "sub": f"spiffe://{v.TRUST_DOMAIN}/agent/victim",
              "aud": v.EXPECTED_AUDIENCE, "iat": now, "exp": now + 300}
    head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(claims, separators=(",", ":")).encode())
    sig = _b64(hmac.new(key.encode(), head + b"." + body, hashlib.sha256).digest())
    return (head + b"." + body + b"." + sig).decode()


def test_the_premise_no_image_carries_pyspiffe():
    # The branch that used to fall back is the branch every TEG image takes.
    assert v.PYSPIFFE_AVAILABLE is False


@pytest.mark.parametrize("configured", [None, "", "a-secret-an-operator-might-set"])
def test_a_self_signed_token_is_refused(monkeypatch, configured):
    if configured is None:
        monkeypatch.delenv("JWT_SVID_SIGNING_KEY", raising=False)
    else:
        monkeypatch.setenv("JWT_SVID_SIGNING_KEY", configured)
    token = _forged(configured or "")
    with pytest.raises(HTTPException) as refused:
        v.verify_jwt_svid(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token))
    assert refused.value.status_code == 503
    with pytest.raises(HTTPException) as refused_direct:
        v.JWTSVIDValidator().validate_jwt_svid(token)
    assert refused_direct.value.status_code == 503


def test_an_optional_endpoint_reads_it_as_anonymous_not_as_the_agent(monkeypatch):
    monkeypatch.delenv("JWT_SVID_SIGNING_KEY", raising=False)
    assert v.get_optional_jwt_svid(HTTPAuthorizationCredentials(scheme="Bearer", credentials=_forged(""))) is None


def test_the_module_holds_no_second_check():
    # Structure, not text: comments may name the class of the trap; the code may not carry it.
    names = {n.name for n in ast.walk(TREE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert not [n for n in names if "fallback" in n.lower()], names
    consts = {n.value for n in ast.walk(TREE) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "JWT_SVID_SIGNING_KEY" not in consts
    decodes = [n for n in ast.walk(TREE) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "decode" and isinstance(n.func.value, ast.Name) and n.func.value.id == "jwt"]
    assert decodes == []
    imports = [a.name for n in ast.walk(TREE) if isinstance(n, (ast.Import, ast.ImportFrom))
               for a in n.names if a.name == "jwt" or (isinstance(n, ast.ImportFrom) and n.module == "jwt")]
    assert imports == []
